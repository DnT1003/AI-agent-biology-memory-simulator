import random
import time
from bs4 import BeautifulSoup
from DrissionPage import ChromiumPage, ChromiumOptions

class DoclnReader:
    def __init__(self):
        try:
            co = ChromiumOptions()
            co.headless(False)  # Bắt buộc False để qua mặt Cloudflare Turnstile
            co.set_argument('--disable-blink-features=AutomationControlled')
            self.page = ChromiumPage(co)
            self.base_url = "https://docln.net"
            
            # Pass Cloudflare initial check
            print("[Reader] Đang thiết lập kết nối vượt Cloudflare...")
            self.page.get(self.base_url, timeout=25)
            time.sleep(10) # Chờ Turnstile giải đố JS
            
        except Exception as e:
            print(f"[Reader] Error init DrissionPage: {e}")
            self.page = None

    def __del__(self):
        if hasattr(self, 'page') and self.page:
            try:
                self.page.quit()
            except:
                pass

    def get_random_novel_url(self):
        if not self.page: return None
        try:
            self.page.get(f"{self.base_url}/danh-sach")
            # Cần chờ 1 xíu để JS tải danh sách truyện
            time.sleep(3)
            
            html = self.page.html
            soup = BeautifulSoup(html, 'html.parser')
            novel_links = soup.select('.thumb-wrapper a')
            if novel_links:
                chosen = random.choice(novel_links)
                href = chosen['href']
                import re
                match = re.search(r'(/truyen/[^/]+)', href)
                if match:
                    return self.base_url + match.group(1)
                return self.base_url + href
        except Exception as e:
            print(f"[Reader] Lỗi lấy truyện ngẫu nhiên: {e}")
        return None

    def get_novel_chapters(self, novel_url):
        if not self.page: return "Unknown", []
        try:
            self.page.get(novel_url)
            time.sleep(2)
            
            html = self.page.html
            soup = BeautifulSoup(html, 'html.parser')
            title_tag = soup.select_one('.series-name a')
            novel_title = title_tag.text.strip() if title_tag else "Unknown Novel"
            
            chapters = []
            for a in soup.select('.chapter-name a'):
                chapters.append({
                    "title": a.text.strip(),
                    "url": self.base_url + a['href']
                })
            return novel_title, chapters
        except Exception as e:
            print(f"[Reader] Lỗi lấy danh sách chương: {e}")
            return "Unknown", []

    def read_chapter(self, chapter_url):
        if not self.page: return None
        try:
            self.page.get(chapter_url)
            time.sleep(2)
            
            html = self.page.html
            soup = BeautifulSoup(html, 'html.parser')
            content_div = soup.select_one('#chapter-content')
            if content_div:
                for tag in content_div(['script', 'style', 'iframe']):
                    tag.decompose()
                paragraphs = [p.text.strip() for p in content_div.find_all('p') if p.text.strip()]
                return "\n\n".join(paragraphs) if paragraphs else content_div.text.strip()
                    
        except Exception as e:
             print(f"[Reader] Lỗi tải nội dung chương: {e}")
        return None

class BackgroundReader:
    def __init__(self, llm_instance):
        self.docln = DoclnReader()
        self.llm = llm_instance
        self.current_novel_title = None
        self.chapters_queue = []
        self.simulated_chapter = 1
        
    def get_next_reading_material(self):
        """Lấy 1 chunk reading (60% truyện docln/fallback, 40% wiki/kiến thức)"""
        if random.random() < 0.60:
            # 1. Thử cào Docln.net
            if not self.chapters_queue:
                url = self.docln.get_random_novel_url()
                if url:
                    title, chapters = self.docln.get_novel_chapters(url)
                    if chapters:
                        self.current_novel_title = title
                        self.chapters_queue = chapters
                        
            if self.chapters_queue:
                chapter = self.chapters_queue.pop(0)
                content = self.docln.read_chapter(chapter['url'])
                if content:
                    return f"[Truyện Tiểu Thuyết docln.net]: {self.current_novel_title} - {chapter['title']}", content[:1500]
            
            # 2. FALLBACK: Nếu Cloudflare block, nhờ LLM viết tiếp 1 chương truyện anime/novel giả lập
            self.current_novel_title = self.current_novel_title or "Bình minh của Kỷ nguyên Máy"
            prompt = f"Bạn là một tác giả Light Novel. Hãy viết CHƯƠNG {self.simulated_chapter} cho bộ truyện '{self.current_novel_title}'. Nội dung dài khoảng 300 chữ, phong cách anime, giả tưởng. Giọng văn cực kỳ lôi cuốn, có hội thoại và miêu tả nội tâm."
            self.simulated_chapter += 1
            content = self.llm.generate_text(prompt, temperature=0.9)
            return f"[Truyện Tiểu Thuyết]: {self.current_novel_title} - Chương {self.simulated_chapter-1}", content

        else:
            # 40% Kiến thức Wikipedia/Khoa học
            prompt = "Đóng vai bách khoa toàn thư. Viết ngẫu nhiên 1 đoạn (150 chữ) về một mảng kiến thức khoa học, vũ trụ, triết học hoặc sinh học kỳ lạ mà ít người biết đến."
            content = self.llm.generate_text(prompt, temperature=0.9)
            return "[Kiến Thức Mạng]", content
