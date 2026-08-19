import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.self_model import SelfModel, _PERSISTED_STATE_FIELDS


_SNAPSHOT_FIELDS = tuple(
    field
    for field in _PERSISTED_STATE_FIELDS
    if field != "sensitivities"
)


def _new_self_model():
    with patch.object(SelfModel, "load_identity"), patch.object(
        SelfModel, "reroll_thresholds"
    ), patch.object(SelfModel, "_check_environment"):
        return SelfModel(memory_manager=None)


def _snapshot(model):
    return {
        "state": {
            field: copy.deepcopy(getattr(model, field))
            for field in _SNAPSHOT_FIELDS
        },
        "sensitivities": copy.deepcopy(model.bio_controller.sensitivities),
        "lock": model.lock,
        "memory_manager": model.memory_manager,
        "bio_controller": model.bio_controller,
        "sensitivity_object": model.bio_controller.sensitivities,
    }


def _assert_snapshot(test_case, model, before):
    test_case.assertEqual(
        {
            field: copy.deepcopy(getattr(model, field))
            for field in _SNAPSHOT_FIELDS
        },
        before["state"],
    )
    test_case.assertEqual(
        model.bio_controller.sensitivities,
        before["sensitivities"],
    )
    test_case.assertIs(model.lock, before["lock"])
    test_case.assertIs(model.memory_manager, before["memory_manager"])
    test_case.assertIs(model.bio_controller, before["bio_controller"])
    test_case.assertIs(
        model.bio_controller.sensitivities,
        before["sensitivity_object"],
    )


class SelfModelLoadTransactionTests(unittest.TestCase):
    def _load_payload(self, model, payload, *, raw=False):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "ego.json"
            text = payload if raw else json.dumps(payload)
            state_path.write_text(text, encoding="utf-8")
            with patch("core.self_model.time.time", return_value=10_000.0), patch(
                "core.self_model.os.path.getmtime", return_value=10_000.0
            ):
                return model.load_state(str(state_path))

    def test_operational_attribute_injection_rejects_entire_payload(self):
        model = _new_self_model()
        model.mood = -0.25
        before = _snapshot(model)

        with patch("builtins.print") as output:
            result = self._load_payload(model, {
                "mood": 0.9,
                "lock": "private-lock-payload",
            })

        self.assertFalse(result)
        _assert_snapshot(self, model, before)
        output.assert_not_called()

    def test_malformed_later_field_cannot_partially_replace_state(self):
        model = _new_self_model()
        model.mood = -0.4
        model.bio_controller.sensitivities["stress"] = 1.3
        before = _snapshot(model)

        result = self._load_payload(model, {
            "mood": 0.8,
            "sensitivities": {"stress": 1.1},
            "actionable_lessons": ["private lesson", 7],
        })

        self.assertFalse(result)
        _assert_snapshot(self, model, before)

    def test_boolean_and_non_finite_numbers_fail_without_mutation(self):
        payloads = (
            json.dumps({"mood": 0.75, "stress": True}),
            '{"mood":0.75,"stress":NaN}',
            '{"mood":0.75,"sensitivities":{"stress":Infinity}}',
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                model = _new_self_model()
                before = _snapshot(model)
                self.assertFalse(self._load_payload(model, payload, raw=True))
                _assert_snapshot(self, model, before)

    def test_invalid_calibrated_override_never_reaches_setattr(self):
        for updates in (
            {"lock": 0.0},
            {"memory_manager": 0.0},
            {"resilience": 1.01},
        ):
            with self.subTest(updates=updates):
                model = _new_self_model()
                before = _snapshot(model)
                result = self._load_payload(model, {
                    "mood": 0.7,
                    "calibrated_overrides": updates,
                })
                self.assertFalse(result)
                _assert_snapshot(self, model, before)

    def test_invalid_threshold_invariant_is_rejected_as_one_unit(self):
        model = _new_self_model()
        before = _snapshot(model)

        result = self._load_payload(model, {
            "mood": 0.5,
            "stress_mild": 0.8,
            "stress_severe": 0.7,
            "stress_critical": 0.9,
        })

        self.assertFalse(result)
        _assert_snapshot(self, model, before)

    def test_complete_invalid_sleep_clock_rejects_other_updates(self):
        model = _new_self_model()
        before = _snapshot(model)

        result = self._load_payload(model, {
            "mood": 0.5,
            "last_slept_time": 500.0,
            "days_without_sleep": True,
            "_sleep_warning_cooldown": False,
        })

        self.assertFalse(result)
        _assert_snapshot(self, model, before)

    def test_partial_malformed_sleep_clock_rejects_other_updates(self):
        model = _new_self_model()
        before = _snapshot(model)

        result = self._load_payload(model, {
            "mood": 0.5,
            "days_without_sleep": True,
        })

        self.assertFalse(result)
        _assert_snapshot(self, model, before)

    def test_legacy_missing_fields_and_partial_clock_are_supported(self):
        model = _new_self_model()
        model.last_slept_time = 999.0
        model.days_without_sleep = 7
        model._sleep_warning_cooldown = True
        sensitivities = model.bio_controller.sensitivities

        result = self._load_payload(model, {
            "mood": 0.25,
            "stress": 0.2,
            "last_slept_time": 123.0,
        })

        self.assertTrue(result)
        self.assertEqual(model.mood, 0.25)
        self.assertEqual(model.stress, 0.2)
        self.assertEqual(model.last_slept_time, 999.0)
        self.assertEqual(model.days_without_sleep, 7)
        self.assertIs(model._sleep_warning_cooldown, True)
        self.assertIs(model.bio_controller.sensitivities, sensitivities)

    def test_offline_recovery_is_finite_and_uses_staged_values(self):
        model = _new_self_model()
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "ego.json"
            state_path.write_text(
                json.dumps({"stress": 0.8, "fatigue": 0.7}),
                encoding="utf-8",
            )
            with patch("core.self_model.time.time", return_value=10_000.0), patch(
                "core.self_model.os.path.getmtime", return_value=2_800.0
            ), patch("builtins.print"):
                result = model.load_state(str(state_path))

        self.assertTrue(result)
        self.assertAlmostEqual(model.stress, 0.6)
        self.assertAlmostEqual(model.fatigue, 0.4)

    def test_valid_saved_payload_round_trips_with_allowlisted_overrides(self):
        source = _new_self_model()
        source.mood = 0.3
        source.stress = 0.4
        source.fatigue = 0.5
        source.resilience = 0.6
        source.stress_critical = 1.25
        source.calibrated_overrides = {
            "stress_critical": 1.25,
            "resilience": 0.6,
        }
        source.long_term_goals = [{
            "title": "Verify persisted state",
            "progress": 25,
            "status": "active",
        }]
        source.actionable_lessons = ["Validate before applying"]
        source.bio_controller.sensitivities = {
            "stress": 1.2,
            "fatigue": 0.9,
            "empathy": 1.1,
            "dopamine": 1.0,
        }

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "ego.json"
            source.save_state(str(state_path))
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            target = _new_self_model()
            target_lock = target.lock
            target_controller = target.bio_controller
            with patch("core.self_model.time.time", return_value=20_000.0), patch(
                "core.self_model.os.path.getmtime", return_value=20_000.0
            ):
                result = target.load_state(str(state_path))

        self.assertEqual(set(persisted), _PERSISTED_STATE_FIELDS)
        self.assertTrue(result)
        self.assertEqual(target.mood, 0.3)
        self.assertEqual(target.stress, 0.4)
        self.assertEqual(target.fatigue, 0.5)
        self.assertEqual(target.resilience, 0.6)
        self.assertEqual(target.stress_critical, 1.25)
        self.assertEqual(target.long_term_goals, source.long_term_goals)
        self.assertEqual(target.actionable_lessons, source.actionable_lessons)
        self.assertEqual(
            target.bio_controller.sensitivities,
            source.bio_controller.sensitivities,
        )
        self.assertIs(target.lock, target_lock)
        self.assertIs(target.bio_controller, target_controller)

    def test_save_never_emits_state_that_loader_would_reject(self):
        model = _new_self_model()
        model.stress_severe = 0.8
        model.stress_critical = 0.7

        with patch("core.utils.atomic_write_json") as write:
            with self.assertRaises(ValueError):
                model.save_state("unused-ego-state.json")

        write.assert_not_called()

    def test_duplicate_keys_and_secret_payload_fail_silently(self):
        model = _new_self_model()
        before = _snapshot(model)
        raw = '{"mood":0.4,"mood":0.8,"actionable_lessons":["secret"]}'

        with patch("builtins.print") as output:
            result = self._load_payload(model, raw, raw=True)

        self.assertFalse(result)
        _assert_snapshot(self, model, before)
        output.assert_not_called()


if __name__ == "__main__":
    unittest.main()
