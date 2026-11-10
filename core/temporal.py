"""Human time words for Aura's prompts.

People remember *when* something happened only roughly ("hôm qua", "hồi đầu
tuần"), never as timestamps. These helpers turn epoch seconds into such fuzzy
Vietnamese labels so recalled memories and pauses in the conversation carry a
sense of time without sounding like a database.
"""

import datetime as _dt

_DAY = 86400
_WEEKDAYS = ("thứ Hai", "thứ Ba", "thứ Tư", "thứ Năm", "thứ Sáu", "thứ Bảy", "Chủ nhật")


def _part_of_day(hour: int) -> str:
    if hour < 5:
        return "đêm"
    if hour < 11:
        return "sáng"
    if hour < 14:
        return "trưa"
    if hour < 18:
        return "chiều"
    return "tối"


def fuzzy_age(then: float, now: float) -> str:
    """How long ago ``then`` was, the way a person would say it."""
    try:
        then, now = float(then), float(now)
    except (TypeError, ValueError):
        return "không nhớ rõ khi nào"
    seconds = now - then
    if seconds < 0:
        return "vừa nãy"
    if seconds < 3600:
        return "vừa nãy"
    then_dt, now_dt = _dt.datetime.fromtimestamp(then), _dt.datetime.fromtimestamp(now)
    days = (now_dt.date() - then_dt.date()).days
    if days == 0:
        if seconds < 3 * 3600:
            return "mấy tiếng trước"
        return f"{_part_of_day(then_dt.hour)} nay"
    if days == 1:
        return "đêm qua" if then_dt.hour >= 22 else f"{_part_of_day(then_dt.hour)} hôm qua"
    if days == 2:
        return "hôm kia"
    if days < 7:
        return "mấy hôm trước"
    if days < 14:
        return "tuần trước"
    if days < 30:
        return "vài tuần trước"
    if days < 60:
        return "tháng trước"
    if days < 365:
        return "mấy tháng trước"
    return "lâu lắm rồi"


def fuzzy_duration(seconds: float) -> str:
    """A rough amount of time ("gần 2 tiếng", "3 ngày")."""
    seconds = max(0.0, float(seconds))
    if seconds < 15 * 60:
        return "một lúc"
    if seconds < 50 * 60:
        return "chừng nửa tiếng"
    hours = seconds / 3600
    if hours < 1.5:
        return "khoảng một tiếng"
    if hours < 20:
        return f"khoảng {round(hours)} tiếng"
    days = hours / 24
    if days < 1.5:
        return "khoảng một ngày"
    return f"khoảng {round(days)} ngày"


def describe_now(now: float) -> str:
    """'tối thứ Ba, 20/10/2026 20:15' — a date the LLM can reason from."""
    moment = _dt.datetime.fromtimestamp(float(now))
    return (
        f"{_part_of_day(moment.hour)} {_WEEKDAYS[moment.weekday()]}, "
        f"{moment.strftime('%d/%m/%Y %H:%M')}"
    )
