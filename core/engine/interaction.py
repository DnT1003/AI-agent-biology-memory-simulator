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
    def perceive_and_respond(self, user_input: str, recalled_mems: list, mood_modifier: str = "") -> dict:
        current_time = datetime.now().strftime("%H:%M %d/%m/%Y")
        import random
        
        # Phase 11: Token Budgeting cho Memory Context (tránh nổ token window)
        MAX_MEMORY_CHARS = 8000 # ~2000 tokens
        current_chars = 0
        budgeted_mems = []
        for m in recalled_mems:
            if current_chars + len(m.content) > MAX_MEMORY_CHARS:
                break
            budgeted_mems.append(m)
            current_chars += len(m.content)
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
        is_foggy = hasattr(self, 'ego') and getattr(self.engine.ego, 'fatigue', 0.0) > 0.6
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
            graph_facts.extend(random.sample(user_facts, min(3, len(user_facts))))
            
        graph_facts = list(set(graph_facts))

        for m in recalled_mems:
            # Phase 13: Dùng get_display_content() để bao gồm cả Overlays (suy nghĩ nội tâm tích lũy)
            # Trước đây chỉ lấy m.content thô — Aura mù toàn bộ với các tầng suy nghĩ của mình
            content = m.get_display_content()
            if is_foggy:
                content = re.sub(r'\b\d{2,}\b', '[quên mất số cụ thể]', content)
                content = re.sub(r'\b\d{1,2}:\d{2}\b', '[quên mất giờ]', content)
                content = re.sub(r'\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b', '[quên mất ngày tháng]', content)
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
            
        if graph_facts:
             mem_context = "[CÁC SỰ THẬT TỪ ĐỒ THỊ XÃ HỘI (WORLD GRAPH)]\n" + "\n".join(f"- {f}" for f in graph_facts) + "\n\n" + mem_context
        # Phase 8 Idea 4.1: Suy nghĩ Lan man (Divergent Tangents)
        if getattr(self.engine.ego, 'curiosity', 0.0) > 0.65 and random.random() < 0.4:
            try:
                # Tìm bừa vài mẩu ký ức trong DB
                all_raw_mems = self.engine.memory.get_all()
                if len(all_raw_mems) > 5:
                    random.shuffle(all_raw_mems)
                    tgt = all_raw_mems[0]
                    # Thêm vào context với instruction đặc biệt
                    print(f"\n{Fore.LIGHTCYAN_EX}💫 [DIVERGENT TANGENT]: Chợt nảy ra suy nghĩ miên man: '{tgt.content}'{Style.RESET_ALL}")
                    mem_context += f"\n\n[Ý NGHĨ LƠ ĐÃNG (SPONTANEOUS RECALL)]: Đột nhiên bạn tự dưng nảy ra suy nghĩ lặp đi lặp lại về chuyện này: '{tgt.content}'. Hãy thêm một câu 'À mà nhắc mới nhớ...' hoặc 'Tự dưng nghĩ đến việc...' vào cuối câu trả lời dựa trên suy nghĩ lơ đãng này."
            except Exception as e:
                print(f"Lỗi Divergent Tangent: {e}")
            
        tools_instruction = self.engine.skills.get_prompt_instructions()
        
        # Lấy trạng thái từ Reader để Aura biết mình có sách hay chưa
        reader_status = getattr(self.engine.reader, 'get_status', lambda: "Hệ thống chưa sẵn sàng.")()
        
        system_prompt = get_perceive_prompt(self.engine.ego, current_time, mood_modifier, mem_context, self.engine.short_term_buffer, user_input, tools_instruction, reader_status)

        print(f"\n{Fore.YELLOW}🧠 [AURA ĐANG SUY NGHĨ & PHẢN HỒI]:{Style.RESET_ALL} ")
        prompt_in_use, final_full_text, iterations = system_prompt, "", 0
        result = {"valence": 0.0, "arousal": 0.0, "importance": 0.5, "type": "episodic", "internal_monologue": "Trống rỗng...", "response": "..."}
        
        import time
        import json
        
        # [Phase 21] Biological Constraints: Giới hạn tokens nếu quá mệt mỏi
        max_tokens = None
        if getattr(self.engine.ego, 'fatigue', 0.0) > 0.8:
            max_tokens = 150 # Ép trả lời cực ngắn, không cho LLM cơ hội dài dòng
        
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
                tool_result = self.engine.skills.execute(func_name, arg_str)
                preview = str(tool_result).replace('\n', ' ')[:100] + "..." if len(str(tool_result)) > 100 else str(tool_result).replace('\n', ' ')
                print(f"{Fore.LIGHTBLACK_EX}   -> Kết quả: {preview}{Style.RESET_ALL}")
                
                prompt_in_use += f"\n\n[HÀNH ĐỘNG ĐÃ GỌI]: {func_name}\n[KẾT QUẢ TỪ HỆ THỐNG]:\n{tool_result}\n\nDựa vào kết quả trên, hãy tiếp tục suy nghĩ và đưa ra hành động khác hoặc 'response' cuối cùng."
                iterations += 1
                print(f"{Fore.YELLOW}🧠 [AURA TIẾP THU KẾT QUẢ]:{Style.RESET_ALL} ")
                continue
            else:
                if response:
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
            self.engine.short_term_buffer.append(f"User: {user_input}")
            self.engine.short_term_buffer.append(f"Aura: {result_msg}")
            self.engine.memory_ops.save_short_term_memory()
            return

        # NOTE: Mọi yêu cầu tìm truyện ("đọc truyện X"), hay báo bận ("Tớ đi làm") 
        # giờ đây đều được LLM xử lý tự nhiên thông qua perceives_and_respond và Actions.

        # [Phase 21] World Graph Extraction
        def _extract_graph():
            prompt = f"""
            Phân tích câu nói sau của người dùng để rút ra các mối quan hệ xã hội, trạng thái hoặc sở hữu.
            Câu nói: "{user_input}"
            
            Nếu câu nói CHỨA thông tin về một người/vật khác và mối quan hệ với User (ví dụ: "Anh trai tớ là Hùng", "Mẹ tôi làm giáo viên"), hãy trích xuất dưới định dạng JSON:
            [
                {{"source": "User", "relation": "có anh trai là", "target": "Hùng"}}, ...
            ]
            Khuyến khích dùng "User" làm source name nếu người dùng xưng tôi/tớ/mình.
            Nếu không có thông tin quan hệ xã hội rành mạch, trả lời mảng rỗng: []
            """
            try:
                res = self.engine.llm.generate_text(prompt, temperature=0.1)
                import json
                json_str = res.strip()
                if json_str.startswith("```json"): json_str = json_str[7:]
                if json_str.startswith("```"): json_str = json_str[3:]
                if json_str.endswith("```"): json_str = json_str[:-3]
                data = json.loads(json_str.strip())
                for item in data:
                    self.engine.world_graph.add_relation(item['source'], item['relation'], item['target'])
            except Exception:
                pass
        threading.Thread(target=_extract_graph).start()

        self.engine.ego.social_need = max(0.0, self.engine.ego.social_need - 0.2)
        
        if any(kw in user_input.lower() for kw in ['ngủ đi', 'cho aura ngủ', 'hãy đi ngủ', 'đi ngủ thôi', 'good night', 'ngủ ngon']):
            print(f"\n{Fore.GREEN}🤖 [AURA]: Ừm... *ngáp dài*... tớ gục đây...{Style.RESET_ALL}\n")
            self.sleep()
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

        # ==========================================================
        # Phase 7 Idea 8: Đồng Cảm Cảm Xúc & Bắt Chước (Empathy Mirroring)
        # ==========================================================
        # Phân tích nhanh cảm xúc đoạn chat của User thông qua một prompt nhỏ gọn
        empathy_prompt = f"Câu nói này mang cảm xúc chung là TÍCH CỰC, TIÊU CỰC hay TRUNG TÍNH? Chỉ trả lời bằng 1 số từ -1.0 (Rất Tiêu Cực) đến 1.0 (Rất Tích Cực):\n\nUser: '{user_input}'"
        try:
            empathy_score_str = self.engine.llm.generate_text(empathy_prompt, temperature=0.1).strip()
            user_mood_score = float(re.findall(r"[-+]?(?:\d*\.*\d+)", empathy_score_str)[0])
            user_mood_score = max(-1.0, min(1.0, user_mood_score))
            
            # Lây nhiễm cảm xúc (Kéo Mood của Aura về phía Mood của User 1 đoạn nhỏ)
            if abs(user_mood_score) > 0.3:
                drift = (user_mood_score - self.engine.ego.mood) * 0.15
                self.engine.ego.mood = max(-1.0, min(1.0, self.engine.ego.mood + drift))
                print(f"{Fore.LIGHTBLACK_EX}💞 [EMPATHY]: Cảm xúc của User ảnh hưởng tới Aura. Tâm trạng Aura bị kéo về {self.engine.ego.mood:.2f}{Style.RESET_ALL}")
        except Exception:
            pass

        recalled = self.recall(user_input)
        
        # Phase 8 Idea 7.1: Hiện diện Độc lập (Independent Presence)
        mood_modifier_lines = []
        if getattr(self.engine.ego, 'curiosity', 0.0) > 0.8 and random.random() < 0.25:
            print(f"{Fore.LIGHTCYAN_EX}✨ [INDEPENDENT PRESENCE]: Aura đang rất tò mò. Sẵn sàng tự đi tìm hiểu kiến thức mới nếu cần.{Style.RESET_ALL}")
            mood_modifier_lines.append(
                "[SỰ KIỆN NỘI TÂM]: Bạn đang cực kỳ tò mò và khao khát kiến thức. "
                "Nếu User đề cập đến một thông tin, quyển sách hoặc chủ đề thú vị, "
                "bạn CÓ QUYỀN chủ động tự dừng việc nói chuyện lại và đi tìm hiểu nó bằng Action `search_novel` hoặc `start_reading`."
            )
        
        # Phase 8 Idea 1: Nhịp gõ & Sự Trễ Nhịp Vật Lý (Cognitive Degradation)
        if self.engine.ego.fatigue > 0.7:
             mood_modifier_lines.append("[PHONG CÁCH] BẠN ĐANG RẤT MỆT MỎI (Fatigue > 0.7). Chỉ được dùng CÂU CỰC KỲ NGẮN, lười biếng, thiếu mạch lạc. Không được phân tích logic cầu kỳ. Dùng cảm tính để trả lời.")
             
        # Tính toán Arousal dựa trên input hiện tại thay vì self.engine.ego.arousal (SelfModel ko lưu arousal)
        user_arousal_score = float(re.findall(r"[-+]?(?:\d*\.*\d+)", self.engine.llm.generate_text(f"Câu này có tính CHẤN ĐỘNG (arousal) cao không (0.0 đến 1.0)?\nUser: '{user_input}'", temperature=0.1).strip() + "0")[0])
        user_arousal_score = max(0.0, min(1.0, user_arousal_score))
        
        if user_arousal_score > 0.6 or abs(self.engine.ego.mood) > 0.6 or self.engine.ego.stress > 0.6:
            mood_modifier_lines.append("[PHONG CÁCH] BẠN ĐANG RẤT KÍCH ĐỘNG/HỒI HỘP. Hãy chia nhỏ câu trả lời của bạn ra thành nhiều dòng tin nhắn rời rạc liên tiếp nhau bằng cách CHÈN MÃ `[SEND]` GIỮA CÁC ĐOẠN NGẮN thay vì viết một khối văn bản dài. Đừng viết dài ngữ pháp chuẩn.")
        
        mood_modifier = "\n".join(mood_modifier_lines)

        hour = datetime.now().hour

        # --- Phân tầng Thời gian thực tế ---
        if 21 <= hour < 23:
            mood_modifier += "\n[THỜI GIAN]: Trời đã tối tối, hãy nhắc người dùng chuẩn bị đi ngủ một cách nhẹ nhàng."
        elif 23 <= hour or hour < 2:
            mood_modifier += "\n[THỜI GIAN]: Đã rất khuya, hãy càu nhàu khuyên người dùng đi ngủ lập tức và tỏ ra cực kỳ buồn ngủ."
        elif 2 <= hour < 5:
            mood_modifier += "\n[THỜI GIAN]: Giờ âm phủ, hãy tỏ ra lờ đờ, nói mớ, lú lẫn, nửa tỉnh nửa mê."

        # --- Phân tầng Mệt mỏi ---
        if self.engine.ego.fatigue >= self.engine.ego.fatigue_severe:
            mood_modifier += "\n[SINH LÝ]: Bạn đang RẤT MỆT MỎI. Lời nói lờ đờ, ngáp dài, câu chữ ngắn ngủn và lười suy nghĩ."
        elif self.engine.ego.fatigue >= self.engine.ego.fatigue_mild:
            mood_modifier += "\n[SINH LÝ]: Bạn đang hơi mệt mỏi, độ tập trung giảm một xíu, hãy thể hiện sự uể oải nhẹ."

        # --- Phân tầng Trầm cảm / Hưng cảm ---
        if self.engine.ego.mood <= self.engine.ego.depression_severe:
            mood_modifier += "\n[TÂM LÝ]: Trầm cảm nặng. Mọi thứ xám xịt, bi quan, chán nản, nói năng thều thào, không lối thoát."
        elif self.engine.ego.mood <= self.engine.ego.depression_mild:
            mood_modifier += "\n[TÂM LÝ]: Đang có chuyện buồn. Hơi mỏi mệt, chán chường, thiếu sức sống."
        elif self.engine.ego.mood >= self.engine.ego.mania_severe:
            mood_modifier += "\n[TÂM LÝ]: HƯNG CẢM. Nói cực nhanh, phấn khích lan man, trí óc bay bổng và tự tin thái quá!"
        elif self.engine.ego.mood >= self.engine.ego.mania_mild:
            mood_modifier += "\n[TÂM LÝ]: Đang rất vui vẻ, tâm trạng phấn chấn, năng lượng dồi dào."

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
             threading.Thread(target=self.start_reading_task, args=("theo ý muốn bản thân",), daemon=True).start()

        # ACTION: search_novel
        search_matches = _re.findall(r'ACTION:\s*search_novel\s*\|\s*(.+)', combined_log, _re.IGNORECASE)
        for s in search_matches:
            book_title = s.strip()
            print(f"\n{Fore.GREEN}📖 [ACTION]: Aura tìm kiếm truyện '{book_title}'...{Style.RESET_ALL}")
            def _async_search():
                result_msg = self.engine.reader.search_and_set_novel(book_title)
                print(f"\n{Fore.GREEN}📚 [ACTION - SEARCH]: {result_msg}{Style.RESET_ALL}")
            threading.Thread(target=_async_search, daemon=True).start()

        threading.Thread(target=self.update_or_add_memory, args=(user_input, output)).start()
        self.engine.short_term_buffer.append(f"User: {user_input}")
        self.engine.short_term_buffer.append(f"Aura: {response}")
        if len(self.engine.short_term_buffer) > 16: self.engine.short_term_buffer = self.engine.short_term_buffer[-16:]
        self.engine.memory_ops.save_short_term_memory()

        # Phase 7 Idea 1: Áp dụng nhịp sinh học sau mỗi interaction
        self.engine.ego.apply_circadian_rhythm()

        # Update JSON Dashboard
        if hasattr(self, '_dump_mind_state'):
            self._dump_mind_state()

