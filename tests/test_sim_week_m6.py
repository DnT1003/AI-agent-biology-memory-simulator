import unittest

from core.sim_week import (
    DEFAULT_SCRIPT,
    QUIET_END,
    QUIET_START,
    ScriptedLLM,
    SimClock,
    _TimeProxy,
    format_report,
    run_week,
)


class SimClockTests(unittest.TestCase):
    def test_proxy_follows_the_simulated_clock(self):
        clock = SimClock(1_000.0)
        proxy = _TimeProxy(clock)
        start_mono = proxy.monotonic()
        clock.advance(90)
        self.assertEqual(proxy.time(), 1_090.0)
        self.assertEqual(proxy.monotonic() - start_mono, 90.0)
        # Everything else is the real time module.
        self.assertTrue(callable(proxy.perf_counter))


class WeekSimulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = run_week(seed=7, days=7)

    def test_every_owner_message_gets_a_reply(self):
        self.assertEqual(sum(d.user_messages for d in self.report.days), len(DEFAULT_SCRIPT))
        self.assertEqual(
            sum(d.replies for d in self.report.days),
            sum(d.user_messages for d in self.report.days),
        )

    def test_no_proactive_message_during_quiet_hours(self):
        self.assertEqual(sum(d.quiet_hour_pings for d in self.report.days), 0, (QUIET_START, QUIET_END))
        self.assertGreater(sum(d.pings for d in self.report.days), 0)

    def test_biology_stays_finite_and_in_range(self):
        self.assertEqual(self.report.non_finite_fields, [])
        for name, (low, high) in self.report.bio_ranges.items():
            floor = -1.0 if name == "mood" else 0.0
            self.assertGreaterEqual(low, floor - 1e-9, name)
            self.assertLessEqual(high, 1.0 + 1e-9, name)

    def test_send_tags_never_reach_short_term_memory(self):
        self.assertEqual(self.report.send_tag_leaks, 0)

    def test_one_drastic_night_does_not_rewrite_identity(self):
        drastic = "cỗ máy phiền phức"
        self.assertTrue(any(drastic in p for p in self.report.pending_by_night))
        self.assertFalse(any(drastic in i for i in self.report.identity_by_night))

    def test_one_night_sleep_per_night_at_bedtime(self):
        nights = [line for line in self.report.sleep_times if "(đêm)" in line]
        # Being woken and dozing off again is the same night: count wake days.
        wake_days = {line.split("->")[1].split()[0] for line in nights}
        self.assertEqual(len(wake_days), len(self.report.days))
        for line in nights:
            onset_hour = int(line.split()[1].split(":")[0])
            self.assertTrue(onset_hour >= 22 or onset_hour < 4, line)
        # Exhaustion may end a fragile day early, never the morning (the old
        # 0.12/h fatigue made her collapse at 09:30).
        collapse_hours = [
            int(stamp.split()[1].split(":")[0])
            for _, stamp, kind, text in self.report.aura_messages
            if kind == "reply" and "mệt rã rời" in text
        ]
        self.assertTrue(all(hour >= 12 for hour in collapse_hours), collapse_hours)
        self.assertLessEqual(len(collapse_hours), 2)

    def test_continuity_owner_event_is_remembered_and_followed_up(self):
        self.assertGreaterEqual(self.report.open_loops_remembered, 1)
        self.assertTrue(self.report.open_loop_follow_ups["phỏng vấn"])
        self.assertEqual(self.report.pings_while_owner_busy, 0)
        self.assertGreater(self.report.recap_turns, 0)

    def test_identity_reflects_once_per_night(self):
        self.assertEqual(len(self.report.identity_by_night), len(self.report.days))

    def test_mood_sinks_when_abandoned_and_recovers_after(self):
        moods = [d.mood_mean for d in self.report.days]
        abandoned = min(moods[3], moods[4])
        self.assertLess(abandoned, moods[0] - 0.15)
        self.assertGreater(moods[6], abandoned + 0.15)
        self.assertGreater(min(moods), -0.6)  # sad, not locked in despair

    def test_report_renders(self):
        text = format_report(self.report)
        self.assertIn("ping giờ ngủ", text)
        self.assertIn("Hỏi lại chuyện dang dở", text)


class DeterminismTests(unittest.TestCase):
    def test_same_seed_same_report(self):
        first = run_week(seed=3, days=2).to_dict()
        second = run_week(seed=3, days=2).to_dict()
        self.assertEqual(first, second)

    def test_scripted_llm_identifies_prompt_kinds(self):
        llm = ScriptedLLM()
        self.assertEqual(llm._kind("bạn vừa quyết định CHỦ ĐỘNG nhắn tin"), "ping")
        self.assertEqual(llm._kind("--- BẢN SẮC HIỆN TẠI CỦA BẠN ---"), "identity")


if __name__ == "__main__":
    unittest.main()
