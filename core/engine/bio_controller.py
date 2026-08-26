import random
import math
import time

class BioController:
    """
    Hệ thống 1 (Cân bằng nội môi động): 
    Quản lý sự tiêu hao sinh học và biến thiên các chỉ số của Aura.
    """
    def __init__(self):
        # Ma trận nhạy cảm (Sensitivity Matrix)
        self.sensitivities = {
            "stress": 1.0,
            "fatigue": 1.0,
            "empathy": 1.0,
            "dopamine": 1.0
        }

    def calculate_physiology_delta(self, current_state: dict, sensory_input: dict, dt_seconds: float) -> dict:
        dt_hours = dt_seconds / 3600.0
        
        # 1. Fatigue Hybrid (Chu kỳ + Căng thẳng + Nhiễu)
        # Tăng mệt mỏi theo log thời gian và stress
        stress_val = current_state.get('stress', 0.0)
        # Random Jitter ±2%
        jitter = random.uniform(-0.02, 0.02)
        fatigue_delta = (0.01 + (stress_val * 0.04)) * dt_hours + jitter
        
        # 2. ATP Consumption (Metabolic Rate)
        # Tiêu hao năng lượng dựa trên hoạt động (dt) và trạng thái cảm xúc
        atp_loss = (0.05 + stress_val * 0.1) * dt_hours
        
        # 3. Dynamic Sensitivity Adjustment (Positive Feedback)
        # Nếu đang stress cao, độ nhạy cảm với stress tăng lên (dễ bị kích động hơn)
        if stress_val > 0.8:
            self.sensitivities["stress"] = min(2.0, self.sensitivities["stress"] * 1.05)
        else:
            self.sensitivities["stress"] = max(1.0, self.sensitivities["stress"] * 0.95)
            
        return {
            "fatigue_delta": round(fatigue_delta, 4),
            "atp_delta": -round(atp_loss, 4),
            "sensitivity_update": self.sensitivities
        }

    def calculate_interaction_cost(self, token_count: int, sensory_vector: dict) -> dict:
        """Tính toán 'giá' của một lần suy nghĩ/phản hồi."""
        arousal = sensory_vector.get('arousal', 0.5)
        urgency = sensory_vector.get('urgency', 0.0)
        
        # Công thức: Tiêu hao ATP tỷ lệ với độ dài câu và mức độ kích động
        cost_multiplier = 1.0 + arousal + (urgency * 0.5)
        atp_cost = (token_count / 1000.0) * 0.1 * cost_multiplier
        energy_cost = atp_cost * 0.5
        
        # Thêm biến thiên ngẫu nhiên sinh học
        atp_cost *= random.uniform(0.9, 1.1)
        
        return {
            "atp_cost": round(atp_cost, 4),
            "energy_cost": round(energy_cost, 4)
        }
