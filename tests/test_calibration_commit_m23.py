import json
import math
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from config import Config
from core.engine.memory_ops import CalibrationError, MemoryOperationsController
from core.self_model import SelfModel


_CALIBRATION_FIELDS = (
    "stress_critical",
    "fatigue_critical",
    "resilience",
)


def _new_self_model():
    with patch.object(SelfModel, "load_identity"), patch.object(
        SelfModel,
        "reroll_thresholds",
    ), patch.object(SelfModel, "_check_environment"):
        return SelfModel(memory_manager=None)


def _snapshot(ego):
    return {
        "attributes": {
            field: getattr(ego, field)
            for field in _CALIBRATION_FIELDS
        },
        "overrides": dict(ego.calibrated_overrides),
    }


def _controller(raw_response, ego=None):
    ego = ego or _new_self_model()
    controller = object.__new__(MemoryOperationsController)
    controller.engine = SimpleNamespace(
        ego=ego,
        stm_lock=threading.Lock(),
        short_term_buffer=["bounded calibration context"],
        llm=SimpleNamespace(
            generate_text=Mock(return_value=(raw_response, {})),
        ),
    )
    return controller


class CalibrationCommitTests(unittest.TestCase):
    def test_valid_plan_is_committed_to_ram_and_disk(self):
        ego = _new_self_model()
        response = json.dumps({
            "analysis": "bounded rationale",
            "updates": {
                "stress_critical": 1.25,
                "fatigue_critical": 1.5,
                "resilience": 0.75,
            },
        })
        controller = _controller(response, ego)

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "ego.json"
            with patch.object(Config, "EGO_STATE_FILE", str(state_path)), patch(
                "builtins.print"
            ):
                controller._calibration_phase()
            persisted = json.loads(state_path.read_text(encoding="utf-8"))

        self.assertEqual(ego.stress_critical, 1.25)
        self.assertEqual(ego.fatigue_critical, 1.5)
        self.assertEqual(ego.resilience, 0.75)
        self.assertEqual(
            ego.calibrated_overrides,
            {
                "stress_critical": 1.25,
                "fatigue_critical": 1.5,
                "resilience": 0.75,
            },
        )
        self.assertEqual(persisted["stress_critical"], 1.25)
        self.assertEqual(persisted["fatigue_critical"], 1.5)
        self.assertEqual(persisted["resilience"], 0.75)
        self.assertEqual(
            persisted["calibrated_overrides"],
            ego.calibrated_overrides,
        )

    def test_malformed_later_field_leaves_everything_unchanged(self):
        ego = _new_self_model()
        ego.calibrated_overrides = {"stress_critical": 0.91}
        before = _snapshot(ego)
        response = json.dumps({
            "analysis": "invalid second update",
            "updates": {
                "stress_critical": 1.2,
                "resilience": "not-a-number",
            },
        })
        controller = _controller(response, ego)

        with patch("core.utils.atomic_write_json") as write, patch(
            "builtins.print"
        ):
            with self.assertRaises(CalibrationError) as raised:
                controller._calibration_phase()

        self.assertEqual(raised.exception.phase, "validation")
        self.assertEqual(_snapshot(ego), before)
        write.assert_not_called()

    def test_lock_and_other_unknown_fields_are_rejected_before_mutation(self):
        ego = _new_self_model()
        original_lock = ego.lock
        before = _snapshot(ego)
        response = json.dumps({
            "updates": {
                "stress_critical": 1.2,
                "lock": 0.0,
            },
        })

        with patch("builtins.print"):
            with self.assertRaises(CalibrationError) as raised:
                _controller(response, ego)._calibration_phase()

        self.assertEqual(raised.exception.phase, "validation")
        self.assertIs(ego.lock, original_lock)
        self.assertEqual(_snapshot(ego), before)

    def test_boolean_nan_infinity_and_out_of_range_are_rejected(self):
        responses = (
            json.dumps({"updates": {"resilience": True}}),
            '{"updates":{"resilience":NaN}}',
            '{"updates":{"resilience":Infinity}}',
            json.dumps({"updates": {"resilience": 1.01}}),
            json.dumps({"updates": {"fatigue_critical": -0.01}}),
        )
        for response in responses:
            with self.subTest(response=response):
                ego = _new_self_model()
                before = _snapshot(ego)
                with patch("builtins.print"):
                    with self.assertRaises(CalibrationError) as raised:
                        _controller(response, ego)._calibration_phase()
                self.assertEqual(raised.exception.phase, "validation")
                self.assertEqual(_snapshot(ego), before)

    def test_save_failure_restores_attributes_and_override_object_exactly(self):
        ego = _new_self_model()
        ego.stress_critical = 0.93
        ego.fatigue_critical = 1.1
        ego.resilience = 0.2
        overrides = ego.calibrated_overrides
        overrides.update({
            "fatigue_critical": 1.1,
            "stress_critical": 0.93,
        })
        before = _snapshot(ego)
        controller = _controller(json.dumps({
            "updates": {
                "stress_critical": 1.3,
                "resilience": 0.8,
            },
        }), ego)

        with patch(
            "core.utils.atomic_write_json",
            side_effect=OSError("secret storage detail"),
        ), patch("builtins.print"):
            with self.assertRaises(CalibrationError) as raised:
                controller._calibration_phase()

        self.assertEqual(raised.exception.phase, "commit")
        self.assertEqual(raised.exception.cause_type, "OSError")
        self.assertNotIn("secret", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIs(ego.calibrated_overrides, overrides)
        self.assertEqual(_snapshot(ego), before)

    def test_base_exception_during_write_also_restores_exact_ram(self):
        ego = _new_self_model()
        ego.calibrated_overrides = {"resilience": 0.1}
        overrides = ego.calibrated_overrides
        before = _snapshot(ego)
        controller = _controller(json.dumps({
            "updates": {"resilience": 0.9},
        }), ego)

        with patch(
            "core.utils.atomic_write_json",
            side_effect=KeyboardInterrupt(),
        ), patch("builtins.print"):
            with self.assertRaises(KeyboardInterrupt):
                controller._calibration_phase()

        self.assertIs(ego.calibrated_overrides, overrides)
        self.assertEqual(_snapshot(ego), before)

    def test_oversized_analysis_fails_safely_without_payload_in_error(self):
        secret = "private-calibration-text"
        response = json.dumps({
            "analysis": secret + ("x" * 4_096),
            "updates": {"resilience": 0.8},
        })
        ego = _new_self_model()
        before = _snapshot(ego)

        with patch("builtins.print"):
            with self.assertRaises(CalibrationError) as raised:
                _controller(response, ego)._calibration_phase()

        self.assertEqual(raised.exception.phase, "validation")
        self.assertNotIn(secret, str(raised.exception))
        self.assertEqual(_snapshot(ego), before)

    def test_empty_update_object_is_a_valid_no_op(self):
        ego = _new_self_model()
        before = _snapshot(ego)
        with patch("core.utils.atomic_write_json") as write, patch(
            "builtins.print"
        ):
            result = _controller('{"analysis":"none","updates":{}}', ego)
            self.assertIsNone(result._calibration_phase())

        self.assertEqual(_snapshot(ego), before)
        write.assert_not_called()

    def test_threshold_order_violation_is_rejected_before_mutation(self):
        ego = _new_self_model()
        ego.stress_severe = 0.8
        ego.stress_critical = 0.9
        overrides = ego.calibrated_overrides
        before = _snapshot(ego)
        controller = _controller(json.dumps({
            "updates": {"stress_critical": 0.7},
        }), ego)

        with patch("core.utils.atomic_write_json") as write, patch(
            "builtins.print"
        ):
            with self.assertRaises(CalibrationError) as raised:
                controller._calibration_phase()

        self.assertEqual(raised.exception.phase, "commit")
        self.assertEqual(raised.exception.cause_type, "ValueError")
        self.assertIs(ego.calibrated_overrides, overrides)
        self.assertEqual(_snapshot(ego), before)
        write.assert_not_called()

    def test_legacy_fake_save_failure_rolls_back_without_relocking(self):
        ego = SimpleNamespace(
            lock=threading.Lock(),
            mood=0.0,
            stress=0.2,
            fatigue=0.3,
            integrity=1.0,
            stress_critical=0.9,
            fatigue_critical=1.0,
            resilience=0.1,
            calibrated_overrides={"fatigue_critical": 1.0},
        )

        def save_state():
            if not ego.lock.acquire(blocking=False):
                raise AssertionError("save_state was called under ego.lock")
            ego.lock.release()
            raise OSError("legacy save failed")

        ego.save_state = save_state
        before = _snapshot(ego)
        controller = _controller(json.dumps({
            "updates": {"stress_critical": 1.2, "resilience": 0.7},
        }), ego)

        with patch("builtins.print"):
            with self.assertRaises(CalibrationError) as raised:
                controller._calibration_phase()

        self.assertEqual(raised.exception.phase, "commit")
        self.assertEqual(raised.exception.cause_type, "OSError")
        self.assertEqual(_snapshot(ego), before)
        self.assertFalse(ego.lock.locked())


if __name__ == "__main__":
    unittest.main()
