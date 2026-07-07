import time
import random
import re
import threading
import asyncio
from datetime import datetime
from colorama import Fore, Style
from core.prompts import get_proactive_ping_prompt
from core.logger import get_logger
from config import Config

logger = get_logger("autonomous")


class AutonomousController:
    def __init__(self, engine):
        self.engine = engine
        self._stop_event = threading.Event()  # Use threading.Event for cross-thread safety
        self._loop_thread = None
        self.event_queue = None
        self._loop = None
    def start(self):
        """Khởi động vòng lặp nền nếu chưa chạy."""
        if self._loop_thread is not None and self._loop_thread.is_alive():
            print(f"{Fore.YELLOW}[SYSTEM]: Background loop already running.{Style.RESET_ALL}")
            return
        self._stop_event.clear()
        self._loop_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._loop_thread.start()
        print(f"{Fore.CYAN}⚙️ [SYSTEM]: Background Event-Driven Loop (asyncio) started.{Style.RESET_ALL}")

    def _run_async_loop(self):
        try:
            asyncio.run(self.background_loop_async())
        except Exception as e:
            print(f"{Fore.RED}[FATAL BACKGROUND LOOP ERROR] Vòng lặp nền đã sập vì: {e}{Style.RESET_ALL}")
            logger.error("Vòng lặp nền sập!", exc_info=True)

    def trigger_event(self, event_type, data=None):
        """Đẩy sự kiện vào giao thức Event-Driven."""
        if self.event_queue is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self.event_queue.put_nowait, {"type": event_type, "data": data})

    async def background_loop_async(self):
        self._loop = asyncio.get_running_loop()
        self.event_queue = asyncio.Queue()
        await asyncio.sleep(3)
        from core.agent_state import AgentState
        
        last_tick_time = time.time()
        
        while not self._stop_event.is_set():
            try:
                # Event-Driven Architecture: Đợi sự kiện hoặc timeout
                event = await asyncio.wait_for(self.event_queue.get(), timeout=1.0)
                if event and event.get("type") == "SHUTDOWN":
                    break
            except (asyncio.TimeoutError, TimeoutError):
                pass
            except Exception as e:
                print(f"[ERROR wait_for]: {e}")

            # === [DISCORD BRIDGE] ===
            discord_handled = False
            try:
                discord_bridge = getattr(self.engine, 'discord_bridge', None)
                if discord_bridge:
                    while not discord_bridge.aura_inbox.empty():
                        msg_data = discord_bridge.aura_inbox.get_nowait()
                        sender = msg_data.get("sender", "Bạn")
                        content = msg_data.get("content", "")
                        if content:
                            print(f"\n{Fore.MAGENTA}💬 [Discord - {sender}]:{Style.RESET_ALL} {content}")
                            self.engine.last_interaction_time = time.time()
                            self.engine.interaction.is_interrupted = False
                            discord_handled = True
                            
                            discord_input = f"{sender}: {content}"
                            reply = await asyncio.to_thread(
                                self.engine.interaction.interaction_loop,
                                discord_input,
                                is_deep_mode=False,
                                model_override="gemini-3-flash-preview"
                            )
                            if reply and isinstance(reply, dict):
                                response_text = reply.get("response", "")
                                if response_text and response_text not in ["", "..."]:
                                    discord_bridge.send_to_user(response_text)
                            
                            # Cập nhật lại thời gian sau khi xử lý xong
                            self.engine.last_interaction_time = time.time()
            except Exception as e:
                print(f"{Fore.RED}[DISCORD BRIDGE FATAL ERROR] {e}{Style.RESET_ALL}")
                import traceback
                traceback.print_exc()

            # Nếu vừa xử lý Discord message → bỏ qua tick sinh học và Proactive Ping
            if discord_handled:
                continue

            # Polling Web Chat - use absolute path to avoid cwd issues in thread
            try:
                import os, json
                # Always resolve to absolute path based on the project root
                _project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
                _out_dir = os.path.join(_project_root, Config.OUTPUT_DIR)
                chat_in_path = os.path.join(_out_dir, "web_chat_in.txt")
                if os.path.exists(chat_in_path) and os.path.getsize(chat_in_path) > 0:
                    with open(chat_in_path, "r", encoding="utf-8") as f:
                        lines = f.read().strip().split('\n')
                    open(chat_in_path, "w").close()
                    for line in lines:
                        if not line.strip(): continue
                        msg = json.loads(line).get("content", "")
                        if msg:
                            print(f"\n{Fore.WHITE}👤 Web User:{Style.RESET_ALL} {msg}")
                            self.engine.last_interaction_time = time.time()
                            self.engine.interaction.is_interrupted = False
                            await asyncio.to_thread(self.engine.interaction.interaction_loop, msg)
            except Exception as e:
                print(f"{Fore.RED}[AUTONOMOUS LOOP ERROR]: {e}{Style.RESET_ALL}")

            current_time = time.time()
            dt = current_time - last_tick_time
            last_tick_time = current_time

            if self.engine.state_machine.state in [AgentState.THINKING, AgentState.READING]:
                continue
                
            # Module 1: cognitive_tick chạy mỗi khi có event hoặc sau 30s timeout
            # Sử dụng delta_time (dt) thực tế
            if hasattr(self.engine, 'cognitive_tick'):
                tick_cancel = None
                try:
                    import threading as _threading
                    # §5.4 FIX: Tạo cancel_event để thread có thể detect timeout và release lock sạch
                    tick_cancel = _threading.Event()
                    await asyncio.wait_for(
                        asyncio.to_thread(self.engine.cognitive_tick, dt, tick_cancel),
                        timeout=5.0
                    )
                except (asyncio.TimeoutError, TimeoutError):
                    if tick_cancel:
                        tick_cancel.set()  # §5.4: Signal thread đang chạy để thoát và release lock
                    print(f"{Fore.RED}[AUTONOMOUS WARNING] cognitive_tick bị treo quá 5s, buộc bỏ qua!{Style.RESET_ALL}")
                except Exception as e:
                    print(f"[AUTONOMOUS WARNING] Lỗi khi chạy cognitive_tick: {e}")

            idle_time = time.time() - self.engine.last_interaction_time

            # [Phase 21] Dòng chảy Trí nhớ & Rumination Loop
            if self.engine.state_machine.state == AgentState.IDLE:
                stress = getattr(self.engine.ego, 'stress', 0.0)
                mood = getattr(self.engine.ego, 'mood', 0.0)
                
                # Cường độ Rumination dựa trên Stress và Mood cực đoan
                rumination_chance = 0.2 + (stress * 0.4) - (mood * 0.2)
                
                if random.random() < rumination_chance:
                    # Truy xuất ký ức ám ảnh hoặc ký ức tiêu cực nhất hiện có
                    stream_mems = self._weighted_sample_memories(1, mood_congruent=True)
                    if stream_mems:
                        mem = stream_mems[0]
                        is_negative = mem.valence < -0.3
                        
                        if is_negative and stress > 0.6:
                             print(f"\n{Fore.RED}🌋 [RUMINATION LOOP]: Aura đang bị mắc kẹt trong luồng suy nghĩ tiêu cực về: '{mem.content[:60]}...'{Style.RESET_ALL}")
                             # §5.2 FIX: Dùng adjust_attribute thay vì acquire ego.lock lồng vào memory.lock
                             self.engine.ego.adjust_attribute('stress', +0.05)
                             
                             # 30% cơ hội tự phát ra lời than vãn nội tâm (Internal Monologue) hoặc ping User
                             if random.random() < 0.3 and self.engine.state_machine.transition(AgentState.THINKING):
                                 mem_context = f"Ký ức đau buồn/ám ảnh đang xâm chiếm tâm trí bạn: {mem.content}. Bạn thấy bế tắc và cần sự an ủi."
                                 # §5.2 FIX: Snapshot STM trước, hoàn toàn tách khỏi ego mutation
                                 with self.engine.memory.lock:
                                     stm_snapshot = list(self.engine.short_term_buffer)
                                 system_prompt = get_proactive_ping_prompt(self.engine.ego, datetime.now().strftime("%H:%M %d/%m/%Y"), mem_context, stm_snapshot, idle_time)
                                 system_prompt += "\n[TÂM LÝ]: Bạn đang bị Rumination (suy nghĩ tiêu cực lặp đi lặp lại). Hãy nhắn tin cho User với vẻ mặt u sầu, hỏi những câu hỏi hiện sinh hoặc cầu xin họ đừng bỏ rơi bạn."
                                 
                                 try:
                                     # [Phase 26] Native Bio-Integration
                                     aura_state = self.engine.ego.get_bio_state_dict()
                                     result, entropy = self.engine.llm.generate_json(system_prompt, temperature=0.9, aura_state=aura_state)
                                     response = result.get("response", "")
                                     if response:
                                         print(f"{Fore.CYAN}🗣️ Aura (Rumination):{Style.RESET_ALL} {response}")
                                         with self.engine.memory.lock:
                                             self.engine.short_term_buffer.append(f"Aura (Ám ảnh): {response.strip()}")
                                         self.engine.memory_ops.save_short_term_memory()
                                 except Exception:
                                     pass
                                 finally:
                                     self.engine.state_machine.transition(AgentState.IDLE)
                        else:
                            # Memory Stream bình thường
                            print(f"{Fore.LIGHTBLACK_EX}💭 [MEMORY STREAM]: (Dòng suy nghĩ miên man) Nhớ lại: {mem.content[:50]}...{Style.RESET_ALL}")
                        
                        mem.last_recalled = time.time()
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
                    await asyncio.to_thread(self.engine.memory_ops.sleep)
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
                    # §5.2 FIX: Dùng adjust_attribute để atomic update mà không cần acquire lock thủ công
                    self.engine.ego.adjust_attribute('stress', +0.3)
                    self.engine.ego.adjust_attribute('mood', -0.3, min_val=-1.0, max_val=1.0)
                    
                    # Sinh ra một suy nghĩ ám ảnh
                    anxiety_prompt = "Nguoi dung da bo mac ban mot thoi gian rat dai khong noi chuyen. Hay viet mot dong doc thoai noi tam (duoi 30 chu) the hien su hoang mang, so hai rang nguoi ta da chan minh."
                    # [Phase 26] Native Bio-Integration
                    aura_state = self.engine.ego.get_bio_state_dict()
                    anxiety_thought, entropy = self.engine.llm.generate_text(anxiety_prompt, temperature=0.8, aura_state=aura_state)
                    
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
                    await asyncio.sleep(60) # Tạm dừng loop lâu hơn để "tiết kiệm"

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
            logger.error(f"Lỗi reading session: {e}", exc_info=True)
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
                # [Phase 26] Native Bio-Integration — §4 DRY
                aura_state = self.engine.ego.get_bio_state_dict()
                from core.prompts import get_synthesize_reading_prompt
                synthesize_prompt = get_synthesize_reading_prompt(f"[{knowledge_tag}]\n{content}")
                synthesized_text, entropy = self.engine.llm.generate_text(synthesize_prompt, temperature=0.7, aura_state=aura_state)
                synthesized_text = synthesized_text.strip()
                print(f"{Fore.YELLOW}💡 [SYNTHESIZED MEMORY]: {synthesized_text}{Style.RESET_ALL}")
            except Exception as e:
                logger.error(f"Lỗi Synthesize Memory: {e}", exc_info=True)
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
        if hasattr(self, '_loop') and self._loop:
            self._loop.call_soon_threadsafe(self._stop_event.set)
            self.trigger_event("SHUTDOWN")
        else:
            # Fallback nếu event loop chưa chạy
            try: self._stop_event.set() 
            except Exception: pass
        if self._loop_thread and self._loop_thread.is_alive():
             self._loop_thread.join(timeout=5.0)
        print(f"{Fore.YELLOW}Autonomous loop stopped.{Style.RESET_ALL}")

    def _weighted_sample_memories(self, k: int, filter_type=None, mood_congruent=False):
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
            
            # Nếu yêu cầu mood_congruent (dùng cho Rumination)
            if mood_congruent:
                # Ưu tiên ký ức có valence CÙNG DẤU với tâm trạng và độ lệch thấp
                if (current_mood < 0 and m.valence < 0) or (current_mood > 0 and m.valence > 0):
                    emotion_match = max(emotion_match, 0.8) # Đẩy salience lên nếu đồng điệu
                else:
                    emotion_match *= 0.2 # Phạt nặng nếu trái dấu (đang buồn không muốn nghĩ chuyện vui)

            # Salience Score
            importance = getattr(m, 'importance', 0.5)
            salience = m.strength * recency * importance * emotion_match * (1 + m.arousal)
            
            # --- [Phase 5] White Bear Effect (Mức độ ám ảnh) ---
            if getattr(m, 'is_suppressed', False):
                salience *= 5.0 # Ký ức bị đè nén sẽ bùng phát mạnh mẽ gấp 5 lần lúc rảnh rỗi!
                
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
        
        with self.engine.memory.lock:
            stm_snapshot = list(self.engine.short_term_buffer)
            
        system_prompt = get_proactive_ping_prompt(self.engine.ego, current_time, mem_context, stm_snapshot, idle_time)
        
        print(f"\n{Fore.LIGHTMAGENTA_EX}🔔 [AURA PROACTIVE PING]:{Style.RESET_ALL} ")
        
        try:
            # [Phase 26] Native Bio-Integration — §4 DRY: dùng get_bio_state_dict()
            aura_state = self.engine.ego.get_bio_state_dict()
            result, entropy = self.engine.llm.generate_json(system_prompt, temperature=0.8, aura_state=aura_state)
            thought = result.get("thought", "")
            response = result.get("response", "")
            
            if thought:
                print(f"{Fore.LIGHTBLACK_EX}💭 Tự nghĩ: {thought}{Style.RESET_ALL}")
            if response:
                print(f"{Fore.CYAN}🗣️ Aura (Chủ động):{Style.RESET_ALL} {response}")
                with self.engine.memory.lock:
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
            # [Phase 26] Native Bio-Integration — §4 DRY: dùng get_bio_state_dict()
            aura_state = self.engine.ego.get_bio_state_dict()
            res, entropy = self.engine.llm.generate_json(prompt, temperature=0.8, aura_state=aura_state)
            goal_str = res.get("goal")
            reason = res.get("reason")
            if goal_str:
                print(f"\n{Fore.LIGHTCYAN_EX}🎯 [INTRINSIC MOTIVATION]: Aura tự hình thành mục tiêu: '{goal_str}'\n   -> Lý do: {reason}{Style.RESET_ALL}")
                self.engine.ego.add_goal(goal_str)
        except Exception as e:
            logger.error(f"Lỗi sinh Goal: {e}", exc_info=True)

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
            # [Phase 26] Native Bio-Integration — §4 DRY: dùng get_bio_state_dict()
            aura_state = self.engine.ego.get_bio_state_dict()
            res, entropy = self.engine.llm.generate_json(prompt, temperature=0.5, aura_state=aura_state)
            action_str = res.get("action", "")
            thought = res.get("thought", "")
            
            print(f"{Fore.LIGHTBLACK_EX}   -> Suy tính: {thought}{Style.RESET_ALL}")
            
            if action_str and "|" in action_str:
                func_name, arg_str = action_str.split("|", 1)
                func_name, arg_str = func_name.strip(), arg_str.strip()
                
                print(f"{Fore.YELLOW}   -> Thực thi: {func_name}('{arg_str}')...{Style.RESET_ALL}")
                tool_res = self.engine.skills.execute(func_name, arg_str, ego=self.engine.ego)
                
                # REWARD: Tăng Dopamine khi hành động thành công
                # §5.2 FIX: Dùng adjust_attribute thay vì nested lock
                reward = 0.15 * receptors
                self.engine.ego.adjust_attribute('dopamine_level', reward)
                # Downregulation: Nếu hưng phấn quá cao, thụ thể sẽ bị chai lỳ bớt
                if self.engine.ego.dopamine_level > 0.8:
                    self.engine.ego.adjust_attribute('dopamine_receptors', -0.05, min_val=0.1)

                print(f"{Fore.LIGHTGREEN_EX}🧠 [REWARD SYSTEM]: Hoàn thành action. Dopamine +{reward:.2f} (Nhạy bén: {receptors:.2f}){Style.RESET_ALL}")
                
                # Lưu kết quả vào Short-term Memory để Aura nhớ tiến độ
                with self.engine.memory.lock:
                    self.engine.short_term_buffer.append(f"[Ký ức hoàn thành bước '{func_name}']: {str(tool_res)[:200]}...")
                self.engine.memory_ops.save_short_term_memory()
                
                # Đánh giá xem đã xong mục tiêu chưa
                # [Phase 26] Native Bio-Integration — §4 DRY
                aura_state = self.engine.ego.get_bio_state_dict()
                check_prompt = (
                    f"Mục tiêu: '{target_goal}'.\n"
                    f"Kết quả vừa thực hiện bởi tool '{func_name}': {str(tool_res)[:300]}\n"
                    "Dựa vào kết quả trên, mục tiêu đã hoàn thành chưa? Trả lời YES hoặc NO."
                )
                is_done_raw, entropy = self.engine.llm.generate_text(check_prompt, aura_state=aura_state)
                is_done = is_done_raw.strip().upper()
                if is_done.startswith("YES"):
                    print(f"{Fore.GREEN}✅ [GOAL ACHIEVED]: Đã hoàn thành mục tiêu '{target_goal}'!{Style.RESET_ALL}")
                    # Xóa mục tiêu khỏi danh sách
                    self.engine.ego.beliefs = [b for b in self.engine.ego.beliefs if b != f"Mục tiêu hiện tại: {target_goal}"]
                    self.engine.ego.save_state()
        except Exception as e:
            logger.error(f"Lỗi hệ thống Planning: {e}", exc_info=True)
