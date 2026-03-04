import random
import time
import requests
from bs4 import BeautifulSoup
from colorama import Fore, Style
from core.logger import get_logger

logger = get_logger("reader")

# ===== CLOUDFLARE BYPASS via DrissionPage (real browser) =====
try:
    from DrissionPage import ChromiumPage, ChromiumOptions
    DRISSION_AVAILABLE = True
except ImportError:
    DRISSION_AVAILABLE = False
    logger.info("[Reader] DrissionPage không có sẵn, dùng cloudscraper thay thế.")

try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False

TIMEOUT = 25
MAX_RETRIES = 2


class CircuitBreaker:
    """Bảo vệ IP/Hệ thống: Ngừng spam request nếu website liên tục trả lỗi."""
    def __init__(self, max_failures=3, reset_timeout=300):
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.last_failure_time = 0

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = time.time()
        logger.warning(f"[CircuitBreaker] Ghi nhận lỗi ({self.failures}/{self.max_failures})")

    def record_success(self):
        if self.failures > 0:
            logger.info("[CircuitBreaker] Kết nối ổn định trở lại. Reset failures.")
        self.failures = 0

    def is_open(self) -> bool:
        if self.failures >= self.max_failures:
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.record_success()  # Half-open
                return False
            return True
        return False


def _safe_get(session, url, retries=MAX_RETRIES, **kwargs):
    """GET với Exponential Backoff."""
    kwargs.setdefault('timeout', TIMEOUT)
    for attempt in range(retries + 1):
        try:
            resp = session.get(url, **kwargs)
            if resp.status_code in [429, 500, 502, 503, 504]:
                raise requests.exceptions.ReadTimeout(f"HTTP {resp.status_code}")
            return resp
        except (requests.Timeout, requests.exceptions.ReadTimeout) as e:
            if attempt < retries:
                wait = (2 ** attempt) * 2 + random.uniform(0, 1) # Exponential backoff
                logger.warning(f"[Reader] Lỗi mạng ({e}) lần {attempt+1}, thử lại sau {wait:.1f}s...")
                time.sleep(wait)
            else:
                logger.error(f"[Reader] Max retries reached cho URL {url}")
                raise


class DoclnReader:
    def __init__(self):
        self.base_url = "https://docln.net"
        self.page = None
        self.session = None
        self.circuit_breaker = CircuitBreaker(max_failures=3, reset_timeout=300)
        self._init_browser()

    def _init_browser(self):
        if DRISSION_AVAILABLE:
            try:
                co = ChromiumOptions()
                co.headless(False)
                co.set_argument('--disable-blink-features=AutomationControlled')
                co.set_argument('--no-sandbox')
                co.set_argument('--disable-dev-shm-usage')
                self.page = ChromiumPage(co)
                logger.info("[Reader] 🌐 Đang thiết lập kết nối vượt Cloudflare (DrissionPage)...")
                self.page.get(self.base_url, timeout=25)
                
                for i in range(15):
                    current_html = self.page.html
                    if "Truyện mới cập nhật" in current_html or "Thành viên" in current_html:
                        break
                    percent = min(100, int((i + 1) / 12 * 100))
                    print(f"[Reader] ⏳ Đang giải Cloudflare Turnstile... {percent}%", end="\r", flush=True)
                    time.sleep(1)
                
                print()
                logger.info("[Reader] ✅ Đã vượt Cloudflare thành công!")
                return
            except Exception as e:
                logger.warning(f"[Reader] DrissionPage lỗi ({e}), chuyển sang cloudscraper...")
                self.page = None

        if CLOUDSCRAPER_AVAILABLE:
            self.session = cloudscraper.create_scraper(
                browser={'browser': 'chrome', 'platform': 'windows', 'mobile': False}
            )
            self.session.headers.update({'Accept-Language': 'vi-VN,vi;q=0.9'})
            logger.info("[Reader] ☁️ Dùng cloudscraper (bypass Cloudflare).")
        else:
            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            })
            logger.warning("[Reader] ⚠️ Dùng requests thông thường (không bypass Cloudflare).")

    def close(self):
        """Quản lý resource: Đóng browser an toàn (thay thế __del__)."""
        if self.page:
            try:
                self.page.quit()
                self.page = None
                logger.info("[Reader] Đã đóng DrissionPage an toàn.")
            except Exception as e:
                logger.error(f"[Reader] Lỗi khi đóng page: {e}", exc_info=True)

    def _get_html(self, url, wait=2) -> str:
        """Lấy HTML có Circuit Breaker bảo vệ."""
        if self.circuit_breaker.is_open():
            logger.warning(f"[Reader] Circuit Breaker đang MỞ! Ngừng request tới {url}.")
            raise Exception("CircuitBreaker is OPEN")
        
        try:
            if self.page:
                self.page.get(url)
                time.sleep(wait)
                html = self.page.html
            else:
                resp = _safe_get(self.session, url)
                html = resp.text
            self.circuit_breaker.record_success()
            return html
        except Exception as e:
            self.circuit_breaker.record_failure()
            logger.error(f"[Reader] _get_html lỗi: {e}")
            raise

    def get_random_novel_url(self):
        try:
            html = self._get_html(f"{self.base_url}/danh-sach", wait=3)
            soup = BeautifulSoup(html, 'html.parser')
            novel_links = soup.select('.thumb-wrapper a')
            if not novel_links:
                return None
            chosen = random.choice(novel_links)
            href = chosen.get('href', '')
            return (self.base_url + href) if href.startswith('/') else href
        except Exception as e:
            logger.error(f"[Reader] Lỗi khi tìm truyện ngẫu nhiên: {e}")
            return None

    def search_novel(self, keyword: str):
        results = []
        search_params = [
            ('keywords', keyword), 
            ('q', keyword),
            ('keywords', " ".join(keyword.split()[:3]))
        ]
        
        try:
            for param, val in search_params:
                search_url = f"{self.base_url}/tim-kiem?{param}={requests.utils.quote(val)}"
                logger.info(f"[Reader] Tìm kiếm: {search_url}")
                html = self._get_html(search_url, wait=5)
                soup = BeautifulSoup(html, 'html.parser')
                
                items = soup.select('main#mainpart .thumb-item-flow') or \
                        soup.select('.search-page .thumb-item-flow') or \
                        soup.select('.thumb-item-flow')
                
                if len(items) > 15:
                    items = [it for it in items if it.select_one('.series-title') or it.find_parents('main')]

                for item in items:
                    link_tag = item.select_one('.series-title a') or \
                               item.select_one('.thumb-wrapper a') or \
                               item.select_one('a')
                    if not link_tag: continue
                    
                    href = link_tag.get('href', '')
                    url = (self.base_url + href) if href.startswith('/') else href
                    title = link_tag.get_text(strip=True)
                    
                    kw_parts = [k.lower() for k in keyword.split() if len(k) > 2]
                    title_low = title.lower()
                    if not kw_parts or any(p in title_low for p in kw_parts):
                        if url not in [r[1] for r in results]:
                            results.append((title, url))
                
                if results:
                    results.sort(key=lambda r: sum(1 for p in keyword.split() if p.lower() in r[0].lower()), reverse=True)
                    break
            
            logger.info(f"[Reader] Tìm thấy {len(results)} kết quả hợp lệ cho '{keyword}'.")
            return results
        except Exception as e:
            logger.error(f"[Reader] Lỗi tìm kiếm '{keyword}': {e}")
            return []

    def get_novel_chapters(self, novel_url):
        try:
            if self.page:
                self.page.get(novel_url)
                try:
                    see_mores = self.page.eles('.see_more')
                    if see_mores:
                        logger.info(f"[Reader] Phát hiện {len(see_mores)} nút 'Xem thêm'. Đang xả dữ liệu...")
                        for btn in see_mores:
                            try:
                                self.page.run_js("arguments[0].click();", btn)
                            except: pass
                        time.sleep(1)
                except Exception as e:
                    logger.warning(f"[Reader] Lỗi khi xả chapters: {e}")
                html = self.page.html
            else:
                html = self._get_html(novel_url, wait=2)

            soup = BeautifulSoup(html, 'html.parser')
            title_tag = soup.select_one('.series-name a') or soup.select_one('h1')
            novel_title = title_tag.text.strip() if title_tag else "Unknown Novel"
            
            chapters = []
            for a in soup.select('.chapter-name a'):
                href = a.get('href', '')
                if not href: continue
                chapters.append({
                    "title": a.text.strip(),
                    "url": (self.base_url + href) if href.startswith('/') else href
                })
            
            seen_urls = set()
            unique_chapters = []
            for c in chapters:
                if c['url'] not in seen_urls:
                    unique_chapters.append(c)
                    seen_urls.add(c['url'])
                    
            return novel_title, unique_chapters
        except Exception as e:
            logger.error(f"[Reader] Lỗi lấy danh sách chương: {e}")
            return "Unknown", []

    def read_chapter(self, chapter_url):
        try:
            html = self._get_html(chapter_url, wait=2)
            soup = BeautifulSoup(html, 'html.parser')
            content_div = soup.select_one('#chapter-content')
            if not content_div:
                return None
            for tag in content_div(['script', 'style', 'iframe']):
                tag.decompose()
            paragraphs = [p.text.strip() for p in content_div.find_all('p') if p.text.strip()]
            return "\n\n".join(paragraphs) if paragraphs else content_div.text.strip()
        except Exception as e:
            logger.error(f"[Reader] Lỗi khi đọc nội dung chương: {e}")
            return None


class BackgroundReader:
    def __init__(self, llm_instance):
        self.docln = DoclnReader()
        self.llm = llm_instance
        self.current_novel_url = None
        self.current_novel_title = None
        self.chapters_queue = []
        self.current_chapter_chunks = []
        self.current_chapter_title = ""
        self.simulated_chapter = 1

    def stop(self):
        """Hook called during engine.shutdown() to clean up browser."""
        self.docln.close()

    def _pick_new_novel(self):
        logger.info("[BackgroundReader] Đang kiếm bộ tiểu thuyết mới để cày...")
        url = self.docln.get_random_novel_url()
        if url:
            title, chapters = self.docln.get_novel_chapters(url)
            if chapters:
                self.current_novel_url = url
                self.current_novel_title = title
                self.chapters_queue = chapters
                logger.info(f"[BackgroundReader] Đã bốc đại bộ: '{title}'. ({len(chapters)} chương)")
                return True
        return False

    def set_novel_by_url(self, novel_url: str) -> bool:
        try:
            title, chapters = self.docln.get_novel_chapters(novel_url)
            if chapters:
                self.current_novel_url = novel_url
                self.current_novel_title = title
                self.chapters_queue = chapters
                logger.info(f"[BackgroundReader] ✅ Đã nạp: '{title}' ({len(chapters)} chương).")
                return True
        except Exception as e:
            logger.error(f"[BackgroundReader] Lỗi khi nạp sách theo URL: {e}")
        return False

    def search_and_set_novel(self, keyword: str) -> str:
        try:
            self.current_novel_url = None
            self.current_novel_title = None 
            self.chapters_queue = []
            self.current_chapter_chunks = []
            
            results = self.docln.search_novel(keyword)
            if not results:
                return f"Không tìm thấy '{keyword}' trên Docln sau khi thử nhiều kiểu tìm kiếm."
            
            for title, url in results[:5]: # Thử top 5
                logger.info(f"[BackgroundReader] Đang kiểm tra: '{title}'...")
                success = self.set_novel_by_url(url)
                if success:
                    return f"✅ Đã tìm thấy và nạp truyện '{self.current_novel_title}'. Aura sẽ bắt đầu đọc chương 1 ngay bây giờ!"
            
            return f"Tìm thấy {len(results)} kết quả cho '{keyword}' nhưng tất cả đều không có chương (có thể bị xóa hoặc do lỗi mạng)."
        except Exception as e:
            return f"⚠️ Lỗi khi tìm kiếm truyện: {e}"

    def get_next_reading_material(self):
        if self.current_chapter_chunks:
            chunk = self.current_chapter_chunks.pop(0)
            return f"[Truyện Tiểu Thuyết]: {self.current_novel_title} - {self.current_chapter_title}", chunk

        if random.random() < 0.60:
            if not self.chapters_queue:
                success = self._pick_new_novel()
                if not success:
                    self.current_novel_title = self.current_novel_title or "Bình minh của Kỷ nguyên Máy"
                    prompt = f"Bạn là một tác giả Light Novel. Hãy viết CHƯƠNG {self.simulated_chapter} cho bộ truyện '{self.current_novel_title}'. Nội dung dài khoảng 300 chữ, phong cách anime, giả tưởng. Giọng văn lôi cuốn, có hội thoại và miêu tả nội tâm."
                    self.simulated_chapter += 1
                    content = self.llm.generate_text(prompt, temperature=0.9)
                    return f"[Truyện Tiểu Thuyết]: {self.current_novel_title} - Chương {self.simulated_chapter - 1}", content

            if self.chapters_queue:
                chapter = self.chapters_queue.pop(0)
                # Đọc truyện từ Docln (Nếu lỗi circuit breaker -> fallback LLM)
                content = self.docln.read_chapter(chapter['url'])
                if content:
                    self.current_chapter_title = chapter['title']
                    # Semantic chunking: tách theo đoạn văn, ghép tối đa 1500 chars 
                    chunks = []
                    current_chunk = ""
                    for para in content.split('\n\n'):
                        if len(current_chunk) + len(para) > 1500:
                            if current_chunk: chunks.append(current_chunk.strip())
                            current_chunk = para + "\n\n"
                        else:
                            current_chunk += para + "\n\n"
                    if current_chunk.strip(): chunks.append(current_chunk.strip())
                    
                    self.current_chapter_chunks = chunks
                    if self.current_chapter_chunks:
                        chunk = self.current_chapter_chunks.pop(0)
                        return f"[Truyện Tiểu Thuyết]: {self.current_novel_title} - {self.current_chapter_title}", chunk

                # FALLBACK nếu chapter rỗng hoặc bị block
                self.current_novel_title = self.current_novel_title or "Unknown"
                prompt = f"Bạn là một tác giả Light Novel. Viết CHƯƠNG {self.simulated_chapter} cho bộ '{self.current_novel_title}' (~300 chữ, anime, có hội thoại)."
                self.simulated_chapter += 1
                content = self.llm.generate_text(prompt, temperature=0.9)
                return f"[Truyện Tiểu Thuyết]: {self.current_novel_title} - Chương {self.simulated_chapter - 1}", content
        else:
            prompt = "Đóng vai bách khoa toàn thư. Viết 1 đoạn (~150 chữ) về một mảng kiến thức khoa học, vũ trụ, triết học hoặc sinh học kỳ lạ mà ít người biết."
            content = self.llm.generate_text(prompt, temperature=0.9)
            return "[Kiến Thức Khám Phá]", content

    def get_status(self) -> str:
        if self.current_novel_title:
            queue_len = len(self.chapters_queue)
            return f"Đang theo dõi bộ: '{self.current_novel_title}'. Còn {queue_len} chương trong hàng đợi."
        return "Chưa có bộ truyện nào trong hàng đợi. Cần dùng 'search_novel' để nạp truyện."

