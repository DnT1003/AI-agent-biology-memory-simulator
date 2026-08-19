import asyncio
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from config import Config, _optional_discord_snowflake


def _discord_get(items, **attributes):
    for item in items:
        if all(getattr(item, key, None) == value for key, value in attributes.items()):
            return item
    return None


# Discord is an optional runtime dependency in the unit-test environment. The
# bridge constructor is patched below, so only a minimal import surface is needed.
if "discord" not in sys.modules:
    sys.modules["discord"] = SimpleNamespace(
        Intents=SimpleNamespace(default=lambda: None),
        Client=object,
        utils=SimpleNamespace(get=_discord_get),
    )

from core.discord_bridge import AuraDiscordBot


class _FakeClient:
    def __init__(self, *, intents):
        self.intents = intents
        self.user = object()
        self.guilds = []

    def event(self, callback):
        setattr(self, callback.__name__, callback)
        return callback

    def is_closed(self):
        return False


class _UnreadableContentMessage:
    def __init__(self, author, channel):
        self.author = author
        self.channel = channel
        self.id = 77

    @property
    def content(self):
        raise AssertionError("unauthorized content was accessed")


def _author(user_id, *, bot=False, display_name="untrusted-display"):
    return SimpleNamespace(id=user_id, bot=bot, display_name=display_name)


def _channel(channel_id=10, name="general"):
    return SimpleNamespace(id=channel_id, name=name)


def _guild(guild_id=42, channels=None):
    return SimpleNamespace(
        id=guild_id,
        name=f"guild-{guild_id}",
        text_channels=list(channels or []),
    )


class DiscordOwnerBoundaryM2Tests(unittest.TestCase):
    def _make_bridge(
        self,
        owner,
        *,
        guild_id=42,
        resolve=True,
        guilds=None,
        channel_name="general",
    ):
        intents = SimpleNamespace(
            message_content=False,
            members=False,
            presences=False,
        )
        active_patches = (
            patch.object(Config, "DISCORD_OWNER_USER_ID", owner),
            patch("core.discord_bridge.discord.Intents.default", return_value=intents),
            patch("core.discord_bridge.discord.Client", _FakeClient),
            patch("core.discord_bridge.discord.utils.get", side_effect=_discord_get),
        )
        for active_patch in active_patches:
            active_patch.start()
            self.addCleanup(active_patch.stop)
        bridge = AuraDiscordBot(
            "token", guild_id=guild_id, channel_name=channel_name
        )
        bridge.client.guilds = list(
            guilds
            if guilds is not None
            else [_guild(42, [_channel()])]
        )
        if resolve:
            with patch("builtins.print"), patch(
                "core.discord_bridge.logger.info"
            ), patch("core.discord_bridge.logger.error"):
                asyncio.run(bridge.client.on_ready())
        return bridge

    def test_missing_owner_disables_inbound_before_content_access(self):
        bridge = self._make_bridge(None)
        message = _UnreadableContentMessage(_author(123), _channel())

        asyncio.run(bridge.client.on_message(message))

        self.assertFalse(bridge.inbound_enabled)
        self.assertTrue(bridge.aura_inbox.empty())

    def test_owner_message_uses_stable_id_and_logs_no_content_or_display(self):
        bridge = self._make_bridge(" 00123 ")
        message = SimpleNamespace(
            author=_author(123, display_name="SECRET-DISPLAY"),
            channel=_channel(),
            id=88,
            content="SECRET-CONTENT",
        )

        with patch("core.discord_bridge.logger.info") as info, patch(
            "builtins.print"
        ) as printed:
            asyncio.run(bridge.client.on_message(message))

        self.assertEqual(
            bridge.aura_inbox.get_nowait(),
            {
                "message_id": "88",
                "sender": "123",
                "content": "SECRET-CONTENT",
            },
        )
        emitted = repr(info.call_args_list) + repr(printed.call_args_list)
        self.assertNotIn("SECRET-CONTENT", emitted)
        self.assertNotIn("SECRET-DISPLAY", emitted)

    def test_non_owner_is_ignored_before_content_access(self):
        bridge = self._make_bridge("123")
        message = _UnreadableContentMessage(_author(999), _channel())

        asyncio.run(bridge.client.on_message(message))

        self.assertTrue(bridge.aura_inbox.empty())

    def test_bot_and_wrong_channel_remain_blocked(self):
        bridge = self._make_bridge(123)
        bot_message = _UnreadableContentMessage(
            _author(123, bot=True), _channel()
        )
        wrong_channel = _UnreadableContentMessage(
            _author(123), _channel(channel_id=11, name="elsewhere")
        )

        asyncio.run(bridge.client.on_message(bot_message))
        asyncio.run(bridge.client.on_message(wrong_channel))

        self.assertTrue(bridge.aura_inbox.empty())

    def test_unresolved_target_blocks_before_content_access(self):
        bridge = self._make_bridge("123", resolve=False)
        message = _UnreadableContentMessage(_author(123), _channel())

        asyncio.run(bridge.client.on_message(message))

        self.assertFalse(bridge.inbound_enabled)
        self.assertIsNone(bridge.target_channel)
        self.assertTrue(bridge.aura_inbox.empty())

    def test_zero_guild_disables_inbound_and_outbound(self):
        bridge = self._make_bridge("123", guild_id=0)
        message = _UnreadableContentMessage(_author(123), _channel())

        asyncio.run(bridge.client.on_message(message))
        with patch("core.discord_bridge.asyncio.run_coroutine_threadsafe") as send:
            bridge.send_to_user("must not send")

        self.assertFalse(bridge.inbound_enabled)
        self.assertIsNone(bridge.target_channel)
        self.assertTrue(bridge.aura_inbox.empty())
        send.assert_not_called()

    def test_missing_exact_channel_does_not_fallback_to_first_text_channel(self):
        public_channel = _channel(channel_id=90, name="public")
        bridge = self._make_bridge(
            "123",
            channel_name="private-owner-channel",
            guilds=[_guild(42, [public_channel])],
        )
        message = _UnreadableContentMessage(_author(123), public_channel)

        asyncio.run(bridge.client.on_message(message))

        self.assertFalse(bridge.inbound_enabled)
        self.assertIsNone(bridge.target_channel)
        self.assertTrue(bridge.aura_inbox.empty())

    def test_same_name_channel_in_other_guild_is_blocked_by_resolved_id(self):
        exact = _channel(channel_id=10, name="general")
        other_guild_channel = _channel(channel_id=99, name="general")
        bridge = self._make_bridge(
            "123",
            guilds=[
                _guild(42, [exact]),
                _guild(43, [other_guild_channel]),
            ],
        )
        message = _UnreadableContentMessage(_author(123), other_guild_channel)

        asyncio.run(bridge.client.on_message(message))

        self.assertEqual(bridge.target_channel.id, exact.id)
        self.assertTrue(bridge.aura_inbox.empty())

    def test_duplicate_channel_name_in_exact_guild_fails_closed(self):
        first = _channel(channel_id=10, name="general")
        second = _channel(channel_id=11, name="general")
        bridge = self._make_bridge(
            "123",
            guilds=[_guild(42, [first, second])],
        )
        message = _UnreadableContentMessage(_author(123), first)

        asyncio.run(bridge.client.on_message(message))

        self.assertFalse(bridge.inbound_enabled)
        self.assertIsNone(bridge.target_channel)
        self.assertTrue(bridge.aura_inbox.empty())

    def test_invalid_config_values_fail_closed(self):
        invalid_values = ("", "  ", "abc", "-1", "1.5", 0, True, 2**64, None)
        for invalid in invalid_values:
            with self.subTest(value=invalid):
                self.assertIsNone(_optional_discord_snowflake(invalid))

        bridge = self._make_bridge("not-a-snowflake")
        self.assertFalse(bridge.inbound_enabled)
        self.assertTrue(bridge.aura_inbox.empty())


if __name__ == "__main__":
    unittest.main()
