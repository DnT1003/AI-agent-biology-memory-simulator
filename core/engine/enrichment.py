"""One post-reply extraction call instead of several.

After Aura has answered, a single structured LLM call reads the exchange and
returns everything the slower memory systems need:

* ``relations``  -> WorldGraph (who is who to whom)
* ``values``     -> ValueSystem (the owner's stance on values)
* ``open_loops`` -> ProspectiveMemory (the owner's upcoming events, Aura's promises)
* ``user_busy``  -> ProspectiveMemory (explicit "I'm busy until ...")

Each section is validated and applied on its own: a malformed section is
dropped without blocking the others, and a malformed item invalidates its
whole section (no partial batches).
"""

import math

from core.logger import get_logger
from core.temporal import describe_now

logger = get_logger("enrichment")
MAX_VALUES = 2
MATERIAL_VALUE_SENTIMENT = 0.4


def build_prompt(user_input: str, aura_reply: str, now: float) -> str:
    return f"""Bây giờ là {describe_now(now)}.
Phân tích lượt trò chuyện dưới đây và trích xuất thông tin có cấu trúc.
User nói: "{user_input}"
Aura (AI) trả lời: "{aura_reply}"

Trả về DUY NHẤT một JSON object:
{{
  "relations": [
    {{"source": "Thực thể A", "relation": "quan hệ ngắn gọn", "target": "Thực thể B",
      "valence": <float -1.0 (ghét) đến 1.0 (yêu)>}}
  ],
  "values": [
    {{"value": "Tên giá trị ngắn gọn (vd: Sự Thành Thật)", "sentiment": <float -1.0 đến 1.0>}}
  ],
  "open_loops": [
    {{"owner": "user" | "aura", "about": "việc gì, ngắn gọn",
      "keyword": "1-3 từ đặc trưng để nhận ra chủ đề (vd: phỏng vấn)",
      "due": "YYYY-MM-DD" | "YYYY-MM-DD HH:MM" | null}}
  ],
  "user_busy": {{"until": "YYYY-MM-DD HH:MM", "reason": "..."}} | null
}}

Quy tắc:
- relations: quan hệ xã hội giữa người/tổ chức. User nhắc về bản thân thì source là "User". Không có thì [].
- values: chỉ khi User thể hiện THÁI ĐỘ RÕ RÀNG với một giá trị đạo đức/quan điểm sống (tối đa {MAX_VALUES}). Không có thì [].
- open_loops: chỉ những việc CỤ THỂ còn bỏ ngỏ trong tương lai:
  * owner "user": sự kiện sắp tới của User (thi, phỏng vấn, đi khám, gặp ai...). Tự quy ngày tương đối ("thứ 4 này", "mai") ra ngày thật dựa vào thời điểm hiện tại.
  * owner "aura": lời Aura HỨA sẽ làm sau (kể tiếp, nhắc, hỏi lại...).
  Không có thì []. Tối đa 3.
- user_busy: chỉ khi User NÓI RÕ mình đang/ sắp bận đến lúc nào (đi họp, đi ngủ, lái xe...). Không thì null.
- Không suy diễn, không bịa."""


def _validated_values(items):
    if not isinstance(items, list) or len(items) > MAX_VALUES:
        raise ValueError(f"values must be an array of at most {MAX_VALUES} items")
    validated = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("value extraction item must be an object")
        raw_name, sentiment = item.get("value"), item.get("sentiment")
        if not isinstance(raw_name, str):
            raise ValueError("value name must be a string")
        name = raw_name.strip()
        if not 1 <= len(name) <= 80:
            raise ValueError("value name length is invalid")
        if (
            isinstance(sentiment, bool)
            or not isinstance(sentiment, (int, float))
            or not math.isfinite(float(sentiment))
            or not -1.0 <= float(sentiment) <= 1.0
        ):
            raise ValueError("value sentiment is invalid")
        validated.append((name, float(sentiment)))
    from core.value_system import ValueSystem

    # Validate the whole batch with ValueSystem's rules before filtering out
    # low-signal items, so a malformed item can never let a partial batch in.
    return ValueSystem.validate_user_value_updates(validated)


def _apply_values(engine, items) -> None:
    value_system = getattr(engine, "value_system", None)
    if value_system is None:
        return
    material = [
        (name, sentiment)
        for name, sentiment in _validated_values(items)
        if abs(sentiment) >= MATERIAL_VALUE_SENTIMENT
    ]
    if material:
        value_system.update_user_values_batch(material)


def _apply_open_loops(engine, items, now: float) -> None:
    prospective = getattr(engine, "prospective", None)
    if prospective is None or not items:
        return
    for intention in prospective.add(items, now):
        logger.info("Open loop remembered owner=%s", intention.owner)


def _apply_busy(engine, busy, now: float) -> None:
    prospective = getattr(engine, "prospective", None)
    if prospective is None or not busy:
        return
    if not isinstance(busy, dict):
        raise ValueError("user_busy must be an object or null")
    prospective.set_busy(busy.get("until"), str(busy.get("reason") or "bận"), now)


def run_enrichment(engine, user_input: str, aura_reply: str, now: float, *,
                   model_override=None, force_local: bool = False) -> dict:
    """Extract and apply; returns {section: ok} for observability."""
    payload, _ = engine.llm.generate_json(
        build_prompt(user_input, aura_reply, now),
        temperature=0.1,
        model_override=model_override,
        force_local=force_local,
        bio_throttle=False,
    )
    if not isinstance(payload, dict):
        raise ValueError("enrichment payload must be an object")

    sections = (
        ("relations", lambda: engine.world_graph.apply_extraction(
            {"relations": payload.get("relations", [])})),
        ("values", lambda: _apply_values(engine, payload.get("values", []))),
        ("open_loops", lambda: _apply_open_loops(engine, payload.get("open_loops", []), now)),
        ("user_busy", lambda: _apply_busy(engine, payload.get("user_busy"), now)),
    )
    outcome = {}
    for name, apply in sections:
        try:
            result = apply()
            outcome[name] = result is not False
        except Exception as exc:
            outcome[name] = False
            logger.warning("Enrichment section %s rejected cause_type=%s", name, type(exc).__name__)
    return outcome
