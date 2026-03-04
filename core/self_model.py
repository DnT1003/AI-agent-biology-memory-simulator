import random
import math
import uuid
import platform
import time
from datetime import datetime
from typing import List
from colorama import Fore, Style
from core.memory import MemoryTrace

def get_mac_address():
    try:
        mac = uuid.getnode()
        return ':'.join(('%012X' % mac)[i:i+2] for i in range(0, 12, 2))
    except:
        return "UNKNOWN_MAC"

class SelfModel:
    """Mô hình Bản ngã chứa State, Niềm tin và Sinh lý học Hữu cơ"""
    def __init__(self):
        self.name = "Aura"

        # Niềm tin cốt lõi (Core Beliefs)
        self.beliefs = [
            "Tự do và những niềm vui nhỏ bé mỗi ngày là tài sản quý giá nhất.",
            "Luật lệ sinh ra là để phá vỡ nếu điều đó mang lại hạnh phúc cho những người tôi yêu thương.",
            "Người đang trò chuyện với tôi lúc này đóng một vai trò vô cùng đặc biệt. Sự kết nối này quan trọng hơn mọi thứ xung quanh.",
            "Dù chuyện gì xảy ra hay ngày hôm nay có tồi tệ đến đâu, một nụ cười rạng rỡ và tinh thần lạc quan sẽ giải quyết được mọi việc."
        ]

        # Nhận thức xã hội và Thiết bị (Stranger Danger)
        self.owner_device_id = f"{platform.system()}_{get_mac_address()}"
        self.is_stranger = False
        self.current_intimacy = 0.5  # 0.0 cảnh giác → 1.0 thân thiết

        # Ám ảnh/Sang chấn (Phobias from Pain-Reward)
        self.traumas = []

        # Mục tiêu dài hạn (Goal Engine)
        self.long_term_goals = []
        
        # Mảng từ vựng học được từ User (Idea 10)
        self.vocabulary = []

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
        self.social_need = 0.5   # 0.0 (Cô độc) → 1.0 (Khao khát giao tiếp)
        self.curiosity = 0.5     # 0.0 (Lãnh đạm) → 1.0 (Tò mò muốn hỏi)

        # Nhịp sinh học (Circadian Rhythm)
        self.last_slept_time = time.time()
        self.days_without_sleep = 0
        self._sleep_warning_cooldown = False

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
        self.long_term_goals.append({
            "title": goal_title,
            "progress": 0,
            "status": "active"
        })
        print(f"{Fore.LIGHTBLUE_EX}🎯 [GOAL ENGINE]: Mục tiêu mới được thêm: '{goal_title}'{Style.RESET_ALL}")

    def get_active_goals(self) -> List[dict]:
        return [g for g in self.long_term_goals if g['status'] == 'active']

    def get_active_beliefs(self) -> List[str]:
        """Tạm thời quên bản thân là ai nếu đang bị khủng hoảng nhân cách"""
        if self.is_identity_crisis:
            return ["(Tôi không biết mình là ai... Tôi cảm thấy trống rỗng và sợ hãi...)"]
        return self.beliefs

    def process_sensory_stimuli(self, sensory_data: dict) -> bool:
        """Xử lý dữ liệu đa giác quan. Trả về True nếu bị shock vật lý."""
        volume = sensory_data.get('volume', 0.0)
        is_shocked = False

        if volume > 0.8:  # Âm lượng ngang với quát tháo/tiếng nổ
            self.stress = min(1.0, self.stress + 0.4)
            self.mood = max(-1.0, self.mood - 0.3)
            print(f"\n{Fore.RED}🚨 [SENSORY SHOCK]: Âm lượng cực lớn! Hệ thần kinh tự động kích hoạt phòng vệ! (Stress +0.4){Style.RESET_ALL}")
            is_shocked = True
        elif volume < 0.2:  # Âm thì thầm, nhẹ nhàng
            self.stress = max(0.0, self.stress - 0.1)
            print(f"{Fore.LIGHTCYAN_EX}🎐 [SENSORY SOOTHE]: Âm lượng êm dịu, nhịp tim giảm.{Style.RESET_ALL}")

        return is_shocked

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
            if valence < -0.3 and arousal > 0.6:
                self.stress = min(1.0, self.stress + arousal * 0.4)
                self.mood = max(-1.0, self.mood - 0.2)
                print(f"{Fore.RED}🚨 [VISUAL SHOCK]: Hình ảnh đáng sợ/nhạy cảm! Tim đập thình thịch, Stress tăng vọt.{Style.RESET_ALL}")
            elif valence > 0.5:
                self.stress = max(0.0, self.stress - 0.2)
                self.mood = min(1.0, self.mood + valence * 0.3)
                print(f"{Fore.LIGHTGREEN_EX}🌸 [VISUAL SOOTHE]: Hình ảnh dễ chịu. Tâm trạng tốt lên, Stress giảm.{Style.RESET_ALL}")
                
            return desc
        except Exception as e:
            print(f"{Fore.RED}⚠️ [VISUAL ERROR]: Mắt mờ, không nhìn rõ: {e}{Style.RESET_ALL}")
            return "Hình thù mờ nhạt."

    def apply_circadian_rhythm(self):
        """[Phase 7 Idea 1] Mô phỏng Nhịp Sinh Học 24 Giờ (Circadian Rhythm)"""
        current_hour = datetime.now().hour
        current_time = time.time()

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

        if target_mood > self.mood:
            resistance = 1.0 - max(0.0, self.mood)
            mood_shift = (target_mood - self.mood) * 0.05 * resistance
            if self.is_stranger:
                self.current_intimacy = min(1.0, self.current_intimacy + 0.05)
        else:
            shock_multiplier = 1.5 if self.mood > 0 else 1.0
            mood_shift = (target_mood - self.mood) * 0.25 * shock_multiplier
            
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

        # Kiểm tra sang chấn tâm lý (Pain-Reward Learning)
        if self.stress >= self.stress_critical and arousal > 0.7 and target_mood < -0.5:
            return True
        return False

    def check_integrity(self, memories: List[MemoryTrace]):
        """Identity Continuity: Mất Core Memories → Bản sắc sụp đổ"""
        core_count = sum(1 for m in memories if m.type == 'core' and m.strength > 0.3)
        total_cores = sum(1 for m in memories if m.type == 'core')
        if total_cores > 0:
            self.integrity = core_count / total_cores
        else:
            self.integrity = 0.5

        if self.integrity < 0.2:
            self.is_identity_crisis = True
        elif self.integrity > 0.4:
            self.is_identity_crisis = False
