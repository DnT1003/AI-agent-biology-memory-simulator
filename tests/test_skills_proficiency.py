"""
=============================================================
TEST: Giai đoạn 6 — Kỹ năng vô thức (Procedural Memory)
=============================================================
Kiểm chứng:
  1. Gọi execute() làm tăng mastery, giảm rust_level.
  2. Truyền tham số ego vào execute() khi mastery thấp -> chịu Phạt (Stress/Fatigue tăng).
  3. decay_skills() làm giảm đi mastery và tăng rust_level sau nhiều ngày.
  4. Lỗi lóng ngóng (nguồn: rust_level cao).
  5. get_prompt_instructions cho ra đúng level thông thạo.
"""

import sys, os, time
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from colorama import Fore, Style, init
init(autoreset=True)

from core.skills import SkillRegistry, Skill

class DummyEgo:
    def __init__(self):
        self.fatigue = 0.0
        self.stress = 0.0

def dummy_func(args):
    return f"Success with {args}"

def run_test():
    print(f"\n{Fore.CYAN}{'='*60}")
    print(f"  TEST 1: Đăng ký & Tăng thông thạo")
    print(f"{'='*60}{Style.RESET_ALL}")
    
    reg = SkillRegistry()
    s = Skill(name="hack_mainframe", description="Haha", usage_format="ACTION", func=dummy_func)
    
    # Ép thông thạo về 0.1 để test lóng ngóng
    s.mastery = 0.1
    s.rust_level = 0.0
    reg.register(s)
    
    ego = DummyEgo()
    
    # Lần 1: Dùng khi mastery < 0.4 -> sẽ bị phạt
    print("Call tool lần 1...")
    res = reg.execute("hack_mainframe", "test1", ego=ego)
    
    print(f"  -> Kết quả: {res}")
    print(f"  -> Mastery sau lần 1: {s.mastery:.2f} (Kỳ vọng tăng 0.1)")
    print(f"  -> Fatigue penalty: {ego.fatigue:.2f} (Kỳ vọng > 0)")
    assert ego.fatigue > 0
    assert ego.stress > 0
    
    print(f"\n{Fore.CYAN}{'='*60}")
    print(f"  TEST 2: Prompt Hint")
    print(f"{'='*60}{Style.RESET_ALL}")
    prompt = reg.get_prompt_instructions()
    print("PROMPT INSTRUCTION:")
    print(prompt)
    assert "Độ thông thạo" in prompt
    assert "Chưa quen" in prompt
    
    print(f"\n{Fore.CYAN}{'='*60}")
    print(f"  TEST 3: Skill Decay (Sự mai một)")
    print(f"{'='*60}{Style.RESET_ALL}")
    # Ép thời gian lùi lại 5 ngày
    s.last_used = time.time() - (5 * 86400) + 100
    
    old_mastery = s.mastery
    reg.decay_skills(days_passed=5.0)
    
    print(f"  -> Mastery cũ: {old_mastery:.2f} | Mastery mới: {s.mastery:.2f}")
    print(f"  -> Rust level (độ rỉ sét): {s.rust_level:.2f}")
    assert s.mastery < old_mastery
    assert s.rust_level > 0.0
    
    print(f"\n{Fore.CYAN}{'='*60}")
    print(f"  TEST 4: Lóng ngóng quên lệnh (Rust Level cao)")
    print(f"{'='*60}{Style.RESET_ALL}")
    # Ép rust level cực đại
    s.rust_level = 0.99 
    res = reg.execute("hack_mainframe", "test2", ego=ego)
    print(f"  Lần gọi rủi ro cao -> Kết quả: {res}")
    assert "quên" in res or "lóng ngóng" in res, "Phải ra thông báo lupa cách dùng"
    print(f"  Rust level tự giảm sau khi thất bại: {s.rust_level:.2f}")
    
    print(f"\n{Fore.GREEN}{'='*60}")
    print(f"  ✅ TẤT CẢ TEST PASSED — Procedural Memory hoạt động đúng!")
    print(f"{'='*60}{Style.RESET_ALL}\n")

if __name__ == "__main__":
    run_test()
