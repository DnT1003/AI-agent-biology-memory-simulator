import discord
import threading
import queue
import asyncio
from colorama import Fore, Style
from core.logger import get_logger

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
        
        self.target_channel = None
        self._loop = None  # Lưu event loop sau khi bot sẵn sàng

        self.aura_inbox: queue.Queue = queue.Queue()

        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        intents.presences = True

        self.client = discord.Client(intents=intents)

        @self.client.event
        async def on_ready():
            self._loop = asyncio.get_running_loop()  # Lưu running loop (chuẩn asyncio 3.10+)
            logger.info(f"[DiscordBridge] Bot đã đăng nhập: {self.client.user}")
            print(f"{Fore.GREEN}📡 [DISCORD]: Đã kết nối với tên {self.client.user}! Lắng nghe trên '{self.channel_name}'...{Style.RESET_ALL}")
            
            # Nếu người dùng truyền số 0 (hoặc string "0"), tự động lấy guild đầu tiên nó nhìn thấy
            # Rất tiện nếu không tìm được Guild ID ngay lập tức
            if not self.guild_id and self.client.guilds:
                guild = self.client.guilds[0]
                print(f"{Fore.YELLOW}[DISCORD]: Đã tự động chọn Server: {guild.name}{Style.RESET_ALL}")
            elif self.guild_id:
                guild = discord.utils.get(self.client.guilds, id=self.guild_id)
            else:
                guild = None
                
            if guild:
                # Tìm kênh theo tên
                self.target_channel = discord.utils.get(guild.text_channels, name=self.channel_name)
                # Fallback lấy kênh Text bất kỳ
                if not self.target_channel and guild.text_channels:
                    self.target_channel = guild.text_channels[0]
                    
                print(f"\n{Fore.CYAN}📋 [DISCORD BOOT]: Liệt kê các Server và Kênh khả dụng:{Style.RESET_ALL}")
                for g in self.client.guilds:
                    print(f"  - Server: {g.name} (ID: {g.id})")
                    for ch in g.text_channels:
                        print(f"    * Kênh: #{ch.name} (ID: {ch.id})")
                
                if self.target_channel:
                    print(f"\n{Fore.GREEN}📡 [DISCORD CONNECTED]: {guild.name} (ID: {guild.id}) -> #{self.target_channel.name} (ID: {self.target_channel.id}){Style.RESET_ALL}")
                    logger.info(f"[DiscordBridge] Đã thiết lập kênh: #{self.target_channel.name} (ID: {self.target_channel.id}) trên Guild (ID: {guild.id})")
            else:
                logger.error(f"[DiscordBridge] KHÔNG tìm thấy server khớp với {self.guild_id}!")

        @self.client.event
        async def on_message(message):
            if message.author == self.client.user:
                return

            # Nếu target_channel đã xác định, chỉ lắng nghe đúng kênh đó
            # Nếu chưa xác định (race condition khi on_message đến trước on_ready xong)
            # → fallback: lọc theo tên kênh
            if self.target_channel:
                if message.channel.id != self.target_channel.id:
                    return
            else:
                # Fallback: so sánh theo tên kênh để tránh bỏ sót tin nhắn đầu
                if message.channel.name != self.channel_name:
                    return

            content = message.content.strip()
            if not content:
                return

            sender = message.author.display_name
            print(f"{Fore.MAGENTA}📨 [DISCORD BRIDGE] Nhận tin từ {sender}: {content}{Style.RESET_ALL}")
            logger.info(f"[DiscordBridge] on_message: {sender}: {content}")
            self.aura_inbox.put({
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
                logger.error(f"[DiscordBridge] Yêu cầu gửi không thành công: {e}")
        else:
            logger.warning("[DiscordBridge] Kênh chưa sẵn sàng, loop chưa khởi tạo, hoặc kết nối bị đứt.")

    def start_in_thread(self):
        def _run():
            # Discord.py chạy một file lock loop chặn, ta bọc nó bằng thead
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.client.run(self.token, log_handler=None)
            
        t = threading.Thread(target=_run, daemon=True, name="AuraDiscordThread")
        t.start()
        return t
