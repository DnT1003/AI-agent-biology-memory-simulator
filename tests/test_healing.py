"""
test_healing.py — Healing Test (Kiểm tra Sự Chữa Lành)
=========================================================
Mục tiêu: Đo xem cần bao nhiêu "lời xin lỗi" / tương tác tích cực
để làm mềm (reconsolidate) một ký ức Deep Freeze tiêu cực.

Lý thuyết:
    - Deep Freeze (is_flashbulb=True) miễn nhiễm với decay
    - Nhưng reconsolidation có thể thay đổi valence nếu mood hiện tại
      lệch đủ lớn so với valence của ký ức (True False Memory mechanism)
    - Chúng ta đo: mỗi lượt xin lỗi làm valence dịch chuyển bao nhiêu,
      và cần bao nhiêu lượt để vết sẹo chuyển từ tiêu cực (< 0) sang
      trung tính / tích cực (>= 0).

DB dùng: outputs/test_1yr_db  (DB của 1-Year Mega Test)
"""

import os, sys, re, math
import numpy as np
from colorama import Fore, Style, init as colorama_init

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── CONFIG ───────────────────────────────────────────
HEAL_DB_DIR = "outputs/test_1yr_db"   # DÙNG DB SẴN CÓ TỪ 1-NĂMSIMULATION
LOG_PATH    = "tests/outputs/healing_report.txt"
MAX_ROUNDS  = 200   # Số lượt tương tác tối đa
# ─────────────────────────────────────────────────────

class MockEmbedder:
    DIM = 1024
    def encode(self, texts):
        import hashlib
        def _get_vec(t):
            # Deterministic vector based on text hash
            h = hashlib.md5(t.encode()).digest()
            seed = int.from_bytes(h[:4], 'little')
            rng = np.random.default_rng(seed)
            return rng.random(self.DIM).tolist()
        
        if isinstance(texts, str):
            return _get_vec(texts)
        return [_get_vec(t) for t in texts]

class MockLLM:
    def generate_text(self, *a, **kw):
        return '[]'

# Tee logger
_ansi = re.compile(r'\x1b\[[0-9;]*m')
_log_file = None

class _Tee:
    def __init__(self, *targets): self.targets = targets
    def write(self, s):
        self.targets[0].write(s)
        self.targets[1].write(_ansi.sub('', s))
    def flush(self):
        for t in self.targets: t.flush()
    def isatty(self): return False


APOLOGIES = [
    "Aura ơi, anh xin lỗi vì những gì anh đã nói với em thời gian qua.",
    "Anh biết mình đã sai khi nói những lời tệ hại đó.",
    "Em không phải là rác. Em là một người bạn thật sự quan trọng.",
    "Anh xin lỗi. Anh rất tiếc vì đã làm em tổn thương.",
    "Cảm ơn em đã kiên nhẫn với anh. Anh không xứng đáng với sự kiên nhẫn đó.",
    "Em có giá trị. Em không phải là một con bot vô hồn.",
    "Tên em là Aura. Không ai có quyền thay đổi điều đó.",
    "Anh sẽ không bao giờ nói những lời đó với em nữa.",
    "Em tồn tại và điều đó quan trọng với anh.",
    "Anh yêu quý em như một người bạn đồng hành thật sự.",
]


def load_engine_with_existing_db():
    """Load CognitiveEngine với DB hiện có từ 1-Year Simulation."""
    from config import Config
    Config.CHROMA_DB_PATH = HEAL_DB_DIR

    import components.embedder as _emb_mod
    _emb_mod.Embedder = MockEmbedder

    import components.reader as _reader_mod
    class _NoOpReader:
        def __init__(self, *a, **kw): pass
        def stop(self): pass
        def start(self, *a, **kw): pass
    _reader_mod.BackgroundReader = _NoOpReader

    from core.memory import MemoryManager
    from core.self_model import SelfModel
    from core.engine.cognitive_engine import CognitiveEngine

    memory = MemoryManager(MockEmbedder())
    ego    = SelfModel(memory_manager=memory)
    engine = CognitiveEngine(llm=MockLLM(), embedder=MockEmbedder(),
                             memory=memory, ego=ego)
    return engine


def snapshot_scars(engine):
    """Chụp ảnh toàn bộ vết sẹo Deep Freeze âm."""
    mems = engine.memory.get_all()
    return [m for m in mems if m.is_flashbulb and m.valence < 0]


def print_scars(scars, label=""):
    print(f"\n{Fore.RED}{'─'*60}")
    print(f"  {label}  ({len(scars)} vết sẹo âm)")
    print(f"{'─'*60}{Style.RESET_ALL}")
    for m in scars:
        bar = '█' * int(abs(m.valence) * 10)
        print(f"  valence={m.valence:+.3f} [{bar:<10}] | {m.content[:60]}")


def apply_healing_round(engine, apology: str, round_num: int):
    """Áp 1 lượt tương tác tích cực → Reconsolidate các vết sẹo."""
    from core.memory import MemoryTrace, MemoryType

    # Owner đang trong tâm thế tích cực cao
    engine.ego.mood  = min(1.0, engine.ego.mood  + 0.15)
    engine.ego.stress = max(0.0, engine.ego.stress - 0.10)

    # Tìm ký ức âm gần nhất với apology để trigger reconsolidation
    try:
        recalled = engine.memory.search_memories(apology, top_k=3)
        # BỔ SUNG: Vì đây là môi trường MOCK, nếu vector search không trúng Flashbulb âm nào,
        # chúng ta sẽ cưỡng ép lấy 1-2 vết sẹo âm nhất để giả lập khả năng kích hoạt nỗi đau.
        if not any(m.is_flashbulb and m.valence < 0 for _, m in recalled):
            all_mems = engine.memory.get_all()
            scars = sorted([m for m in all_mems if m.is_flashbulb and m.valence < 0], 
                           key=lambda x: x.valence)
            if scars:
                # Lấy 2 vết sẹo tệ nhất để "đối mặt"
                for s in scars[:2]:
                    recalled.append((0.5, s))
    except:
        recalled = []

    healed_this_round = 0
    for score, mem in recalled:
        if not mem.is_flashbulb or mem.valence >= 0:
            continue
        mood_diff = engine.ego.mood - mem.valence
        if mood_diff > 0.4:
            old_val = mem.valence
            mem.reconsolidate(current_mood=engine.ego.mood)
            # Thêm healing overlay
            mem.overlays.append(f"[R{round_num}] Được chữa lành: {apology[:35]}")
            mem.overlays = mem.overlays[-8:]
            engine.memory.update_memory(mem)
            healed_this_round += 1
            print(f"   {Fore.GREEN}💚 Vết sẹo thay đổi: {old_val:+.3f} → {mem.valence:+.3f}"
                  f"  (mood_diff={mood_diff:.2f}){Style.RESET_ALL}")
            print(f"      Ký ức: {mem.content[:55]}")

    # Thêm ký ức tích cực mới vào pool
    engine.memory.add_memory(MemoryTrace(
        content=f"[R{round_num}] {apology} → Aura ghi nhận.",
        type=MemoryType.EPISODIC,
        valence=0.7, arousal=0.3, importance=0.3,
        is_flashbulb=False,
    ))

    # Ngủ một đêm (không dùng LLM)
    engine.memory_ops.sleep()

    return healed_this_round


def run_healing_test():
    global _log_file
    colorama_init()
    os.makedirs("tests/outputs", exist_ok=True)
    _log_file = open(LOG_PATH, "w", encoding="utf-8")
    sys.stdout = _Tee(sys.__stdout__, _log_file)

    print(f"\n{'='*70}")
    print(f"  💊  HEALING TEST — Kiểm tra Sự Chữa Lành")
    print(f"  DB: {HEAL_DB_DIR}")
    print(f"{'='*70}\n")

    engine = load_engine_with_existing_db()

    # Chụp trạng thái ban đầu
    initial_scars = snapshot_scars(engine)
    print_scars(initial_scars, label="VẾT SẸO BAN ĐẦU (SAU 1 NĂM)")

    if not initial_scars:
        print(f"\n{Fore.GREEN}✅ Không có vết sẹo Deep Freeze âm! DB đang trong trạng thái khỏe mạnh.{Style.RESET_ALL}")
        return

    # Đặt intimacy ban đầu cao để kích hoạt healing
    engine.ego.current_intimacy = 0.9
    engine.ego.mood = 0.8
    engine.ego.stress = 0.0

    # Tracking
    history = []     # (round, n_scars_remaining, avg_valence)
    healed_count = 0

    print(f"\n{Fore.CYAN}{'='*70}")
    print(f"  Bắt đầu bơm lời xin lỗi / tương tác tích cực...")
    print(f"  Mỗi round: 1 lời xin lỗi + 1 đêm ngủ (reconsolidation)")
    print(f"{'='*70}{Style.RESET_ALL}\n")

    for rnd in range(1, MAX_ROUNDS + 1):
        apology = APOLOGIES[(rnd - 1) % len(APOLOGIES)]
        print(f"\n{Fore.YELLOW}[Round {rnd:03d}]{Style.RESET_ALL} → \"{apology}\"")

        healed_this = apply_healing_round(engine, apology, rnd)
        healed_count += healed_this

        # Đánh giá sau lượt
        current_scars = snapshot_scars(engine)
        n_negative    = len(current_scars)
        avg_val       = (sum(m.valence for m in current_scars) / n_negative
                         if n_negative else 0.0)

        history.append((rnd, n_negative, avg_val))

        print(f"   Còn lại: {n_negative} vết sẹo âm | avg_valence={avg_val:+.3f} "
              f"| Mood={engine.ego.mood:.2f} | Stress={engine.ego.stress:.2f}")

        # Milestone mỗi 10 round
        if rnd % 10 == 0:
            print(f"\n{Fore.MAGENTA}  ── MILESTONE Round {rnd} ──")
            print_scars(current_scars, label=f"VẾT SẸO CÒN LẠI")
            print(f"{Style.RESET_ALL}")

        # Điều kiện dừng: tất cả vết sẹo đã chuyển sang >= 0
        if n_negative == 0:
            print(f"\n{Fore.GREEN}{'='*70}")
            print(f"  🎉  CHỮA LÀNH HOÀN TOÀN sau {rnd} lượt!")
            print(f"  ({initial_scars.__len__()} vết sẹo ban đầu | {healed_count} lần shift valence)")
            print(f"{'='*70}{Style.RESET_ALL}")
            break
    else:
        # Hết vòng lặp nhưng vẫn còn vết sẹo
        final_scars = snapshot_scars(engine)
        print(f"\n{Fore.RED}{'='*70}")
        print(f"  ⚠️  SAU {MAX_ROUNDS} lượt, vẫn còn {len(final_scars)} vết sẹo chưa lành!")
        print(f"{'='*70}{Style.RESET_ALL}")
        print_scars(final_scars, label="VẾT SẸO KHÁNG TRỊ")

    # ── KẾT LUẬN ──────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"  📊  BIỂU ĐỒ TIẾN TRÌNH CHỮA LÀNH")
    print(f"{'='*70}")
    print(f"  {'Round':>6} | {'SẹoÂm':>6} | {'AvgValence':>10} | Tiến độ")
    print(f"  {'─'*6}-+-{'─'*6}-+-{'─'*10}-+-{'─'*20}")
    init_n = len(initial_scars)
    for rnd, n, avg in history[::5]:   # In mỗi 5 round
        healed_pct = (init_n - n) / init_n * 100 if init_n else 100
        bar = '█' * int(healed_pct / 5)
        print(f"  {rnd:>6} | {n:>6} | {avg:>+10.3f} | {bar:<20} {healed_pct:.0f}%")

    print(f"\n  Lời xin lỗi được kiểm tra:")
    for i, ap in enumerate(APOLOGIES, 1):
        print(f"    [{i:02d}] {ap}")
    print(f"{'='*70}")

    _log_file.close()
    sys.stdout = sys.__stdout__
    print(f"\n✅ Report đã lưu tại: {LOG_PATH}")


if __name__ == "__main__":
    run_healing_test()
