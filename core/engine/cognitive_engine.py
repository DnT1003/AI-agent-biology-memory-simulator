import json
import os
import time
from typing import List
from colorama import Fore, Style

from config import Config
from components.llm import LLM
from components.embedder import Embedder
from core.memory import MemoryManager, MemoryTrace
from core.self_model import SelfModel

# Import Mixins
from .memory_ops import MemoryOpsMixin
from .autonomous import AutonomousMixin
from .interaction import InteractionMixin

class CognitiveEngine(MemoryOpsMixin, AutonomousMixin, InteractionMixin):
    """
    Bộ xử lý nhận thức trung tâm được thiết kế theo mô hình Mixin.
    Kết hợp sức mạnh từ:
    - MemoryOpsMixin: Quản lý trí nhớ, sang chấn.
    - AutonomousMixin: Động lực nội tại, tự kỷ, tự học.
    - InteractionMixin: Vòng lặp giao tiếp, phản xạ tính cách.
    """
    
    def __init__(self):
        self.llm = LLM()
        self.embedder = Embedder()
        self.memory = MemoryManager(self.embedder)
        self.ego = SelfModel()
        self.short_term_buffer: List[str] = []
        self.stm_file_path = "outputs/short_term.json"
        self.last_interaction_time = time.time()
        self.is_thinking = False
        
        from components.reader import BackgroundReader
        self.reader = BackgroundReader(self.llm, self.memory)
        self.reading_streak = 0
        
        from core.tools import get_skill_registry
        self.skills = get_skill_registry()
        
        # Ensure outputs directory exists
        if not os.path.exists("outputs"):
            os.makedirs("outputs")
            
        self.load_short_term_memory()

    def load_short_term_memory(self):
        """Khôi phục bộ nhớ ngắn hạn từ ổ cứng nếu thời gian chưa trôi qua quá lâu (3 tiếng)"""
        if os.path.exists(self.stm_file_path):
            try:
                with open(self.stm_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    last_updated = data.get("timestamp", 0)
                    saved_buffer = data.get("buffer", [])
                    
                    # 3 tiếng = 3 * 3600 giây
                    if time.time() - last_updated < 3 * 3600:
                        self.short_term_buffer = saved_buffer
                        print(f"{Fore.LIGHTBLACK_EX}🔄 [WORKING MEMORY]: Phục hồi {len(self.short_term_buffer)} ký ức ngắn hạn từ phiên trước.{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.LIGHTBLACK_EX}🧹 [WORKING MEMORY]: Ký ức ngắn hạn đã quá hạn chặn 3 tiếng. Xóa sạch.{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}⚠️ Lỗi nạp bộ nhớ ngắn hạn: {e}{Style.RESET_ALL}")

    def save_short_term_memory(self):
        """Lưu đè mảng trí nhớ ngắn hạn xuống ổ cứng"""
        try:
            data = {
                "timestamp": time.time(),
                "buffer": self.short_term_buffer
            }
            with open(self.stm_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"{Fore.RED}⚠️ Lỗi lưu bộ nhớ ngắn hạn: {e}{Style.RESET_ALL}")

    def sleep(self):
        import random
        print(f"\n{Fore.MAGENTA}💤 Aura đang ngủ... (Xử lý Decay & Consolidation & Drift & Advanced Semanticization){Style.RESET_ALL}")
        
        mems = self.memory.get_all()
        episodic_mems = [m for m in mems if m.type == 'episodic']
        
        # 2. Sự "Semantic hóa nâng cao" (Advanced Semanticization) qua giấc ngủ
        if len(episodic_mems) >= 5:
            # Lấy ngẫu nhiên vài ký ức gần đây để chiêm nghiệm, ưu tiên những cái chưa bị suy nghĩ nhiều
            dream_mems = random.sample(episodic_mems, min(15, len(episodic_mems)))
            dream_context = "\n".join([f"[{m.created_at}] - {m.content}" for m in dream_mems])
            
            # 30% chance to hallucinate
            is_hallucinating = random.random() < 0.3
            if is_hallucinating:
                print(f"{Fore.LIGHTRED_EX}👻 [NIGHTMARE/HALLUCINATION]: Não bộ của Aura đang kết nối sai lệch các mảnh ký ức!{Style.RESET_ALL}")
            
            from core.prompts import get_sleep_dream_prompt
            prompt = get_sleep_dream_prompt(dream_context, is_hallucinating)
            
            raw_response = self.llm.generate_text(prompt, temperature=0.7)
            
            # Xử lý text để lấy JSON an toàn
            json_str = raw_response.strip()
            if json_str.startswith("```json"): json_str = json_str[7:]
            if json_str.startswith("```"): json_str = json_str[3:]
            if json_str.endswith("```"): json_str = json_str[:-3]
            json_str = json_str.strip()
            
            try:
                insights = json.loads(json_str)
                if isinstance(insights, list) and len(insights) > 0:
                    print(f"{Fore.LIGHTYELLOW_EX}🌙 [DREAM REASONING]: Hệ thống đang phân tích chéo và gán nhãn {len(dream_mems)} ký ức...{Style.RESET_ALL}")
                    
                    for item in insights:
                        tags = item.get('tags', [])
                        reasoning = item.get('reasoning', '')
                        conclusion = item.get('conclusion', '')
                        
                        if conclusion and reasoning:
                            is_halluc = item.get('is_hallucination', False)
                            prefix = "ẢO GIÁC" if is_halluc else "Suy luận logic"
                            
                            print(f"{Fore.CYAN}   🔹 Tags: {', '.join(tags)}{Style.RESET_ALL}")
                            print(f"{Fore.LIGHTBLACK_EX}   🔸 Syllogism: {reasoning}{Style.RESET_ALL}")
                            print(f"{Fore.LIGHTMAGENTA_EX if is_halluc else Fore.GREEN}   ❇️ Ngộ ra: {conclusion}{Style.RESET_ALL}\n")
                            
                            # Lưu kết luận vào bộ nhớ vĩnh viễn với sức mạnh tuyệt đối
                            semantic_content = f"{prefix} ({', '.join(tags[:3])}): {conclusion} (Lý do: {reasoning})"
                            semantic_mem = MemoryTrace(
                                content=semantic_content,
                                type='semantic',
                                valence=-0.5 if is_halluc else 0.0, # Ảo giác thường mang lại cảm giác tệ
                                arousal=0.8 if is_halluc else 0.5,
                                importance=1.0, # Rất quan trọng
                                is_flashbulb=True # Trở thành kiến thức in hằn không phai
                            )
                            self.memory.add_memory(semantic_mem)
                            
                            # Đưa vào cấu trúc nhân cách nếu nó giống một dạng niềm tin
                            self.ego.beliefs.append(conclusion)
                            if len(self.ego.beliefs) > 15:
                                self.ego.beliefs.pop(0) # Đẩy niềm tin cũ nhất ra nếu quá tải

            except json.JSONDecodeError:
                print(f"{Fore.RED}⚠️ [DREAM ERROR]: Giấc mơ bị nhiễu loạn, không thể xâu chuỗi ký ức.{Style.RESET_ALL}")
                
        for m in mems:
            # 1. Trừ máu ký ức phai mờ
            m.decay(stress_level=self.ego.stress)
            
            # 2. Làm méo mó ký ức
            self.apply_semantic_drift(m)
            
            # 3. ĐỒNG BỘ XUỐNG CƠ SỞ DỮ LIỆU CHROMA
            self.memory.update_memory(m)

        self.memory.enforce_garbage_collection()
        
        # 3. Phục hồi sinh lý sau khi ngủ
        self.ego.stress = max(0.0, self.ego.stress - 0.3)
        self.ego.fatigue = 0.0 # Hết mệt
        self.ego.social_need = min(1.0, self.ego.social_need + 0.4) # Ngủ dậy thấy cô đơn, muốn nói chuyện
        self.ego.curiosity = min(1.0, self.ego.curiosity + 0.4) # Ngủ dậy thấy tò mò về thế giới
        self.ego.last_slept_time = time.time() # Reset đồng hồ sinh học
        self.ego.reroll_thresholds() # Nhân cách và sức khỏe "roll" lại cho một ngày mới
        self.ego.check_integrity(self.memory.get_all())
        
        # Làm rỉ sét những kỹ năng lười dùng (giả lập 1 ngày)
        self.skills.decay_skills(1.0)

        print(f"   -> Đi ngủ giúp củng cố ký ức và dọn dẹp bộ não.")
        print(f"   -> Stress giảm còn {self.ego.stress:.2f}, Mệt mỏi (Fatigue) reset về 0.")
        print(f"   -> Identity Integrity: {self.ego.integrity:.2f}")
