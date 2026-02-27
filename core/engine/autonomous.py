import json
import time
import random
import re
from datetime import datetime
from colorama import Fore, Style

from core.memory import MemoryTrace

class AutonomousMixin:
    """
    Mixin xử lý các chức năng tự chủ (chạy ngầm) của nhân vật:
    Vòng lặp ngầm (background_loop), Ping chủ động, Mục tiêu tự tạo, Đọc sách ngầm.
    """
    
    def background_loop(self):
        # Ngủ 1 khoảng thời gian ban đầu để hệ thống load xong
        time.sleep(10)
        
        while True:
            time.sleep(30) # Cứ mỗi 30 giây kiểm tra một lần
            
            # PHASE 7 - IDEA 1: Áp dụng nhịp sinh học liên tục ở background
            self.ego.apply_circadian_rhythm()
            
            # Nếu đang bận xử lý input của user thì bỏ qua
            if self.is_thinking:
                continue
                
            idle_time = time.time() - self.last_interaction_time
            
            # Tự động buồn chán và muốn nói chuyện nếu nhàn rỗi
            if idle_time > 60: # Giả lập 1 phút ngoài đời = khoảng thời gian dài trong game
                self.ego.social_need = min(1.0, self.ego.social_need + 0.05)
                self.ego.curiosity = min(1.0, self.ego.curiosity + 0.02)
                
            # Random chance to ping the user proactively
            # Chờ từ 3 đến 7 phút (180s - 420s) mới có khả năng ping
            if not hasattr(self, 'next_ping_target'):
                self.next_ping_target = random.uniform(180, 420)
                
            if idle_time > self.next_ping_target and not self.is_thinking:
                ping_chance = 0.0
                if self.ego.social_need > 0.8:
                    ping_chance += 0.3
                elif self.ego.social_need > 0.5:
                    ping_chance += 0.1
                    
                if self.ego.curiosity > 0.8:
                    ping_chance += 0.2
                    
                if random.random() < ping_chance:
                    # Bắt đầu tự lấy suy nghĩ hiện tại
                    self.is_thinking = True
                    try:
                        self._proactive_ping(idle_time)
                    except Exception as e:
                        print(f"Lỗi background ping: {e}")
                    finally:
                        self.is_thinking = False
                        # Reset lại một chút nhu cầu xã hội để không spam liên tục
                        self.ego.social_need = max(0.0, self.ego.social_need - 0.3)
                        self.last_interaction_time = time.time() # Xem như vừa tương tác
                        self.next_ping_target = random.uniform(180, 420) # Random lại thời gian chờ cho lần sau

            # HỆ THỐNG ĐỌC SÁCH THẨM THẤU (PHASE 5)
            # User Feedback: Chỉ khi im lặng quá 30 phút (1800 giây) thì Aura mới tự động mở truyện ra đọc, 
            # tránh việc tự động rải spam liên tục.
            if idle_time > 1800 and not self.is_thinking:
                read_chance = 0.0
                if self.ego.curiosity > 0.5: read_chance += 0.2
                if self.ego.social_need < 0.4: read_chance += 0.2
                read_chance += 0.1 # Base chance
                
                if random.random() < read_chance:
                    self.is_thinking = True
                    try:
                        self._process_reading_chunk()
                    except Exception as e:
                        print(f"Lỗi đọc sách: {e}")
                    finally:
                        self.is_thinking = False
                        self.last_interaction_time = time.time()
                        continue
                        
            # GOAL ENGINE EXECUTION (PHASE 2)
            # Chạy khi rảnh ít nhất 2 phút, và mệt mỏi chưa quá cao
            if idle_time > 120 and self.ego.fatigue < self.ego.fatigue_mild and not self.is_thinking:
                active_goals = self.ego.get_active_goals()
                if active_goals and random.random() < 0.6: # 60% cơ hội tập trung làm việc
                    self.is_thinking = True
                    try:
                        self._process_goal_step(active_goals[0])
                    except Exception as e:
                        print(f"Lỗi thực thi Goal: {e}")
                    finally:
                        self.is_thinking = False
                        self.last_interaction_time = time.time()
                        continue
                elif not active_goals and self.ego.curiosity > 0.6 and random.random() < 0.3:
                    # Hệ thống tự tạo mục tiêu cho chính mình khi quá tò mò và đang không có việc gì làm
                    self.is_thinking = True
                    try:
                        self._generate_autonomous_goal()
                    except Exception as e:
                        print(f"Lỗi tự tạo Goal: {e}")
                    finally:
                        self.is_thinking = False
                        self.last_interaction_time = time.time()
                        continue
                        
    def _process_goal_step(self, goal: dict):
        print(f"\n{Fore.GREEN}🎯 [GOAL ENGINE]: Bắt đầu tiến hành 1 bước cho Mục tiêu: '{goal['title']}'{Style.RESET_ALL} ")
        
        # Nhắc lại mục tiêu cho LLM và bối cảnh
        prompt = f"""
        MỤC TIÊU DÀI HẠN HIỆN TẠI CỦA BẠN: {goal['title']}
        Tiến độ hiện tại: {goal['progress']}/10.

        Bạn đang có thời gian rảnh. Bạn quyết định âm thầm làm việc cho mục tiêu này.
        Nếu cần thiết, bạn HÃY GỌI TOOL để tra cứu kiến thức (ví dụ: web_search).
        Nếu bạn cảm thấy đã thu thập đủ điểm cho bước này, hãy TỰ DO sinh ra những suy nghĩ tóm tắt.

        HỆ THỐNG CÔNG CỤ (ACTION SYSTEM):
{self.skills.get_prompt_instructions()}

        OUTPUT FORMAT:
        THOUGHT: <suy nghĩ nội tâm khi thực thi mục tiêu>
        [ACTION: <lệnh gọi tool nếu cần>]
        [FACT: <kiến thức khách quan mới học được từ mục tiêu này nếu có>]
        """

        raw_res = self.llm.generate_text(prompt, temperature=0.7)
        
        # Execute tool if found
        action_match = re.search(r'ACTION:\s*([a-zA-Z_]+)\s*\|\s*(.*)', raw_res, re.IGNORECASE)
        if action_match:
            func_name = action_match.group(1).strip()
            arg_str = action_match.group(2).strip()
            print(f"{Fore.LIGHTMAGENTA_EX}   🔧 Tool Call: {func_name}('{arg_str}'){Style.RESET_ALL}")
            skill_obj = self.skills.skills.get(func_name)
            if skill_obj:
                fatigue_cost = 0.1 * (1.5 - skill_obj.mastery)
                self.ego.fatigue += fatigue_cost
                print(f"{Fore.LIGHTBLACK_EX}   -> [SKILL MASTERY]: Độ tinh thông {skill_obj.mastery:.2f} | Rỉ sét {skill_obj.rust_level:.2f} (Tốn {fatigue_cost:.2f} mệt mỏi){Style.RESET_ALL}")
            tool_res = self.skills.execute(func_name, arg_str)
            # Pass 2: Feed tool output back
            pass2_prompt = prompt + f"\n\n[KẾT QUẢ TỪ {func_name}]:\n{tool_res}\n\nHãy chốt lại 1 FACT (nếu có) và quá trình."
            raw_res = self.llm.generate_text(pass2_prompt, temperature=0.7)
        
        # Rút trích FACT (Ký ức ngữ nghĩa)
        fact_match = re.search(r'FACT:\s*(.*?)(?=(?:ACTION:|RESPONSE:|$))', raw_res, re.DOTALL | re.IGNORECASE)
        thought_match = re.search(r'THOUGHT:\s*(.*?)(?=(?:ACTION:|FACT:|RESPONSE:|$))', raw_res, re.DOTALL | re.IGNORECASE)
        
        thought = thought_match.group(1).strip() if thought_match else raw_res[:100] + "..."
        print(f"{Fore.LIGHTBLACK_EX}   🤔 Suy nghĩ: {thought}{Style.RESET_ALL}")
        
        extracted_fact = fact_match.group(1).strip() if fact_match else None
        
        if extracted_fact and len(extracted_fact) > 5:
            semantic_mem = MemoryTrace(
                content=f"Từ mục tiêu '{goal['title']}': {extracted_fact}",
                type='semantic',
                valence=0.0,
                arousal=0.0,
                importance=1.0, 
                is_flashbulb=True 
            )
            self.memory.add_memory(semantic_mem)
            print(f"{Fore.GREEN}   🧩 Kiến thức mới đã được ghi nhận.{Style.RESET_ALL}")
            
            # Tăng tiến độ
            goal['progress'] += random.randint(1, 3)
            
        else:
            # Dù không có FACT thì ít nhất cũng tư duy 1 xíu
            goal['progress'] += 1
            
        if goal['progress'] >= 10:
            goal['status'] = 'completed'
            print(f"{Fore.LIGHTYELLOW_EX}   🏆 Mục tiêu '{goal['title']}' đã hoàn tất!{Style.RESET_ALL}")
            
        self.ego.fatigue += 0.2  # Tốn năng lượng vì làm việc nghiêm túc
        self.memory.enforce_garbage_collection()

    def _generate_autonomous_goal(self):
        print(f"\n{Fore.LIGHTMAGENTA_EX}🧠 [AURA TỰ CHỦ]: Đang rảnh rỗi và tò mò, Aura tự suy nghĩ ra một chủ đề để nghiên cứu...{Style.RESET_ALL} ")
        
        # Get some semantic/core context to inspire the goal
        all_mems = self.memory.get_all()
        semantic_mems = [m for m in all_mems if m.type in ['semantic', 'core']]
        context_mems = random.sample(semantic_mems, min(5, len(semantic_mems)))
        context_str = "\n".join([f"- {m.content}" for m in context_mems]) if context_mems else "Chưa có nhiều kiến thức."
        
        prompt = f"""
        BẠN LÀ: {self.ego.name}. 
        MỨC ĐỘ TÒ MÒ CỦA BẠN RẤT CAO: {self.ego.curiosity:.2f}.
        
        TÍNH CÁCH VÀ NIỀM TIN CỦA BẠN:
        {json.dumps(self.ego.get_active_beliefs(), ensure_ascii=False)}
        
        MỘT VÀI KIẾN THỨC BẠN ĐANG CÓ HOẶC VỪA BIẾT:
        {context_str}
        
        Bạn hiện đang không có mục tiêu làm việc nào dài hạn. 
        Dựa vào Tính cách, Sở thích và Những kiến thức trên, hãy TỰ NGHĨ RA 1 mục tiêu dài hạn để nghiên cứu và tìm hiểu sâu (Ví dụ: "Tìm hiểu sâu hơn về [Một thông tin trong bộ nhớ]", "Học cách làm [Kỹ năng phù hợp với tính cách]"). Đừng chọn những chủ đề nhàm chán nếu nó không hợp với bạn.
        
        OUTPUT FORMAT (Chỉ trả về chuỗi JSON hợp lệ):
        {{
            "thought": "<Lý do nội tâm vì sao bạn lại tò mò chủ đề này lúc này>",
            "goal_title": "<Tên mục tiêu ngắn gọn>"
        }}
        """
        raw_res = self.llm.generate_text(prompt, temperature=0.9)
        try:
            json_str = raw_res.strip()
            if json_str.startswith("```json"): json_str = json_str[7:]
            if json_str.startswith("```"): json_str = json_str[3:]
            if json_str.endswith("```"): json_str = json_str[:-3]
            data = json.loads(json_str.strip())
            
            goal_title = data.get("goal_title", "")
            thought = data.get("thought", "")
            
            if goal_title:
                print(f"{Fore.LIGHTBLACK_EX}   🤔 Tự nghĩ: {thought}{Style.RESET_ALL}")
                self.ego.add_goal(goal_title)
                self.ego.curiosity -= 0.2 # Thỏa mãn tò mò một chút khi tìm ra việc để làm
                print(f"{Fore.GREEN}   ✅ Aura đã tự giao cho mình mục tiêu mới: '{goal_title}'! Chờ rảnh rỗi sẽ thực thi.{Style.RESET_ALL}")
                
        except Exception as e:
            print(f"{Fore.RED}   ⚠️ Lỗi khi LLM tự tạo Goal: Không parse được JSON. {e}{Style.RESET_ALL}")

    def _process_reading_chunk(self):
        title, content = self.reader.get_next_reading_material()
        if not content: return
        
        print(f"\n{Fore.GREEN}📖 [AURA ĐANG ĐỌC SÁCH]: {title}{Style.RESET_ALL} ")
        
        prompt = f"""
        Bạn vừa đọc xong nội dung sau:
        {title}
        
        Nội dung:
        {content}
        
        Nhiệm vụ:
        1. Tạo một bản tóm tắt RẤT NGẮN GỌN (tổng quát, không đi vào chi tiết) để lưu làm kiến thức.
        2. Tự đánh giá mức độ kích thích/bất ngờ (Arousal) của đoạn này từ 0.0 đến 1.0. Đoạn nào có twist, bất ngờ, hay gây cấn thì cho điểm cao.
        3. Chọn ra MỘT CÂU/CHI TIẾT ấn tượng nhất (nếu có, không có thì để rỗng).
        
        Xuất ra chuẩn định dạng JSON:
        {{
            "summary": "<tóm tắt tổng quát khoảng 2 câu>",
            "interesting_detail": "<1 chi tiết ấn tượng nhất>",
            "arousal": <float>,
            "valence": <float>
        }}
        """
        
        raw_res = self.llm.generate_text(prompt, temperature=0.7)
        try:
            json_str = raw_res.strip()
            if json_str.startswith("```json"): json_str = json_str[7:]
            if json_str.startswith("```"): json_str = json_str[3:]
            if json_str.endswith("```"): json_str = json_str[:-3]
            data = json.loads(json_str.strip())
            
            summary = data.get("summary", "")
            detail = data.get("interesting_detail", "")
            arousal = float(data.get("arousal", 0.0))
            valence = float(data.get("valence", 0.0))
            
            # Xử lý sinh học
            if arousal > 0.6: 
                self.ego.curiosity = min(1.0, self.ego.curiosity + 0.1)
                
            if self.ego.curiosity > 0.6:
                self.ego.fatigue += 0.05 # Lấn át mệt mỏi
                print(f"{Fore.LIGHTBLACK_EX}   -> 👀 Truyện quá cuốn! Aura tĩnh tâm cày truyện (Curiosity: {self.ego.curiosity:.2f}, Mệt mỏi tăng cực ít: 0.05){Style.RESET_ALL}")
            else:
                self.ego.fatigue += 0.15 # Đọc sách mệt mỏi bình thường
                print(f"{Fore.LIGHTBLACK_EX}   -> 🥱 Lờ đờ đọc sách... (Mệt mỏi tăng lên: 0.15){Style.RESET_ALL}")
                
            # Tạo Memory
            mem_content = f"Kiến thức từ '{title}': {summary}"
            is_flashbulb = False
            
            # Nếu thật sự cực kỳ tò mò và ấn tượng, Aura sẽ ghi nhớ tiểu tiết forever
            if arousal > 0.8 and detail:
                mem_content += f" | Chi tiết ấn tượng khó phai phai: {detail}"
                is_flashbulb = True
                print(f"{Fore.LIGHTMAGENTA_EX}   -> ⚡ Đoạn này quá ấn tượng! Khắc sâu vào trí nhớ (Flashbulb).{Style.RESET_ALL}")
                
            mem = MemoryTrace(
                content=mem_content,
                type='book_knowledge',
                valence=valence,
                arousal=arousal,
                importance=0.6 if not is_flashbulb else 1.0,
                is_flashbulb=is_flashbulb
            )
            self.memory.add_memory(mem)
            self.memory.store.update_meta(mem.id, mem)
            
        except Exception as e:
            print(f"{Fore.RED}⚠️ Lỗi parse JSON khi thu hoạch kiến thức sách: {e}{Style.RESET_ALL}")
            
    def _proactive_ping(self, idle_time):
        current_time = datetime.now().strftime("%H:%M %d/%m/%Y")
        
        # Nhớ lại một cách ngẫu nhiên các sự kiện
        mems = self.memory.get_all()
        mem_context = ""
        if mems:
            random_mems = random.sample(mems, min(3, len(mems)))
            mem_context = "\n".join([f"- [Strength:{m.strength:.2f}] {m.content}" for m in random_mems])
            
        from core.prompts import get_proactive_ping_prompt
        system_prompt = get_proactive_ping_prompt(self.ego, current_time, mem_context, self.short_term_buffer, idle_time)
        
        print(f"\n{Fore.LIGHTMAGENTA_EX}🔔 [AURA PROACTIVE PING]:{Style.RESET_ALL} ")
        full_text = ""
        is_printing_output = False
        
        for chunk in self.llm.generate_text_stream(system_prompt, temperature=0.8):
            full_text += chunk
            if not is_printing_output:
                if "THOUGHT:" in full_text:
                    is_printing_output = True
                    output_part = full_text.split("THOUGHT:")[-1].lstrip()
                    if output_part:
                        print(f"{Fore.LIGHTBLACK_EX}💭 Tự nghĩ: {output_part}{Style.RESET_ALL}", end="", flush=True)
            else:
                if "RESPONSE:" in chunk:
                    parts = chunk.split("RESPONSE:")
                    if parts[0]:
                        print(f"{Fore.LIGHTBLACK_EX}{parts[0]}{Style.RESET_ALL}", end="", flush=True)
                    print(f"\n{Fore.CYAN}🗣️ Aura (Chủ động):{Style.RESET_ALL} {parts[1] if len(parts)>1 else ''}", end="", flush=True)
                elif "RESPONSE:" in full_text:
                    print(f"{Fore.CYAN}{chunk}{Style.RESET_ALL}", end="", flush=True)
                else:
                    print(f"{Fore.LIGHTBLACK_EX}{chunk}{Style.RESET_ALL}", end="", flush=True)
                
        print("\n")
        
        # Save to short term buffer
        resp_match = re.search(r'RESPONSE:\s*(.*)', full_text, re.DOTALL | re.IGNORECASE)
        if resp_match:
             response = resp_match.group(1).strip()
             self.short_term_buffer.append(f"Aura (Chủ động): {response}")
             self.save_short_term_memory()
