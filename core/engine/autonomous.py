import time
import random
import re
from datetime import datetime
from colorama import Fore, Style
from core.prompts import get_proactive_ping_prompt

class AutonomousMixin:
    def background_loop(self):
        time.sleep(10)
        while True:
            time.sleep(30)
            if self.is_thinking: continue
            idle_time = time.time() - self.last_interaction_time
            if idle_time > 60:
                self.ego.social_need = min(1.0, self.ego.social_need + 0.05)
                self.ego.curiosity = min(1.0, self.ego.curiosity + 0.02)
            
            if idle_time > 60 and not self.is_thinking:
                ping_chance = 0.3 if self.ego.social_need > 0.8 else (0.1 if self.ego.social_need > 0.5 else 0.0)
                if self.ego.curiosity > 0.8: ping_chance += 0.2
                if random.random() < ping_chance:
                    self.is_thinking = True
                    try: self._proactive_ping(idle_time)
                    except Exception as e: print(f"Lỗi background ping: {e}")
                    finally:
                        self.is_thinking, self.ego.social_need = False, max(0.0, self.ego.social_need - 0.3)
                        self.last_interaction_time = time.time()
                        
    def _proactive_ping(self, idle_time):
        current_time = datetime.now().strftime("%H:%M %d/%m/%Y")
        mems = self.memory.get_all()
        mem_context = "\n".join([f"- [Strength:{m.strength:.2f}] {m.content}" for m in random.sample(mems, min(3, len(mems)))]) if mems else ""
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
