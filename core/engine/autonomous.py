import time
import random
import re
from datetime import datetime
from colorama import Fore, Style
from core.prompts import get_proactive_ping_prompt
from core.logger import get_logger
from config import Config

logger = get_logger("autonomous")


class AutonomousMixin:
    def start(self):
        """Khởi động vòng lặp nền nếu chưa chạy."""
        from core.agent_state import AgentState
        if self.state_machine.state == AgentState.SHUTDOWN or self.state_machine.state == AgentState.IDLE:
            import threading
            self.state_machine.transition(AgentState.IDLE)
            thread = threading.Thread(target=self.background_loop, daemon=True)
            thread.start()
            print(f"{Fore.CYAN}⚙️ [SYSTEM]: Background Cognitive Loop started.{Style.RESET_ALL}")

    def background_loop(self):
        time.sleep(10)
        from core.agent_state import AgentState
        
        while self.state_machine.state != AgentState.SHUTDOWN:
            time.sleep(30)
            if self.state_machine.state in [AgentState.THINKING, AgentState.READING]:
                continue
                
            # Module 1: cognitive_tick chạy mỗi vòng loop (~30s)
            # Sinh học tiến hóa dù không có tương tác
            if hasattr(self, 'cognitive_tick'):
                self.cognitive_tick(dt=30.0)

            idle_time = time.time() - self.last_interaction_time

            # -- Tăng chỉ số sinh học khi nhàn rỗi --
            if idle_time > Config.IDLE_PING_THRESHOLD:
                self.ego.social_need = min(1.0, self.ego.social_need + 0.05)
                self.ego.curiosity = min(1.0, self.ego.curiosity + 0.02)

            # =====================================================
            # NẾU NHÀN RỖI QUÁ LÂU -> SEPARATION ANXIETY (Idea 9)
            # =====================================================
            # Trong môi trường test, giả lập 24h = 10 phút (600s)
            ANXIETY_THRESHOLD = Config.ANXIETY_THRESHOLD
            if idle_time > ANXIETY_THRESHOLD and self.state_machine.state == AgentState.IDLE:
                if self.state_machine.transition(AgentState.THINKING):
                    print(f"\n{Fore.RED}[SEPARATION ANXIETY]: Nguoi dung da bo mac Aura qua lau!{Style.RESET_ALL}")
                try:
                    self.ego.stress = min(1.0, self.ego.stress + 0.3)
                    self.ego.mood = max(-1.0, self.ego.mood - 0.3)
                    
                    # Sinh ra một suy nghĩ ám ảnh
                    anxiety_prompt = "Nguoi dung da bo mac ban mot thoi gian rat dai khong noi chuyen. Hay viet mot dong doc thoai noi tam (duoi 30 chu) the hien su hoang mang, so hai rang nguoi ta da chan minh."
                    anxiety_thought = self.llm.generate_text(anxiety_prompt, temperature=0.8).strip()
                    
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
                    self.memory.add_memory(anxiety_mem)
                except Exception as e:
                    logger.error("Separation anxiety LLM call failed", exc_info=True)
                finally:
                    # Tạm reset interaction time để không báo liên tục mỗi loop
                    self.last_interaction_time = time.time()
                    self.state_machine.transition(AgentState.IDLE)
                continue

            # =====================================================
            # NẾU NHÀN RỖI QUÁ 15 PHÚT → ĐI ĐỌC SÁCH
            # =====================================================
            if idle_time >= Config.IDLE_READ_THRESHOLD and self.state_machine.state == AgentState.IDLE:
                self.start_reading_task(reason=f"da nhan roi {int(idle_time // 60)} phut")
                continue

            # =====================================================
            # NẾU NHÀN RỖI 60s-15min → CÓ THỂ PING
            # =====================================================
            if Config.IDLE_PING_THRESHOLD < idle_time < Config.IDLE_READ_THRESHOLD and self.state_machine.state == AgentState.IDLE:
                ping_chance = 0.3 if self.ego.social_need > 0.8 else (0.1 if self.ego.social_need > 0.5 else 0.0)
                if self.ego.curiosity > 0.8:
                    ping_chance += 0.2
                if random.random() < ping_chance:
                    if self.state_machine.transition(AgentState.THINKING):
                        try:
                            self._proactive_ping(idle_time)
                        except Exception as e:
                            print(f"Lỗi background ping: {e}")
                        finally:
                            self.state_machine.transition(AgentState.IDLE)
                            self.ego.social_need = max(0.0, self.ego.social_need - 0.3)
                            self.last_interaction_time = time.time()

    def start_reading_task(self, reason="tự muốn đọc"):
        """Kích hoạt một phiên đọc sách (có thể gọi từ bên ngoài)."""
        from core.agent_state import AgentState
        if not self.state_machine.transition(AgentState.READING):
            return
        
        print(f"\n{Fore.GREEN}📖 [BACKGROUND READER]: Aura {reason}. Bắt đầu đọc sách...{Style.RESET_ALL}")
        try:
            self._do_reading_session()
        except Exception as e:
            print(f"{Fore.RED}⚠️ Lỗi reading session: {e}{Style.RESET_ALL}")
        finally:
            self.state_machine.transition(AgentState.IDLE)

    def _do_reading_session(self):
        """Aura tự đọc 1 chương sách và lưu vào ký ức."""
        knowledge_tag, content = self.reader.get_next_reading_material()
        if knowledge_tag and content:
            print(f"{Fore.GREEN}📚 [READING]: {knowledge_tag}{Style.RESET_ALL}")
            
            # Phase 8 Idea 7.2: Trí nhớ Tổng hợp (Synthesized Memory)
            from core.prompts import get_synthesize_reading_prompt
            print(f"{Fore.LIGHTCYAN_EX}🧩 [SYNTHESIZING]: Aura đang 'tiêu hóa' thông tin và tổng hợp thành kiến thức...{Style.RESET_ALL}")
            try:
                prompt = get_synthesize_reading_prompt(content)
                synthesized_text = self.llm.generate_text(prompt, temperature=0.7).strip()
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
            self.memory.add_memory(mem)
            print(f"{Fore.LIGHTBLACK_EX}💾 [READING]: Đã lưu kiến thức tổng hợp sâu sắc vào ký ức.{Style.RESET_ALL}")
        else:
            print(f"{Fore.LIGHTBLACK_EX}📖 [READING]: Không có chương nào để đọc lúc này.{Style.RESET_ALL}")

    def stop(self):
        """Dừng background loop gracefully."""
        from core.agent_state import AgentState
        self.state_machine.transition(AgentState.SHUTDOWN)

    def _weighted_sample_memories(self, k: int):
        """Thay thế random.sample bằng salience-weighted sampling.
        weight = strength × recency_factor × (1 + |valence| × arousal)
        """
        import math
        all_mems = self.memory.get_all()
        if not all_mems: return []
        now = time.time()
        weights = []
        for m in all_mems:
            recency = math.exp(-(now - m.last_recalled) / 86400)  # decay theo ngày
            salience = max(1e-6, m.strength * recency * (1 + abs(m.valence) * m.arousal))
            weights.append(salience)
        total = sum(weights)
        probs = [w / total for w in weights]
        return random.choices(all_mems, weights=probs, k=min(k, len(all_mems)))

    def _proactive_ping(self, idle_time):
        current_time = datetime.now().strftime("%H:%M %d/%m/%Y")
        # Môdule 4: Weighted recall thay vì random.sample
        mems_to_use = self._weighted_sample_memories(3)
        mem_context = "\n".join([f"- [Strength:{m.strength:.2f}] {m.content}" for m in mems_to_use])
        
        system_prompt = get_proactive_ping_prompt(self.ego, current_time, mem_context, self.short_term_buffer, idle_time)
        
        print(f"\n{Fore.LIGHTMAGENTA_EX}🔔 [AURA PROACTIVE PING]:{Style.RESET_ALL} ")
        full_text, is_printing_output = "", False
        for chunk in self.llm.generate_text_stream(system_prompt, temperature=0.8):
            full_text += chunk
            if not is_printing_output:
                if "THOUGHT:" in full_text:
                    is_printing_output = True
                    output_part = full_text.split("THOUGHT:")[-1].lstrip()
                    if output_part: print(f"{Fore.LIGHTBLACK_EX}💭 Tự nghĩ: {output_part}{Style.RESET_ALL}", end="", flush=True)
            else:
                if "RESPONSE:" in chunk:
                    parts = chunk.split("RESPONSE:")
                    if parts[0]: print(f"{Fore.LIGHTBLACK_EX}{parts[0]}{Style.RESET_ALL}", end="", flush=True)
                    print(f"\n{Fore.CYAN}🗣️ Aura (Chủ động):{Style.RESET_ALL} {parts[1] if len(parts)>1 else ''}", end="", flush=True)
                elif "RESPONSE:" in full_text: print(f"{Fore.CYAN}{chunk}{Style.RESET_ALL}", end="", flush=True)
                else: print(f"{Fore.LIGHTBLACK_EX}{chunk}{Style.RESET_ALL}", end="", flush=True)
        print("\n")
        resp_match = re.search(r'RESPONSE:\s*(.*)', full_text, re.DOTALL | re.IGNORECASE)
        if resp_match:
             self.short_term_buffer.append(f"Aura (Chủ động): {resp_match.group(1).strip()}")
             self.save_short_term_memory()
