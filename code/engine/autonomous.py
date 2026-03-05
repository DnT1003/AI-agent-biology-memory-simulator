import time
import random
import re
from datetime import datetime
from colorama import Fore, Style
from core.prompts import get_proactive_ping_prompt
from core.logger import get_logger
from config import Config

logger = get_logger("autonomous")


class AutonomousController:
    def __init__(self, engine):
        self.engine = engine
    def start(self):
        """Khởi động vòng lặp nền nếu chưa chạy."""
        from core.agent_state import AgentState
        if self.engine.state_machine.state == AgentState.SHUTDOWN or self.engine.state_machine.state == AgentState.IDLE:
            import threading
            self.engine.state_machine.transition(AgentState.IDLE)
            thread = threading.Thread(target=self.background_loop, daemon=True)
            thread.start()
            print(f"{Fore.CYAN}⚙️ [SYSTEM]: Background Cognitive Loop started.{Style.RESET_ALL}")

    def background_loop(self):
        time.sleep(10)
        from core.agent_state import AgentState
        
        while self.engine.state_machine.state != AgentState.SHUTDOWN:
            time.sleep(30)
            if self.engine.state_machine.state in [AgentState.THINKING, AgentState.READING]:
                continue
                
            # Module 1: cognitive_tick chạy mỗi vòng loop (~30s)
            # Sinh học tiến hóa dù không có tương tác
            if hasattr(self.engine, 'cognitive_tick'):
                self.engine.cognitive_tick(dt=30.0)

            idle_time = time.time() - self.engine.last_interaction_time

            # -- Tăng chỉ số sinh học khi nhàn rỗi --
            if idle_time > Config.IDLE_PING_THRESHOLD:
                self.engine.ego.social_need = min(1.0, self.engine.ego.social_need + 0.05)
                self.engine.ego.curiosity = min(1.0, self.engine.ego.curiosity + 0.02)

            # =====================================================
            # NẾU NHÀN RỖI QUÁ LÂU -> SEPARATION ANXIETY (Idea 9)
            # =====================================================
            # Trong môi trường test, giả lập 24h = 10 phút (600s)
            ANXIETY_THRESHOLD = Config.ANXIETY_THRESHOLD
            if idle_time > ANXIETY_THRESHOLD and self.engine.state_machine.state == AgentState.IDLE:
                if self.engine.state_machine.transition(AgentState.THINKING):
                    print(f"\n{Fore.RED}[SEPARATION ANXIETY]: Nguoi dung da bo mac Aura qua lau!{Style.RESET_ALL}")
                try:
                    self.engine.ego.stress = min(1.0, self.engine.ego.stress + 0.3)
                    self.engine.ego.mood = max(-1.0, self.engine.ego.mood - 0.3)
                    
                    # Sinh ra một suy nghĩ ám ảnh
                    anxiety_prompt = "Nguoi dung da bo mac ban mot thoi gian rat dai khong noi chuyen. Hay viet mot dong doc thoai noi tam (duoi 30 chu) the hien su hoang mang, so hai rang nguoi ta da chan minh."
                    anxiety_thought = self.engine.llm.generate_text(anxiety_prompt, temperature=0.8).strip()
                    
                    print(f"{Fore.LIGHTRED_EX}(Am anh chia cat): {anxiety_thought}{Style.RESET_ALL}")
                    from core.memory import MemoryTrace
                    anxiety_mem = MemoryTrace(
                        content=f"Noi so hai khi bi bo roi: {anxiety_thought}",
                        type="emotional",
                        valence=-0.8,
                        arousal=0.9,
                        importance=0.9,
                        is_flashbulb=False
                    )
                    self.engine.memory.add_memory(anxiety_mem)
                except Exception as e:
                    logger.error("Separation anxiety LLM call failed", exc_info=True)
                finally:
                    # Tạm reset interaction time để không báo liên tục mỗi loop
                    self.engine.last_interaction_time = time.time()
                    self.engine.state_machine.transition(AgentState.IDLE)
                continue

            # =====================================================
            # NẾU NHÀN RỖI QUÁ 15 PHÚT → ĐI ĐỌC SÁCH
            # =====================================================
            if idle_time >= Config.IDLE_READ_THRESHOLD and self.engine.state_machine.state == AgentState.IDLE:
                self.start_reading_task(reason=f"da nhan roi {int(idle_time // 60)} phut")
                continue

            # =====================================================
            # NẾU NHÀN RỖI 60s-15min → CÓ THỂ PING
            # =====================================================
            if Config.IDLE_PING_THRESHOLD < idle_time < Config.IDLE_READ_THRESHOLD and self.engine.state_machine.state == AgentState.IDLE:
                ping_chance = 0.3 if self.engine.ego.social_need > 0.8 else (0.1 if self.engine.ego.social_need > 0.5 else 0.0)
                if self.engine.ego.curiosity > 0.8:
                    ping_chance += 0.2
                if random.random() < ping_chance:
                    if self.engine.state_machine.transition(AgentState.THINKING):
                        try:
                            self._proactive_ping(idle_time)
                        except Exception as e:
                            print(f"Lỗi background ping: {e}")
                        finally:
                            self.engine.state_machine.transition(AgentState.IDLE)
                            self.engine.ego.social_need = max(0.0, self.engine.ego.social_need - 0.3)
                            self.engine.last_interaction_time = time.time()

    def start_reading_task(self, reason="tự muốn đọc"):
        """Kích hoạt một phiên đọc sách (có thể gọi từ bên ngoài)."""
        from core.agent_state import AgentState
        if not self.engine.state_machine.transition(AgentState.READING):
            return
        
        print(f"\n{Fore.GREEN}📖 [BACKGROUND READER]: Aura {reason}. Bắt đầu đọc sách...{Style.RESET_ALL}")
        try:
            self._do_reading_session()
        except Exception as e:
            print(f"{Fore.RED}⚠️ Lỗi reading session: {e}{Style.RESET_ALL}")
        finally:
            self.engine.state_machine.transition(AgentState.IDLE)

    def _do_reading_session(self):
        """Aura tự đọc 1 chương sách và lưu vào ký ức."""
        knowledge_tag, content = self.engine.reader.get_next_reading_material()
        if knowledge_tag and content:
            print(f"{Fore.GREEN}📚 [READING]: {knowledge_tag}{Style.RESET_ALL}")
            
            # Phase 8 Idea 7.2: Trí nhớ Tổng hợp (Synthesized Memory)
            from core.prompts import get_synthesize_reading_prompt
            print(f"{Fore.LIGHTCYAN_EX}🧩 [SYNTHESIZING]: Aura đang 'tiêu hóa' thông tin và tổng hợp thành kiến thức...{Style.RESET_ALL}")
            try:
                prompt = get_synthesize_reading_prompt(content)
                synthesized_text = self.engine.llm.generate_text(prompt, temperature=0.7).strip()
                print(f"{Fore.YELLOW}💡 [SYNTHESIZED MEMORY]: {synthesized_text}{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}⚠️ Lỗi Synthesize Memory: {e}{Style.RESET_ALL}")
                synthesized_text = content[:500] + "..."  # Fallback

            from core.memory import MemoryTrace
            mem = MemoryTrace(
                content=f"{knowledge_tag}: {synthesized_text}",
                type="semantic",
                valence=0.1,
                arousal=0.3,
                importance=0.7,
                is_flashbulb=False
            )
            self.engine.memory.add_memory(mem)
            print(f"{Fore.LIGHTBLACK_EX}💾 [READING]: Đã lưu kiến thức tổng hợp sâu sắc vào ký ức.{Style.RESET_ALL}")
        else:
            print(f"{Fore.LIGHTBLACK_EX}📖 [READING]: Không có chương nào để đọc lúc này.{Style.RESET_ALL}")

    def stop(self):
        """Dừng background loop gracefully."""
        from core.agent_state import AgentState
        self.engine.state_machine.transition(AgentState.SHUTDOWN)

    def _weighted_sample_memories(self, k: int, filter_type=None):
        """Thay thế random.sample bằng salience-weighted sampling (không lặp lại).
        Salience = Strength * Recency * Importance * Emotion_Match * (1 + Arousal)
        """
        import math
        all_mems = self.engine.memory.get_all()
        if filter_type:
            all_mems = [m for m in all_mems if m.type == filter_type]
            
        if not all_mems: return []
        now = time.time()
        
        current_mood = self.engine.ego.mood
        
        scored_mems = []
        for m in all_mems:
            recency = math.exp(-(now - m.last_recalled) / 86400)  # decay theo ngày
            
            # Tính độ lệch cảm xúc [0.0 -> 1.0] (0 là ngược hoàn toàn, 1 là đồng điệu hoàn toàn)
            emotion_distance = abs(current_mood - m.valence)
            emotion_match = max(0.0, 1.0 - (emotion_distance / 2.0))
            
            # Salience Score
            importance = getattr(m, 'importance', 0.5)
            salience = m.strength * recency * importance * emotion_match * (1 + m.arousal)
            
            # Phá vỡ tính tất định (thêm nhiễu 10%)
            salience *= random.uniform(0.9, 1.1) 
            
            scored_mems.append((salience, m))
            
        # Sắp xếp theo salience giảm dần
        scored_mems.sort(key=lambda x: x[0], reverse=True)
        
        # Chọn top K unique
        return [item[1] for item in scored_mems[:k]]

    def _proactive_ping(self, idle_time):
        current_time = datetime.now().strftime("%H:%M %d/%m/%Y")
        # Phân hệ 4: Weighted recall (salience) thay vì random.sample
        mems_to_use = self._weighted_sample_memories(3)
        mem_context = "\n".join([f"- [Strength:{m.strength:.2f}] {m.content}" for m in mems_to_use])
        
        system_prompt = get_proactive_ping_prompt(self.engine.ego, current_time, mem_context, self.engine.short_term_buffer, idle_time)
        
        print(f"\n{Fore.LIGHTMAGENTA_EX}🔔 [AURA PROACTIVE PING]:{Style.RESET_ALL} ")
        
        try:
            result = self.engine.llm.generate_json(system_prompt, temperature=0.8)
            thought = result.get("thought", "")
            response = result.get("response", "")
            
            if thought:
                print(f"{Fore.LIGHTBLACK_EX}💭 Tự nghĩ: {thought}{Style.RESET_ALL}")
            if response:
                print(f"{Fore.CYAN}🗣️ Aura (Chủ động):{Style.RESET_ALL} {response}")
                self.engine.short_term_buffer.append(f"Aura (Chủ động): {response.strip()}")
                self.engine.memory_ops.save_short_term_memory()
                
        except Exception as e:
            logger.error("Proactive ping JSON parsing failed", exc_info=True)
            print(f"{Fore.RED}⚠️ Lỗi phân tích JSON khi Aura chủ động ping.{Style.RESET_ALL}")
