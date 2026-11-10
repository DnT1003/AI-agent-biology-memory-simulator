"""Strip "helpful assistant" habits from what Aura says in chat.

LLMs drift into assistant register: markdown headers and bullet lists,
"Mình có thể giúp gì thêm cho bạn không?", "Hy vọng thông tin này hữu ích",
essays in answer to a two-word message. A person texting does none of that.

``humanize`` runs on the generated reply before it is committed (regex only,
no extra LLM call). It never touches tool output, keeps ``[SEND]`` bubble
breaks, and never returns an empty reply.
"""

from __future__ import annotations

import re

from core.message_bubbles import split_bubbles

_HEADER_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_BULLET_RE = re.compile(r"^\s*(?:[-*•+]|\d{1,2}[.)])\s+", re.MULTILINE)
_EMPHASIS_RE = re.compile(r"(\*\*|__)(.+?)\1", re.DOTALL)
_BACKTICK_RE = re.compile(r"`([^`\n]+)`")
_SENTENCE_RE = re.compile(r"[^.!?…\n]+(?:[.!?…]+|$)")

# Whole sentences that only an assistant would say.
_CLICHE_RES = tuple(re.compile(p, re.IGNORECASE) for p in (
    r"\b(mình|tôi|em|tớ) có thể giúp (gì|được gì)\b",
    r"\bcần (mình|tôi|em|tớ) giúp gì\b",
    r"\bnếu (bạn|anh|cậu) cần (thêm|gì)\b.*\b(cứ|hãy|đừng ngần ngại)\b",
    r"\bđừng ngần ngại\b",
    r"\bcần (?:\w+ )?giúp đỡ\b",
    r"\bcứ (?:thoải mái|tự nhiên) (?:hỏi|nói|chia sẻ|nhắn)\b",
    r"\b(?:luôn|vẫn|đang) sẵn sàng (?:đón|giúp|hỗ trợ|lắng nghe|đồng hành)\b",
    r"\bchúc (?:bạn|anh|chị) có một ngày (?:làm việc )?(?:hiệu quả|năng suất|sản xuất|ý nghĩa|tốt lành)\b",
    r"\bhy vọng (điều này|thông tin này|câu trả lời này|những thông tin)\b",
    r"\b(là|như) một (mô hình ngôn ngữ|trợ lý ảo|trợ lý ai|trí tuệ nhân tạo)\b",
    r"\bas an ai\b",
    r"\bhow can i (help|assist)\b",
    r"\bi hope this helps\b",
    r"^\s*(chắc chắn rồi|tất nhiên rồi|dưới đây là)\s*[!:.]?\s*$",
))

# Internal state leaking into speech: prompt labels read back aloud.
_JARGON_PAREN_RE = re.compile(r"\s*\((?:[A-Za-z][A-Za-z _-]{1,24})\)")
_JARGON_SENTENCE_RE = re.compile(
    r"\b(?:dopamine|cortisol|serotonin|atp|fatigue|arousal|valence|mood|stress level|"
    r"chỉ số|trạng thái (?:sảng khoái|cân bằng nội môi|nội môi))\b",
    re.IGNORECASE,
)

# Asking for an explanation earns a longer answer.
_EXPLAIN_RE = re.compile(
    r"\b(giải thích|là gì|tại sao|vì sao|như thế nào|thế nào là|hướng dẫn|cách nào|kể chi tiết|kể đi|kể anh nghe)\b",
    re.IGNORECASE,
)
SHORT_MESSAGE_CHARS = 40
LONG_REPLY_CHARS = 420
TRIMMED_REPLY_CHARS = 260


# "Là một mô hình ngôn ngữ, em ..." -> "Em ...": drop the disclaimer clause,
# keep what she actually says.
_DISCLAIMER_CLAUSE_RE = re.compile(
    r"\b(?:là|như) một (?:mô hình ngôn ngữ|trợ lý ảo|trợ lý ai|trí tuệ nhân tạo|ai)\s*,\s*"
    r"|\bas an ai\s*,\s*",
    re.IGNORECASE,
)


def _drop_disclaimer_clause(sentence: str) -> str:
    stripped = _DISCLAIMER_CLAUSE_RE.sub("", sentence, count=1)
    if stripped != sentence and stripped:
        stripped = stripped[0].upper() + stripped[1:]
    return stripped


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.findall(text) if s.strip()]


def _join_items(items: list[str]) -> str:
    """'- Nghỉ ngơi nhé' / '- Uống nước' -> 'Nghỉ ngơi nhé, uống nước'."""
    parts = [item.rstrip(" .;,") for item in items if item.strip()]
    parts = [parts[0]] + [p[:1].lower() + p[1:] for p in parts[1:]] if parts else []
    return ", ".join(parts)


def _plain(chunk: str) -> tuple[str, set]:
    changes = set()
    out = chunk
    for pattern, repl in ((_EMPHASIS_RE, r"\2"), (_BACKTICK_RE, r"\1")):
        new = pattern.sub(repl, out)
        if new != out:
            changes.add("markdown")
            out = new
    new = _JARGON_PAREN_RE.sub("", out)
    if new != out:
        changes.add("jargon")
        out = new

    # Headers are labels, not speech: drop them. Consecutive list items
    # become one spoken sentence.
    lines, items = [], []
    for line in out.splitlines():
        if _HEADER_RE.match(line):
            changes.add("markdown")
            continue
        if _BULLET_RE.match(line):
            changes.add("list")
            items.append(_BULLET_RE.sub("", line, count=1))
            continue
        if items:
            lines.append(_join_items(items))
            items = []
        lines.append(line)
    if items:
        lines.append(_join_items(items))

    kept = []
    for line in lines:
        original = _sentences(line)
        sentences = [_drop_disclaimer_clause(s) for s in original]
        good = [s for s in sentences if s and not any(r.search(s) for r in _CLICHE_RES)]
        if sentences != original or len(good) != len(sentences):
            changes.add("cliche")
        spoken = [s for s in good if not _JARGON_SENTENCE_RE.search(s)]
        if len(spoken) != len(good):
            changes.add("jargon")
        good = spoken
        if good:
            kept.append(" ".join(good))
    return "\n".join(kept).strip(), changes


def _trim(text: str, limit: int) -> str:
    out = ""
    for sentence in _sentences(text):
        candidate = f"{out} {sentence}".strip()
        if out and len(candidate) > limit:
            break
        out = candidate
    return out or text[:limit]


def humanize(reply: str, user_input: str = "") -> tuple[str, set]:
    """Return (cleaned reply, set of applied fixes). Falls back to the input."""
    if not isinstance(reply, str) or not reply.strip():
        return reply, set()
    changes: set = set()
    bubbles = []
    for chunk in split_bubbles(reply) or [reply]:
        cleaned, applied = _plain(chunk)
        changes |= applied
        if cleaned:
            bubbles.append(cleaned)
    if not bubbles:
        return reply, set()  # everything looked like boilerplate: keep the original

    text = " [SEND] ".join(bubbles)
    short_message = len(str(user_input or "").strip()) <= SHORT_MESSAGE_CHARS
    total = sum(len(b) for b in bubbles)
    if short_message and total > LONG_REPLY_CHARS and not _EXPLAIN_RE.search(str(user_input or "")):
        trimmed, budget = [], TRIMMED_REPLY_CHARS
        for bubble in bubbles:
            if budget <= 0:
                break
            piece = _trim(bubble, budget)
            trimmed.append(piece)
            budget -= len(piece)
        text = " [SEND] ".join(trimmed)
        changes.add("length")
    return text, changes
