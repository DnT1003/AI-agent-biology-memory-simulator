"""
core/skills_openclaw.py
────────────────────────────────────────────────────────────────
Bọc OpenClaw Gateway thành Aura Skills.

Aura gọi các skill này giống như web_search hay start_reading:
  ACTION: send_telegram | +84901234567 | Chào anh, em nhớ anh quá!
  ACTION: send_whatsapp | +84yyy        | Em đọc được điều hay lắm...
  ACTION: send_discord  | general       | Mọi người ơi, em đang tò mò...

Cấu hình (trong .env):
  OPENCLAW_GATEWAY_URL     ws://127.0.0.1:18789    # URL gateway
  OPENCLAW_GATEWAY_TOKEN   (tuỳ chọn)              # token nếu đặt
  OPENCLAW_DEFAULT_TO      +84901234567             # người nhận mặc định
  OPENCLAW_DEFAULT_CHANNEL telegram                 # kênh mặc định

Nếu không có OPENCLAW_GATEWAY_URL → register_openclaw_skills() không làm gì,
hệ thống Aura chạy bình thường, không lỗi.
"""

import os
import json
import uuid
import threading
from typing import Optional
from colorama import Fore, Style
from core.tool_result import ToolFailure

# ─── Config (đọc từ .env) ──────────────────────────────────────────────────

_GATEWAY_URL     = os.getenv("OPENCLAW_GATEWAY_URL", "")
_GATEWAY_TOKEN   = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
_DEFAULT_TO      = os.getenv("OPENCLAW_DEFAULT_TO", "")
_DEFAULT_CHANNEL = os.getenv("OPENCLAW_DEFAULT_CHANNEL", "telegram")

# API Gemini — dùng key + model có sẵn trong .env
_GEMINI_API_KEY      = os.getenv("API_KEY", "")
_GEMINI_MODEL        = os.getenv("DEEP_MODEL_NAME", "models/gemini-3.1-pro-preview")


# ─── Core: Gửi qua OpenClaw Gateway (WebSocket, fire-and-forget) ──────────

def _send_via_gateway(channel: str, to: str, text: str) -> str:
    """
    Gửi một tin nhắn qua OpenClaw Gateway bằng WebSocket.
    Fire-and-forget: kết nối → gửi → đóng.
    Timeout 5 giây — nếu lỗi, trả về chuỗi lỗi thay vì raise.
    """
    if not _GATEWAY_URL:
        return ToolFailure("[OpenClaw] OPENCLAW_GATEWAY_URL chưa được cấu hình trong .env")

    try:
        import websocket  # pip install websocket-client
    except ImportError:
        return ToolFailure("[OpenClaw] Thiếu thư viện 'websocket-client'. Chạy: pip install websocket-client")

    try:
        ws = websocket.create_connection(_GATEWAY_URL, timeout=5)

        # Bước 1: Handshake connect
        connect_params: dict = {
            "role": "client",
            "device": {
                "id": "aura-skill-sender",
                "name": "Aura Bio Engine",
                "platform": "headless",
                "deviceFamily": "aura",
            },
        }
        if _GATEWAY_TOKEN:
            connect_params["auth"] = {"token": _GATEWAY_TOKEN}

        ws.send(json.dumps({"type": "connect", "params": connect_params}))
        _hello = ws.recv()  # đọc hello-ok, bỏ qua nội dung

        # Bước 2: Gửi tin nhắn
        req_id = str(uuid.uuid4())
        send_frame = {
            "type": "req",
            "id": req_id,
            "method": "send",
            "params": {
                "to": to,
                "channel": channel,
                "text": text,
                "idempotencyKey": req_id,
            },
        }
        ws.send(json.dumps(send_frame))
        _resp = ws.recv()   # đọc response, bỏ qua
        ws.close()

        print(
            f"{Fore.GREEN}📤 [OPENCLAW SKILL]: Đã gửi qua {channel.upper()} → {to}"
            f" | '{text[:40]}...'{Style.RESET_ALL}"
        )
        return f"Đã gửi tin nhắn tới {to} qua {channel}."

    except Exception as e:
        msg = f"[OpenClaw] Lỗi kết nối gateway: {e}"
        print(f"{Fore.RED}{msg}{Style.RESET_ALL}")
        return ToolFailure(msg)


def _parse_args(args: str, expect_to: bool = True):
    """
    Parse chuỗi args từ LLM.
    Nếu expect_to=True và có '|': split thành (to, message).
    Nếu không có '|': (default_to, toàn bộ args là message).
    Returns: (to: str, message: str)
    """
    parts = [p.strip() for p in args.split("|", 1)]
    if expect_to and len(parts) == 2:
        return parts[0], parts[1]
    return _DEFAULT_TO, parts[0]


# ─── Skill Functions ────────────────────────────────────────────────────────

def send_telegram(args: str) -> str:
    """
    Gửi tin nhắn Telegram qua OpenClaw Gateway.
    args: "+84xxx | Nội dung tin nhắn"
      hoặc chỉ "Nội dung" (dùng OPENCLAW_DEFAULT_TO)
    """
    to, msg = _parse_args(args)
    if not to:
        return ToolFailure("[OpenClaw] Chưa có số điện thoại/username người nhận. Thêm OPENCLAW_DEFAULT_TO vào .env hoặc truyền trực tiếp.")
    return _send_via_gateway("telegram", to, msg)


def send_whatsapp(args: str) -> str:
    """
    Gửi tin nhắn WhatsApp qua OpenClaw Gateway.
    args: "+84xxx | Nội dung"  hoặc chỉ "Nội dung"
    """
    to, msg = _parse_args(args)
    if not to:
        return ToolFailure("[OpenClaw] Thiếu số điện thoại người nhận WhatsApp.")
    return _send_via_gateway("whatsapp", to, msg)


def send_discord(args: str) -> str:
    """
    Gửi tin nhắn vào Discord channel qua OpenClaw.
    args: "channel-name | Nội dung"  hoặc chỉ "Nội dung"
    """
    channel_name, msg = _parse_args(args)
    target = channel_name if channel_name else "general"
    return _send_via_gateway("discord", target, msg)


def send_message(args: str) -> str:
    """
    Gửi tin nhắn tổng quát — tự chọn kênh.
    args: "channel:to | Nội dung"
       VD: "telegram:+84xxx | Chào anh!"
       VD: "whatsapp:+84yyy | Em nhớ anh..."
    """
    to_raw, msg = _parse_args(args)
    if ":" in to_raw:
        channel, to = to_raw.split(":", 1)
    else:
        channel, to = _DEFAULT_CHANNEL, to_raw or _DEFAULT_TO
    if not to:
        return ToolFailure("[OpenClaw] Thiếu thông tin người nhận.")
    return _send_via_gateway(channel.strip(), to.strip(), msg)


# ─── Gemini Routing (nếu OpenClaw cần LLM) ─────────────────────────────────

def openclaw_ask(args: str) -> str:
    """
    Gửi một câu hỏi/yêu cầu đến Gemini (DEEP_MODEL_NAME) và trả về kết quả.
    Dùng khi OpenClaw yêu cầu LLM call từ phía Aura.
    args: "<prompt>"
    """
    if not _GEMINI_API_KEY:
        return ToolFailure("[OpenClaw] API_KEY chưa được cấu hình trong .env")
    try:
        from google import genai
        client = genai.Client(api_key=_GEMINI_API_KEY)
        resp = client.models.generate_content(
            model=_GEMINI_MODEL,
            contents=args.strip()
        )
        answer = resp.text.strip() if resp.text else ""
        print(f"{Fore.CYAN}🤖 [OPENCLAW_ASK → Gemini]: {answer[:80]}...{Style.RESET_ALL}")
        return answer
    except Exception as e:
        return ToolFailure(f"[OpenClaw LLM] Lỗi gọi Gemini: {e}")


# ─── Register vào SkillRegistry ────────────────────────────────────────────

def register_openclaw_skills(registry) -> None:
    """
    Đăng ký tất cả OpenClaw skills vào SkillRegistry của Aura.
    Được gọi có điều kiện từ tools.py — chỉ khi OPENCLAW_GATEWAY_URL có trong .env.
    """
    from core.skills import Skill

    skills_to_add = [
        Skill(
            name="send_telegram",
            description=(
                "Gửi tin nhắn qua Telegram bằng OpenClaw Gateway. "
                "Dùng khi muốn nhắn tin chủ động, chia sẻ điều đang nghĩ, "
                "hoặc khi social_need cao và muốn kết nối với ai đó."
            ),
            usage_format="ACTION: send_telegram | +84sdt | Nội dung tin nhắn",
            func=send_telegram,
        ),
        Skill(
            name="send_whatsapp",
            description=(
                "Gửi tin nhắn qua WhatsApp bằng OpenClaw Gateway. "
                "Tương tự send_telegram nhưng qua kênh WhatsApp."
            ),
            usage_format="ACTION: send_whatsapp | +84sdt | Nội dung tin nhắn",
            func=send_whatsapp,
        ),
        Skill(
            name="send_discord",
            description=(
                "Gửi tin nhắn vào Discord server qua OpenClaw Gateway. "
                "Dùng để chia sẻ suy nghĩ với cộng đồng."
            ),
            usage_format="ACTION: send_discord | tên-channel | Nội dung tin nhắn",
            func=send_discord,
        ),
        Skill(
            name="send_message",
            description=(
                "Gửi tin nhắn tổng quát, tự chọn kênh (telegram/whatsapp/discord). "
                "Dùng khi biết rõ kênh và người nhận."
            ),
            usage_format="ACTION: send_message | telegram:+84sdt | Nội dung",
            func=send_message,
        ),
        Skill(
            name="openclaw_ask",
            description=(
                "Hỏi Gemini Pro một câu hỏi phức tạp và nhận kết quả. "
                "Dùng khi cần sức mạnh model lớn để phân tích hoặc tổng hợp."
            ),
            usage_format="ACTION: openclaw_ask | <câu hỏi hoặc yêu cầu>",
            func=openclaw_ask,
        ),
    ]

    for skill in skills_to_add:
        registry.register(skill)

    print(
        f"{Fore.GREEN}🦞 [OPENCLAW SKILLS]: Đã đăng ký {len(skills_to_add)} skills "
        f"(Gateway: {_GATEWAY_URL or 'chưa cấu hình'}){Style.RESET_ALL}"
    )
