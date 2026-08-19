import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from core.engine.autonomous import AutonomousController
from dashboard import server


class TransportJournalM1Tests(unittest.TestCase):
    def test_brain_delivery_event_contains_only_public_correlation_metadata(self):
        journal = Mock()
        controller = AutonomousController.__new__(AutonomousController)
        controller.engine = SimpleNamespace(event_journal=journal)

        controller._record_web_delivery("00000000000000000001-0123456789abcdef0123456789abcdef")

        journal.append_safe.assert_called_once()
        args, kwargs = journal.append_safe.call_args
        self.assertEqual(args[0], "delivery.durable")
        self.assertEqual(
            args[1],
            {
                "transport": "web",
                "message_id": "00000000000000000001-0123456789abcdef0123456789abcdef",
            },
        )
        self.assertEqual(kwargs["outcome"], "durable")
        self.assertNotIn("content", repr(journal.append_safe.call_args).lower())

    def test_dashboard_ack_drops_receipt_lease_and_secret_token(self):
        journal = Mock()
        message_id = "00000000000000000001-0123456789abcdef0123456789abcdef"
        receipt_secret = "fedcba9876543210fedcba9876543210"
        receipt = f"{message_id}.00000000000000000002.{receipt_secret}"

        with patch.object(server, "_get_event_journal", return_value=journal):
            server._record_delivery_acks([receipt])

        journal.append_safe.assert_called_once()
        args, kwargs = journal.append_safe.call_args
        self.assertEqual(args[0], "delivery.acked")
        self.assertEqual(args[1]["message_id"], message_id)
        serialized_call = repr(journal.append_safe.call_args)
        self.assertNotIn(receipt_secret, serialized_call)
        self.assertEqual(kwargs["outcome"], "acked")

    def test_dashboard_ack_observability_is_fail_open(self):
        journal = Mock()
        journal.append_safe.side_effect = RuntimeError("journal unavailable")
        receipt = (
            "00000000000000000001-0123456789abcdef0123456789abcdef."
            "00000000000000000002.fedcba9876543210fedcba9876543210"
        )

        with (
            patch.object(server, "_get_event_journal", return_value=journal),
            patch.object(server.logger, "warning") as warning,
        ):
            server._record_delivery_acks([receipt])

        warning.assert_called_once()


if __name__ == "__main__":
    unittest.main()
