import urllib.request
import urllib.parse
from bs4 import BeautifulSoup
from core.skills import SkillRegistry, Skill

def web_search(query: str) -> str:
    """Tự động tìm kiếm trên DuckDuckGo Lite bằng HTTP truyền thống (không cần API Key)."""
    try:
        url = 'https://html.duckduckgo.com/html/?q=' + urllib.parse.quote(query.strip())
        req = urllib.request.Request(
            url, 
            data=None, 
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        )
        with urllib.request.urlopen(req) as response:
            html = response.read()

        soup = BeautifulSoup(html, 'html.parser')
        
        results = []
        for i, a in enumerate(soup.find_all('a', class_='result__snippet')):
            if i >= 3: # Lấy top 3 kết quả
                break
            results.append(a.text.strip())
            
        if not results:
            return "Không tìm thấy kết quả đáng chú ý."
            
        return "\n".join([f"- {r}" for r in results])
    except Exception as e:
        return f"Lỗi tìm kiếm: {e}"

def read_time(args: str = "") -> str:
    """Trả về thời gian hiện tại."""
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S %A, %d %B %Y")

def get_skill_registry() -> SkillRegistry:
    registry = SkillRegistry()
    registry.register(Skill(
        name="web_search",
        description="Tìm kiếm mạng lấy sự thật, tin tức",
        usage_format="ACTION: web_search | thời tiết hà nội hôm nay",
        func=web_search
    ))
    registry.register(Skill(
        name="read_time",
        description="Đọc đồng hồ hệ thống",
        usage_format="ACTION: read_time | None",
        func=read_time
    ))
    return registry
