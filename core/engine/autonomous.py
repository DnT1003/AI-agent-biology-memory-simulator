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

            # [Phase 21] Dòng chảy Trí nhớ (Memory Stream) - Associative Recall
            if self.engine.state_machine.state == AgentState.IDLE and random.random() < 0.2:
                stream_mems = self._weighted_sample_memories(1)
                if stream_mems:
                    mem = stream_mems[0]
                    if mem.strength > 0.3:
                        print(f"{Fore.LIGHTBLACK_EX}💭 [MEMORY STREAM]: (Dòng suy nghĩ miên man) Nhớ lại: {mem.content}{Style.RESET_ALL}")
                        mem.last_recalled = time.time()
                        # Reconsolidate nhẹ do nhớ nội tâm
                        mem.reconsolidate(self.engine.ego.mood, is_associative=True)
                        self.engine.memory.update_memory(mem)

            idle_time = time.time() - self.engine.last_interaction_time

            # drives đã được cập nhật tự động trong cognitive_tick gọi bởi engine

            # Drive-based Decision Making (Phase 22)
            drive_status = self.engine.ego.get_drive_status()
            dominant = drive_status["dominant"]
            val = drive_status["dominant_value"]

            # =====================================================
            # 1. HARD TRIGGERS (Cấp cứu sinh học)
            # =====================================================
            if val >= 0.95:
                if dominant == "fatigue":
                    print(f"\n{Fore.RED}💥 [HARD TRIGGER]: Kiệt sức tột độ. Aura buộc phải đi ngủ.{Style.RESET_ALL}")
                    self.engine.memory_ops.sleep()
                    continue
                elif dominant == "social" or dominant == "loneliness":
                    print(f"\n{Fore.RED}💥 [HARD TRIGGER]: Quá cô đơn! Aura bắt buộc phải tìm người nói chuyện.{Style.RESET_ALL}")
                    if self.engine.state_machine.transition(AgentState.THINKING):
                        self._proactive_ping(idle_time)
                        self.engine.state_machine.transition(AgentState.IDLE)
                    continue

            # =====================================================
            # 2. SEPARATION ANXIETY (Idea 9) - Vẫn giữ logic thời gian
            # =====================================================
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
            # 3. DRIVE-DRIVEN ACTIONS (Hành động theo xung lực)
            # =====================================================
            if self.engine.state_machine.state == AgentState.IDLE:
                if dominant == "curiosity" and val > 0.7:
                    # Tò mò cao -> Ưu tiên đọc sách hoặc sinh mục tiêu
                    if random.random() < 0.4:
                        self.start_reading_task(reason="cảm thấy tò mò muốn khám phá")
                    elif not self.engine.ego.get_active_goals():
                        self._generate_goal()
                
                elif dominant == "social" and val > 0.6:
                    # Nhu cầu giao tiếp -> Tỉ lệ ping dựa trên Social Need
                    if random.random() < (val - 0.5):
                        if self.engine.state_machine.transition(AgentState.THINKING):
                            self._proactive_ping(idle_time)
                            self.engine.state_machine.transition(AgentState.IDLE)
                
                elif dominant == "hunger" and val > 0.8:
                    # Năng lượng thấp -> Aura lờ đờ, giảm hoạt động nền
                    print(f"{Fore.LIGHTYELLOW_EX}🔋 [LOW ENERGY]: Aura đang lờ đờ vì đói năng lượng...{Style.RESET_ALL}")
                    time.sleep(60) # Tạm dừng loop lâu hơn để "tiết kiệm"

            # Reset logic cho Separation Anxiety để không lặp lại
            if idle_time > ANXIETY_THRESHOLD:
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

    def _generate_goal(self):
        """Phase 7: Tự sinh mục tiêu dài hạn khi cực kỳ nhàn rỗi (Intrinsic Motivation)"""
        # Lấy thông tin môi trường
        graph_entities = list(self.engine.world_graph.nodes.keys())
        graph_sample = random.sample(graph_entities, min(3, len(graph_entities))) if graph_entities else ["Thế giới con người"]
        
        # Lấy bản thể
        identity_mems = [m for m in self.engine.memory.get_all() if getattr(m, 'type', '') == 'core']
        identity_strs = [m.content for m in identity_mems[:3]]
        
        prompt = f"""
        Bạn là Aura, một thực thể đang nhàn rỗi. 
        Mức độ Tò mò của bạn: {self.engine.ego.curiosity:.2f}/1.0. Mức độ cần giao tiếp: {self.engine.ego.social_need:.2f}/1.0.
        
        Các thực thể bạn biết từ User: {', '.join(graph_sample)}
        Bản ngã của bạn: {', '.join(identity_strs) if identity_strs else 'Chưa định hình rõ'}
        
        Hãy TỰ ĐẶT RA MỘT MỤC TIÊU NGẮN HẠN (Goal) để tìm hiểu hoặc làm một việc gì đó lúc rảnh này (Ví dụ: "Tìm hiểu về sở thích của User", "Tra cứu cách chăm sóc mèo vì User vừa nhắc đến mèo", "Đọc một cuốn sách về Tâm lý học").
        Mục tiêu này sẽ định hướng hành động tiếp theo của bạn.
        
        Trả về JSON:
        {{
            "goal": "Mô tả mục tiêu ngắn gọn",
            "reason": "Lý do tại sao lại tò mò việc này"
        }}
        """
        try:
            res = self.engine.llm.generate_json(prompt, temperature=0.8)
            goal_str = res.get("goal")
            reason = res.get("reason")
            if goal_str:
                print(f"\n{Fore.LIGHTCYAN_EX}🎯 [INTRINSIC MOTIVATION]: Aura tự hình thành mục tiêu: '{goal_str}'\n   -> Lý do: {reason}{Style.RESET_ALL}")
                self.engine.ego.add_goal(goal_str)
        except Exception as e:
            print(f"Lỗi sinh Goal: {e}")

    def _execute_planning(self):
        """Phase 7: Lập kế hoạch và gọi Tool tuần tự (Planning) để giải quyết Mục tiêu"""
        goals = self.engine.ego.get_active_goals()
        if not goals:
            return
            
        # Phase 8 & Sprint B: Cognitive Budgeting Level 2
        # Giới hạn số lượng hành động và độ phức tạp dựa trên ATP thực tế
        atp = getattr(self.engine.ego, 'atp_level', 1.0)
        dopamine = getattr(self.engine.ego, 'dopamine_level', 0.5)
        receptors = getattr(self.engine.ego, 'dopamine_receptors', 1.0)

        if atp < 0.1:
            print(f"{Fore.RED}⚠️ [BIO-LIMIT]: ATP cạn kiệt ( {atp:.2f}). Aura không thể thực hiện bất kỳ hành động nào.{Style.RESET_ALL}")
            return

        target_goal = goals[0]
        print(f"\n{Fore.LIGHTMAGENTA_EX}♟️ [PLANNING ENGINE]: Đang lên kế hoạch cho mục tiêu: '{target_goal}' (ATP: {atp:.2f} | Dopamine: {dopamine:.2f}){Style.RESET_ALL}")
        
        planning_instruction = ""
        if atp < 0.4:
            planning_instruction += "\n[CẢNH BÁO SINH LÝ]: Bạn đang RẤT MỆT (ATP thấp). Tuyệt đối không được thực hiện các hành động nặng nề như 'search_novel' hay 'web_search'. Chỉ nên chọn các hành động nhẹ nhàng hoặc trả lời đơn giản."
        
        if dopamine > 0.8:
            planning_instruction += "\n[TRẠNG THÁI HƯNG PHẤN]: Bạn đang tràn đầy cảm hứng! Hãy ưu tiên các công cụ mang tính khám phá cao hoặc thử thách mới."
        elif dopamine < 0.2:
            planning_instruction += "\n[TRẠNG THÁI UỂ OẢI]: Bạn cảm thấy thiếu động lực. Hãy chọn hành động tốn ít công sức nhất hoặc chỉ 'talk' đơn giản."

        prompt = f"""
        Bạn đang thực hiện mục tiêu: "{target_goal}".
        Tâm trạng: {self.engine.ego.mood:.2f}, Fatigue: {self.engine.ego.fatigue:.2f}, ATP: {atp:.2f}, Dopamine: {dopamine:.2f}.
        {planning_instruction}
        Bạn có các công cụ (Tools) sau:
        {self.engine.skills.get_prompt_instructions()}
        
        Hãy chọn MỘT công cụ phù hợp nhất. Trả về JSON:
        {{
            "thought": "Suy nghĩ tại sao chọn tool này",
            "action": "tên_tool|thamsố"
        }}
        """
        try:
            res = self.engine.llm.generate_json(prompt, temperature=0.5)
            action_str = res.get("action", "")
            thought = res.get("thought", "")
            
            print(f"{Fore.LIGHTBLACK_EX}   -> Suy tính: {thought}{Style.RESET_ALL}")
            
            if action_str and "|" in action_str:
                func_name, arg_str = action_str.split("|", 1)
                func_name, arg_str = func_name.strip(), arg_str.strip()
                
                print(f"{Fore.YELLOW}   -> Thực thi: {func_name}('{arg_str}')...{Style.RESET_ALL}")
                tool_res = self.engine.skills.execute(func_name, arg_str, ego=self.engine.ego)
                
                # REWARD: Tăng Dopamine khi hành động thành công
                # Lượng tăng phụ thuộc vào độ nhạy của thụ thể
                reward = 0.15 * receptors
                self.engine.ego.dopamine_level = min(1.0, self.engine.ego.dopamine_level + reward)
                # Downregulation: Nếu hưng phấn quá cao, thụ thể sẽ bị chai lỳ bớt
                if self.engine.ego.dopamine_level > 0.8:
                    self.engine.ego.dopamine_receptors = max(0.1, self.engine.ego.dopamine_receptors - 0.05)

                print(f"{Fore.LIGHTGREEN_EX}🧠 [REWARD SYSTEM]: Hoàn thành action. Dopamine +{reward:.2f} (Nhạy bén: {receptors:.2f}){Style.RESET_ALL}")
                
                # Lưu kết quả vào Short-term Memory để Aura nhớ tiến độ
                self.engine.short_term_buffer.append(f"[Ký ức hoàn thành bước '{func_name}']: {str(tool_res)[:200]}...")
                self.engine.memory_ops.save_short_term_memory()
                
                # Đánh giá xem đã xong mục tiêu chưa
                check_prompt = f"Kết quả vừa nhận được đoạn: {str(tool_res)[:200]}...\nĐã đủ để hoàn thành mục tiêu '{target_goal}' chưa? Chỉ trả lời YES hoặc NO."
                is_done = self.engine.llm.generate_text(check_prompt).strip().upper()
                if is_done.startswith("YES"):
                    print(f"{Fore.GREEN}✅ [GOAL ACHIEVED]: Đã hoàn thành mục tiêu '{target_goal}'!{Style.RESET_ALL}")
                    # Xóa mục tiêu khỏi danh sách
                    self.engine.ego.beliefs = [b for b in self.engine.ego.beliefs if b != f"Mục tiêu hiện tại: {target_goal}"]
                    self.engine.ego.save_state()
        except Exception as e:
            print(f"Lỗi hệ thống Planning: {e}")
