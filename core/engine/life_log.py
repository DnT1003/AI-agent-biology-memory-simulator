"""What Aura actually did between conversations.

A short in-memory diary of real events (chapters read, sleep, pings sent,
worrying, mind-wandering). When the owner comes back after a while, the
prompt gets "since we last talked, you ..." built only from these entries, so
she can say what she has been up to without inventing a life.
"""

import collections
import datetime as _dt
import threading

MAX_ENTRIES = 60
MAX_LINES = 6
# Below this gap the conversation is still ongoing; no recap.
RECAP_AFTER_SECONDS = 3600


class LifeLog:
    def __init__(self):
        self._lock = threading.Lock()
        self._entries = collections.deque(maxlen=MAX_ENTRIES)

    def add(self, kind: str, text: str, now: float) -> None:
        text = " ".join(str(text or "").split())[:140]
        if text:
            with self._lock:
                self._entries.append((float(now), kind, text))

    def since(self, start: float) -> list[tuple[float, str, str]]:
        with self._lock:
            return [entry for entry in self._entries if entry[0] > start]

    def recap_lines(self, start: float, limit: int = MAX_LINES) -> list[str]:
        entries = self.since(start)
        lines = []
        reads = [text for _, kind, text in entries if kind == "read"]
        if reads:
            more = f" (và {len(reads) - 1} đoạn khác)" if len(reads) > 1 else ""
            lines.append(f"đọc sách: {reads[-1]}{more}")
        for ts, kind, text in entries:
            if kind == "read":
                continue
            at = _dt.datetime.fromtimestamp(ts).strftime("%H:%M")
            lines.append(f"{at} {text}")
        return lines[-limit:] if len(lines) > limit else lines


LATE_REPLY_SECONDS = 10 * 60
_MAX_PENDING_RECEIPTS = 200


def note_message_received(engine, request_id, received_at: float) -> None:
    """Remember when a transport received a message, keyed by its request id."""
    if not request_id:
        return
    receipts = getattr(engine, "message_received_at", None)
    if not isinstance(receipts, dict):
        receipts = {}
        engine.message_received_at = receipts
    receipts[str(request_id)] = float(received_at)
    while len(receipts) > _MAX_PENDING_RECEIPTS:
        receipts.pop(next(iter(receipts)))


def late_reply_prompt(engine, request_id, now: float) -> str:
    """'[TRẢ LỜI MUỘN] ...' when the message waited, with the real reason."""
    receipts = getattr(engine, "message_received_at", None)
    if not request_id or not isinstance(receipts, dict):
        return ""
    received_at = receipts.pop(str(request_id), None)
    if received_at is None or now - received_at < LATE_REPLY_SECONDS:
        return ""
    from core.temporal import fuzzy_duration

    # Only real reasons: she was asleep when it arrived, or reading since.
    reasons = []
    ego = getattr(engine, "ego", None)
    intervals = getattr(ego, "sleep_intervals", None) or []
    if any(onset <= received_at < wake for onset, wake in intervals):
        reasons.append("đang ngủ")
    if any(kind == "read" for _, kind, _ in life_log_of(engine).since(received_at)):
        reasons.append("đang đọc sách")
    because = (
        f"Lúc tin đến bạn {' rồi '.join(reasons)} nên giờ mới thấy."
        if reasons else "Bạn chưa để ý tin này tới giờ (đừng bịa lý do)."
    )
    return (
        f"[TRẢ LỜI MUỘN]: Tin này User gửi {fuzzy_duration(now - received_at)} trước. "
        f"{because} Có thể nói tự nhiên là mình giờ mới thấy tin."
    )


ACTIVITY_WINDOW_SECONDS = {"wake": 45 * 60, "read": 30 * 60}


def activity_prompt(engine, now: float) -> str:
    """What she was just doing, from the diary only ('' if nothing recent)."""
    entries = life_log_of(engine).since(now - max(ACTIVITY_WINDOW_SECONDS.values()))
    for ts, kind, text in reversed(entries):
        window = ACTIVITY_WINDOW_SECONDS.get(kind)
        if window is None or now - ts > window:
            continue
        at = _dt.datetime.fromtimestamp(ts).strftime("%H:%M")
        if kind == "wake":
            return f"[BẠN ĐANG]: vừa ngủ dậy lúc {at}, còn hơi ngái ngủ."
        return f"[BẠN ĐANG]: vừa gấp sách lại sau khi đọc {text} (lúc {at})."
    return ""


def life_log_of(engine) -> LifeLog:
    log = getattr(engine, "life_log", None)
    if not isinstance(log, LifeLog):
        log = LifeLog()
        engine.life_log = log
    return log


def recap_prompt(engine, previous_contact, now: float) -> str:
    """'[TỪ LẦN CUỐI NÓI CHUYỆN ...]' block, or '' when the talk is ongoing."""
    if previous_contact is None or now - float(previous_contact) < RECAP_AFTER_SECONDS:
        return ""
    from core.temporal import fuzzy_duration

    lines = life_log_of(engine).recap_lines(float(previous_contact))
    body = "\n".join(f"- {line}" for line in lines) if lines else "- không có gì đặc biệt"
    return (
        f"[TỪ LẦN CUỐI NÓI CHUYỆN — {fuzzy_duration(now - float(previous_contact))} trước]: "
        "Trong lúc đó bạn đã (chỉ những điều này là có thật, đừng bịa thêm):\n" + body
    )
