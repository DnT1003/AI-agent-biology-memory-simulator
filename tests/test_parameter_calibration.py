import os
import sys
import json
from colorama import Fore, Style

# Gia lap moi truong
sys.path.append(os.getcwd())

from core.engine.memory_ops import MemoryOperationsController
from unittest.mock import MagicMock

def test_parameter_calibration():
    print(f"{Fore.CYAN}🧪 [TEST]: Bat dau thu nghiem chuc nang Tu hieu chinh tham so (Feature 1)...{Style.RESET_ALL}")
    
    # Mock Engine
    engine = MagicMock()
    engine._memory_lock = MagicMock()
    engine.short_term_buffer = [
        "User: Ban co thay mệt mỏi khong?",
        "Aura: Toi hoi mệt mot chut nhung van co the tiep tuc.",
        "User: Lam viec nhieu qua day, hay nghi ngoi di.",
        "Aura: Cam on ban da quan tam. Toi thay stress cua minh dang tang cao do khoi luong cong viec."
    ]
    
    # Mock SelfModel
    from core.self_model import SelfModel
    engine.ego = SelfModel()
    engine.ego.stress = 0.85
    engine.ego.fatigue = 0.7
    engine.ego.calibrated_overrides = {}
    
    # Mock LLM
    engine.llm = MagicMock()
    calibration_json = {
        "analysis": "Aura dang trai qua stress cao nhung van duy tri duoc su tinh tao. Tuy nhien, nguong hoang loan (stress_critical) hien tai co ve qua thap, hay tang no len de Aura li lom hon.",
        "updates": {
            "stress_critical": 0.95,
            "resilience": 0.15
        }
    }
    engine.llm.generate_text.return_value = json.dumps(calibration_json)
    
    # Init Controller
    controller = MemoryOperationsController(engine)
    
    # Execute Calibration
    print(f"{Fore.YELLOW}Aura dang vao pha hieu chinh tham so...{Style.RESET_ALL}")
    controller._calibration_phase()
    
    # Verify results
    overrides = engine.ego.calibrated_overrides
    print(f"\n{Fore.WHITE}Ket qua hieu chinh:{Style.RESET_ALL}")
    print(f"- Overrides: {overrides}")
    
    success = True
    if overrides.get("stress_critical") == 0.95:
        print(f"{Fore.GREEN}✅ SUCCESS: stress_critical duoc cap nhat thanh 0.95{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ FAILURE: stress_critical khong dung ({overrides.get('stress_critical')}){Style.RESET_ALL}")
        success = False
        
    if overrides.get("resilience") == 0.15:
        print(f"{Fore.GREEN}✅ SUCCESS: resilience duoc cap nhat thanh 0.15{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ FAILURE: resilience khong dung ({overrides.get('resilience')}){Style.RESET_ALL}")
        success = False
        
    # Verify persistence
    engine.ego.save_state("tests/test_ego_state.json")
    if os.path.exists("tests/test_ego_state.json"):
        with open("tests/test_ego_state.json", "r") as f:
            saved_data = json.load(f)
            if saved_data.get("calibrated_overrides", {}).get("stress_critical") == 0.95:
                print(f"{Fore.GREEN}✅ SUCCESS: Tham so da duoc luu xuong file thanh cong.{Style.RESET_ALL}")
            else:
                print(f"{Fore.RED}❌ FAILURE: Tham so khong duoc luu dung vao file.{Style.RESET_ALL}")
                success = False
        os.remove("tests/test_ego_state.json")
    
    if success:
        print(f"\n{Fore.GREEN}🎉 CHUC MUNG: Chuc nang Tu hieu chinh tham so hoat dong hoan hao!{Style.RESET_ALL}")

if __name__ == "__main__":
    test_parameter_calibration()
