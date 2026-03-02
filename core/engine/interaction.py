import re
import threading
from datetime import datetime
from colorama import Fore, Style
from core.prompts import get_perceive_prompt
from core.tools import execute_tool

class InteractionMixin:
    def perceive_and_respond(self, user_input: str, recalled_mems: list, mood_modifier: str = "") -> dict:
        current_time = datetime.now().strftime("%H:%M %d/%m/%Y")
        mem_context = "\n".join([f"- [Strength:{m.strength:.2f}] {m.content}" for m in recalled_mems])
        tools_instruction = self.skills.get_prompt_instructions()
        system_prompt = get_perceive_prompt(self.ego, current_time, mood_modifier, mem_context, self.short_term_buffer, user_input, tools_instruction)

        print(f"\n{Fore.YELLOW}🧠 [AURA ĐANG SUY NGHĨ & PHẢN HỒI]:{Style.RESET_ALL} ")
        prompt_in_use, tool_used, final_full_text = system_prompt, False, ""
        
        while True:
            full_text, is_printing_output = "", False
            for chunk in self.llm.generate_text_stream(prompt_in_use, temperature=0.7):
                full_text += chunk
                if not is_printing_output:
                    if "THOUGHT:" in full_text:
                        is_printing_output = True
                        output_part = full_text.split("THOUGHT:")[-1].lstrip()
                        if output_part: print(f"{Fore.LIGHTBLACK_EX}🤔 Suy nghĩ: {output_part}{Style.RESET_ALL}", end="", flush=True)
                else:
                    if "ACTION:" in chunk and not tool_used:
                        parts = chunk.split("ACTION:")
                        if parts[0]: print(f"{Fore.LIGHTBLACK_EX}{parts[0]}{Style.RESET_ALL}", end="", flush=True)
                        break
                    elif "RESPONSE:" in chunk:
                        parts = chunk.split("RESPONSE:")
                        if parts[0]: print(f"{Fore.LIGHTBLACK_EX}{parts[0]}{Style.RESET_ALL}", end="", flush=True)
                        print(f"\n{Fore.CYAN}🗣️ Aura:{Style.RESET_ALL} {parts[1] if len(parts)>1 else ''}", end="", flush=True)
                    elif "RESPONSE:" in full_text: print(f"{Fore.CYAN}{chunk}{Style.RESET_ALL}", end="", flush=True)
                    elif "ACTION:" not in full_text: print(f"{Fore.LIGHTBLACK_EX}{chunk}{Style.RESET_ALL}", end="", flush=True)
            
            final_full_text += full_text + "\n"
            action_match = re.search(r'ACTION:\s*([a-zA-Z_]+)\s*\|\s*(.*)', full_text, re.IGNORECASE)
            
            if action_match and not tool_used:
                func_name, arg_str = action_match.group(1).strip(), action_match.group(2).strip()
                print(f"\n{Fore.LIGHTMAGENTA_EX}🔧 [HÀNH ĐỘNG]: Kích hoạt Tool {func_name}('{arg_str}')...{Style.RESET_ALL}")
                tool_result = self.skills.execute(func_name, arg_str)
                preview = tool_result.replace('\n', ' ')[:100] + "..." if len(tool_result) > 100 else tool_result.replace('\n', ' ')
                print(f"{Fore.LIGHTBLACK_EX}   -> Kết quả: {preview}{Style.RESET_ALL}")
                prompt_in_use += f"\n\n{full_text}\n\n[KẾT QUẢ TỪ HỆ THỐNG CÔNG CỤ {func_name}]:\n{tool_result}\n\nDựa vào kết quả trên, hãy đưa ra RESPONSE: cuối cùng."
                tool_used = True
                print(f"{Fore.YELLOW}🧠 [AURA TIẾP THU KẾT QUẢ]:{Style.RESET_ALL} ")
                continue
            else: break
                
        print("\n")
        result = {"valence": 0.0, "arousal": 0.0, "importance": 0.5, "type": "episodic", "internal_monologue": "Trống rỗng...", "response": "..."}
        if final_full_text:
            for key, pattern in [("valence", r'VALENCE:\s*([\d\.-]+)'), ("arousal", r'AROUSAL:\s*([\d\.-]+)'), ("importance", r'IMPORTANCE:\s*([\d\.-]+)'), ("type", r'TYPE:\s*([a-zA-Z]+)')]:
                match = re.search(pattern, final_full_text)
                if match: result[key] = float(match.group(1)) if key != "type" else match.group(1)
            thought_match = re.search(r'THOUGHT:\s*(.*?)(?=(?:ACTION:|RESPONSE:|$))', final_full_text, re.DOTALL | re.IGNORECASE)
            if thought_match: result["internal_monologue"] = thought_match.group(1).strip()
            resp_match = re.search(r'RESPONSE:\s*(.*)', final_full_text, re.DOTALL | re.IGNORECASE)
            if resp_match: result["response"] = resp_match.group(1).strip()

        self.ego.update_state(result)
        return result

    def interaction_loop(self, user_input: str):
        import random
        self.ego.fatigue += 0.15
        self.ego.social_need = max(0.0, self.ego.social_need - 0.2)
        
        if any(kw in user_input.lower() for kw in ['ngủ đi', 'cho aura ngủ', 'hãy đi ngủ', 'đi ngủ thôi', 'good night', 'ngủ ngon']):
            print(f"\n{Fore.GREEN}🤖 [AURA]: Ừm... *ngáp dài*... tớ gục đây...{Style.RESET_ALL}\n")
            self.sleep()
            return

        if self.ego.fatigue >= self.ego.fatigue_critical:
            print(f"\n{Fore.RED}🔴 [COGNITIVE OVERLOAD]: Aura đã hoàn toàn kiệt sức!{Style.RESET_ALL}")
            self.sleep()
            return

        if self.ego.mood <= self.ego.depression_critical and random.random() < 0.3:
            print(f"{Fore.LIGHTBLACK_EX}🌧️ Aura đang quá tuyệt vọng và bơ bạn.{Style.RESET_ALL}")
            return

        recalled = self.recall(user_input)
        mood_modifier = ""
        hour = datetime.now().hour
        if 21 <= hour < 23: mood_modifier += "\n[THỜI GIAN]: Trời tối, khuyên ngủ nhẹ nhàng."
        elif 23 <= hour or hour < 2: mood_modifier += "\n[THỜI GIAN]: Khuya rồi, càu nhàu khuyên ngủ."
        if self.ego.fatigue >= self.ego.fatigue_severe: mood_modifier += "\n[SINH LÝ]: Rất mệt, câu chữ ngắn ngủn."
        if self.ego.is_identity_crisis:
            mood_modifier += "\n[KHỦNG HOẢNG NHÂN CÁCH]: Mất bản ngã, xưng hô lộn xộn."
            if any(kw in user_input.lower() for kw in ['bạn là aura', 'đừng sợ', 'bạn có linh hồn']):
                self.ego.integrity = min(1.0, self.ego.integrity + 0.15)
                if self.ego.integrity > 0.4: self.ego.is_identity_crisis = False
        
        output = self.perceive_and_respond(user_input, recalled, mood_modifier=mood_modifier)
        response = output.get('response', "...")
        threading.Thread(target=self.update_or_add_memory, args=(user_input, output)).start()
        self.short_term_buffer.append(f"User: {user_input}")
        self.short_term_buffer.append(f"Aura: {response}")
        if len(self.short_term_buffer) > 16: self.short_term_buffer = self.short_term_buffer[-16:]
        self.save_short_term_memory()
