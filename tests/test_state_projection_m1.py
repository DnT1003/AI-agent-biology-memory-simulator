import json
import math
import threading
import unittest
from enum import Enum
from types import SimpleNamespace

from core.agent_state import AgentState, StateMachine
from core.state_projection import (
    apply_projection_patch,
    canonical_json,
    capture_state_projection,
    diff_projection,
    projection_hash,
    validate_projection,
)


class StateProjectionTests(unittest.TestCase):
    def _engine(self):
        ego = SimpleNamespace(
            lock=threading.Lock(),
            mood=0.25,
            stress=0.2,
            fatigue=1.2,
            integrity=0.9,
            curiosity=0.4,
            social_need=0.5,
            energy=0.8,
            atp_level=0.7,
            dopamine_level=0.6,
            resilience=0.1,
            is_identity_crisis=False,
            secret_text="must not be captured",
            long_term_goals=["also secret"],
        )
        return SimpleNamespace(
            state_machine=StateMachine(AgentState.IDLE),
            ego=ego,
            stm_lock=threading.Lock(),
            short_term_buffer=["private one", "private two"],
        )

    def test_capture_contains_only_safe_scalars_and_stm_count(self):
        projection = capture_state_projection(self._engine())

        self.assertEqual(projection["agent_state"], "IDLE")
        self.assertEqual(projection["stm"], {"count": 2})
        self.assertEqual(projection["ego"]["mood"], 0.25)
        serialized = canonical_json(projection)
        self.assertNotIn("secret", serialized)
        self.assertNotIn("private", serialized)
        self.assertNotIn("long_term_goals", projection["ego"])
        self.assertEqual(validate_projection(projection, stm_max_entries=2), ())

    def test_capture_never_nests_state_ego_and_stm_locks(self):
        tracker = {"depth": 0, "maximum": 0}

        class TrackingLock:
            def __enter__(self):
                tracker["depth"] += 1
                tracker["maximum"] = max(tracker["maximum"], tracker["depth"])

            def __exit__(self, *_args):
                tracker["depth"] -= 1

        class TrackingState:
            @property
            def state(self):
                with TrackingLock():
                    return AgentState.THINKING

        class LenOnly:
            def __len__(self):
                return 3

            def __iter__(self):
                raise AssertionError("STM content must not be inspected")

        engine = SimpleNamespace(
            state_machine=TrackingState(),
            ego=SimpleNamespace(lock=TrackingLock(), mood=0.0),
            stm_lock=TrackingLock(),
            short_term_buffer=LenOnly(),
        )

        projection = capture_state_projection(engine)
        self.assertEqual(projection["stm"]["count"], 3)
        self.assertEqual(tracker, {"depth": 0, "maximum": 1})

    def test_canonical_json_and_hash_are_order_independent(self):
        left = {"z": [1, True], "a": {"v": "Tiếng Việt"}}
        right = {"a": {"v": "Tiếng Việt"}, "z": [1, True]}

        self.assertEqual(
            canonical_json(left),
            '{"a":{"v":"Tiếng Việt"},"z":[1,true]}',
        )
        self.assertEqual(projection_hash(left), projection_hash(right))
        with self.assertRaises(ValueError):
            canonical_json({"bad": math.nan})

    def test_diff_is_deterministic_and_round_trips(self):
        before = {
            "a/b": {"old": 1, "remove": True},
            "list": [1, 2],
            "same": {"value": 1},
        }
        after = {
            "a/b": {"old": 2, "new~key": False},
            "list": [1, 3],
            "same": {"value": 1},
        }

        patch = diff_projection(before, after)
        self.assertEqual(
            patch,
            [
                {"op": "add", "path": "/a~1b/new~0key", "value": False},
                {"op": "replace", "path": "/a~1b/old", "value": 2},
                {"op": "remove", "path": "/a~1b/remove"},
                {"op": "replace", "path": "/list", "value": [1, 3]},
            ],
        )
        self.assertEqual(apply_projection_patch(before, patch), after)
        self.assertNotEqual(before, after)

    def test_diff_replaces_root_and_distinguishes_bool_from_int(self):
        self.assertEqual(
            diff_projection(True, 1),
            [{"op": "replace", "path": "", "value": 1}],
        )
        self.assertEqual(apply_projection_patch(True, diff_projection(True, 1)), 1)

    def test_validation_reports_all_core_invariants(self):
        projection = {
            "schema_version": 1,
            "agent_state": "NOT_A_STATE",
            "ego": {
                "mood": 1.1,
                "stress": -0.1,
                "integrity": math.inf,
                "fatigue": -0.2,
            },
            "stm": {"count": 4},
        }

        violations = validate_projection(projection, stm_max_entries=3)
        self.assertIn("agent_state is invalid: 'NOT_A_STATE'", violations)
        self.assertIn("ego.mood must be in [-1, 1]", violations)
        self.assertIn("ego.stress must be in [0, 1]", violations)
        self.assertIn("ego.integrity must be finite", violations)
        self.assertIn("ego.fatigue must be >= 0", violations)
        self.assertIn("stm.count must be <= 3", violations)


if __name__ == "__main__":
    unittest.main()
