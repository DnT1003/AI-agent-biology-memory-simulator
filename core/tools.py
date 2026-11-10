import urllib.request
import urllib.parse
import json
from bs4 import BeautifulSoup
from core.skills import Skill, SkillRegistry
from core.tool_result import ToolFailure

def web_search(query: str) -> str:
    """Tự động tìm kiếm trên DuckDuckGo Lite bằng HTTP truyền thống (không cần API Key)."""
    try:
        url = 'https://html.duckduckgo.com/html/?q=' + urllib.parse.quote(query)
        req = urllib.request.Request(
            url, 
            data=None, 
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        )
        with urllib.request.urlopen(req, timeout=10) as response:
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
        return ToolFailure(f"Lỗi tìm kiếm: {e}")

def read_time() -> str:
    """Trả về thời gian hiện tại."""
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S %A, %d %B %Y")

# Khai báo cấu trúc Function Declaration cho Google GenAI
TOOLS_DECLARATION = [
    {
        "name": "web_search",
        "description": "Tìm kiếm thông tin trực tuyến trên Internet. Sử dụng công cụ này khi người dùng hỏi các thông tin thực tế, kiến thức khách quan, tình hình thời tiết, sự kiện đang diễn ra hoặc bất kỳ thông tin nào bạn không biết chắc chắn.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": "Câu truy vấn tìm kiếm ngắn gọn (Ví dụ: 'Thời tiết Hà Nội hôm nay', 'Tỷ giá USD', 'Ai trúng cử tổng thống Mỹ')"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "read_time",
        "description": "Đọc đồng hồ hệ thống. Sử dụng khi cần biết chính xác ngày giờ hiện tại, thứ mấy.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    }
]

def execute_tool(func_name: str, args: dict) -> str:
    """Thực thi function dựa trên tên"""
    print(f"\n[HỆ THỐNG]: Đang thực thi Tool {func_name}({args})...")
    if func_name == "web_search":
        return web_search(args.get("query", ""))
    elif func_name == "read_time":
        return read_time()
    return ToolFailure(f"Unknown tool: {func_name}")

def get_skill_registry() -> SkillRegistry:
    """Khởi tạo và trả về SkillRegistry với các kỹ năng mặc định."""
    registry = SkillRegistry()
    
    registry.register(Skill(
        name="web_search",
        description="Tìm kiếm thông tin trực tuyến trên Internet. Dùng khi cần tra cứu kiến thức khách quan, tin tức, thời tiết, sự kiện thực tế.",
        usage_format="ACTION: web_search | <câu truy vấn>",
        func=web_search
    ))
    
    registry.register(Skill(
        name="read_time",
        description="Đọc giờ hệ thống hiện tại.",
        usage_format="ACTION: read_time | now",
        func=lambda x: read_time()
    ))
    
    # --- CÁC CÔNG CỤ NHẬN THỨC CỐT LÕI (COGNITIVE ACTIONS) ---
    registry.register(Skill(
        name="add_goal",
        description="Thiết lập mục tiêu dài hạn để Aura thực hiện ngầm.",
        usage_format="ACTION: add_goal | <tên mục tiêu>",
        func=lambda x: registry._ego_action(x, "add_goal")
    ))
    
    registry.register(Skill(
        name="search_novel",
        description="Tìm kiếm truyện trên docln.net và nạp vào hàng đợi đọc.",
        usage_format="ACTION: search_novel | <tên truyện>",
        func=lambda x: registry._reader_action(x, "search_novel")
    ))
    
    registry.register(Skill(
        name="start_reading",
        description="Bắt đầu phiên đọc tiểu thuyết ngay lập tức.",
        usage_format="ACTION: start_reading | now",
        func=lambda x: registry._autonomous_action(x, "start_reading")
    ))
    
    # --- Nạp các kỹ năng tự học (Self-Evolution) ---
    registry.load_dynamic_skills()

    # --- OpenClaw Gateway Skills (tuỳ chọn) ---
    # Chỉ đăng ký nếu OPENCLAW_GATEWAY_URL có trong .env — không ảnh hưởng gì nếu thiếu
    import os
    if os.getenv("OPENCLAW_GATEWAY_URL"):
        try:
            from core.skills_openclaw import register_openclaw_skills
            register_openclaw_skills(registry)
        except Exception as e:
            print(f"[tools.py] Không thể nạp OpenClaw skills: {e}")

    return registry
