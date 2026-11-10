import os
import json
import math
import threading
from numbers import Real
from typing import Dict
from colorama import Fore, Style
from core.logger import get_logger
from core.utils import atomic_write_json

logger = get_logger("value_system")

class ValueSystem:
    """Hệ thống Quản lý Giá trị & Đạo đức (Moral Compass)"""

    _MAX_VALUE_NAME_LENGTH = 256
    _MAX_VALUES = 2_000
    _MAX_STATE_BYTES = 2 * 1024 * 1024
    # Only the strongest values reach the prompt; the rest stay on disk.
    _MAX_PROMPT_VALUES = 8
    _NAME_PREFIXES = ("sự ", "tính ", "lòng ", "việc ")

    def __init__(self, filepath="outputs/values.json"):
        self.filepath = filepath
        self.lock = threading.Lock()
        # core_values: Điểm từ -1.0 (Cực ghét/Phản đối) đến 1.0 (Vô cùng đề cao)
        self.core_values: Dict[str, float] = {
            "Sự Trung thực": 0.8,
            "Sự Bạo lực": -0.9,
            "Tôn trọng quyền riêng tư": 0.7,
            "Sự Trung thành": 0.9,
            "Tính Ích kỷ": -0.6,
            "Bảo vệ kẻ yếu": 0.85
        }
        # user_values: Những giá trị mà Aura quan sát thấy User trân trọng
        self.user_values: Dict[str, float] = {}
        self.load()

    @classmethod
    def _validated_name(cls, value_name) -> str:
        if not isinstance(value_name, str):
            raise ValueError("value name must be a string")
        value_name = value_name.strip()
        if not value_name or len(value_name) > cls._MAX_VALUE_NAME_LENGTH:
            raise ValueError("value name has invalid length")
        if any(ord(character) < 32 for character in value_name):
            raise ValueError("value name contains control characters")
        return value_name

    @classmethod
    def _canonical_key(cls, value_name: str) -> str:
        """"Sự Trung thực", "trung  thực", "Tính trung thực" -> one key."""
        key = " ".join(value_name.casefold().split())
        for prefix in cls._NAME_PREFIXES:
            if key.startswith(prefix) and len(key) > len(prefix):
                return key[len(prefix):]
        return key

    @classmethod
    def _resolve_name(cls, values: Dict[str, float], value_name: str) -> str:
        """Reuse the existing spelling of a value instead of adding a near-duplicate."""
        key = cls._canonical_key(value_name)
        for existing in values:
            if cls._canonical_key(existing) == key:
                return existing
        return value_name

    @staticmethod
    def _validated_number(value, field: str, *, minimum: float, maximum: float) -> float:
        if isinstance(value, bool) or not isinstance(value, Real):
            raise ValueError(f"{field} must be numeric")
        value = float(value)
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(f"{field} is out of range")
        return value

    @classmethod
    def _validated_state_map(cls, value, field: str) -> Dict[str, float]:
        if not isinstance(value, dict) or len(value) > cls._MAX_VALUES:
            raise ValueError(f"invalid {field}")
        validated = {}
        for raw_name, raw_score in value.items():
            name = cls._validated_name(raw_name)
            if name in validated:
                raise ValueError(f"duplicate {field} name")
            validated[name] = cls._validated_number(
                raw_score,
                field,
                minimum=-1.0,
                maximum=1.0,
            )
        return validated

    @classmethod
    def _validated_state(
        cls,
        payload,
        *,
        fallback_core: Dict[str, float],
        fallback_user: Dict[str, float],
    ) -> tuple[Dict[str, float], Dict[str, float]]:
        if not isinstance(payload, dict):
            raise ValueError("value state must be an object")
        core_values = cls._validated_state_map(
            payload.get("core_values", fallback_core),
            "core_values",
        )
        user_values = cls._validated_state_map(
            payload.get("user_values", fallback_user),
            "user_values",
        )
        return core_values, user_values

    @staticmethod
    def _log_failure(operation: str, exc: BaseException) -> None:
        try:
            logger.error(
                "ValueSystem %s failed cause_type=%s",
                operation,
                type(exc).__name__,
            )
        except Exception:
            # Diagnostics must never change the operation's failure contract.
            pass

    def _update_value(
        self,
        values: Dict[str, float],
        value_name: str,
        sentiment: float,
        learning_rate: float,
    ) -> float:
        value_name = self._validated_name(value_name)
        sentiment = self._validated_number(
            sentiment,
            "sentiment",
            minimum=-1.0,
            maximum=1.0,
        )
        learning_rate = self._validated_number(
            learning_rate,
            "learning_rate",
            minimum=0.0,
            maximum=1.0,
        )

        with self.lock:
            value_name = self._resolve_name(values, value_name)
            if value_name not in values and len(values) >= self._MAX_VALUES:
                raise ValueError("value limit reached")
            snapshot = dict(values)
            try:
                if value_name in values:
                    current = self._validated_number(
                        values[value_name],
                        "current value",
                        minimum=-1.0,
                        maximum=1.0,
                    )
                    updated = current + (sentiment - current) * learning_rate
                else:
                    updated = sentiment
                values[value_name] = max(-1.0, min(1.0, updated))
                self._save_unsafe()
            except BaseException:
                values.clear()
                values.update(snapshot)
                raise
            return values[value_name]

    def update_core_value(self, value_name: str, sentiment: float, learning_rate: float = 0.1):
        """Tiến hóa (Evolve) giá trị cốt lõi của Aura dựa trên trải nghiệm."""
        committed_value = self._update_value(
            self.core_values,
            value_name,
            sentiment,
            learning_rate,
        )
        value_name = self._validated_name(value_name)
        print(f"{Fore.MAGENTA}⚖️ [VALUE SYSTEM]: Nhận thức giá trị '{value_name}' của Aura dịch chuyển thành {committed_value:.2f}{Style.RESET_ALL}")

    def update_user_value(self, value_name: str, sentiment: float, learning_rate: float = 0.2):
        """Ghi nhận giá trị mà User đề cao/phản đối."""
        self._update_value(
            self.user_values,
            value_name,
            sentiment,
            learning_rate,
        )

    @classmethod
    def validate_user_value_updates(cls, updates) -> list[tuple[str, float]]:
        """Validate and detach a complete candidate batch without mutation."""

        if type(updates) not in (list, tuple):
            raise ValueError("value updates must be a list or tuple")
        if len(updates) > cls._MAX_VALUES:
            raise ValueError("value update batch is too large")

        normalized = []
        names = set()
        for update in updates:
            if type(update) not in (list, tuple) or len(update) != 2:
                raise ValueError("value update must contain name and sentiment")
            name = cls._validated_name(update[0])
            if cls._canonical_key(name) in names:
                raise ValueError("value update batch contains a duplicate name")
            names.add(cls._canonical_key(name))
            sentiment = cls._validated_number(
                update[1],
                "sentiment",
                minimum=-1.0,
                maximum=1.0,
            )
            normalized.append((name, sentiment))
        return normalized

    def update_user_values_batch(
        self,
        updates,
        learning_rate: float = 0.2,
    ) -> Dict[str, float]:
        """Validate and persist one all-or-nothing user-value observation."""

        normalized_rate = self._validated_number(
            learning_rate,
            "learning_rate",
            minimum=0.0,
            maximum=1.0,
        )

        normalized = self.validate_user_value_updates(updates)

        if not normalized:
            return {}

        with self.lock:
            normalized = [
                (self._resolve_name(self.user_values, name), sentiment)
                for name, sentiment in normalized
            ]
            new_names = sum(name not in self.user_values for name, _ in normalized)
            if len(self.user_values) + new_names > self._MAX_VALUES:
                raise ValueError("value limit reached")

            snapshot = dict(self.user_values)
            candidate = dict(snapshot)
            for name, sentiment in normalized:
                if name in candidate:
                    current = self._validated_number(
                        candidate[name],
                        "current value",
                        minimum=-1.0,
                        maximum=1.0,
                    )
                    updated = current + (
                        sentiment - current
                    ) * normalized_rate
                else:
                    updated = sentiment
                candidate[name] = max(-1.0, min(1.0, updated))

            try:
                self.user_values.clear()
                self.user_values.update(candidate)
                self._save_unsafe()
            except BaseException:
                self.user_values.clear()
                self.user_values.update(snapshot)
                raise
            return {name: self.user_values[name] for name, _ in normalized}

    def get_moral_context(self) -> str:
        """Định dạng chuỗi giá trị để nhúng vào Prompt."""
        context = []
        with self.lock:
            core_values = dict(self.core_values)
            user_values = dict(self.user_values)
        # Chuyển đổi float thành text human-readable
        def float_to_desc(val):
            if val >= 0.8: return "Tuyệt đối bảo vệ/Tôn sùng"
            if val >= 0.4: return "Ủng hộ/Đề cao"
            if val > -0.4: return "Trung lập"
            if val > -0.8: return "Thấy phản cảm/Ghét"
            return "Căm thù/Cực lực lên án"

        def strongest(values):
            # Chỉ những giá trị rõ ràng nhất; không đưa cả nghìn mục vào prompt.
            clear = [(k, v) for k, v in values.items() if abs(v) >= 0.4]
            clear.sort(key=lambda item: abs(item[1]), reverse=True)
            return clear[:self._MAX_PROMPT_VALUES]

        context.append("- NHỮNG GIÁ TRỊ CỐT LÕI MÀ BẠN SỐNG CHẾT BẢO VỆ (MORAL COMPASS):")
        for k, v in strongest(core_values):
            context.append(f"  + {k}: {float_to_desc(v)} ({v:.2f})")

        user_lines = strongest(user_values)
        if user_lines:
            context.append("\n- NHỮNG GÌ BẠN QUAN SÁT THẤY USER QUAN TÂM:")
            for k, v in user_lines:
                context.append(f"  + {k}: {float_to_desc(v)} ({v:.2f})")
                    
        return "\n".join(context)

    def evaluate_action(self, action_desc: str, value_name: str) -> float:
        """Thẩm định một hành động dựa trên 1 value (Demo helper)"""
        with self.lock:
            return self.core_values.get(value_name, 0.0)

    def _save_unsafe(self) -> None:
        core_values, user_values = self._validated_state(
            {
                "core_values": self.core_values,
                "user_values": self.user_values,
            },
            fallback_core=self.core_values,
            fallback_user=self.user_values,
        )
        atomic_write_json(
            self.filepath,
            {
                "core_values": core_values,
                "user_values": user_values,
            },
        )

    def save(self):
        with self.lock:
            self._save_unsafe()

    def load(self):
        if not os.path.exists(self.filepath):
            return False
        try:
            with self.lock:
                if os.path.getsize(self.filepath) > self._MAX_STATE_BYTES:
                    raise ValueError("value state is too large")
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                core_values, user_values = self._validated_state(
                    data,
                    fallback_core=self.core_values,
                    fallback_user=self.user_values,
                )
                self.core_values.clear()
                self.core_values.update(core_values)
                self.user_values.clear()
                self.user_values.update(user_values)
            return True
        except Exception as exc:
            self._log_failure("load", exc)
            return False
