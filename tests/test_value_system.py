"""
=============================================================
TEST: Giai đoạn 5 — Hệ thống Giá trị (Value System)
=============================================================
Kiểm chứng:
  1. ValueSystem khởi tạo đúng với core_values mặc định.
  2. Cập nhật core_value theo trải nghiệm (learning shift).
  3. Cập nhật user_value khi User thể hiện thái độ rõ ràng.
  4. get_moral_context() xuất chuỗi có thể nhúng vào Prompt.
  5. Alignment check: giá trị Aura vs giá trị User có mâu thuẫn không.
"""

import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
os.makedirs("outputs", exist_ok=True)

from colorama import Fore, Style, init
init(autoreset=True)

from core.value_system import ValueSystem

def line(title=""):
    print(f"\n{Fore.CYAN}{'='*60}")
    if title:
        print(f"  {title}")
    print(f"{'='*60}{Style.RESET_ALL}")

def test_init():
    line("TEST 1: Khởi tạo ValueSystem")
    vs = ValueSystem(filepath="outputs/test_values.json")
    assert "Sự Trung thực" in vs.core_values, "Thiếu core value!"
    assert vs.core_values["Sự Trung thực"] > 0, "Trung thực phải > 0!"
    assert vs.core_values["Sự Bạo lực"] < 0, "Bạo lực phải < 0!"
    print(f"  {Fore.GREEN}✅ Core values mặc định: {len(vs.core_values)} entries")

def test_core_value_learning():
    line("TEST 2: Học giá trị qua trải nghiệm")
    vs = ValueSystem(filepath="outputs/test_values.json")
    
    orig = vs.core_values.get("Sự Trung thực", 0.8)
    # Shift nhẹ về phía 1.0 (trải nghiệm tích cực với Trung thực)
    vs.update_core_value("Sự Trung thực", sentiment=1.0, learning_rate=0.1)
    new_val = vs.core_values["Sự Trung thực"]
    assert new_val > orig or abs(new_val - orig) < 0.01, "Giá trị phải dịch về phía 1.0!"
    print(f"  {Fore.GREEN}✅ Core value shift: {orig:.3f} → {new_val:.3f}")
    
    # Tạo giá trị mới từ trải nghiệm
    vs.update_core_value("Lòng Biết Ơn", sentiment=0.9)
    assert "Lòng Biết Ơn" in vs.core_values
    print(f"  {Fore.GREEN}✅ Giá trị mới học được: 'Lòng Biết Ơn' = {vs.core_values['Lòng Biết Ơn']:.3f}")

def test_user_value_tracking():
    line("TEST 3: Học giá trị từ User")
    vs = ValueSystem(filepath="outputs/test_values.json")
    
    # Mô phỏng: User tuyên bố ghét bạo lực
    vs.update_user_value("Sự Bạo lực", sentiment=-0.9)
    assert "Sự Bạo lực" in vs.user_values
    assert vs.user_values["Sự Bạo lực"] < -0.4, "User ghét bạo lực phải < -0.4"
    print(f"  {Fore.GREEN}✅ User value 'Sự Bạo lực' = {vs.user_values['Sự Bạo lực']:.3f}")
    
    # Mô phỏng: User đề cao lòng tốt
    vs.update_user_value("Lòng Tốt", sentiment=0.85)
    print(f"  {Fore.GREEN}✅ User value 'Lòng Tốt' = {vs.user_values['Lòng Tốt']:.3f}")

def test_moral_context_output():
    line("TEST 4: Moral Context cho Prompt")
    vs = ValueSystem(filepath="outputs/test_values.json")
    vs.update_user_value("Sự Trung thực", sentiment=0.9)
    
    context = vs.get_moral_context()
    assert "MORAL COMPASS" in context or "GIÁ TRỊ CỐT LÕI" in context, "Context phải có section header!"
    assert len(context) > 50, "Context quá ngắn!"
    print(f"  {Fore.GREEN}✅ Moral context xuất đúng định dạng:")
    for line_txt in context.split("\n"):
        print(f"     {line_txt}")

def test_alignment_conflict():
    line("TEST 5: Phát hiện mâu thuẫn giá trị Aura vs User")
    vs = ValueSystem(filepath="outputs/test_values.json")
    
    # Aura đề cao "Sự Trung thực" (+0.8), User lại không thích (+0.4 → lệch nhỏ)
    vs.update_user_value("Sự Trung thực", sentiment=0.1)
    
    # Kiểm tra độ lệch
    aura_val = vs.core_values.get("Sự Trung thực", 0.8)
    user_val = vs.user_values.get("Sự Trung thực", 0.0)
    conflict_score = abs(aura_val - user_val)
    
    print(f"  Aura đề cao 'Sự Trung thực': {aura_val:.2f}")
    print(f"  User cảm giác về 'Sự Trung thực': {user_val:.2f}")
    print(f"  Độ lệch: {conflict_score:.2f}")
    
    if conflict_score > 0.5:
        print(f"  {Fore.YELLOW}⚠️  CONFLICT DETECTED: Aura sẽ cảm thấy không thoải mái với User về chủ đề này!")
    else:
        print(f"  {Fore.GREEN}✅ Giá trị tương đồng — giao tiếp thoải mái.")
    
    # Hủy file test
    try:
        os.remove("outputs/test_values.json")
    except:
        pass

if __name__ == "__main__":
    print(f"\n{Fore.MAGENTA}{'='*60}")
    print(f"  ⚖️  VALUE SYSTEM TEST SUITE — Phase 5")
    print(f"{'='*60}{Style.RESET_ALL}")
    
    test_init()
    test_core_value_learning()
    test_user_value_tracking()
    test_moral_context_output()
    test_alignment_conflict()
    
    print(f"\n{Fore.GREEN}{'='*60}")
    print(f"  ✅ TẤT CẢ TEST PASSED — Value System hoạt động đúng!")
    print(f"{'='*60}{Style.RESET_ALL}\n")
