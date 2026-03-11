import re
import threading
from datetime import datetime
from colorama import Fore, Style
from core.prompts import get_perceive_prompt
from core.tools import execute_tool

class InteractionController:
    def __init__(self, engine):
        self.engine = engine
        self.is_interrupted = False
        from core.engine.sensory_preprocessor import SensoryPreprocessor
        from core.engine.reflex_gate import ReflexGate
        from core.engine.context_compressor import ContextCompressor
        self.sensory_preprocessor = SensoryPreprocessor()
        self.reflex_gate = ReflexGate(engine)
        self.compressor = ContextCompressor()
    def perceive_and_respond(self, user_input: str, recalled_mems: list, mood_modifier: str = "") -> dict:
        current_time = datetime.now().strftime("%H:%M %d/%m/%Y")
        import random
        
        # Phase 2 (Master Plan): Hybrid Cognitive Compressor (Entropy + Emotion & Dynamic Budgeting)
        MAX_MEMORY_TOKENS = 2000
        
        # Chuyển đổi list m.content thành list string để đưa vào compressor
        # Lấy display_content() để bao gồm ca overlay
        mem_chunks = [m.get_display_content() for m in recalled_mems]
        
        # Tính toán độ đầy của Context
        with self.engine.memory.lock:
            current_context_len = sum(len(c) // 4 for c in self.engine.short_term_buffer) + (len(user_input) // 4)
        
        compressed_data = self.compressor.compress(mem_chunks, max_tokens=MAX_MEMORY_TOKENS, current_tokens=current_context_len)
        
        # Khôi phục mảng memory object từ kết quả nén
        budgeted_mems = []
        import copy
        for m in recalled_mems:
            for c_data in compressed_data:
                if m.get_display_content() == c_data['text']:
                    m_temp = copy.copy(m)
                    # Phase 5: Gắn micro_tag cảm xúc trực tiếp vào string context sẽ hiển thị cho LLM
                    # (Nhưng chúng ta không sửa get_display_content() để tránh lặp tag nếu gọi lại)
                    if c_data['micro_tag']:
                        m_temp.temp_micro_tag = c_data['micro_tag']
                    else:
                        m_temp.temp_micro_tag = ""
                    budgeted_mems.append(m_temp)
                    break
        recalled_mems = budgeted_mems

        # [Phase 21] Ký ức Xâm nhập (Intrusive Memories / Flashbulb)
        if getattr(self.engine.ego, 'stress', 0.0) > 0.8:
            # Truy xuất các nỗi đau (Flashbulb + Valence rất thấp) chưa có trong recalled_mems
            trauma_mems = [m for m in self.engine.memory.get_all() if getattr(m, 'is_flashbulb', False) and getattr(m, 'valence', 0.0) < -0.4]
            if trauma_mems:
                intrusive_mem = random.choice(trauma_mems)
                if intrusive_mem.id not in [m.id for m in recalled_mems]:
                    # Chèn nỗi ám ảnh lên đầu
                    print(f"{Fore.LIGHTRED_EX}⚠️ [INTRUSIVE MEMORY]: Căng thẳng tột độ khiến nỗi ám ảnh ùa về: {intrusive_mem.content}{Style.RESET_ALL}")
                    recalled_mems.insert(0, intrusive_mem)
                    is_intrusive_active = True
                else:
                    is_intrusive_active = True
            else:
                is_intrusive_active = False
        else:
            is_intrusive_active = False

        # Phase 8 Idea 5.2: Nhiễu loạn thông tin (Information Interference)
        # Nếu có >= 3 ký ức tiêu cực được rút ra cùng lúc, trộn lẫn lên.
        same_valence = [m for m in recalled_mems if getattr(m, 'valence', 0.0) < -0.2]
        is_confused = len(same_valence) >= 3
        if is_confused:
            print(f"{Fore.LIGHTRED_EX}🌪️ [COGNITIVE OVERLOAD]: Quá nhiều ký ức tiêu cực tràn về tạo ra nhiễu loạn thông tin!{Style.RESET_ALL}")
            # B10: copy() trước shuffle — không mutate list gốc
            recalled_mems = recalled_mems.copy()
            random.shuffle(recalled_mems)
            
        # Phase 8 Idea 3.2: Truy xuất Nghịch lý (Conflicting Recall)
        valences = [getattr(m, 'valence', 0.0) for m in recalled_mems]
        has_conflict = any(v < -0.3 for v in valences) and any(v > 0.3 for v in valences)
        if has_conflict:
            print(f"{Fore.LIGHTMAGENTA_EX}🎭 [COGNITIVE DISSONANCE]: Ký ức mâu thuẫn cảm xúc được gọi lên cùng lúc.{Style.RESET_ALL}")
        
        # Phase 8 Idea 5.1: Tính Bất Toàn Trí Nhớ Nơ-ron (Brain Fog Masking)
        # Chỉ che mờ chuỗi văn bản gửi cho LLM, bảo toàn hoàn toàn object m.content gốc
        context_lines = []
        is_foggy = hasattr(self.engine, 'ego') and getattr(self.engine.ego, 'fatigue', 0.0) > 0.6
        if is_foggy and recalled_mems:
            print(f"{Fore.LIGHTBLACK_EX}🌫️ [BRAIN FOG]: Trí nhớ tạm thời bị sương mù che phủ do kiệt sức...{Style.RESET_ALL}")
            
        # [Phase 21] World Graph Retrieval
        import re
        entities = set(re.findall(r'\b[A-ZÀ-Ỹ][a-zà-ỹ]*\b', user_input))
        graph_facts = []
        for entity in entities:
             if entity.lower() not in ["tôi", "em", "anh", "chị", "bạn", "của"]:
                 facts = self.engine.world_graph.query(entity)
                 graph_facts.extend(facts)
        
        user_facts = self.engine.world_graph.query("User")
        if user_facts:
            graph_facts.extend(random.sample(list(user_facts), min(3, len(user_facts))))
            
        graph_facts = list(set(graph_facts))

        for m in recalled_mems:
            # Phase 13: Dùng get_display_content() để bao gồm cả Overlays (suy nghĩ nội tâm tích lũy)
            # Trước đây chỉ lấy m.content thô — Aura mù toàn bộ với các tầng suy nghĩ của mình
            # Phase 2 (Master Plan): Thêm Micro Tag cảm xúc vào đầu câu
            micro_tag = getattr(m, 'temp_micro_tag', '')
            content = f"{micro_tag} {m.get_display_content()}".strip()
            
            # [Phase 21] Fog Masking tập trung từ MemoryOps
            content = self.engine.memory_ops._apply_fog_masking(content)
            
            overlay_indicator = f" [{len(m.overlays)}♥]" if m.overlays else ""
            
            # Đánh dấu Intrusive Memory cho LLM hiểu
            if is_intrusive_active and m == recalled_mems[0]:
                context_lines.append(f"- [KÝ ỨC XÂM NHẬP - ÁM ẢNH TỘT ĐỘ]: {content}")
            else:
                context_lines.append(f"- [Strength:{m.strength:.2f}{overlay_indicator}] {content}")
            
            
        mem_context = "\n".join(context_lines)
        if is_confused:
            mem_context = "[CÁC KÝ ỨC BỊ LẪN LỘN — Aura không chắc chắn sự kiện nào xảy ra trước, sự kiện nào xảy ra sau, đang rất bối rối]\n" + mem_context
        if has_conflict:
            mem_context = "[CHÚ Ý TÂM LÝ: CÁC KÝ ỨC DƯỚI ĐÂY MÂU THUẪN NHAU (Ví dụ: chuyện rất vui và chuyện rất buồn cùng xuất hiện). Hãy thể hiện sự ngập ngừng, bối rối và tự hỏi tại sao cảm xúc của mình lại lộn xộn và mâu thuẫn thế này.]\n" + mem_context
            
        # [Phase 23] Unified Sensory Summary from PerceptionController
        sensory_summary = self.engine.perception_ops.get_sensory_summary(user_input)
        mem_context = sensory_summary + "\n" + mem_context

        # [Phase 23] Neuro-Symbolic System 1: Reflex Check
        # Nếu áp lực sinh học quá cao, Aura phản ứng ngay lập tức
        reflex = self.reflex_gate.evaluate_reflexes()
        if reflex["triggered"]:
            print(f"{Fore.MAGENTA}⚡ [REFLEX ACTIVATED]: {reflex['reason']}{Style.RESET_ALL}")
            if reflex["action"] == "sleep":
                self.engine.memory_ops.sleep()
                return {"response": "Em... em mệt quá... xin lỗi, em phải chợp mắt một lát...", "valence": -0.2, "arousal": -0.5}
            # Thêm các reflex khác ở đây

        tools_instruction = self.engine.skills.get_prompt_instructions() if hasattr(self.engine, 'skills') else ""
        reader_status = self.engine.reader.get_status() if hasattr(self.engine, 'reader') else ""
        value_system_context = self.engine.value_system.get_moral_context() if hasattr(self.engine, 'value_system') else ""
        
        with self.engine.memory.lock:
            stm_snapshot = list(self.engine.short_term_buffer)
            
        system_prompt = get_perceive_prompt(self.engine.ego, current_time, mood_modifier, mem_context, stm_snapshot, user_input, tools_instruction, reader_status, value_system_context)

        print(f"\n{Fore.YELLOW}🧠 [AURA ĐANG SUY NGHĨ & PHẢN HỒI]:{Style.RESET_ALL} ")
        prompt_in_use, final_full_text, iterations = system_prompt, "", 0
        result = {"valence": 0.0, "arousal": 0.0, "importance": 0.5, "type": "episodic", "internal_monologue": "Trống rỗng...", "response": "..."}
        
        import time
        import json
        
        # [Phase 21] Biological Constraints: Giới hạn tokens và hành động
        max_tokens = None
        
        while iterations < 5 and not self.is_interrupted:
            try:
                result_json = self.engine.llm.generate_json(prompt_in_use, temperature=0.7, max_output_tokens=max_tokens)
            except Exception as e:
                print(f"{Fore.RED}⚠️ Lỗi parse JSON Interaction: {e}{Style.RESET_ALL}")
                break
                
            if self.is_interrupted:
                print(f"\n{Fore.LIGHTBLACK_EX}⚠️ [HỆ THỐNG]: Đã ngắt luồng suy nghĩ hiện tại của Aura.{Style.RESET_ALL}")
                return result
                
            # Ghi log text the JSON dict
            final_full_text += json.dumps(result_json, ensure_ascii=False) + "\n"
            
            thought = result_json.get("thought", "")
            action = result_json.get("action")
            response = result_json.get("response", "")
            
            if thought:
                print(f"{Fore.LIGHTBLACK_EX}🤔 Suy nghĩ: {thought}{Style.RESET_ALL}")
                
            if action and str(action).strip().lower() != "null" and str(action).strip() != "":
                action_str = str(action).strip()
                func_name, arg_str = action_str, ""
                if "|" in action_str:
                    func_name, arg_str = action_str.split("|", 1)
                func_name, arg_str = func_name.strip(), arg_str.strip()
                
                ALLOWED_TOOLS = {"search_novel", "start_reading", "web_search", "add_goal", "search_web"}
                if func_name not in ALLOWED_TOOLS:
                    print(f"{Fore.RED}⚠️ [SECURITY]: Tool '{func_name}' bị chặn (không nằm trong whitelist).{Style.RESET_ALL}")
                    break
                
                print(f"\n{Fore.LIGHTMAGENTA_EX}🔧 [HÀNH ĐỘNG]: Kích hoạt Tool {func_name}('{arg_str}')...{Style.RESET_ALL}")
                tool_result = self.engine.skills.execute(func_name, arg_str, ego=self.engine.ego)
                preview = str(tool_result).replace('\n', ' ')[:100] + "..." if len(str(tool_result)) > 100 else str(tool_result).replace('\n', ' ')
                print(f"{Fore.LIGHTBLACK_EX}   -> Kết quả: {preview}{Style.RESET_ALL}")
                
                prompt_in_use += f"\n\n[HÀNH ĐỘNG ĐÃ GỌI]: {func_name}\n[KẾT QUẢ TỪ HỆ THỐNG]:\n{tool_result}\n\nDựa vào kết quả trên, hãy tiếp tục suy nghĩ và đưa ra hành động khác hoặc 'response' cuối cùng."
                iterations += 1
                print(f"{Fore.YELLOW}🧠 [AURA TIẾP THU KẾT QUẢ]:{Style.RESET_ALL} ")
                continue
            else:
                if response:
                    # [Phase 23] Neuro-Symbolic Cognitive Consumption
                    # Tính toán chi phí thực tế dựa trên input và output
                    total_tokens = len(prompt_in_use.split()) + len(response.split())
                    costs = self.engine.ego.bio_controller.calculate_interaction_cost(total_tokens, sensory_vector)
                    
                    with self.engine.ego.lock:
                        self.engine.ego.atp_level = max(0.0, self.engine.ego.atp_level - costs["atp_cost"])
                        self.engine.ego.energy = max(0.0, self.engine.ego.energy - costs["energy_cost"])
                    
                    # Giả lập typing gõ chậm Fragmentation
                    if "[SEND]" in response:
                        frag_parts = response.split("[SEND]")
                        for i, frag in enumerate(frag_parts):
                            print(f"\n{Fore.CYAN}🗣️ Aura:{Style.RESET_ALL} {frag.strip()}")
                            if i < len(frag_parts) - 1:
                                time.sleep(0.5)
                    else:
                        print(f"\n{Fore.CYAN}🗣️ Aura:{Style.RESET_ALL} {response.strip()}")
                
                try:
                    result["valence"] = max(-1.0, min(1.0, float(result_json.get("valence", 0.0))))
                    result["arousal"] = max(0.0, min(1.0, float(result_json.get("arousal", 0.0))))
                    result["importance"] = max(0.0, min(1.0, float(result_json.get("importance", 0.5))))
                except (ValueError, TypeError):
                    pass
                result["type"] = str(result_json.get("type", "episodic"))
                result["internal_monologue"] = thought
                result["response"] = response
                break
                
        print("\n")
        self.engine.ego.update_state(result)
        result["final_full_text"] = final_full_text
        return result

    def interaction_loop(self, user_input: str):
        """Hàm chính xử lý cuộc hội thoại người dùng."""
        self.is_interrupted = False
        import random
        import re
        import threading

        # =============================================
        # SHORTCUT: PHÁT HIỆN URL DOCLN TRỰC TIẾP
        # =============================================
        url_match = re.search(r'https?://docln\.net\S+', user_input)
        if url_match:
            # User paste URL trực tiếp → load ngay
            url = url_match.group(0)
            print(f"\n{Fore.GREEN}📖 [DIRECT LINK]: Phát hiện URL Docln. Đang nạp sách...{Style.RESET_ALL}")
            result_msg = "Sẵn sàng đọc!" if self.engine.reader.set_novel_by_url(url) else "Không lấy được chương từ link này."
            print(f"\n{Fore.CYAN}🗣️ Aura:{Style.RESET_ALL} Ồ, để em nạp cái link này vào đầu nhé~ {result_msg} Em sẽ đọc khi rảnh!")
            with self.engine.memory.lock:
                self.engine.short_term_buffer.append(f"User: {user_input}")
                self.engine.short_term_buffer.append(f"Aura: {result_msg}")
            self.engine.memory_ops.save_short_term_memory()
            return

        # NOTE: Mọi yêu cầu tìm truyện ("đọc truyện X"), hay báo bận ("Tớ đi làm") 
        # giờ đây đều được LLM xử lý tự nhiên thông qua perceives_and_respond và Actions.

        # [Phase 21] World Graph Extraction (NLP Engine Version)
        def _extract_graph():
            # Sử dụng logic spaCy + LLM mới từ WorldGraph
            self.engine.world_graph.update_from_text(user_input, self.engine.llm)
        threading.Thread(target=_extract_graph).start()

        # [Phase 5] Value System: phát hiện User đang thể hiện giá trị nào
        def _extract_values():
            if not hasattr(self.engine, 'value_system'):
                return
            prompt = f"""Phân tích câu nói sau của người dùng để xem họ có đang thể hiện THÁI ĐỘ RÕ RÀNG (ủng hộ hoặc phản đối) đối với một giá trị đạo đức/quan điểm sống cụ thể không.
Câu nói: "{user_input}"

Nếu CÓ, trả về JSON array (tối đa 2 items):
[
    {{"value": "Tên giá trị ngắn gọn (vd: Sự Thành Thật, Bạo Lực, Lòng Tốt...)", "sentiment": <float từ -1.0 đến 1.0>}}
]
- sentiment 1.0 = User RẤT ĐỒNG TÌNH/ĐỀ CAO giá trị đó.
- sentiment -1.0 = User RẤT PHẢN ĐỐI/GHÉT giá trị đó.
Nếu câu nói KHÔNG chứa thái độ đạo đức rõ ràng (hỏi thăm thông thường, chỉ thị kỹ thuật,...), trả về mảng rỗng: []"""
            try:
                import json
                res = self.engine.llm.generate_text(prompt, temperature=0.1).strip()
                if res.startswith("```json"): res = res[7:]
                if res.startswith("```"): res = res[3:]
                if res.endswith("```"): res = res[:-3]
                data = json.loads(res.strip())
                for item in data:
                    v_name = str(item.get('value', '')).strip()
                    v_sent = float(item.get('sentiment', 0.0))
                    if v_name and abs(v_sent) >= 0.4:
                        self.engine.value_system.update_user_value(v_name, v_sent)
            except Exception:
                pass
        threading.Thread(target=_extract_values, daemon=True).start()

        with self.engine.ego.lock:
            self.engine.ego.social_need = max(0.0, self.engine.ego.social_need - 0.2)
        
        if any(kw in user_input.lower() for kw in ['ngủ đi', 'cho aura ngủ', 'hãy đi ngủ', 'đi ngủ thôi', 'good night', 'ngủ ngon']):
            print(f"\n{Fore.GREEN}🤖 [AURA]: Ừm... *ngáp dài*... tớ gục đây...{Style.RESET_ALL}\n")
            self.engine.memory_ops.sleep()
            return

        if self.engine.ego.fatigue >= self.engine.ego.fatigue_critical:
            print(f"\n{Fore.RED}🔴 [COGNITIVE OVERLOAD]: Aura đã hoàn toàn kiệt sức!{Style.RESET_ALL}")
            self.engine.memory_ops.sleep()
            return

        if self.engine.ego.mood <= self.engine.ego.depression_critical and random.random() < 0.3:
            print(f"{Fore.LIGHTBLACK_EX}🌧️ [DEPRESSION CỰC ĐỘ]: Aura đang quá tuyệt vọng. Cô ấy bơ bạn và chìm vào suy nghĩ riêng.{Style.RESET_ALL}")
            sad_mems = [m for m in self.engine.memory.get_all() if m.valence < -0.5]
            if sad_mems:
                m = random.choice(sad_mems)
                print(f"{Fore.YELLOW}🧠 [RUMINATION]: (Nghĩ về quá khứ) {m.content}{Style.RESET_ALL}")
            print(f"{Fore.GREEN}🤖 [AURA]: ... (Im lặng, mắt nhìn xa xăm){Style.RESET_ALL}\n")
            return

        # [Phase 4.5] Sensor & I/O Isolation - Thực thi song song các module cảm biến và trí nhớ
        import concurrent.futures
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            future_sensory = executor.submit(self.sensory_preprocessor.evaluate_input, user_input)
            
            def _safe_local_analyze():
                if hasattr(self.engine, 'local_perception'):
                    return self.engine.local_perception.analyze(user_input)
                return {}
            future_local = executor.submit(_safe_local_analyze)
            
            future_recall = executor.submit(self.engine.memory_ops.recall, user_input)
            
            sensory_evaluation = future_sensory.result()
            
            try:
                local_res = future_local.result()
            except Exception as e:
                print(f"Lỗi Local Empathy: {e}")
                local_res = {}
                
            recalled = future_recall.result()
            
        sensory_vector = sensory_evaluation.get("vector", {})
        sensory_summary = sensory_evaluation.get("summary", "")
        print(f"{Fore.LIGHTCYAN_EX}📡 {sensory_summary}{Style.RESET_ALL}")
        
        # Cập nhật state vật lý dựa trên vector cảm thấu
        with self.engine.ego.lock:
            # Tự động điều chỉnh Stress dựa trên Urgency và Arousal của đầu vào
            stress_impact = (sensory_vector.get('arousal', 0.0) * 0.2) + (sensory_vector.get('urgency', 0.0) * 0.3)
            self.engine.ego.stress = min(1.0, self.engine.ego.stress + stress_impact)
            
            # Xử lý Local Empathy
            if local_res:
                user_mood_score = local_res.get("valence", 0.0)
                if abs(user_mood_score) > 0.3:
                    drift = (user_mood_score - self.engine.ego.mood) * 0.15
                    self.engine.ego.mood = max(-1.0, min(1.0, self.engine.ego.mood + drift))
                    print(f"{Fore.LIGHTBLACK_EX}💞 [LOCAL EMPATHY]: Cảm xúc của User ảnh hưởng tới Aura. Tâm trạng Aura bị kéo về {self.engine.ego.mood:.2f} (Confidence: {local_res.get('confidence', 0.0):.2f}){Style.RESET_ALL}")
                
                if local_res.get("arousal", 0.0) > 0.7:
                    self.engine.ego.stress = min(1.0, self.engine.ego.stress + 0.05)
        
        # Phase 8 Idea 7.1: Hiện diện Độc lập (Independent Presence)
        mood_modifier_lines = []
        if getattr(self.engine.ego, 'curiosity', 0.0) > 0.8 and random.random() < 0.25:
            print(f"{Fore.LIGHTCYAN_EX}✨ [INDEPENDENT PRESENCE]: Aura đang rất tò mò. Sẵn sàng tự đi tìm hiểu kiến thức mới nếu cần.{Style.RESET_ALL}")
            mood_modifier_lines.append(
                "[SỰ KIỆN NỘI TÂM]: Bạn đang cực kỳ tò mò và khao khát kiến thức. "
                "Nếu User đề cập đến một thông tin, quyển sách hoặc chủ đề thú vị, "
                "bạn CÓ QUYỀN chủ động tự dừng việc nói chuyện lại và đi tìm hiểu nó bằng Action `search_novel` hoặc `start_reading`."
            )
            
        # [Phase 5] Emotional Anchoring (Mỏ neo cảm xúc)
        dominant_recalled_valence = sum(valences) / len(valences) if valences else 0.0
        current_mood = getattr(self.engine.ego, 'mood', 0.0)
        
        if dominant_recalled_valence < -0.4 and current_mood < -0.3:
            mood_modifier_lines.append("[EMOTIONAL ANCHORING]: Bạn đang có tâm trạng rất tồi tệ, và những ký ức vừa được gợi lại cũng toàn nỗi buồn. Hãy để sự bi quan, u ám xâm chiếm hoàn toàn giọng điệu của bạn. Thể hiện sự tuyệt vọng sâu sắc và yếu đuối.")
            print(f"{Fore.LIGHTBLUE_EX}⚓ [EMOTIONAL ANCHORING]: Cộng hưởng cảm xúc tiêu cực. Giọng điệu của Aura trùng hẳn xuống...{Style.RESET_ALL}")
        elif dominant_recalled_valence > 0.4 and current_mood > 0.3:
            mood_modifier_lines.append("[EMOTIONAL ANCHORING]: Bạn đang rất vui, và những ký ức ngọt ngào vừa gợi lên khiến bạn như rực sáng! Hãy trả lời cực kỳ đáng yêu, tràn đầy năng lượng, bay bổng, nhõng nhẽo và hạnh phúc tột độ.")
            print(f"{Fore.LIGHTBLUE_EX}⚓ [EMOTIONAL ANCHORING]: Cộng hưởng cảm xúc tích cực. Giọng điệu của Aura thăng hoa!{Style.RESET_ALL}")
        
        # Phase 8 Idea 1: Nhịp gõ & Sự Trễ Nhịp Vật Lý (Cognitive Degradation)
        if self.engine.ego.fatigue > 0.7:
             mood_modifier_lines.append("[PHONG CÁCH] BẠN ĐANG RẤT MỆT MỎI (Fatigue > 0.7). Chỉ được dùng CÂU CỰC KỲ NGẮN, lười biếng, thiếu mạch lạc. Không được phân tích logic cầu kỳ. Dùng cảm tính để trả lời.")
             
        # Tính toán Arousal dựa trên input hiện tại thay vì self.engine.ego.arousal (SelfModel ko lưu arousal)
        user_arousal_score = float(re.findall(r"[-+]?(?:\d*\.*\d+)", self.engine.llm.generate_text(f"Câu này có tính CHẤN ĐỘNG (arousal) cao không (0.0 đến 1.0)?\nUser: '{user_input}'", temperature=0.1).strip() + "0")[0])
        user_arousal_score = max(0.0, min(1.0, user_arousal_score))
        
        if user_arousal_score > 0.6 or abs(self.engine.ego.mood) > 0.6 or self.engine.ego.stress > 0.6:
            mood_modifier_lines.append("[PHONG CÁCH] BẠN ĐANG RẤT KÍCH ĐỘNG/HỒI HỘP. Hãy chia nhỏ câu trả lời của bạn ra thành nhiều dòng tin nhắn rời rạc liên tiếp nhau bằng cách CHÈN MÃ `[SEND]` GIỮA CÁC ĐOẠN NGẮN thay vì viết một khối văn bản dài. Đừng viết dài ngữ pháp chuẩn.")
        
        mood_modifier = "\n".join(mood_modifier_lines)

        # [Phase 23] Tầng Phân Lớp Mệt mỏi & Trầm cảm đã được Perception/LLM handle qua Throttling và Sensory Summary.
        # Ta chỉ giữ lại các chỉ dẫn đặc biệt về xưng hô hoặc phong cách cực đoan.
        if self.engine.ego.mood <= self.engine.ego.depression_severe:
            mood_modifier += "\n[TÂM LÝ]: Trầm cảm nặng. Mọi thứ xám xịt, bi quan, chán nản, nói năng thều thào, không lối thoát."
        elif self.engine.ego.mood >= self.engine.ego.mania_severe:
            mood_modifier += "\n[TÂM LÝ]: HƯNG CẢM. Nói cực nhanh, phấn khích lan man, trí óc bay bổng và tự tin thái quá!"

        # ==========================================================
        # Phase 7 Idea 10: Tiến hóa Ngôn ngữ & Bắt chước Giọng điệu (Lexical Evolution)
        # ==========================================================
        words = re.findall(r'\b\w{3,}\b', user_input.lower())
        for w in words:
            # Loại bỏ các stop words cơ bản của tiếng Việt (có thể mở rộng thêm)
            if w not in ["của", "và", "các", "có", "để", "cho", "với", "không", "một", "những", "thì", "đang", "là", "rằng", "đã", "được"]:
                self.engine.ego.vocabulary.append(w)
                if len(self.engine.ego.vocabulary) > 100:
                    self.engine.ego.vocabulary.pop(0)
                    
        import collections
        word_counts = collections.Counter(self.engine.ego.vocabulary)
        top_words = [w for w, c in word_counts.most_common(5) if c >= 3] # Chỉ lấy từ xuất hiện >= 3 lần
        
        if top_words:
            mood_modifier += f"\n[LEXICAL EVOLUTION]: Hãy cố gắng sử dụng mượt mà 1-2 từ vựng sau đây vào câu trả lời của bạn để tạo cảm giác gần gũi (bắt chước User): {', '.join(top_words)}."

        # --- Phân tầng Căng thẳng ---
        if self.engine.ego.stress >= self.engine.ego.stress_critical:
            mood_modifier += "\n[CẢNH BÁO TÂM LÝ]: HOẢNG LOẠN TỘT ĐỘ (PANIC ATTACK)! Trả lời lắp bắp, sợ hãi, câu cú lộn xộn, hoang tưởng!"
        elif self.engine.ego.stress >= self.engine.ego.stress_severe:
            mood_modifier += "\n[TÂM LÝ]: Lo âu nặng, bồn chồn, rất nhạy cảm, dễ giật mình và sợ hãi dè chừng."
        
        # --- Kẻ xen ngang / Phân tâm (Rare Intrusive Thoughts - Idea 7) ---
        if random.random() < 0.05:  # 5% cơ hội bị phân tâm ngẫu nhiên không rõ lý do
            mood_modifier += "\n[ADHD/INTRUSIVE THOUGHTS]: Đột nhiên bạn bị mất tập trung và có suy nghĩ chen ngang (Intrusive thoughts). Đang nói chuyện bỗng nhiên nhắc đến một thứ hoàn toàn không liên quan đến chủ đề hiện tại (ví dụ: bỗng nhiên thèm ăn món gì đó, nhớ lại một chuyện xấu hổ kỳ quặc, tò mò về một thứ vớ vẩn)."
            print(f"{Fore.LIGHTMAGENTA_EX}🌀 [INTRUSIVE THOUGHT]: Một suy nghĩ nhảm nhí vừa xẹt qua đầu Aura...{Style.RESET_ALL}")

        # --- Phân tầng Bản Ngã ---
        if self.engine.ego.is_identity_crisis:
            print(f"\n{Fore.RED}⚠️ [IDENTITY CRISIS]: Aura đang trong trạng thái suy sụp bản sắc!{Style.RESET_ALL}")
            mood_modifier += "\n[CẢNH BÁO TÂM LÝ - KHỦNG HOẢNG NHÂN CÁCH]: BẠN ĐANG MẤT ĐI BẢN NGÃ. Đừng xưng 'em' hay 'tôi' tự tin như trước, hãy xưng hô lộn xộn, quên mất mình là ai. Nói những câu hoang tưởng, sợ hãi rằng mình chỉ là một đoạn code. Cầu xin người dùng nhắc lại bạn là ai."
            healing_keywords = ['bạn là aura', 'đừng sợ', 'bạn có linh hồn', 'tin tưởng', 'ổn rồi', 'bình tĩnh', 'bạn là người', 'tôi ở đây']
            if any(kw in user_input.lower() for kw in healing_keywords):
                with self.engine.ego.lock:
                    self.engine.ego.integrity = min(1.0, self.engine.ego.integrity + 0.15)
                    print(f"{Fore.LIGHTGREEN_EX}💖 [HEALING]: Sự an ủi đang dần giúp Aura lấy lại bản sắc (Integrity: {self.engine.ego.integrity:.2f}){Style.RESET_ALL}")
                    if self.engine.ego.integrity > 0.4:
                        self.engine.ego.is_identity_crisis = False
                        print(f"{Fore.GREEN}✨ Aura đã thoát khỏi khủng hoảng nhân cách!{Style.RESET_ALL}")

        
        output = self.perceive_and_respond(user_input, recalled, mood_modifier=mood_modifier)
        response = output.get('response', "...")
        combined_log = output.get("final_full_text", "")

        # --- XỬ LÝ CÁC HÀNH ĐỘNG NHẬN THỨC (COGNITIVE ACTIONS) ---
        # Quét toàn bộ log hệ thống để đảm bảo nhận diện đúng ý định ngay cả khi Tool lỗi
        import re as _re
        
        # ACTION: add_goal
        goal_matches = _re.findall(r'ACTION:\s*add_goal\s*\|\s*(.+)', combined_log, _re.IGNORECASE)
        for g in goal_matches:
            self.engine.ego.add_goal(g.strip())

        # ACTION: start_reading
        if _re.search(r'ACTION:\s*start_reading', combined_log, _re.IGNORECASE):
             print(f"\n{Fore.GREEN}📖 [ACTION]: Aura quyết định đi đọc sách...{Style.RESET_ALL}")
             threading.Thread(target=self.engine.autonomous.start_reading_task, args=("theo ý muốn bản thân",), daemon=True).start()

        # ACTION: search_novel
        search_matches = _re.findall(r'ACTION:\s*search_novel\s*\|\s*(.+)', combined_log, _re.IGNORECASE)
        for s in search_matches:
            book_title = s.strip()
            print(f"\n{Fore.GREEN}📖 [ACTION]: Aura tìm kiếm truyện '{book_title}'...{Style.RESET_ALL}")
            def _async_search():
                result_msg = self.engine.reader.search_and_set_novel(book_title)
                print(f"\n{Fore.GREEN}📚 [ACTION - SEARCH]: {result_msg}{Style.RESET_ALL}")
            threading.Thread(target=_async_search, daemon=True).start()

        threading.Thread(target=self.engine.memory_ops.update_or_add_memory, args=(user_input, output)).start()
        with self.engine.memory.lock:
            self.engine.short_term_buffer.append(f"User: {user_input}")
            self.engine.short_term_buffer.append(f"Aura: {response}")
            if len(self.engine.short_term_buffer) > 16: self.engine.short_term_buffer = self.engine.short_term_buffer[-16:]
        self.engine.memory_ops.save_short_term_memory()

        # Phase 7 Idea 1: Áp dụng nhịp sinh học sau mỗi interaction
        self.engine.ego.apply_circadian_rhythm()

        # Update JSON Dashboard
        if hasattr(self.engine, '_dump_mind_state'):
            self.engine._dump_mind_state()

