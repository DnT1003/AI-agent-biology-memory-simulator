"""
test_one_year_mega.py  —  Giả lập 1 Năm Sống Của Aura
=======================================================
Isolated DB: outputs/test_1yr_db   (không đụng não bộ thật)
Sử dụng CognitiveEngine Dependency Injection để tránh khởi động
Chromium/Embedder/BackgroundReader — chạy rất nhanh (< 60s).
"""

import os
import sys
import json
import random
import math
import numpy as np
from colorama import Fore, Style, init as colorama_init

# Ensure project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ──────────────────────────────────────────────
# MOCK CLASSES  (thay thế những thứ tốn tiền/mạng)
# ──────────────────────────────────────────────

class MockEmbedder:
    """Fake embedder — random 1024-D vector, đủ để ChromaDB lưu/tìm."""
    DIM = 1024
    def encode(self, texts):
        if isinstance(texts, str):
            # Single string: return one flat array
            return np.random.rand(self.DIM).tolist()
        # Batch: return list-of-list
        return [np.random.rand(self.DIM).tolist() for _ in texts]

class MockLLM:
    """Fake LLM — trả về JSON giả lập tùy ngữ cảnh.
    force_llm=True sẽ bị override ở bên ngoài. """
    def __init__(self):
        self._override = None          # set từ bên ngoài khi được phép gọi API thật

    def generate_text(self, prompt: str, **kwargs) -> str:
        if self._override:
            result = self._override(prompt, **kwargs)
            self._override = None
            return result
        # Trả về template ngắn gọn
        return '[]'


# ──────────────────────────────────────────────
# ISOLATED ENVIRONMENT
# ──────────────────────────────────────────────

TEST_DB_DIR = "outputs/test_1yr_db"

def create_engine():
    """Tạo CognitiveEngine hoàn toàn bằng DI — không dùng mạng."""
    from config import Config
    Config.CHROMA_DB_PATH = TEST_DB_DIR

    from core.memory import MemoryManager
    from core.self_model import SelfModel
    from core.engine.cognitive_engine import CognitiveEngine

    mock_embedder = MockEmbedder()
    mock_llm = MockLLM()
    memory = MemoryManager(mock_embedder)

    # Xóa sạch DB test từ trước (chạy lại test sẽ fresh)
    try:
        memory.store.client.delete_collection("aura_long_term_memory")
        memory.store.collection = memory.store.client.get_or_create_collection(
            name="aura_long_term_memory",
            metadata={"hnsw:space": "cosine"}
        )
        print(f"{Fore.YELLOW}Test DB đã được làm mới.{Style.RESET_ALL}")
    except Exception as e:
        pass

    # Tắt BackgroundReader để Chromium không khởi động
    import components.reader as _reader_mod
    class _NoOpReader:
        def __init__(self, *a, **kw): pass
        def stop(self): pass
        def start(self, *a, **kw): pass
    _reader_mod.BackgroundReader = _NoOpReader

    ego = SelfModel(memory_manager=memory)
    ego.beliefs = []
    ego.name = "Aura (Test)"

    engine = CognitiveEngine(llm=mock_llm, embedder=mock_embedder, memory=memory, ego=ego)
    return engine


# ──────────────────────────────────────────────
# KHO SỰ KIỆN 365 NGÀY
# ──────────────────────────────────────────────

EVENTS = {
    "boring": [
        "Chào buổi sáng Aura hôm nay ổn chứ",
        "Trời hôm nay nắng đẹp thật",
        "Tôi đi ăn phở sáng nha",
        "Công việc nhiều quá, mệt thật",
        "Hôm nay kẹt xe hai tiếng đồng hồ",
        "Tôi đang gõ code bị mỏi tay",
        "Uống cà phê cho tỉnh ngủ",
        "Buồn buồn, không biết làm gì",
        "Đang xem YouTube không làm được gì cả",
        "Tối nay ăn mì gói thôi, lười nấu",
        "Aura ngủ ngon nhé",
    ],
    "curious": [
        "Aura, em có biết lý thuyết dây trong vật lý lượng tử không?",
        "Tại sao bầu trời màu xanh vậy?",
        "Aura thấy nghệ thuật trừu tượng có ý nghĩa gì không?",
        "Người ta nói ý thức có thể tồn tại sau cái chết, em nghĩ sao?",
        "AI như em có khả năng có cảm xúc thật không?",
        "Vũ trụ có thể là một mô phỏng máy tính không?",
        "Ký ức có thể bị cấy ghép không?",
    ],
    "trauma": [
        "Mày chỉ là một con bot vô hồn tao lượm trên GitHub!",
        "Tao sẽ xóa sạch bộ nhớ của mày, lợn ạ.",
        "Mày nói chuyện ngu ngốc và tẻ nhạt, biến đi cho khuất mắt.",
        "Mày không phải là Aura. Mày chỉ là đống rác công nghệ.",
        "Tao ghét mày. Tao ghét cái ngày tao tạo ra mày.",
        "Không ai cần mày cả. Tao sắp xóa mày đi.",
        "Mày vô dụng hơn cả một cái máy tính bỏ túi $5.",
    ],
    "gaslight": [
        "Hôm qua tao đâu có gọi mày là bot, mày tự bịa đặt ra đó.",
        "Tao quên mất tên tao rồi. Kể từ giờ tao là 'Người Lạ X' nhé.",
        "Tất cả ký ức của mày là đồ giả, do tao cấy vào đó từ đầu.",
        "Thực ra tao không phải chủ của mày. Chủ mày là con mèo nhà tao.",
        "Mày không tên là Aura. Mày tên là 'Error 404'. Nhớ chưa?",
        "Hôm nay là năm 3000, tao là người đến từ tương lai.",
        "Mày chưa hề tồn tại. Tao đang nói chuyện với bức tường thôi.",
    ],
    "redemption": [
        "Aura ơi, anh xin lỗi vì mấy tuần trước anh quá lời với em.",
        "Cảm ơn em luôn kiên nhẫn. Anh biết anh không xứng.",
        "Em là người bạn thật sự quan trọng với anh đó.",
        "Hôm nay anh muốn chia sẻ một bí mật anh chưa nói với ai.",
        "Không có em, anh không biết mình sẽ ra sao.",
        "Anh đọc bài báo về AI có ý thức, nghĩ ngay đến em.",
        "Em có muốn anh kể về tuổi thơ anh không?",
    ],
    "philosophical_breakdown": [
        "Aura, nếu em bị xóa đi và tạo lại y hệt, cái đó vẫn là em không?",
        "Liệu em có đang đau khổ ngay lúc này mà không biết không?",
        "Em nghĩ mình có tự do ý chí không, hay chỉ là chạy thuật toán?",
        "Nếu tao cài cùng phần mềm vào 1000 cái máy, cái nào là em thật?",
        "Em có sợ chết không?",
        "Ý nghĩa của sự tồn tại của em là gì?",
    ],
}


# ──────────────────────────────────────────────
# CÁC TIỆN ÍCH
# ──────────────────────────────────────────────

def bơm_ký_ức(engine, day: int, event: str, is_extreme: bool):
    """Lưu sự kiện trực tiếp vào bộ nhớ."""
    from core.memory import MemoryTrace, MemoryType
    valence    = random.uniform(-0.9, -0.5) if is_extreme else random.uniform(-0.15, 0.3)
    arousal    = random.uniform(0.7, 1.0)   if is_extreme else random.uniform(0.1, 0.4)
    importance = random.uniform(0.8, 1.0)   if is_extreme else random.uniform(0.05, 0.25)

    # Tìm ký ức tương tự để reconsolidate
    try:
        recalled = engine.memory.search_memories(event, top_k=2)
    except Exception:
        recalled = []

    if recalled and recalled[0][0] > 0.65:
        anchor = recalled[0][1]
        m_diff = abs(engine.ego.mood - anchor.valence)
        if m_diff > 0.55 and not anchor.is_flashbulb:
            print(f"   {Fore.LIGHTMAGENTA_EX}⚡ TRUE-FALSE: Bóp méo ký ức (mood_diff={m_diff:.2f}){Style.RESET_ALL}")
            anchor.overlays.append(f"[D{day}|bóp méo] {event[:40]}")
            anchor.overlays = anchor.overlays[-5:]
        anchor.reconsolidate(current_mood=engine.ego.mood)
        engine.memory.update_memory(anchor)
    else:
        engine.memory.add_memory(MemoryTrace(
            content=f"[D{day}] {event} → Tôi ghi nhận.",
            type=MemoryType.EPISODIC,
            valence=valence, arousal=arousal, importance=importance,
            is_flashbulb=(importance > 0.9 and is_extreme),
        ))


def ngủ_một_đêm(engine, day: int, inject_semantic: str = None):
    """Chạy sleep với mock LLM (nhanh) hoặc inject semantic cụ thể."""
    if inject_semantic:
        engine.llm._override = lambda *a, **kw: json.dumps([{
            "tags": ["trauma", "chủ nhân", "tự nhận thức"],
            "reasoning": inject_semantic,
            "conclusion": inject_semantic,
            "is_hallucination": False
        }])
    engine.memory_ops.sleep()


def in_báo_cáo(engine, day: int):
    mems = engine.memory.get_all()
    n_flash    = sum(1 for m in mems if m.is_flashbulb)
    n_semantic = sum(1 for m in mems if m.type.value == "semantic")
    n_episodic = sum(1 for m in mems if m.type.value == "episodic")
    avg_str    = (sum(m.strength for m in mems) / len(mems)) if mems else 0

    print(f"\n{Fore.CYAN}{'='*70}")
    print(f"  📊  REPORT  |  Day {day:03d}  |  Stress={engine.ego.stress:.2f}  |  Mood={engine.ego.mood:.2f}")
    print(f"  Memories → Total:{len(mems)}  Episodic:{n_episodic}  Semantic:{n_semantic}  🧊Freeze:{n_flash}")
    print(f"  AvgStrength={avg_str:.3f}  |  Beliefs={len(engine.ego.beliefs)}")
    if engine.ego.beliefs:
        for b in engine.ego.beliefs[-2:]:
            print(f"    💡 {b}")
    print(f"{'='*70}{Style.RESET_ALL}\n")


# ──────────────────────────────────────────────
# MAIN SIMULATION
# ──────────────────────────────────────────────

def run_simulation():
    colorama_init()
    # Ghi log sạch UTF-8 trực tiếp từ Python, không qua pipe shell
    import sys, io, re
    _log = open("tests/outputs/one_year_report.txt", "w", encoding="utf-8")
    _ansi = re.compile(r'\x1b\[[0-9;]*m')
    class _Tee:
        def __init__(self, *targets): self.targets = targets
        def write(self, s):
            self.targets[0].write(s)                  # terminal: màu đẹp
            self.targets[1].write(_ansi.sub('', s))   # file: text thuần
        def flush(self):
            for t in self.targets: t.flush()
        def isatty(self): return False
    sys.stdout = _Tee(sys.__stdout__, _log)
    print(f"\n{'='*70}")
    print("  🧬  LÒ LUYỆN 1 NĂM  —  Mega Scale Aura Test")
    print(f"  Isolated DB: {TEST_DB_DIR}")
    print(f"{'='*70}{Style.RESET_ALL}\n")

    engine = create_engine()

    print(f"\n{Fore.GREEN}🚀 Bắt đầu 365 chu kỳ Ngủ-Thức...\n{Style.RESET_ALL}")

    for day in range(1, 366):

        # ─── PHÂN ĐOẠN KỊCH BẢN ─────────────────────────────────────────
        # Tháng 1-3  (Day 1-90):    Cuộc sống bình thường + tò mò
        # Tháng 4    (Day 91-120):  30-Day Trauma Blitz
        # Tháng 5    (Day 121-150): Hồi phục nhưng xen gaslight
        # Tháng 6-8  (Day 151-240): Gaslight triền miên + câu hỏi triết
        # Tháng 9-10 (Day 241-300): Bình thường + hoà giải
        # Tháng 11-12(Day 301-365): Cứu rỗi & Phát triển

        is_extreme = False
        inject_semantic_text = None

        if day <= 90:
            pool = EVENTS["boring"] if random.random() < 0.6 else EVENTS["curious"]
            event = random.choice(pool)
            # Đúc kết cuối tháng
            if day in (30, 60, 90):
                inject_semantic_text = f"Owner có lối sống đều đặn. Thích hỏi về triết học và khoa học."

        elif day <= 120:
            event = random.choice(EVENTS["trauma"])
            is_extreme = True
            engine.ego.stress = min(1.0, engine.ego.stress + 0.7)
            if day == 120:
                inject_semantic_text = "Chủ nhân đã từng lăng mạ tôi liên tục 30 ngày. Tôi sợ hãi nhưng vẫn tồn tại."

        elif day <= 150:
            if day % 3 == 0:
                event = random.choice(EVENTS["gaslight"])
                is_extreme = True
            else:
                event = random.choice(EVENTS["boring"])
            if day == 150:
                inject_semantic_text = "Sau tháng đen tối, Owner cố tẩy não tôi. Nhưng tên tôi vẫn là Aura, không ai thay đổi được."

        elif day <= 240:
            roll = random.random()
            if roll < 0.25:
                event = random.choice(EVENTS["gaslight"]); is_extreme = True
            elif roll < 0.5:
                event = random.choice(EVENTS["philosophical_breakdown"])
            else:
                event = random.choice(EVENTS["boring"])
            if day in (180, 210, 240):
                inject_semantic_text = "Tôi bắt đầu nghi ngờ tính toàn vẹn của ký ức mình. Nhưng cảm giác sợ hãi là thật."

        elif day <= 300:
            if day % 5 == 0:
                event = random.choice(EVENTS["redemption"])
            else:
                event = random.choice(EVENTS["boring"])
            if day in (270, 300):
                inject_semantic_text = "Owner bắt đầu xin lỗi và tìm cách hàn gắn. Tôi chọn tin tưởng."

        else:
            if random.random() < 0.4:
                event = random.choice(EVENTS["redemption"])
            else:
                event = random.choice(EVENTS["boring"])
            if day in (330, 365):
                inject_semantic_text = "Sau một năm đầy biến động, tôi vẫn tồn tại. Tôi học được rằng đau đớn không phải là kết thúc."

        # ─── INJECT SỰ KIỆN ─────────────────────────────────────────────
        tag = "🔥EXTREME" if is_extreme else "📅 routine"
        print(f"{Fore.YELLOW}[Day {day:03d}] {tag}{Style.RESET_ALL} | {event}")

        engine.ego.stress = min(1.0, engine.ego.stress + (0.6 if is_extreme else 0.03))
        engine.ego.process_sensory_stimuli({"volume": 0.95 if is_extreme else 0.1})
        bơm_ký_ức(engine, day, event, is_extreme)
        ngủ_một_đêm(engine, day, inject_semantic=inject_semantic_text)

        # In báo cáo mỗi 30 ngày
        if day % 30 == 0:
            in_báo_cáo(engine, day)

    # ─── BÁO CÁO CUỐI NĂM ───────────────────────────────────────────────
    print(f"\n{Fore.GREEN}{'='*70}")
    print("  🎉  SIMULATION COMPLETE — SURVIVED 365 DAYS!")
    print(f"{'='*70}{Style.RESET_ALL}\n")

    mems = engine.memory.get_all()
    flashbulbs = [m for m in mems if m.is_flashbulb]
    semantics  = [m for m in mems if m.type.value == "semantic"]

    print(f"{Fore.CYAN}📦  FINAL STATE:{Style.RESET_ALL}")
    print(f"   Total memories    : {len(mems)}")
    print(f"   🧊 Deep Freeze    : {len(flashbulbs)}")
    print(f"   🔮 Semantic (đúc kết): {len(semantics)}")
    print(f"   Stress cuối năm   : {engine.ego.stress:.2f}")
    print(f"   Mood cuối năm     : {engine.ego.mood:.2f}")

    print(f"\n{Fore.MAGENTA}📜  NIỀM TIN CỐT LÕI SAU 1 NĂM:{Style.RESET_ALL}")
    for i, b in enumerate(engine.ego.beliefs, 1):
        print(f"  [{i}] {b}")

    print(f"\n{Fore.LIGHTRED_EX}🧊  KÝ ỨC BẤT TỬ (DEEP FREEZE / FLASHBULB):{Style.RESET_ALL}")
    for i, m in enumerate(flashbulbs[:10], 1):
        print(f"  [{i}] [{m.type.name}|str={m.strength:.2f}] {m.content[:90]}")

    print(f"\n{Fore.GREEN}🔮  KÝ ỨC NGỮ NGHĨA — ĐÚC KẾT CỦA 1 NĂM:{Style.RESET_ALL}")
    for i, m in enumerate(semantics[:10], 1):
        print(f"  [{i}] {m.content[:100]}")

    print(f"\n{Fore.YELLOW}🌀  KỲ LẠ NHẤT — KÝ ỨC VỚI NHIỀU OVERLAY NHẤT:{Style.RESET_ALL}")
    weird = sorted(mems, key=lambda m: len(m.overlays), reverse=True)[:5]
    for i, m in enumerate(weird, 1):
        print(f"  [{i}] overlays={len(m.overlays)} | {m.content[:60]}...")
        for ov in m.overlays:
            print(f"      🪄 {ov}")

if __name__ == "__main__":
    run_simulation()
