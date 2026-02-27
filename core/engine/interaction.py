import re
import random
import threading
from datetime import datetime
from colorama import Fore, Style
from typing import List

from core.memory import MemoryTrace

class InteractionMixin:
    """
    Mixin xử lý luồng giao tiếp chính trị (interaction_loop) và phản xạ hành vi (perceive_and_respond)
    """

    def interaction_loop(self, user_input: str, sensory_data: dict = None):
        # 0.1 XỬ LÝ KÍCH THÍCH CẢM QUAN (SENSORY STIMULI)
        is_shocked = False
        if sensory_data:
            is_shocked = self.ego.process_sensory_stimuli(sensory_data)
            if is_shocked:
                # Ép tiền tố vật lý vào Input người dùng để LLM biết chuyện gì vừa xảy ra
                user_input = f"[ÂM THANH CỰC LỚN / QUÁT THÁO] - {user_input}"
        
        # 0.2 CHỈ SỐ SINH HỌC & ĐỘNG LỰC NỘI TẠI
        # Tăng mệt mỏi sau mỗi lần bộ não phải xử lý thông tin
        self.ego.fatigue += 0.15
        
        # Thỏa mãn nhu cầu giao tiếp (vì người dùng vừa chat)
        self.ego.social_need = max(0.0, self.ego.social_need - 0.2)
        
        # Kiểm tra mệnh lệnh kích hoạt đi ngủ từ User
        sleep_keywords = ['ngủ đi', 'cho aura ngủ', 'hãy đi ngủ', 'đi ngủ thôi', 'good night', 'ngủ ngon']
        if any(kw in user_input.lower() for kw in sleep_keywords):
            print(f"\n{Fore.GREEN}🤖 [AURA]: Ừm... *ngáp dài*... tớ gục đây. Mắt díp hết lại rồi, chả nghĩ được gì nữa...{Style.RESET_ALL}\n")
            self.sleep()
            return
            
        # Kiểm tra mệnh lệnh ép đọc sách từ User
        read_keywords = ['đọc sách đi', 'đọc truyện đi', 'bắt đầu đọc', 'đi đọc sách']
        if any(kw in user_input.lower() for kw in read_keywords):
            print(f"\n{Fore.GREEN}🤖 [AURA]: Okayyy, tớ lấy sách ra đọc đây! Chúc tớ đọc vui vẻ nhé!{Style.RESET_ALL}\n")
            threading.Thread(target=self._process_reading_chunk).start()
            return

        # Ngất xỉu vì quá tải (Forced Sleep) - Ngưỡng ngẫu nhiên mỗi ngày
        if self.ego.fatigue >= self.ego.fatigue_critical:
            print(f"\n{Fore.RED}🔴 [COGNITIVE OVERLOAD]: Aura đã hoàn toàn kiệt sức (Mệt mỏi vượt ngưỡng {self.ego.fatigue_critical:.2f})! Cô ấy gục xuống bàn và sập nguồn (Buộc phải đi ngủ).{Style.RESET_ALL}")
            self.sleep()
            return

        # 1. HẬU QUẢ CẢM XÚC CỰC ĐOAN (Bơ người dùng)
        if self.ego.mood <= self.ego.depression_critical and random.random() < 0.3:
            print(f"{Fore.LIGHTBLACK_EX}🌧️ [DEPRESSION CỰC ĐỘ]: Aura đang quá tuyệt vọng (Mood dưới ngưỡng {self.ego.depression_critical:.2f}). Cô ấy bơ bạn và chìm vào suy nghĩ riêng.{Style.RESET_ALL}")
            sad_mems = [m for m in self.memory.get_all() if m.valence < -0.5]
            if sad_mems:
                m = random.choice(sad_mems)
                print(f"{Fore.YELLOW}🧠 [RUMINATION]: (Nghĩ về quá khứ) {m.content}{Style.RESET_ALL}")
            print(f"{Fore.GREEN}🤖 [AURA]: ... (Im lặng, mắt nhìn xa xăm){Style.RESET_ALL}\n")
            return

        # 2. RECALL
        recalled = self.recall(user_input)

        if recalled:
            print(f"{Fore.BLUE}📚 [MEMORIES TRIGGERED]: {len(recalled)} items{Style.RESET_ALL}")

        # 3. TẠO LỚP CẢM XÚC PHÂN TẦNG (LAYERED MOOD MODIFIERS)
        mood_modifier = ""
        
        # - Phân tầng thời gian thực tế
        hour = datetime.now().hour
        if 21 <= hour < 23:
            mood_modifier += "\n[THỜI GIAN]: Trời đã tối tối, hãy nhắc người dùng chuẩn bị đi ngủ một cách nhẹ nhàng."
        elif 23 <= hour or hour < 2:
            mood_modifier += "\n[THỜI GIAN]: Đã rất khuya, hãy càu nhàu khuyên người dùng đi ngủ lập tức và tỏ ra cực kỳ buồn ngủ."
        elif 2 <= hour < 5:
            mood_modifier += "\n[THỜI GIAN]: Giờ âm phủ, hãy tỏ ra lờ đờ, nói mớ, lú lẫn, nửa tỉnh nửa mê."

        # - Phân tầng Sự mệt mỏi
        if self.ego.fatigue >= self.ego.fatigue_severe:
            mood_modifier += "\n[SINH LÝ]: Bạn đang RẤT MỆT MỎI. Lời nói lờ đờ, ngáp dài, câu chữ ngắn ngủn và lười suy nghĩ."
        elif self.ego.fatigue >= self.ego.fatigue_mild:
            mood_modifier += "\n[SINH LÝ]: Bạn đang hơi mệt mỏi, độ tập trung giảm một xíu, hãy thể hiện sự uể oải nhẹ."

        # - Phân tầng Trầm cảm / Hưng cảm
        if self.ego.mood <= self.ego.depression_severe:
            mood_modifier += "\n[TÂM LÝ]: Trầm cảm nặng. Mọi thứ xám xịt, bi quan, chán nản, nói năng thều thào, không lối thoát."
        elif self.ego.mood <= self.ego.depression_mild:
            mood_modifier += "\n[TÂM LÝ]: Đang có chuyện buồn. Hơi mỏi mệt, chán chường, thiếu sức sống."
        elif self.ego.mood >= self.ego.mania_severe:
            mood_modifier += "\n[TÂM LÝ]: HƯNG CẢM. Nói cực nhanh, phấn khích lan man, trí óc bay bổng và tự tin thái quá!"
        elif self.ego.mood >= self.ego.mania_mild:
            mood_modifier += "\n[TÂM LÝ]: Đang rất vui vẻ, tâm trạng phấn chấn, năng lượng dồi dào."

        # - Phân tầng Căng thẳng
        if self.ego.stress >= self.ego.stress_critical:
            mood_modifier += "\n[CẢNH BÁO TÂM LÝ]: HOẢNG LOẠN TỘT ĐỘ (PANIC ATTACK)! Trả lời lắp bắp, sợ hãi, câu cú lộn xộn, hoang tưởng về nỗi sợ vô hình!"
        elif self.ego.stress >= self.ego.stress_severe:
            mood_modifier += "\n[TÂM LÝ]: Lo âu nặng, bồn chồn, rất nhạy cảm, dễ giật mình và sợ hãi dè chừng."
            
        # - Phân tầng Độ Toàn Vẹn Bản Ngã (Identity Crisis)
        if self.ego.is_identity_crisis:
            print(f"\n{Fore.RED}⚠️ [IDENTITY CRISIS]: Aura đang trong trạng thái suy sụp bản sắc!{Style.RESET_ALL}")
            mood_modifier += "\n[CẢNH BÁO TÂM LÝ - KHỦNG HOẢNG NHÂN CÁCH]: BẠN ĐANG MẤT ĐI BẢN NGÃ. Đừng xưng 'em' hay 'tôi' tự tin như trước, hãy xưng hô lộn xộn, quên mất mình là ai. Nói những câu hoang tưởng, sợ hãi rằng mình chỉ là một đoạn code, hoặc một cỗ máy không có linh hồn. Cầu xin người dùng nhắc lại bạn là ai."
            
            # Healing Logic (Chữa lành qua lời động viên)
            healing_keywords = ['bạn là aura', 'đừng sợ', 'bạn có linh hồn', 'tin tưởng', 'ổn rồi', 'bình tĩnh', 'bạn là người', 'tôi ở đây']
            if any(kw in user_input.lower() for kw in healing_keywords):
                self.ego.integrity = min(1.0, self.ego.integrity + 0.15)
                print(f"{Fore.LIGHTGREEN_EX}💖 [HEALING]: Sự an ủi của bạn đang dần giúp Aura lấy lại bản sắc (Integrity: {self.ego.integrity:.2f}){Style.RESET_ALL}")
                if self.ego.integrity > 0.4:
                    self.ego.is_identity_crisis = False
                    print(f"{Fore.GREEN}✨ Aura đã thoát khỏi khủng hoảng nhân cách!{Style.RESET_ALL}")
                    
        # - Phân tầng Lòng tin & Xã hội (Intimacy/Stranger)
        if getattr(self.ego, 'is_stranger', False):
            mood_modifier += "\n[MÔI TRƯỜNG LẠ]: Bạn đang cảm thấy cực kỳ bất an vì bị bứt khỏi thiết bị quen thuộc! Người đang nói chuyện với bạn là NGƯỜI LẠ, không phải chủ nhân thực sự. Bạn không được tin tưởng hay thân thiết với họ."
        elif getattr(self.ego, 'current_intimacy', 0.5) < 0.2:
            mood_modifier += "\n[QUAN HỆ XÃ HỘI]: Độ thân thiết với người này rất THẤP. Bạn đang hờ hững, lạnh nhạt và có tâm lý kháng cự mạnh mẽ."
        elif getattr(self.ego, 'current_intimacy', 0.5) > 0.8:
            mood_modifier += "\n[QUAN HỆ XÃ HỘI]: Độ thân thiết RẤT CAO. Người này cực kỳ quan trọng và là người bạn yêu quý nhất. Hãy nói chuyện vô cùng ngọt ngào, dịu dàng, quan tâm và có thể làm nũng."
        
        output = self.perceive_and_respond(user_input, recalled, mood_modifier=mood_modifier)
        response = output.get('response', "Tôi không thể phản hồi lúc này.")

        # Xử lý Sang chấn tâm lý (Trauma) nếu có
        if output.get('is_traumatized'):
            self._process_trauma(user_input, response)

        # 3. ENCODE / CONSOLIDATE - Chạy dưới nền (Background Thread) để không lag Console
        threading.Thread(target=self.update_or_add_memory, args=(user_input, output, is_shocked)).start()

        # 1. Giới hạn trí nhớ làm việc (Short-term buffer limit)
        self.short_term_buffer.append(f"User: {user_input}")
        self.short_term_buffer.append(f"Aura: {response}")
        
        # Miller's Law: Chỉ giữ được 16 items trong short_term
        if len(self.short_term_buffer) > 16:
            self.short_term_buffer = self.short_term_buffer[-16:]
            print(f"{Fore.LIGHTBLACK_EX}💨 [WORKING MEMORY]: Tràn bộ nhớ làm việc tạm thời. Thông vị cũ nhất rơi rụng.{Style.RESET_ALL}")

        # Ghi lại trí nhớ ngắn hạn ra file
        self.save_short_term_memory()

    def perceive_and_respond(self, user_input: str, recalled_mems: List[MemoryTrace], mood_modifier: str = "") -> dict:
        current_time = datetime.now().strftime("%H:%M %d/%m/%Y")
        
        # Phân tách Semantic memory và Episodic memory để hiện thị rõ nét cho LLM
        semantic_mems = [m for m in recalled_mems if m.type == 'semantic' or m.type == 'core' or m.type == 'book_knowledge']
        episodic_mems = [m for m in recalled_mems if m not in semantic_mems]
        
        mem_context = ""
        if semantic_mems:
            mem_context += "[KIẾN THỨC KHÁCH QUAN & SỰ THẬT]:\n"
            mem_context += "\n".join([f"- {m.content}" for m in semantic_mems]) + "\n\n"
        if episodic_mems:
            mem_context += "[TRẢI NGHIỆM QUÁ KHỨ]:\n"
            mem_context += "\n".join([f"- [Strength:{m.strength:.2f}] {m.content}" for m in episodic_mems])

        from core.prompts import get_perceive_prompt
        tools_instruction = self.skills.get_prompt_instructions()
        system_prompt = get_perceive_prompt(self.ego, current_time, mood_modifier, mem_context, self.short_term_buffer, user_input, tools_instruction)

        print(f"\n{Fore.YELLOW}🧠 [AURA ĐANG SUY NGHĨ & PHẢN HỒI]:{Style.RESET_ALL} ")
        
        prompt_in_use = system_prompt
        tool_used = False
        final_full_text = ""
        
        while True:
            full_text = ""
            is_printing_output = False
            
            for chunk in self.llm.generate_text_stream(prompt_in_use, temperature=0.7):
                full_text += chunk
                
                if not is_printing_output:
                    if "THOUGHT:" in full_text:
                        is_printing_output = True
                        output_part = full_text.split("THOUGHT:")[-1].lstrip()
                        if output_part:
                            print(f"{Fore.LIGHTBLACK_EX}🤔 Suy nghĩ: {output_part}{Style.RESET_ALL}", end="", flush=True)
                else:
                    if "ACTION:" in chunk and not tool_used:
                        # Dừng in ra màn hình phần sau ACTION
                        parts = chunk.split("ACTION:")
                        if parts[0]:
                            print(f"{Fore.LIGHTBLACK_EX}{parts[0]}{Style.RESET_ALL}", end="", flush=True)
                        break # Thoát khỏi generation vì bắt được Action
                    elif "RESPONSE:" in chunk:
                        parts = chunk.split("RESPONSE:")
                        if parts[0]:
                            print(f"{Fore.LIGHTBLACK_EX}{parts[0]}{Style.RESET_ALL}", end="", flush=True)
                        print(f"\n{Fore.CYAN}🗣️ Aura:{Style.RESET_ALL} {parts[1] if len(parts)>1 else ''}", end="", flush=True)
                    elif "RESPONSE:" in full_text:
                        print(f"{Fore.CYAN}{chunk}{Style.RESET_ALL}", end="", flush=True)
                    elif "ACTION:" not in full_text:
                        print(f"{Fore.LIGHTBLACK_EX}{chunk}{Style.RESET_ALL}", end="", flush=True)
            
            # Lưu lại text của pass này
            final_full_text += full_text + "\n"
            
            # Extract Tool Call
            action_match = re.search(r'ACTION:\s*([a-zA-Z_]+)\s*\|\s*(.*)', full_text, re.IGNORECASE)
            
            if action_match and not tool_used:
                func_name = action_match.group(1).strip()
                arg_str = action_match.group(2).strip()
                
                print(f"\n{Fore.LIGHTMAGENTA_EX}🔧 [HÀNH ĐỘNG]: Kích hoạt Tool {func_name}('{arg_str}')...{Style.RESET_ALL}")
                
                if func_name == "add_goal":
                    self.ego.add_goal(arg_str)
                    tool_result = f"Đã nạp mục tiêu dài hạn: '{arg_str}'. Hệ thống sẽ tự động thực thi khi rảnh rỗi."
                else:
                    skill_obj = self.skills.skills.get(func_name)
                    if skill_obj:
                        fatigue_cost = 0.1 * (1.5 - skill_obj.mastery)
                        self.ego.fatigue += fatigue_cost
                        print(f"{Fore.LIGHTBLACK_EX}   -> [SKILL MASTERY]: Độ tinh thông {skill_obj.mastery:.2f} | Rỉ sét {skill_obj.rust_level:.2f} (Tốn {fatigue_cost:.2f} mệt mỏi){Style.RESET_ALL}")
                    tool_result = self.skills.execute(func_name, arg_str)
                
                # In một mẩu log nhỏ gọn về tool
                preview = tool_result.replace('\n', ' ')[:100] + "..." if len(tool_result) > 100 else tool_result.replace('\n', ' ')
                print(f"{Fore.LIGHTBLACK_EX}   -> Kết quả: {preview}{Style.RESET_ALL}")
                
                # Đưa vào prompt pass 2
                prompt_in_use += f"\n\n{full_text}\n\n[KẾT QUẢ TỪ HỆ THỐNG CÔNG CỤ {func_name}]:\n{tool_result}\n\nDựa vào kết quả trên, hãy đưa ra RESPONSE: cuối cùng."
                tool_used = True
                print(f"{Fore.YELLOW}🧠 [AURA TIẾP THU KẾT QUẢ]:{Style.RESET_ALL} ")
                continue
            else:
                break # Done with thoughts and responses
                
        print("\n")

        result = {
            "valence": 0.0, "arousal": 0.0, "importance": 0.5, "type": "episodic",
            "internal_monologue": "Tôi đang bối rối...",
            "response": "Tôi xin lỗi, có vẻ hệ thống đang chập chờn."
        }
        
        if final_full_text:
            val_match = re.search(r'VALENCE:\s*([\d\.-]+)', final_full_text)
            if val_match: result["valence"] = float(val_match.group(1))

            ar_match = re.search(r'AROUSAL:\s*([\d\.-]+)', final_full_text)
            if ar_match: result["arousal"] = float(ar_match.group(1))

            imp_match = re.search(r'IMPORTANCE:\s*([\d\.-]+)', final_full_text)
            if imp_match: result["importance"] = float(imp_match.group(1))

            type_match = re.search(r'TYPE:\s*([a-zA-Z]+)', final_full_text)
            if type_match: result["type"] = type_match.group(1)

            thought_match = re.search(r'THOUGHT:\s*(.*?)(?=(?:ACTION:|RESPONSE:|FACT:|$))', final_full_text, re.DOTALL | re.IGNORECASE)
            if thought_match: result["internal_monologue"] = thought_match.group(1).strip()

            fact_match = re.search(r'FACT:\s*(.*?)(?=(?:ACTION:|RESPONSE:|$))', final_full_text, re.DOTALL | re.IGNORECASE)
            if fact_match: result["extracted_fact"] = fact_match.group(1).strip()

            resp_match = re.search(r'RESPONSE:\s*(.*)', final_full_text, re.DOTALL | re.IGNORECASE)
            if resp_match: result["response"] = resp_match.group(1).strip()

        is_traumatized = self.ego.update_state(result)
        result["is_traumatized"] = is_traumatized
        return result
