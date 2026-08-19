import discord
import threading
import queue
import asyncio
import time
from colorama import Fore, Style
from core.logger import get_logger
from config import Config, _optional_discord_snowflake

logger = get_logger("discord_bridge")

class AuraDiscordBot:
    """
    Cầu nối hai chiều Aura <-> Discord.
    NHẬN: Lắng nghe sự kiện on_message -> đẩy vào aura_inbox (Queue)
    GỬI: send_to_user(text) -> chèn lệnh gọi send vào event loop của discord
    """
    def __init__(self, token: str, guild_id: int = 0, channel_name: str = "general"):
        self.token = token
        self.guild_id = guild_id
        self.channel_name = channel_name
        self.owner_user_id = _optional_discord_snowflake(
            getattr(Config, "DISCORD_OWNER_USER_ID", None)
        )
        # Owner configuration alone is insufficient. Inbound stays closed
        # until on_ready resolves the exact configured guild and channel.
        self.inbound_enabled = False
        
        self.target_channel = None
        self._loop = None  # Lưu event loop sau khi bot sẵn sàng
        self._thread = None
        self._thread_lock = threading.Lock()

        self.aura_inbox: queue.Queue = queue.Queue()

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True

        self.client = discord.Client(intents=intents)

        if self.owner_user_id is None:
            logger.warning(
                "[DiscordBridge] Inbound disabled: owner ID is not configured"
            )

        @self.client.event
        async def on_ready():
            self._loop = asyncio.get_running_loop()  # Lưu running loop (chuẩn asyncio 3.10+)
            logger.info("[DiscordBridge] Bot connected")
            # Reconnects must re-resolve the exact target. A stale channel is
            # never an acceptable ingress or egress fallback.
            self.target_channel = None
            self.inbound_enabled = False
            print(
                f"{Fore.GREEN}📡 [DISCORD]: Đã kết nối; "
                f"đang xác minh target đã cấu hình...{Style.RESET_ALL}"
            )
            
            # Guild 0/không rõ phải fail closed. Không tự chọn một server mà
            # operator chưa cấu hình vì response có thể bị gửi sai audience.
            if not self.guild_id:
                guild = None
            elif self.guild_id:
                guild = discord.utils.get(self.client.guilds, id=self.guild_id)
            else:
                guild = None
                
            if guild:
                # Discord permits duplicate channel names. Resolve only when
                # the configured name identifies exactly one channel in the
                # exact guild; ambiguity is a closed boundary, not a fallback.
                matching_channels = [
                    channel
                    for channel in guild.text_channels
                    if channel.name == self.channel_name
                ]
                self.target_channel = (
                    matching_channels[0]
                    if len(matching_channels) == 1
                    else None
                )
                print(f"\n{Fore.CYAN}📋 [DISCORD BOOT]: Liệt kê các Server và Kênh khả dụng:{Style.RESET_ALL}")
                for g in self.client.guilds:
                    print(f"  - Server: {g.name} (ID: {g.id})")
                    for ch in g.text_channels:
                        print(f"    * Kênh: #{ch.name} (ID: {ch.id})")
                
                if self.target_channel:
                    self.inbound_enabled = self.owner_user_id is not None
                    print(f"\n{Fore.GREEN}📡 [DISCORD CONNECTED]: {guild.name} (ID: {guild.id}) -> #{self.target_channel.name} (ID: {self.target_channel.id}){Style.RESET_ALL}")
                    logger.info(f"[DiscordBridge] Đã thiết lập kênh: #{self.target_channel.name} (ID: {self.target_channel.id}) trên Guild (ID: {guild.id})")
            else:
                logger.error(f"[DiscordBridge] KHÔNG tìm thấy server khớp với {self.guild_id}!")

        @self.client.event
        async def on_message(message):
            author = message.author
            if author == self.client.user or bool(getattr(author, "bot", False)):
                return

            # Authorize the stable principal before channel lookup and, most
            # importantly, before accessing message.content.
            if not self.inbound_enabled:
                return
            author_id = _optional_discord_snowflake(getattr(author, "id", None))
            if author_id != self.owner_user_id:
                return

            target_channel = self.target_channel
            if target_channel is None or message.channel.id != target_channel.id:
                return

            content = message.content.strip()
            if not content:
                return

            # The canonical owner ID is the principal. Never propagate a
            # mutable display name, message content, or user display data to logs.
            sender = self.owner_user_id
            print(
                f"{Fore.MAGENTA}📨 [DISCORD BRIDGE] "
                f"Owner message accepted.{Style.RESET_ALL}"
            )
            logger.info("[DiscordBridge] Owner message accepted")
            self.aura_inbox.put({
                "message_id": str(message.id),
                "sender": sender,
                "content": content
            })

    def send_to_user(self, text: str):
        """Gửi tin từ luồng của Aura tới luồng của Discord"""
        if self.target_channel and not self.client.is_closed() and self._loop:
            # Sử dụng run_coroutine_threadsafe với loop đã lưu (tránh deprecated client.loop)
            future = asyncio.run_coroutine_threadsafe(
                self.target_channel.send(text),
                self._loop
            )
            try:
                future.result(timeout=10)
            except Exception as e:
                logger.error(
                    "[DiscordBridge] Outbound send failed; error_type=%s",
                    type(e).__name__,
                )
        else:
            logger.warning("[DiscordBridge] Kênh chưa sẵn sàng, loop chưa khởi tạo, hoặc kết nối bị đứt.")

    def start_in_thread(self):
        def _run():
            try:
                # Client.run owns its asyncio loop; on_ready records that exact
                # loop for thread-safe send/close operations.
                self.client.run(self.token, log_handler=None)
            finally:
                self._loop = None

        with self._thread_lock:
            if self._thread is not None and self._thread.is_alive():
                return self._thread
            self._thread = threading.Thread(
                target=_run,
                daemon=True,
                name="AuraDiscordThread",
            )
            self._thread.start()
            return self._thread

    def stop(self, timeout: float = 5.0) -> bool:
        """Close the Discord client and join its owned thread boundedly."""
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout must be a non-negative number")
        if timeout < 0:
            raise ValueError("timeout must be non-negative")

        with self._thread_lock:
            thread = self._thread
        if thread is None or not thread.is_alive():
            return True

        deadline = time.monotonic() + float(timeout)
        loop = self._loop
        if loop is not None and not loop.is_closed() and not self.client.is_closed():
            try:
                close_future = asyncio.run_coroutine_threadsafe(
                    self.client.close(), loop
                )
                close_future.result(
                    timeout=max(0.0, deadline - time.monotonic())
                )
            except Exception:
                logger.warning(
                    "[DiscordBridge] Client close did not finish cleanly",
                    exc_info=True,
                )

        thread.join(timeout=max(0.0, deadline - time.monotonic()))
        stopped = not thread.is_alive()
        if not stopped:
            logger.warning("[DiscordBridge] Thread missed shutdown deadline")
        return stopped
