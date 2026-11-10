import random
import time
import requests
from urllib.parse import quote
from bs4 import BeautifulSoup
from colorama import Fore, Style
from core.logger import get_logger

logger = get_logger("reader")

# ===== CLOUDFLARE BYPASS via DrissionPage (real browser) =====
# Tạm thời vô hiệu hóa DrissionPage để tránh dính Cloudflare làm treo khởi động
DRISSION_AVAILABLE = False
logger.info("[Reader] DrissionPage đã bị tắt, dùng cloudscraper thay thế.")

try:
    from DrissionPage import ChromiumPage, ChromiumOptions
except ImportError:
    ChromiumPage, ChromiumOptions = None, None  # type: ignore

try:
    import cloudscraper
    CLOUDSCRAPER_AVAILABLE = True
except ImportError:
    CLOUDSCRAPER_AVAILABLE = False

TIMEOUT = 25
MAX_RETRIES = 2


class CircuitBreaker:
    """Bảo vệ IP/Hệ thống: Ngừng spam request nếu website liên tục trả lỗi."""
    def __init__(self, max_failures=3, reset_timeout=600):
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.last_failure_time = 0.0

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
    raise RuntimeError("Request failed after retries")


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
                co = ChromiumOptions()  # type: ignore
                co.headless(False)
                co.set_argument('--disable-blink-features=AutomationControlled')
                co.set_argument('--no-sandbox')
                co.set_argument('--disable-dev-shm-usage')
                self.page = ChromiumPage(co)  # type: ignore
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
            href = str(chosen.get('href', ''))
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
                search_url = f"{self.base_url}/tim-kiem?{param}={quote(val)}"
                logger.info(f"[Reader] Tìm kiếm: {search_url}")
                html = self._get_html(search_url, wait=5)
                soup = BeautifulSoup(html, 'html.parser')
                
                items = list(soup.select('main#mainpart .thumb-item-flow')) or \
                        list(soup.select('.search-page .thumb-item-flow')) or \
                        list(soup.select('.thumb-item-flow'))
                
                if len(items) > 15:
                    items = [it for it in items if it.select_one('.series-title') or it.find_parents('main')]

                for item in items:
                    link_tag = item.select_one('.series-title a') or \
                               item.select_one('.thumb-wrapper a') or \
                               item.select_one('a')
                    if not link_tag: continue
                    
                    href = str(link_tag.get('href', ''))
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
                href = str(a.get('href', ''))
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
    """Đọc sách THẬT một cách tuần tự và nhớ tiến độ, giống người đọc.

    Không bao giờ để LLM tự bịa nội dung: nếu không lấy được sách thật,
    phiên đọc trả về ``(None, None)`` và bị bỏ qua.
    """

    _PROGRESS_VERSION = 1
    _MAX_FINISHED = 200

    def __init__(self, llm_instance=None, *, sources=None, progress_path=None, segment_chars=None):
        import threading
        from config import Config
        from components.book_sources import build_sources

        self.llm = llm_instance  # kept for constructor compatibility; never used to write books
        self.sources = list(sources) if sources is not None else build_sources(Config)
        self.progress_path = progress_path or Config.READER_PROGRESS_FILE
        self.segment_chars = max(500, int(segment_chars or Config.READER_SEGMENT_CHARS))
        self.lock = threading.Lock()
        self.current_book = None
        self.chapters = []
        self.chapter_index = 0
        self.segments = []
        self.segment_index = 0
        self._loaded_chapter = None
        self._fresh_book = False
        self.finished_books = []
        self.last_material_new_book = False
        self._fetch_failures = 0
        self._load_progress()

    # ------------------------------------------------------------ lifecycle
    def stop(self):
        """Hook called during engine.shutdown() to release source resources."""
        for source in self.sources:
            close = getattr(source, "close", None)
            if callable(close):
                close()

    def _source(self, name):
        return next((s for s in self.sources if s.name == name), None)

    # ------------------------------------------------------------- progress
    def _load_progress(self):
        import json
        import os
        from components.book_sources import BookRef

        try:
            if not os.path.exists(self.progress_path):
                return
            with open(self.progress_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            finished = data.get("finished", [])
            if isinstance(finished, list):
                self.finished_books = [k for k in finished if isinstance(k, str)][-self._MAX_FINISHED:]
            source, book_id, title = data.get("source"), data.get("book_id"), data.get("title")
            chapter_index, segment_index = data.get("chapter_index"), data.get("segment_index")
            if (
                all(isinstance(v, str) and v for v in (source, book_id, title))
                and self._source(source) is not None
                and type(chapter_index) is int and chapter_index >= 0
                and type(segment_index) is int and segment_index >= 0
            ):
                self.current_book = BookRef(source, book_id, title)
                self.chapter_index = chapter_index
                self.segment_index = segment_index
        except Exception as exc:
            logger.warning("[BackgroundReader] progress load failed cause_type=%s", type(exc).__name__)

    def _save_progress(self):
        from core.utils import atomic_write_json

        with self.lock:
            book = self.current_book
            payload = {
                "version": self._PROGRESS_VERSION,
                "finished": list(self.finished_books),
                "chapter_index": self.chapter_index,
                "segment_index": self.segment_index,
            }
            if book is not None:
                payload.update(source=book.source, book_id=book.book_id, title=book.title)
        try:
            atomic_write_json(self.progress_path, payload)
        except Exception as exc:
            logger.warning("[BackgroundReader] progress save failed cause_type=%s", type(exc).__name__)

    # ------------------------------------------------------------ selection
    @staticmethod
    def _book_key(book):
        return f"{book.source}:{book.book_id}"

    def _select_book(self, book) -> bool:
        source = self._source(book.source)
        chapters = source.chapters(book) if source is not None else []
        if not chapters:
            return False
        with self.lock:
            self.current_book = book
            self.chapters = chapters
            self.chapter_index = 0
            self.segment_index = 0
            self.segments = []
            self._loaded_chapter = None
            self._fresh_book = True
            self._fetch_failures = 0
        self._save_progress()
        logger.info(f"[BackgroundReader] Đã chọn sách '{book.title}' ({book.source}, {len(chapters)} phần).")
        return True

    # Consecutive failed fetches of the current book before giving it up. A
    # short network outage keeps our place; a deleted file or a removed page
    # must not leave her stuck on the same book forever.
    MAX_FETCH_FAILURES = 5

    def _fetch_failed(self, book) -> bool:
        """Count a failed fetch; True when the book was abandoned."""
        with self.lock:
            if self.current_book != book:
                return False
            self._fetch_failures += 1
            if self._fetch_failures < self.MAX_FETCH_FAILURES:
                return False
            # Listed as finished so _pick_new_book does not choose it again.
            self.finished_books.append(self._book_key(book))
            self.finished_books = self.finished_books[-self._MAX_FINISHED:]
            self.current_book = None
            self.chapters = []
            self.segments = []
            self._loaded_chapter = None
            self._fetch_failures = 0
        logger.warning(
            "[BackgroundReader] giving up on unreadable book source=%s after %d failures",
            book.source, self.MAX_FETCH_FAILURES,
        )
        self._save_progress()
        return True

    def _pick_new_book(self) -> bool:
        with self.lock:
            finished = set(self.finished_books)
        for source in self.sources:
            exclude = {k.split(":", 1)[1] for k in finished if k.startswith(f"{source.name}:")}
            try:
                book = source.random_book(exclude=frozenset(exclude))
            except Exception as exc:
                logger.warning("[BackgroundReader] random_book failed cause_type=%s", type(exc).__name__)
                continue
            if book is not None and self._select_book(book):
                return True
        return False

    def _split_segments(self, text: str) -> list:
        segments, current = [], ""
        for para in text.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            while len(para) > self.segment_chars:  # very long paragraph
                head, para = para[:self.segment_chars], para[self.segment_chars:]
                if current:
                    segments.append(current.strip())
                    current = ""
                segments.append(head)
            if current and len(current) + len(para) > self.segment_chars:
                segments.append(current.strip())
                current = ""
            current += para + "\n\n"
        if current.strip():
            segments.append(current.strip())
        return segments

    # -------------------------------------------------------------- reading
    def get_next_reading_material(self):
        """Return ``(tag, text)`` for the next real passage, or ``(None, None)``."""
        self.last_material_new_book = False
        for _attempt in range(8):
            with self.lock:
                book = self.current_book
                need_chapters = book is not None and not self.chapters
                if (
                    book is not None
                    and not need_chapters
                    and self._loaded_chapter == self.chapter_index
                ):
                    if self.segment_index < len(self.segments):
                        segment = self.segments[self.segment_index]
                        self.segment_index += 1
                        part, total = self.segment_index, len(self.segments)
                        chapter_title = self.chapters[self.chapter_index].title
                        fresh, self._fresh_book = self._fresh_book, False
                        tag = f"[Sách]: {book.title}"
                        if chapter_title and chapter_title != book.title:
                            tag += f" - {chapter_title}"
                        if total > 1:
                            tag += f" (đoạn {part}/{total})"
                        result = (tag, segment)
                    else:
                        # Chapter finished -> move on.
                        self.chapter_index += 1
                        self.segment_index = 0
                        self.segments = []
                        self._loaded_chapter = None
                        result = None
                    if result is not None:
                        self.last_material_new_book = fresh
                else:
                    result = None
                book_done = (
                    book is not None
                    and not need_chapters
                    and self.chapter_index >= len(self.chapters)
                )
                if book_done:
                    self.finished_books.append(self._book_key(book))
                    self.finished_books = self.finished_books[-self._MAX_FINISHED:]
                    self.current_book = None
                    self.chapters = []
                chapter = (
                    self.chapters[self.chapter_index]
                    if book is not None and not need_chapters and not book_done
                    else None
                )

            if result is not None:
                self._save_progress()
                return result
            if book is None or book_done:
                self._save_progress()
                if not self._pick_new_book():
                    return None, None
                continue

            source = self._source(book.source)
            if source is None:
                with self.lock:
                    self.current_book = None
                continue
            if need_chapters:
                chapters = source.chapters(book)
                if not chapters:
                    if self._fetch_failed(book):
                        continue  # gave up on it: pick another book
                    return None, None  # source unreachable: try again later
                with self.lock:
                    if self.current_book == book:
                        self.chapters = chapters
                continue

            text = source.fetch_chapter(book, chapter)
            if text is None:
                if self._fetch_failed(book):
                    continue
                # Network failure: keep our place instead of skipping the chapter.
                return None, None
            segments = self._split_segments(text)
            with self.lock:
                if self.current_book == book:
                    self._fetch_failures = 0
                    self.segments = segments
                    self._loaded_chapter = self.chapter_index
                    # A restored position past the end just finishes the chapter.
                    self.segment_index = min(self.segment_index, len(segments))
        return None, None

    # ----------------------------------------------------- user-facing tools
    def search_and_set_novel(self, keyword: str) -> str:
        try:
            for source in self.sources:
                for book in source.search(keyword, limit=5):
                    if self._select_book(book):
                        return f"✅ Đã tìm thấy và nạp sách '{book.title}' (nguồn: {source.name}). Aura sẽ đọc khi rảnh!"
            from core.tool_result import ToolFailure

            names = ", ".join(s.name for s in self.sources) or "không có nguồn nào"
            return ToolFailure(f"Không tìm thấy sách '{keyword}' trong các nguồn sách thật ({names}).")
        except Exception as e:
            from core.tool_result import ToolFailure

            return ToolFailure(f"⚠️ Lỗi khi tìm kiếm sách: {e}")

    def set_novel_by_url(self, novel_url: str) -> bool:
        for source in self.sources:
            try:
                book = source.book_from_url(novel_url)
                if book is not None and self._select_book(book):
                    return True
            except Exception as e:
                logger.error(f"[BackgroundReader] Lỗi khi nạp sách theo URL: {e}")
        return False

    def get_status(self) -> str:
        with self.lock:
            book = self.current_book
            if book is not None:
                remaining = max(0, len(self.chapters) - self.chapter_index) if self.chapters else "?"
                return f"Đang đọc: '{book.title}' ({book.source}). Còn {remaining} phần chưa đọc."
            return "Chưa có cuốn sách nào đang đọc. Có thể dùng 'search_novel' để tìm sách thật."
