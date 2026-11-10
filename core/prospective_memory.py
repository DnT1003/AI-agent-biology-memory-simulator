"""Prospective memory: things still open that Aura should come back to.

Two directions, like between people:

* the owner's open loops: "thứ 4 anh phỏng vấn" -> after Wednesday, ask how it went;
* Aura's own promises: "mai em kể tiếp chương này" -> keep the promise.

It also remembers an explicit "I'm busy until ..." so she doesn't ping into a
meeting. Items come only from what was actually said (the enrichment
extraction), expire when stale, and are stored as a small JSON file.
"""

from __future__ import annotations

import datetime as _dt
import math
import threading
import uuid
from dataclasses import asdict, dataclass
from typing import Optional

OWNERS = ("user", "aura")
MAX_ITEMS = 50
# Ask about an owner's event once it is over, while it is still fresh.
FOLLOW_UP_AFTER_SECONDS = 2 * 3600
FOLLOW_UP_WINDOW_SECONDS = 3 * 86400
# Mention an owner's upcoming event from the day before.
LEAD_SECONDS = 86400
# Undated items (and anything) fade after two weeks.
STALE_SECONDS = 14 * 86400
MAX_BUSY_SECONDS = 12 * 3600


@dataclass
class Intention:
    id: str
    owner: str
    about: str
    keyword: str
    due_ts: Optional[float]
    created_ts: float
    status: str = "open"  # open | followed | expired
    followed_ts: Optional[float] = None


def parse_due(value) -> Optional[float]:
    """'YYYY-MM-DD' (end of that day's evening) or 'YYYY-MM-DD HH:MM'."""
    if value in (None, "", "null"):
        return None
    if not isinstance(value, str):
        raise ValueError("due must be a date string or null")
    value = value.strip()
    for fmt, default_hour in (("%Y-%m-%d %H:%M", None), ("%Y-%m-%d", 18)):
        try:
            moment = _dt.datetime.strptime(value, fmt)
        except ValueError:
            continue
        if default_hour is not None:
            moment = moment.replace(hour=default_hour)
        return moment.timestamp()
    raise ValueError(f"unrecognised due date: {value!r}")


def _clean_text(value, limit: int, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be text")
    value = " ".join(value.split())
    if not 1 <= len(value) <= limit:
        raise ValueError(f"{field} length is invalid")
    return value


class ProspectiveMemory:
    def __init__(self, path: Optional[str] = None):
        self.path = path
        self.lock = threading.Lock()
        self.items: list[Intention] = []
        self.busy_until: float = 0.0
        self.busy_reason: str = ""
        self._load()

    # ---------------------------------------------------------------- storage
    def _load(self):
        if not self.path:
            return
        import json
        import os

        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            items = [Intention(**item) for item in data.get("items", [])]
            self.items = [i for i in items if i.owner in OWNERS][-MAX_ITEMS:]
            busy = float(data.get("busy_until", 0.0) or 0.0)
            self.busy_until = busy if math.isfinite(busy) else 0.0
            self.busy_reason = str(data.get("busy_reason", ""))[:120]
        except (OSError, ValueError, TypeError):
            self.items = []

    def _save_unlocked(self):
        if not self.path:
            return
        from core.utils import atomic_write_json

        atomic_write_json(self.path, {
            "items": [asdict(i) for i in self.items],
            "busy_until": self.busy_until,
            "busy_reason": self.busy_reason,
        })

    # ----------------------------------------------------------------- writes
    @staticmethod
    def validate(items) -> list[dict]:
        """Validate a whole extraction batch before anything is stored."""
        if not isinstance(items, list) or len(items) > 3:
            raise ValueError("open_loops must be a list of at most 3 items")
        cleaned = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("open loop must be an object")
            owner = item.get("owner")
            if owner not in OWNERS:
                raise ValueError("open loop owner must be 'user' or 'aura'")
            cleaned.append({
                "owner": owner,
                "about": _clean_text(item.get("about"), 120, "about"),
                "keyword": _clean_text(item.get("keyword"), 40, "keyword").lower(),
                "due_ts": parse_due(item.get("due")),
            })
        return cleaned

    def add(self, items, now: float) -> list[Intention]:
        cleaned = self.validate(items)
        added = []
        with self.lock:
            self._expire_unlocked(now)
            for item in cleaned:
                existing = next(
                    (i for i in self.items
                     if i.status == "open" and i.owner == item["owner"] and i.keyword == item["keyword"]),
                    None,
                )
                if existing is not None:
                    existing.about = item["about"]
                    existing.due_ts = item["due_ts"] or existing.due_ts
                    continue
                intention = Intention(
                    id=uuid.uuid4().hex, created_ts=now, **item,
                )
                self.items.append(intention)
                added.append(intention)
            self.items = self.items[-MAX_ITEMS:]
            self._save_unlocked()
        return added

    def set_busy(self, until, reason: str, now: float) -> None:
        until_ts = parse_due(until) if isinstance(until, str) else until
        if until_ts is None:
            return
        until_ts = min(float(until_ts), now + MAX_BUSY_SECONDS)
        if until_ts <= now:
            return
        with self.lock:
            self.busy_until = until_ts
            self.busy_reason = _clean_text(reason or "bận", 120, "reason")
            self._save_unlocked()

    def is_busy(self, now: float) -> bool:
        return self.busy_until > now

    def mark_followed(self, intention_id: str, now: float) -> None:
        with self.lock:
            for item in self.items:
                if item.id == intention_id and item.status == "open":
                    item.status, item.followed_ts = "followed", now
            self._save_unlocked()

    def mark_mentioned(self, text: str, now: float) -> list[Intention]:
        """Aura brought these up herself in ``text``: they are followed up."""
        lowered = str(text or "").lower()
        hits = []
        with self.lock:
            for item in self._relevant_unlocked(now):
                # Wishing luck before the event does not close it: only asking
                # afterwards (or keeping a promise) counts as following up.
                upcoming = item.owner == "user" and item.due_ts is not None and item.due_ts > now
                if item.keyword in lowered and not upcoming:
                    item.status, item.followed_ts = "followed", now
                    hits.append(item)
            if hits:
                self._save_unlocked()
        return hits

    # ------------------------------------------------------------------ reads
    def _expire_unlocked(self, now: float) -> None:
        for item in self.items:
            if item.status != "open":
                continue
            too_old = now - item.created_ts > STALE_SECONDS
            past_window = item.due_ts is not None and now - item.due_ts > FOLLOW_UP_WINDOW_SECONDS
            if too_old or past_window:
                item.status = "expired"

    def _relevant_unlocked(self, now: float) -> list[Intention]:
        self._expire_unlocked(now)
        relevant = []
        for item in self.items:
            if item.status != "open":
                continue
            if item.due_ts is None or item.due_ts - LEAD_SECONDS <= now:
                relevant.append(item)
        return relevant

    def relevant(self, now: float) -> list[Intention]:
        with self.lock:
            return list(self._relevant_unlocked(now))

    def due_follow_ups(self, now: float) -> list[Intention]:
        """Owner events that are over: time to ask how it went."""
        return [
            item for item in self.relevant(now)
            if item.owner == "user"
            and item.due_ts is not None
            and now - item.due_ts >= FOLLOW_UP_AFTER_SECONDS
        ]

    def context_lines(self, now: float) -> list[str]:
        from core.temporal import fuzzy_age

        lines = []
        for item in self.relevant(now):
            if item.owner == "user":
                if item.due_ts is not None and item.due_ts > now:
                    lines.append(f"- User sắp có việc: {item.about} (bạn biết từ {fuzzy_age(item.created_ts, now)})")
                else:
                    lines.append(f"- User đã có việc: {item.about} — chưa hỏi xem kết quả thế nào")
            else:
                lines.append(f"- Bạn đã hứa với User: {item.about} ({fuzzy_age(item.created_ts, now)})")
        if self.is_busy(now):
            lines.append(f"- User đang bận ({self.busy_reason}), nên nhắn ngắn hoặc để sau")
        return lines
