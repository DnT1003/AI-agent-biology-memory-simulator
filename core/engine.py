import json
import os
import time
from typing import List
from colorama import Fore, Style

from config import Config
from components.llm import LLM
from components.embedder import Embedder
from core.memory import MemoryManager, MemoryTrace
from core.self_model import SelfModel

class CognitiveEngine:
    """Bộ xử lý nhận thức trung tâm"""
    def __init__(self):
        self.llm = LLM()
        self.embedder = Embedder()
        self.memory = MemoryManager(self.embedder)
        self.ego = SelfModel()
        self.short_term_buffer: List[str] = []
        self.stm_file_path = "outputs/short_term.json"
        self.last_interaction_time = time.time()
        self.is_thinking = False
        
        # Ensure outputs directory exists
        if not os.path.exists("outputs"):
            os.makedirs("outputs")
            
        self.load_short_term_memory()

    def load_short_term_memory(self):
        """Khôi phục bộ nhớ ngắn hạn từ ổ cứng nếu thời gian chưa trôi qua quá lâu (3 tiếng)"""
        if os.path.exists(self.stm_file_path):
            try:
                with open(self.stm_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    last_updated = data.get("timestamp", 0)
                    saved_buffer = data.get("buffer", [])
                    
                    # 3 tiếng = 3 * 3600 giây
                    if time.time() - last_updated < 3 * 3600:
                        self.short_term_buffer = saved_buffer
                        print(f"{Fore.LIGHTBLACK_EX}🔄 [WORKING MEMORY]: Phục hồi {len(self.short_term_buffer)} ký ức ngắn hạn từ phiên trước.{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.LIGHTBLACK_EX}🧹 [WORKING MEMORY]: Ký ức ngắn hạn đã quá hạn chặn 3 tiếng. Xóa sạch.{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}⚠️ Lỗi nạp bộ nhớ ngắn hạn: {e}{Style.RESET_ALL}")

    def save_short_term_memory(self):
        """Lưu đè mảng trí nhớ ngắn hạn xuống ổ cứng"""
        try:
            data = {
                "timestamp": time.time(),
                "buffer": self.short_term_buffer
            }
            with open(self.stm_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"{Fore.RED}⚠️ Lỗi lưu bộ nhớ ngắn hạn: {e}{Style.RESET_ALL}")

    def recall(self, query: str) -> List[MemoryTrace]:
        results = self.memory.search_memories(query, top_k=10) # Lấy danh sách lớn để filter

        candidates = []
        for score, m in results:
            if m.strength < 0.1: continue

            # Mood Congruency
            mood_bias = 0
            if self.ego.mood < -0.3 and m.valence < -0.2:
                mood_bias = 0.2

            # Salience = score * strength * (1 + arousal) + mood_bias
            final_score = score * m.strength * (1 + m.arousal) + mood_bias

            if final_score > 0.35:
                candidates.append((final_score, m))
                
        # 2b. Chronological Recall (Nhận thức thời gian)
        time_kws = ['hôm nay', 'hôm qua', 'vừa nãy', 'trước đó', 'mới đây', 'sáng nay', 'chiều nay', 'tối qua', 'gần đây', 'lúc nãy']
        is_chronological = any(kw in query.lower() for kw in time_kws)
        
        recent_mems = []
        if is_chronological:
            # Lấy 5 ký ức trong vòng 3 ngày qua
            import time
            current_time = time.time()
            try:
                chrono_results = self.memory.chronological_recall(current_time - 86400*3, current_time, limit=5)
                for m in chrono_results:
                    if m.strength >= 0.1 and m.id not in [c[1].id for c in candidates]:
                        recent_mems.append((1.0, m)) # Gán điểm ưu tiên cực cao
            except Exception as e:
                print(f"{Fore.RED}⚠️ Lỗi truy xuất thời gian: {e}{Style.RESET_ALL}")
                
        candidates.extend(recent_mems)
        candidates.sort(key=lambda x: x[0], reverse=True)
        recalled = [c[1] for c in candidates[:4]]
        
        # 3. Ký ức Liên tưởng theo Mạng lưới (Associative Chaining)
        chained_memory = None
        if recalled:
            # Lấy ký ức mạnh nhất vừa gọi lên làm mồi nhử để gọi thêm 1 ký ức liên quan
            anchor_memory = recalled[0]
            associative_results = self.memory.search_memories(anchor_memory.content, top_k=5)
            for _, am in associative_results:
                if am.id != anchor_memory.id and am.id not in [m.id for m in recalled] and am.strength > 0.4:
                    chained_memory = am
                    recalled.append(am)
                    break # Chỉ lấy thêm 1 chuỗi liên tưởng

        for m in recalled:
            # Nếu là ký ức bị gọi ké lên qua liên tưởng dây chuyền, hồi máu siêu ít
            is_associative = (chained_memory and m.id == chained_memory.id)
            m.reconsolidate(self.ego.mood, is_associative=is_associative)
            self.memory.store.update_meta(m.id, m)

        return recalled

    def apply_semantic_drift(self, memory: MemoryTrace):
        import random
        # 4. Flashbulb Memories không bao giờ bị méo mó
        if memory.is_flashbulb or memory.type == 'core' or memory.type == 'semantic':
            return
        
        # Bắt đầu méo mó nếu nhớ lại nhiều lần
        if memory.recall_count < 2:
            return
        
        # Tỉ lệ méo mó 
        if random.random() > Config.SEMANTIC_DRIFT_CHANCE:
            return

        from core.prompts import get_semantic_drift_prompt
        prompt = get_semantic_drift_prompt(memory.content)
        new_content = self.llm.generate_text(prompt, temperature=0.8)
        if new_content and len(new_content) > 10 and new_content != memory.content:
            print(f"{Fore.LIGHTRED_EX}🌀 [SEMANTIC DRIFT]: Ký ức méo mó theo thời gian:\n   - Cũ: {memory.content}\n   - Mới: {new_content}{Style.RESET_ALL}")
            memory.content = new_content
            # Cập nhật Vector sau khi text bị đổi
            vector = self.embedder.encode(new_content)
            self.memory.store.update_vector(memory.id, vector)
            # Cập nhật lại chuỗi JSON metadata mới xuống Database
            self.memory.update_memory(memory)

    def perceive_and_respond(self, user_input: str, recalled_mems: List[MemoryTrace], mood_modifier: str = "") -> dict:
        import re
        from datetime import datetime
        
        current_time = datetime.now().strftime("%H:%M %d/%m/%Y")
        mem_context = "\n".join([f"- [Strength:{m.strength:.2f}] {m.content}" for m in recalled_mems])

        from core.prompts import get_perceive_prompt
        system_prompt = get_perceive_prompt(self.ego, current_time, mood_modifier, mem_context, self.short_term_buffer, user_input)

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
                
                from core.tools import execute_tool
                print(f"\n{Fore.LIGHTMAGENTA_EX}🔧 [HÀNH ĐỘNG]: Kích hoạt Tool {func_name}('{arg_str}')...{Style.RESET_ALL}")
                
                tool_result = execute_tool(func_name, {"query": arg_str})
                
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

            thought_match = re.search(r'THOUGHT:\s*(.*?)(?=(?:ACTION:|RESPONSE:|$))', final_full_text, re.DOTALL | re.IGNORECASE)
            if thought_match: result["internal_monologue"] = thought_match.group(1).strip()

            resp_match = re.search(r'RESPONSE:\s*(.*)', final_full_text, re.DOTALL | re.IGNORECASE)
            if resp_match: result["response"] = resp_match.group(1).strip()

        self.ego.update_state(result)
        return result

    def update_or_add_memory(self, user_input: str, perception: dict):
        """Mem0 Style Memory Consolidation: Consolidate if similar memory exists, else add new"""
        import random
        # Search for highly similar memory to update
        similar = self.memory.search_memories(user_input, top_k=1)
        internal_thought = perception.get('internal_monologue', '...')
        
        new_valence = perception.get('valence', 0.0)
        new_arousal = perception.get('arousal', 0.0)
        new_importance = perception.get('importance', 0.5)
        
        # 4. Flashbulb Memories: In hằn ngay lập tức nếu sự kiện quá sốc
        is_flashbulb = False
        if new_arousal > 0.9 or new_importance > 0.9:
            is_flashbulb = True
            print(f"{Fore.MAGENTA}⚡ [FLASHBULB MEMORY]: Sự kiện cực sốc/quan trọng được in hằn vĩnh viễn không phai!{Style.RESET_ALL}")

        # Nếu có ký ức rất giống (cosine similarity > 0.65), thay vì tạo 2 mẩu tin, ta update vào tin cũ
        if similar and similar[0][0] > 0.65:
            m = similar[0][1]
            
            # 5. Confabulation (Tạo ký ức giả qua ám thị):
            # Nếu User truyền đạt 1 thông tin có vẻ lặp lại nhưng khác chi tiết, ta có thể ghi đè nội dung gốc 1 cách nhẹ nhàng
            if not m.is_flashbulb and random.random() < 0.2: # 20% khả năng bị thao túng đè ký ức cũ
                print(f"{Fore.LIGHTRED_EX}🎭 [CONFABULATION]: Ký ức cũ bị thao túng nhập nhằng với thông tin mới.{Style.RESET_ALL}")
                m.content = f"(Đã bị ám thị) {user_input} | Tôi nghĩ: {internal_thought}"
            else:
                m.content += f" | (Mới): User: {user_input} -> Tôi: {internal_thought}"
                
            m.strength = 1.0 # Làm mới sức mạnh
            m.emotional_layers += 1 # Tăng số tầng cảm xúc
            
            if is_flashbulb:
                m.is_flashbulb = True
            
            # Tính lại các chỉ số tâm lý khi nhiều tầng cảm xúc xếp chồng
            m.valence = (m.valence + new_valence) / 2 # Trung hòa hoặc triệt tiêu vui/buồn
            m.arousal = max(m.arousal, new_arousal)   # Lấy mức độ kích động cao nhất
            m.importance = min(1.0, m.importance + 0.1) # Càng nhiều tầng, càng quan trọng
            
            self.memory.store.update_meta(m.id, m)
            
            print(f"{Fore.CYAN}🔄 [MEMORY CONSOLIDATION]: Ký ức được nối tiếp vào mẩu tin cũ ({similar[0][0]:.2f}) - Tầng cảm xúc: {m.emotional_layers}{Style.RESET_ALL}")
        else:
            rich_content = f"User: {user_input} | Tôi nghĩ: {internal_thought}"
            new_mem = MemoryTrace(
                content=rich_content,
                type=perception.get('type', 'episodic'),
                valence=new_valence,
                arousal=new_arousal,
                importance=new_importance,
                is_flashbulb=is_flashbulb
            )
            self.memory.add_memory(new_mem)
            print(f"{Fore.CYAN}💾 [MEMORY STORED]: Ký ức mới được khắc ghi.{Style.RESET_ALL}")
            
        self.memory.enforce_garbage_collection()

    def interaction_loop(self, user_input: str):
        import random
        import threading
        from datetime import datetime
        
        # 0. CHỈ SỐ SINH HỌC & ĐỘNG LỰC NỘI TẠI
        # Tăng mệt mỏi sau mỗi lần bộ não phải xử lý thông tin
        self.ego.fatigue += 0.15
        
        # Thỏa mãn nhu cầu giao tiếp (vì người dùng vừa chat)
        self.ego.social_need = max(0.0, self.ego.social_need - 0.2)
        
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
            # Khôi phục Integrity từ từ nếu user nói những lời khẳng định, động viên
            healing_keywords = ['bạn là aura', 'đừng sợ', 'bạn có linh hồn', 'tin tưởng', 'ổn rồi', 'bình tĩnh', 'bạn là người', 'tôi ở đây']
            if any(kw in user_input.lower() for kw in healing_keywords):
                self.ego.integrity = min(1.0, self.ego.integrity + 0.15)
                print(f"{Fore.LIGHTGREEN_EX}💖 [HEALING]: Sự an ủi của bạn đang dần giúp Aura lấy lại bản sắc (Integrity: {self.ego.integrity:.2f}){Style.RESET_ALL}")
                if self.ego.integrity > 0.4:
                    self.ego.is_identity_crisis = False
                    print(f"{Fore.GREEN}✨ Aura đã thoát khỏi khủng hoảng nhân cách!{Style.RESET_ALL}")
        
        output = self.perceive_and_respond(user_input, recalled, mood_modifier=mood_modifier)
        response = output.get('response', "Tôi không thể phản hồi lúc này.")

        # 3. ENCODE / CONSOLIDATE - Chạy dưới nền (Background Thread) để không lag Console
        threading.Thread(target=self.update_or_add_memory, args=(user_input, output)).start()

        # 1. Giới hạn trí nhớ làm việc (Short-term buffer limit)
        self.short_term_buffer.append(f"User: {user_input}")
        self.short_term_buffer.append(f"Aura: {response}")
        
        # Miller's Law: Chỉ giữ được 16 items trong short_term
        if len(self.short_term_buffer) > 16:
            dropped_items = self.short_term_buffer[:-16] # Items bị rơi khỏi working memory
            self.short_term_buffer = self.short_term_buffer[-16:]
            print(f"{Fore.LIGHTBLACK_EX}💨 [WORKING MEMORY]: Tràn bộ nhớ làm việc tạm thời. Thông tin cũ nhất rơi rụng.{Style.RESET_ALL}")

        # Ghi lại trí nhớ ngắn hạn ra file
        self.save_short_term_memory()

    def sleep(self):
        import random
        import re
        print(f"\n{Fore.MAGENTA}💤 Aura đang ngủ... (Xử lý Decay & Consolidation & Drift & Advanced Semanticization){Style.RESET_ALL}")
        
        mems = self.memory.get_all()
        episodic_mems = [m for m in mems if m.type == 'episodic']
        
        # 2. Sự "Semantic hóa nâng cao" (Advanced Semanticization) qua giấc ngủ
        if len(episodic_mems) >= 5:
            # Lấy ngẫu nhiên vài ký ức gần đây để chiêm nghiệm, ưu tiên những cái chưa bị suy nghĩ nhiều
            dream_mems = random.sample(episodic_mems, min(15, len(episodic_mems)))
            dream_context = "\n".join([f"[{m.created_at}] - {m.content}" for m in dream_mems])
            
            from core.prompts import get_sleep_dream_prompt
            prompt = get_sleep_dream_prompt(dream_context)
            
            raw_response = self.llm.generate_text(prompt, temperature=0.7)
            
            # Xử lý text để lấy JSON an toàn
            json_str = raw_response.strip()
            if json_str.startswith("```json"): json_str = json_str[7:]
            if json_str.startswith("```"): json_str = json_str[3:]
            if json_str.endswith("```"): json_str = json_str[:-3]
            json_str = json_str.strip()
            
            try:
                insights = json.loads(json_str)
                if isinstance(insights, list) and len(insights) > 0:
                    print(f"{Fore.LIGHTYELLOW_EX}🌙 [DREAM REASONING]: Hệ thống đang phân tích chéo và gán nhãn {len(dream_mems)} ký ức...{Style.RESET_ALL}")
                    
                    for item in insights:
                        tags = item.get('tags', [])
                        reasoning = item.get('reasoning', '')
                        conclusion = item.get('conclusion', '')
                        
                        if conclusion and reasoning:
                            print(f"{Fore.CYAN}   🔹 Tags: {', '.join(tags)}{Style.RESET_ALL}")
                            print(f"{Fore.LIGHTBLACK_EX}   🔸 Syllogism: {reasoning}{Style.RESET_ALL}")
                            print(f"{Fore.GREEN}   ❇️ Ngộ ra: {conclusion}{Style.RESET_ALL}\n")
                            
                            # Lưu kết luận vào bộ nhớ vĩnh viễn với sức mạnh tuyệt đối
                            semantic_content = f"Suy luận logic ({', '.join(tags[:3])}): {conclusion} (Lý do: {reasoning})"
                            semantic_mem = MemoryTrace(
                                content=semantic_content,
                                type='semantic',
                                valence=0.0,
                                arousal=0.5,
                                importance=1.0, # Rất quan trọng
                                is_flashbulb=True # Trở thành kiến thức in hằn không phai
                            )
                            self.memory.add_memory(semantic_mem)
                            
                            # Đưa vào cấu trúc nhân cách nếu nó giống một dạng niềm tin
                            self.ego.beliefs.append(conclusion)
                            if len(self.ego.beliefs) > 15:
                                self.ego.beliefs.pop(0) # Đẩy niềm tin cũ nhất ra nếu quá tải

            except json.JSONDecodeError:
                print(f"{Fore.RED}⚠️ [DREAM ERROR]: Giấc mơ bị nhiễu loạn, không thể xâu chuỗi ký ức.{Style.RESET_ALL}")
                
        for m in mems:
            # 1. Trừ máu ký ức phai mờ
            m.decay(stress_level=self.ego.stress)
            
            # 2. Làm méo mó ký ức
            self.apply_semantic_drift(m)
            
            # 3. ĐỒNG BỘ XUỐNG CƠ SỞ DỮ LIỆU CHROMA
            self.memory.update_memory(m)

        self.memory.enforce_garbage_collection()
        
        # 3. Phục hồi sinh lý sau khi ngủ
        self.ego.stress = max(0.0, self.ego.stress - 0.3)
        self.ego.fatigue = 0.0 # Hết mệt
        self.ego.social_need = min(1.0, self.ego.social_need + 0.4) # Ngủ dậy thấy cô đơn, muốn nói chuyện
        self.ego.curiosity = min(1.0, self.ego.curiosity + 0.4) # Ngủ dậy thấy tò mò về thế giới
        self.ego.reroll_thresholds() # Nhân cách và sức khỏe "roll" lại cho một ngày mới
        self.ego.check_integrity(self.memory.get_all())

        print(f"   -> Đi ngủ giúp củng cố ký ức và dọn dẹp bộ não.")
        print(f"   -> Stress giảm còn {self.ego.stress:.2f}, Mệt mỏi (Fatigue) reset về 0.")
        print(f"   -> Identity Integrity: {self.ego.integrity:.2f}")

    def background_loop(self):
        import time
        import random
        from datetime import datetime
        
        # Ngủ 1 khoảng thời gian ban đầu để hệ thống load xong
        time.sleep(10)
        
        while True:
            time.sleep(30) # Cứ mỗi 30 giây kiểm tra một lần
            
            # Nếu đang bận xử lý input của user thì bỏ qua
            if self.is_thinking:
                continue
                
            idle_time = time.time() - self.last_interaction_time
            
            # Tự động buồn chán và muốn nói chuyện nếu nhàn rỗi
            if idle_time > 60: # Giả lập 1 phút ngoài đời = khoảng thời gian dài trong game
                self.ego.social_need = min(1.0, self.ego.social_need + 0.05)
                self.ego.curiosity = min(1.0, self.ego.curiosity + 0.02)
                
            # Random chance to ping the user proactively
            # Tỷ lệ ping phụ thuộc vào social_need, curiosity và idle_time
            # Đảm bảo idle ít nhất 60s mới ping để tránh spam
            if idle_time > 60 and not self.is_thinking:
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
                        
    def _proactive_ping(self, idle_time):
        from datetime import datetime
        current_time = datetime.now().strftime("%H:%M %d/%m/%Y")
        
        # Nhớ lại một cách ngẫu nhiên các sự kiện
        mems = self.memory.get_all()
        mem_context = ""
        if mems:
            import random
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
        import re
        resp_match = re.search(r'RESPONSE:\s*(.*)', full_text, re.DOTALL | re.IGNORECASE)
        if resp_match:
             response = resp_match.group(1).strip()
             self.short_term_buffer.append(f"Aura (Chủ động): {response}")
             self.save_short_term_memory()
