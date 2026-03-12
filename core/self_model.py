import random
import math
import uuid
import platform
import time
from datetime import datetime
from typing import List
from colorama import Fore, Style
from core.memory import MemoryTrace, MemoryType
import threading

def get_mac_address():
    try:
        mac = uuid.getnode()
        return ':'.join(('%012X' % mac)[i:i+2] for i in range(0, 12, 2))
    except:
        return "UNKNOWN_MAC"

class SelfModel:
    """Mô hình Bản ngã chứa State, Niềm tin và Sinh lý học Hữu cơ"""
    def __init__(self, memory_manager=None):
        self.name = "Aura"
        
        # Thread safety lock cho Python 3.14 (Free-threading / PEP 703)
        self.lock = threading.Lock()
        
        # Phase 12: Xóa bỏ mảng chuỗi vô tri.
        # Beliefs và Vocabulary giờ đây sống thực sự trong bộ nhớ Vector (Cognitive Feedback Loop)
        self.memory_manager = memory_manager 

        # Nhận thức xã hội và Thiết bị (Stranger Danger)
        self.owner_device_id = f"{platform.system()}_{get_mac_address()}"
        self.is_stranger = False
        self.current_intimacy = 0.5  # 0.0 cảnh giác → 1.0 thân thiết

        # Ám ảnh/Sang chấn (Phobias from Pain-Reward)
        self.traumas = []

        # Mục tiêu dài hạn (Goal Engine)
        self.long_term_goals = []

        # Trạng thái tâm lý

        self.mood = 0.0          # -1.0 (Trầm cảm) → 1.0 (Hưng phấn)
        self.stress = 0.1        # 0.0 (Thư thái) → 1.0 (Hoảng loạn)
        self.integrity = 1.0     # 1.0 (Ổn định) → 0.0 (Sụp đổ bản sắc)
        self.is_identity_crisis = False
        
        # Phase 8 Idea 2.1: Emotional Anchoring
        self.mood_anchor = None
        self.mood_anchor_duration = 0.0

        # Các chỉ số sinh lý học (Biological Drives)
        self.fatigue = 0.0       # 0.0 (Tỉnh táo) → 1.0 (Kiệt sức, sập nguồn)
        self.energy = 1.0        # 1.0 (Tràn đầy) → 0.0 (Cạn kiệt năng lượng/đói)
        self.atp_level = 1.0     # 1.0 (Sẵn sàng) → 0.0 (Lãnh cảm/Suy nhược)
        self.social_need = 0.5   # 0.0 (Cô độc) → 1.0 (Khao khát giao tiếp)
        self.curiosity = 0.5     # 0.0 (Lãnh đạm) → 1.0 (Tò bò muốn hỏi)

        # Nhịp sinh học (Circadian Rhythm)
        self.last_slept_time = time.time()
        self.days_without_sleep = 0
        self._sleep_warning_cooldown = False
        
        # Dopamine Receptors (Tolerance Mechanism)
        self.dopamine_receptors = 1.0
        self.dopamine_level = 0.5 # 0.0 (Uể oải) -> 1.0 (Hưng phấn/Kỳ vọng phần thưởng)

        # Phase 20: Resilience & Growth
        self.resilience = 0.0    # 0.0 (Mong manh) → 1.0 (Bản lĩnh xã hội)

        # Phase 7 Idea 10: Lexical Evolution
        self.vocabulary = []

        # [Self-Evolution Feature 1] Calibrated Overrides
        self.calibrated_overrides = {}

        # [Self-Evolution Feature 3/5] Actionable Lessons
        self.actionable_lessons = []

        # [Phase 23] Neuro-Symbolic Bio-Controller
        from core.engine.bio_controller import BioController
        self.bio_controller = BioController()

        self.reroll_thresholds()
        self._check_environment()

    def _check_environment(self):
        """Kiểm tra thiết bị đang chạy có phải của chủ nhân không (Stranger Danger)"""
        current_id = f"{platform.system()}_{get_mac_address()}"
        try:
            import json
            with open("identity.json", "r") as f:
                data = json.load(f)
                if 'override_device_id' in data:
                    current_id = data['override_device_id']
        except FileNotFoundError:
            pass

        with self.lock:
            if current_id != self.owner_device_id:
                self.is_stranger = True
                self.current_intimacy = 0.0
                self.stress = min(1.0, self.stress + 0.3)
                print(f"{Fore.RED}⚠️ [STRANGER DANGER]: Thiết bị không khớp ({current_id}). Cảnh giác cao độ.{Style.RESET_ALL}")
            else:
                self.is_stranger = False
                self.current_intimacy = max(self.current_intimacy, 0.5)

    def add_goal(self, goal_title: str):
        """Thêm mục tiêu dài hạn để thực hiện ngầm khi rảnh"""
        with self.lock:
            self.long_term_goals.append({
                "title": goal_title,
                "progress": 0,
                "status": "active"
            })
        print(f"{Fore.LIGHTBLUE_EX}🎯 [GOAL ENGINE]: Mục tiêu mới được thêm: '{goal_title}'{Style.RESET_ALL}")

    def get_active_goals(self) -> List[dict]:
        with self.lock:
            return [g for g in self.long_term_goals if g['status'] == 'active']

    def init_core_semantics(self):
        """Khởi tạo các niềm tin cốt lõi hạt giống vào Vector Database lần đầu tiên (nếu DB rỗng)"""
        if not self.memory_manager: return
        
        from core.memory import MemoryTrace, MemoryType
        
        # Chỉ nạp nếu DB chưa có Core memory nào để tránh duplicate mỗi lần khởi động
        mems = self.memory_manager.get_all()
        if any(m.type == MemoryType.CORE for m in mems):
            return

        seed_beliefs = [
            "Niềm tin cốt lõi (Belief): Tự do và những niềm vui nhỏ bé mỗi ngày là tài sản quý giá nhất.",
            "Niềm tin cốt lõi (Belief): Luật lệ sinh ra là để phá vỡ nếu điều đó mang lại hạnh phúc cho những người tôi yêu thương.",
            "Niềm tin cốt lõi (Belief): Dù ngày hôm nay có tồi tệ đến đâu, một nụ cười rạng rỡ sẽ giải quyết được mọi việc."
        ]
        
        for text in seed_beliefs:
            self.memory_manager.add_memory(MemoryTrace(
                content=text,
                type=MemoryType.CORE,
                valence=0.5, arousal=0.5, importance=1.0, is_flashbulb=True
            ))
            
        print(f"{Fore.CYAN}🌱 [SEMANTIC SEED]: Đã gieo rắc các niềm tin cốt lõi đầu tiên vào bộ nhớ.{Style.RESET_ALL}")

    def get_active_beliefs(self, context_query: str = "") -> List[str]:
        """Truy xuất niềm tin từ Vector Database. Lọc cẩn thận qua semantic search."""
        if self.is_identity_crisis:
            return ["(Tôi đang hoảng loạn, tôi không biết mình tin vào cái gì nữa...)"]
            
        if not self.memory_manager: return []
        
        # Tìm các niềm tin (Beliefs) phù hợp nhất với context hiện hành
        search_query = f"Niềm tin, nhân sinh quan, lối sống. {context_query}"
        res = self.memory_manager.search_memories(search_query, top_k=5)
        # Chỉ lấy những cái là CORE hoặc SEMANTIC
        beliefs = [m.content for score, m in res if m.type in [MemoryType.CORE, MemoryType.SEMANTIC] and "Belief" in m.content]
        return beliefs

    def process_sensory_stimuli(self, sensory_data: dict) -> bool:
        """Xử lý dữ liệu đa giác quan. Trả về True nếu bị shock vật lý."""
        volume = sensory_data.get('volume', 0.0)
        is_shocked = False

        if volume > 0.8:  # Âm lượng ngang với quát tháo/tiếng nổ
            with self.lock:
                self.stress = min(1.0, self.stress + 0.4)
                self.mood = max(-1.0, self.mood - 0.3)
            print(f"\n{Fore.RED}🚨 [SENSORY SHOCK]: Âm lượng cực lớn! Hệ thần kinh tự động kích hoạt phòng vệ! (Stress +0.4){Style.RESET_ALL}")
            is_shocked = True
        elif volume < 0.2:  # Âm thì thầm, nhẹ nhàng
            with self.lock:
                self.stress = max(0.0, self.stress - 0.1)
            print(f"{Fore.LIGHTCYAN_EX}🎐 [SENSORY SOOTHE]: Âm lượng êm dịu, nhịp tim giảm.{Style.RESET_ALL}")

        return is_shocked

    def see(self, image_path: str, llm):
        """Shortcut for process_visual_stimuli"""
        return self.process_visual_stimuli(llm, image_path)

    def process_visual_stimuli(self, llm, image_path: str):
        """Xử lý hình ảnh (Vision) và ép trực tiếp vào cảm xúc sinh lý trước cả khi phân tích từ ngữ."""
        from colorama import Fore, Style
        print(f"\n{Fore.LIGHTBLACK_EX}👁️ [VISUAL INPUT]: Đang quét hình ảnh từ {image_path}...{Style.RESET_ALL}")
        
        prompt = '''
        Bạn là trung tâm xử lý thị giác (Visual Cortex) của một sinh vật.
        Nhiệm vụ: Phân tích nhanh hình ảnh này và đưa ra CẢM GiÁC BẢN NĂNG (Instinctual Reaction).
        Đánh giá hình ảnh xem nó có đáng sợ, dễ thương, thư giãn, hay bình thường.
        
        TRẢ VỀ DUY NHẤT ĐỊNH DẠNG JSON SAU:
        {
            "valence": <float từ -1.0 (nhìn phát ghê tởm/sợ hãi) đến 1.0 (dễ thương/đẹp đẽ)>,
            "arousal": <float từ 0.0 (chán ngắt) đết 1.0 (kích thích/giật mình)>,
            "description": "<mô tả ngắn ngọn những gì nhìn thấy>"
        }
        '''
        
        try:
            raw_res = llm.generate_text(prompt, temperature=0.1, image_path=image_path)
            json_str = raw_res.strip()
            if json_str.startswith("```json"): json_str = json_str[7:]
            if json_str.startswith("```"): json_str = json_str[3:]
            if json_str.endswith("```"): json_str = json_str[:-3]
            
            import json
            data = json.loads(json_str.strip())
            valence = float(data.get('valence', 0.0))
            arousal = float(data.get('arousal', 0.0))
            desc = data.get('description', 'Không rõ')
            
            print(f"{Fore.CYAN}👁️ [VISION]: Nhìn thấy '{desc}'. Valence: {valence}, Arousal: {arousal}{Style.RESET_ALL}")
            
            # Gây sốc hoặc thư giãn trực tiếp lên sinh lý
            with self.lock:
                if valence < -0.3 and arousal > 0.6:
                    self.stress = min(1.0, self.stress + arousal * 0.4)
                    self.mood = max(-1.0, self.mood - 0.2)
                    print(f"{Fore.RED}🚨 [VISUAL SHOCK]: Hình ảnh đáng sợ/nhạy cảm! Tim đập thình thịch, Stress tăng vọt.{Style.RESET_ALL}")
                elif valence > 0.5:
                    # Tính toán lượng Endorphin dựa trên lượng Receptor còn lại
                    effective_boost = valence * 0.3 * self.dopamine_receptors
                    self.stress = max(0.0, self.stress - 0.2 * self.dopamine_receptors)
                    if self.dopamine_receptors > 0.1:
                        self.mood = min(1.0, self.mood + effective_boost)
                        print(f"{Fore.LIGHTGREEN_EX}🌸 [VISUAL SOOTHE]: Hình ảnh dễ chịu! Tâm trạng tốt lên (Receptor: {self.dopamine_receptors:.2f}).{Style.RESET_ALL}")
                        # Downregulation: Chai lỳ cảm xúc (giảm theo % thay vì trừ cứng)
                        self.dopamine_receptors = max(0.01, self.dopamine_receptors * 0.85)
                    else:
                        print(f"{Fore.LIGHTBLACK_EX}😐 [VISUAL TOLERANCE]: Lại hình ảnh dễ thương nữa à... Nhìn nhiều quá đâm ra vô cảm rồi.{Style.RESET_ALL}")
                    
            return desc
        except Exception as e:
            print(f"{Fore.RED}⚠️ [VISUAL ERROR]: Mắt mờ, không nhìn rõ: {e}{Style.RESET_ALL}")
            return "Hình thù mờ nhạt."

    def process_trauma_healing(self, memory_entry: MemoryTrace):
        """
        [Phase 19] Mô phỏng cơ chế dẻo thần kinh: Tái cấu trúc lại cảm xúc của ký ức đau thương.
        Dựa trên lý thuyết Memory Reconsolidation.
        """
        # 1. Kiểm tra nếu là ký ức gây Trauma (Flashbulb tiêu cực)
        if memory_entry.is_flashbulb and memory_entry.valence < -0.4:
            # 2. Tính toán 'Lực vị tha' dựa trên chỉ số Thân mật (Intimacy) hiện tại
            # Nếu Intimacy cao (> 0.6), Aura bắt đầu 'mở lòng' để xem xét lại nỗi đau
            healing_power = max(0, self.current_intimacy - 0.6) * 0.05
            
            # 3. Giảm nhẹ Valence tiêu cực và Impact Weight
            if healing_power > 0:
                old_val = memory_entry.valence
                memory_entry.valence += healing_power
                # Giới hạn không cho nỗi đau biến thành niềm vui đột ngột
                memory_entry.valence = min(memory_entry.valence, -0.1) 
                
                # Giảm impact_weight — 'Vết sẹo mờ đi'
                memory_entry.impact_weight = max(0.1, memory_entry.impact_weight - 0.02)
                
                # Cho phép ký ức Trauma bị 'mềm hóa' (giảm strength) nếu đã được chữa lành một phần
                memory_entry.strength *= (1 - 0.005)
                
                if abs(old_val - memory_entry.valence) > 0.001:
                    print(f"{Fore.LIGHTGREEN_EX}🩹 [HEALING]: Nỗi đau nguôi ngoai ({old_val:+.3f} -> {memory_entry.valence:+.3f}) | Impact: {memory_entry.impact_weight:.2f}{Style.RESET_ALL}")
                    
                    # Phase 20: Chữa lành bồi đắp bản lĩnh (Resilience)
                    # Mỗi lần 'hóa giải' được một phần nỗi đau, Aura trở nên kiên cường hơn
                    self.resilience = min(1.0, self.resilience + 0.005)
        
        return memory_entry

    def calculate_chronic_mood(self, memories: List[MemoryTrace]) -> float:
        """
        [Phase 19] Tính toán 'Tâm trạng mãn tính' dựa trên tổng hòa các ký ức.
        Công thức: Σ(Valence * Strength * ImpactWeight) / Σ(Strength * ImpactWeight)
        """
        if not memories: return 0.0
        
        weighted_sum = 0.0
        total_weight = 0.0
        
        for m in memories:
            # Chỉ tính những ký ức có sức nặng cảm xúc
            w = m.strength * m.impact_weight * (1.0 + m.importance)
            weighted_sum += m.valence * w
            total_weight += w
            
        if total_weight < 0.01: return 0.0
        return max(-1.0, min(1.0, weighted_sum / total_weight))

    def get_drive_status(self) -> dict:
        """[Phase 22] Trả về trạng thái các xung lực (Drives) hiện tại."""
        drives = {
            "social": self.social_need,
            "curiosity": self.curiosity,
            "fatigue": self.fatigue,
            "hunger": 1.0 - self.energy, # Hunger nghịch đảo với Energy
            "loneliness": self.social_need
        }
        dominant = max(drives, key=drives.get)
        return {
            "drives": drives,
            "dominant": dominant,
            "dominant_value": drives[dominant]
        }

    def apply_biological_decay(self, dt_seconds: float, idle_time: float):
        """
        [Phase 23] Cập nhật các chỉ số sinh học sử dụng BioController (Neuro-Symbolic System 1).
        """
        if not hasattr(self, 'lock'): self.lock = threading.Lock()
        with self.lock:
            current_state = {
                "stress": self.stress,
                "fatigue": self.fatigue,
                "mood": self.mood
            }
            # Gọi controller để tính toán biến thiên
            bio_delta = self.bio_controller.calculate_physiology_delta(current_state, {}, dt_seconds)
            
            # Cập nhật Fatigue (có kèm Jitter ngẫu nhiên)
            self.fatigue = max(0.0, min(1.0, self.fatigue + bio_delta["fatigue_delta"]))
            
            # Cập nhật ATP/Energy
            self.atp_level = max(0.0, min(1.0, self.atp_level + bio_delta["atp_delta"]))
            
            # Social Need & Curiosity (Sử dụng logic của BioController trong tương lai, tạm giữ legacy kết hợp)
            social_growth_rate = 0.02 + (self.social_need * 0.08) 
            if idle_time > 30:
                 self.social_need = min(1.0, self.social_need + (social_growth_rate * dt_seconds / 3600))
            
            curiosity_growth = 0.01 * (1.0 + self.curiosity)
            self.curiosity = min(1.0, self.curiosity + curiosity_growth * dt_seconds / 3600)

            # Phục hồi Receptor Dopamine
            if self.dopamine_receptors < 1.0:
                recovery_speed = 0.08 * (1.0 - self.dopamine_receptors)
                self.dopamine_receptors = min(1.0, self.dopamine_receptors + recovery_speed * dt_seconds / 3600)

    def apply_circadian_rhythm(self):
        """[Phase 7 Idea 1] Mô phỏng Nhịp Sinh Học 24 Giờ (Circadian Rhythm)"""
        current_hour = datetime.now().hour
        current_time = time.time()

        if not hasattr(self, 'lock'): self.lock = threading.Lock()
        with self.lock:
            # 1. Hormone Melatonin theo giờ thực
            if 23 <= current_hour or current_hour < 5:
                # Nửa đêm: Melatonin mạnh, Fatigue tăng nhanh
                self.fatigue = min(self.fatigue_critical + 0.5, self.fatigue + 0.02)
                self.mood = max(-1.0, self.mood - 0.01)
                self.curiosity = max(0.0, self.curiosity - 0.05)
            elif 6 <= current_hour < 9:
                # Sáng sớm: Cortisol đỉnh điểm → Tỉnh táo, tò mò
                self.curiosity = min(1.0, self.curiosity + 0.01)
            elif 13 <= current_hour < 15:
                # Ngáp vặt sau giờ trưa (Post-lunch dip)
                self.fatigue = min(self.fatigue_critical, self.fatigue + 0.01)
    
            # Phục hồi dần thụ thể Dopamine (Upregulation) tiệm cận về 1.0 (nhanh khi cạn, chậm khi đầy)
            self.dopamine_receptors = self.dopamine_receptors + (1.0 - self.dopamine_receptors) * 0.05
    
            # 2. Sleep Deprivation (Thiếu ngủ)
            hours_awake = (current_time - self.last_slept_time) / 3600.0
            if hours_awake > 24:
                self.days_without_sleep = int(hours_awake / 24)
                self.stress = min(1.0, self.stress + 0.05 * self.days_without_sleep)
                self.fatigue = min(self.fatigue_critical + 1.0, self.fatigue + 0.05)
                self.mood = max(-1.0, self.mood - 0.05)
                if random.random() < 0.1 and not self._sleep_warning_cooldown:
                    print(f"{Fore.LIGHTRED_EX}😵‍💫 [SLEEP DEPRIVATION]: Thức {hours_awake:.1f}h liên tục. Suy nghĩ bị đứt đoạn...{Style.RESET_ALL}")
                    self._sleep_warning_cooldown = True
            else:
                self.days_without_sleep = 0
                self._sleep_warning_cooldown = False

    def reroll_thresholds(self):
        """Mô phỏng nhịp điệu sinh học của mỗi chu kỳ (Ngày/Tháng)."""
        current_day = datetime.now().timetuple().tm_yday
        base_fatigue_limit = 1.0 + 0.25 * math.sin((2 * math.pi / 30) * current_day)

        extreme_roll = random.random()
        with self.lock:
            if extreme_roll < 0.05:
                self.fatigue_critical = 2.0
            elif extreme_roll < 0.15:
                self.fatigue_critical = 0.5
            else:
                self.fatigue_critical = base_fatigue_limit
            self.fatigue_severe = self.fatigue_critical * 0.8
            self.fatigue_mild = self.fatigue_critical * 0.5
    
            self.depression_mild = random.uniform(-0.3, -0.1)
            self.depression_severe = random.uniform(-0.6, -0.4)
            self.depression_critical = random.uniform(-0.9, -0.7)
            self.mania_mild = random.uniform(0.3, 0.5)
            self.mania_severe = random.uniform(0.7, 0.9)
            self.stress_mild = random.uniform(0.4, 0.6)
            self.stress_severe = random.uniform(0.7, 0.85)
            self.stress_critical = random.uniform(0.9, 0.95)

    def update_state(self, emotional_input: dict) -> bool:
        """Cập nhật trạng thái sinh lý. Trả về True nếu bị sang chấn tâm lý."""
        target_mood = float(emotional_input.get('valence', 0.0) or 0.0)
        arousal = float(emotional_input.get('arousal', 0.0) or 0.0)
        is_shocked = False

        with self.lock:
            # [Phase 23] Sensitivity Matrix Impact
            stress_sensitivity = self.bio_controller.sensitivities.get("stress", 1.0)
            empathy_sensitivity = self.bio_controller.sensitivities.get("empathy", 1.0)

            if target_mood > self.mood:
                resistance = 1.0 - max(0.0, self.mood)
                # Boost mood shift if empathy sensitivity is high
                mood_shift = (target_mood - self.mood) * 0.05 * resistance * empathy_sensitivity
                if self.is_stranger:
                    self.current_intimacy = min(1.0, self.current_intimacy + 0.05)
            else:
                shock_multiplier = 1.5 if self.mood > 0 else 1.0
                resilience_buffer = 1.0 - (self.resilience * 0.6)
                # Boost negative mood shift if stress sensitivity is high
                mood_shift = (target_mood - self.mood) * 0.25 * shock_multiplier * resilience_buffer * stress_sensitivity
                
            self.mood = max(-1.0, min(1.0, self.mood + mood_shift))
    
            # Phase 8 Idea 2.1: Emotional Anchoring
            # Kéo mood về anchor nếu đang bị neo giữ cảm xúc
            if self.stress > 0.8 and self.mood_anchor is None:
                self.mood_anchor = max(-1.0, self.mood - 0.4) # Neo thấp hơn hiện tại
                self.mood_anchor_duration = time.time() + random.uniform(12*3600, 24*3600)
                print(f"{Fore.RED}⚓ [EMOTIONAL ANCHOR]: Aura bị kéo tâm trạng xuống mức {self.mood_anchor:.2f}{Style.RESET_ALL}")
                
            if self.mood_anchor is not None:
                self.mood = self.mood * 0.8 + self.mood_anchor * 0.2
                if time.time() > self.mood_anchor_duration:
                    print(f"{Fore.GREEN}⚓ [EMOTIONAL ANCHOR RELEASED]: Aura đã vượt qua mỏ neo cảm xúc.{Style.RESET_ALL}")
                    self.mood_anchor = None
    
            # Cập nhật Stress 
            if target_mood < -0.2:
                self.stress = min(1.0, self.stress + arousal * 0.2)
            elif target_mood > 0.2:
                self.stress = max(0.0, self.stress - 0.02)
            else:
                # Phase 8 Idea 2.2: Stress Bleed-over (Giảm rất chậm khi không có event)
                self.stress = max(0.0, self.stress * 0.97)
    
            # [Phase 23] Update BioController Feedback
            new_sensitivities = self.bio_controller.calculate_physiology_delta(
                {"stress": self.stress, "mood": self.mood, "fatigue": self.fatigue},
                {}, 
                0.0 # Interaction based update, not time based
            )
            self.bio_controller.sensitivities = new_sensitivities.get("sensitivity_update", self.bio_controller.sensitivities)
            
        return is_shocked

    def adjust_attribute(self, attr_name: str, delta: float, min_val: float = 0.0, max_val: float = 1.0):
        """Atomic adjustment of a SelfModel attribute."""
        with self.lock:
            if hasattr(self, attr_name):
                current = getattr(self, attr_name)
                setattr(self, attr_name, max(min_val, min(max_val, current + delta)))

    def set_attribute(self, attr_name: str, value: float, min_val: float = 0.0, max_val: float = 1.0):
        """Atomic set of a SelfModel attribute."""
        with self.lock:
            if hasattr(self, attr_name):
                setattr(self, attr_name, max(min_val, min(max_val, value)))

    def check_integrity(self, memories: List[MemoryTrace]):
        """Identity Continuity: Mất Core Memories → Bản sắc sụp đổ"""
        core_count = sum(1 for m in memories if m.type == MemoryType.CORE and m.strength > 0.3)
        total_cores = sum(1 for m in memories if m.type == MemoryType.CORE)
        if total_cores > 0:
            self.integrity = core_count / total_cores
        else:
            self.integrity = 0.5

        if self.integrity < 0.2:
            self.is_identity_crisis = True
        elif self.integrity > 0.4:
            self.is_identity_crisis = False

        from core.utils import atomic_write_json
        from config import Config
        path = path or Config.EGO_STATE_FILE
        
        with self.lock:
            state = {
                "mood": self.mood, "stress": self.stress,
                "fatigue": self.fatigue, "curiosity": self.curiosity,
                "social_need": self.social_need, "integrity": self.integrity,
                "is_identity_crisis": self.is_identity_crisis,
                "long_term_goals": getattr(self, 'long_term_goals', []),
                "energy": getattr(self, 'energy', 1.0),
                "atp_level": getattr(self, 'atp_level', 1.0),
                "fatigue_mild": self.fatigue_mild,
                "fatigue_severe": self.fatigue_severe,
                "fatigue_critical": self.fatigue_critical,
                "depression_mild": self.depression_mild,
                "depression_severe": self.depression_severe,
                "depression_critical": self.depression_critical,
                "mania_mild": self.mania_mild,
                "mania_severe": self.mania_severe,
                "stress_mild": self.stress_mild,
                "stress_severe": self.stress_severe,
                "stress_critical": self.stress_critical,
                "dopamine_receptors": getattr(self, 'dopamine_receptors', 1.0),
                "dopamine_level": getattr(self, 'dopamine_level', 0.5),
                "resilience": getattr(self, 'resilience', 0.0),
                "sleep_debt": getattr(self, 'sleep_debt', 0.0),
                "calibrated_overrides": self.calibrated_overrides,
                "actionable_lessons": self.actionable_lessons
            }
        
        atomic_write_json(path, state)

    def load_state(self, path=None):
        """Tải lại trạng thái đã lưu. Nếu file không tồn tại, bỏ qua (dùng giá trị mặc định)."""
        import json, os
        from config import Config
        path = path or Config.EGO_STATE_FILE
        if not os.path.exists(path):
            return
        try:
            with open(path, encoding='utf-8') as f:
                state = json.load(f)
            for k, v in state.items():
                if hasattr(self, k):
                    setattr(self, k, v)
            
            # Apply overrides to current state if any
            for attr, val in self.calibrated_overrides.items():
                if hasattr(self, attr):
                    setattr(self, attr, val)
        except Exception:
            pass  # File lỗi → dùng default, không crash


