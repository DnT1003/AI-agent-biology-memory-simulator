import json
import os
import time
import random
from typing import List
from colorama import Fore, Style
from config import Config
from core.memory import MemoryTrace
from core.prompts import get_semantic_drift_prompt, get_sleep_dream_prompt

class MemoryOpsMixin:
    def load_short_term_memory(self):
        """Khôi phục bộ nhớ ngắn hạn từ ổ cứng nếu thời gian chưa trôi qua quá lâu (3 tiếng)"""
        if os.path.exists(self.stm_file_path):
            try:
                with open(self.stm_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    last_updated = data.get("timestamp", 0)
                    saved_buffer = data.get("buffer", [])
                    
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
        results = self.memory.search_memories(query, top_k=10)
        candidates = []
        for score, m in results:
            if m.strength < 0.1: continue
            # Phase 8 Idea 6.2: Emotional State-Dependent Retrieval
            mood_bias = 0.0
            if self.ego.mood < -0.3 and m.valence < -0.2:
                mood_bias = 0.3   # Tăng ký ức buồn khi đang buồn
            elif self.ego.mood > 0.3 and m.valence > 0.2:
                mood_bias = 0.3   # Tăng ký ức vui khi đang vui
            elif self.ego.mood < -0.3 and m.valence > 0.3:
                mood_bias = -0.2  # Phạt ký ức vui khi đang buồn
            final_score = score * m.strength * (1 + m.arousal) + mood_bias
            if final_score > 0.35:
                candidates.append((final_score, m))
                
        time_kws = ['h\u00f4m nay', 'h\u00f4m qua', 'v\u1eeba n\u00e3y', 'tr\u01b0\u1edbc \u0111\u00f3', 'm\u1edbi \u0111\u00e2y', 's\u00e1ng nay', 'chi\u1ec1u nay', 't\u1ed1i qua', 'g\u1ea7n \u0111\u00e2y', 'l\u00fac n\u00e3y']
        recent_mems = []  # Bug #1 fix: khai b\u00e1o tr\u01b0\u1edbc khi d\u00f9ng
        if any(kw in query.lower() for kw in time_kws):
            current_time = time.time()
            try:
                chrono_results = self.memory.chronological_recall(current_time - 86400*3, current_time, limit=5)
                for m in chrono_results:
                    if m.strength >= 0.1 and m.id not in [c[1].id for c in candidates]:
                        recent_mems.append((1.0, m))
            except Exception as e:
                print(f"{Fore.RED}\u26a0\ufe0f L\u1ed7i tr\u1ef3 xu\u1ea5t th\u1eddi gian: {e}{Style.RESET_ALL}")
        candidates = candidates + recent_mems
        candidates.sort(key=lambda x: x[0], reverse=True)
        recalled = [c[1] for c in candidates[:4]]

        # =======================================================
        # Phase 7 Idea 11: Sự Não Cá Vàng Tạm Thời (Brain Fog)
        # =======================================================
        import re
        if self.ego.fatigue >= self.ego.fatigue_mild:
            for m in recalled:
                if random.random() < 0.3: # 30% cơ hội bị che mờ chi tiết trong mỗi mẩu ký ức
                    # Che mờ các con số
                    m.content = re.sub(r'\b\d+\b', '[quên mất số bao nhiêu rồi]', m.content)
                    # Giả lập lú lẫn tẻ nhạt
                    if len(m.content) > 20:
                         words = m.content.split()
                         if len(words) > 5:
                              idx = random.randint(0, len(words) - 2)
                              words[idx] = "[cái gì đó]"
                              m.content = " ".join(words)
                    print(f"{Fore.LIGHTBLACK_EX}🌫️ [BRAIN FOG]: Ký ức bị che mờ do mệt mỏi: {m.content[:50]}...{Style.RESET_ALL}")

        
        chained_memory = None
        if recalled:
            anchor_memory = recalled[0]
            associative_results = self.memory.search_memories(anchor_memory.content, top_k=5)
            for _, am in associative_results:
                if am.id != anchor_memory.id and am.id not in [m.id for m in recalled] and am.strength > 0.4:
                    chained_memory = am
                    recalled.append(am)
                    break

        for m in recalled:
            is_associative = (chained_memory and m.id == chained_memory.id)
            m.reconsolidate(self.ego.mood, is_associative=is_associative)
            self.memory.store.update_meta(m.id, m)
        return recalled

    def apply_semantic_drift(self, memory: MemoryTrace):
        if memory.is_flashbulb or memory.type in ['core', 'semantic'] or memory.recall_count < 2:
            return
        if random.random() > Config.SEMANTIC_DRIFT_CHANCE:
            return
        prompt = get_semantic_drift_prompt(memory.content)
        new_content = self.llm.generate_text(prompt, temperature=0.8)
        if new_content and len(new_content) > 10 and new_content != memory.content:
            print(f"{Fore.LIGHTRED_EX}🌀 [SEMANTIC DRIFT]: Ký ức méo mó theo thời gian:\n   - Cũ: {memory.content}\n   - Mới: {new_content}{Style.RESET_ALL}")
            memory.content = new_content
            self.memory.store.update_vector(memory.id, self.embedder.encode(new_content))
            self.memory.update_memory(memory)

    def update_or_add_memory(self, user_input: str, perception: dict):
        similar = self.memory.search_memories(user_input, top_k=1)
        internal_thought = perception.get('internal_monologue', '...')
        new_valence, new_arousal, new_importance = perception.get('valence', 0.0), perception.get('arousal', 0.0), perception.get('importance', 0.5)
        
        is_flashbulb = new_arousal > 0.9 or new_importance > 0.9
        if is_flashbulb:
            print(f"{Fore.MAGENTA}⚡ [FLASHBULB MEMORY]: Sự kiện cực sốc/quan trọng được in hằn vĩnh viễn không phai!{Style.RESET_ALL}")

        if similar and similar[0][0] > 0.65:
            m = similar[0][1]
            if not m.is_flashbulb and random.random() < 0.2:
                print(f"{Fore.LIGHTRED_EX}🎭 [CONFABULATION]: Ký ức cũ bị thao túng nhập nhằng với thông tin mới.{Style.RESET_ALL}")
                m.content = f"(Đã bị ám thị) {user_input} | Tôi nghĩ: {internal_thought}"
            else:
                m.content += f" | (Mới): User: {user_input} -> Tôi: {internal_thought}"
            m.strength, m.emotional_layers = 1.0, m.emotional_layers + 1
            if is_flashbulb: m.is_flashbulb = True
            m.valence, m.arousal, m.importance = (m.valence + new_valence) / 2, max(m.arousal, new_arousal), min(1.0, m.importance + 0.1)
            self.memory.store.update_meta(m.id, m)
            print(f"{Fore.CYAN}🔄 [MEMORY CONSOLIDATION]: Ký ức được nối tiếp vào mẩu tin cũ ({similar[0][0]:.2f}) - Tầng cảm xúc: {m.emotional_layers}{Style.RESET_ALL}")
        else:
            new_mem = MemoryTrace(content=f"User: {user_input} | Tôi nghĩ: {internal_thought}", type=perception.get('type', 'episodic'), valence=new_valence, arousal=new_arousal, importance=new_importance, is_flashbulb=is_flashbulb)
            self.memory.add_memory(new_mem)
            print(f"{Fore.CYAN}💾 [MEMORY STORED]: Ký ức mới được khắc ghi.{Style.RESET_ALL}")
        self.memory.enforce_garbage_collection()

    def sleep(self):
        print(f"\n{Fore.MAGENTA}💤 Aura đang ngủ... (Xử lý Decay & Consolidation & Drift & Advanced Semanticization){Style.RESET_ALL}")
        mems = self.memory.get_all()
        episodic_mems = [m for m in mems if m.type == 'episodic']
        if len(episodic_mems) >= 5:
            dream_mems = random.sample(episodic_mems, min(15, len(episodic_mems)))
            prompt = get_sleep_dream_prompt("\n".join([f"[{m.created_at}] - {m.content}" for m in dream_mems]))
            raw_response = self.llm.generate_text(prompt, temperature=0.7, model_override=Config.DEEP_MODEL_NAME)
            json_str = raw_response.strip().replace("```json", "").replace("```", "").strip()
            try:
                insights = json.loads(json_str)
                if isinstance(insights, list):
                    for item in insights:
                        tags, reasoning, conclusion = item.get('tags', []), item.get('reasoning', ''), item.get('conclusion', '')
                        if conclusion and reasoning:
                            print(f"{Fore.GREEN}   ❇️ Ngộ ra: {conclusion}{Style.RESET_ALL}\n")
                            self.memory.add_memory(MemoryTrace(content=f"Suy luận logic ({', '.join(tags[:3])}): {conclusion} (Lý do: {reasoning})", type='semantic', valence=0.0, arousal=0.5, importance=1.0, is_flashbulb=True))
                            self.ego.beliefs.append(conclusion)
                            if len(self.ego.beliefs) > 15: self.ego.beliefs.pop(0)
            except: pass
        for m in mems:
            m.decay(stress_level=self.ego.stress)
            self.apply_semantic_drift(m)
            self.memory.update_memory(m)
        self.memory.enforce_garbage_collection()
        self.ego.stress, self.ego.fatigue = max(0.0, self.ego.stress - 0.3), 0.0
        self.ego.social_need, self.ego.curiosity = min(1.0, self.ego.social_need + 0.4), min(1.0, self.ego.curiosity + 0.4)
        self.ego.reroll_thresholds()
        self.ego.check_integrity(self.memory.get_all())
        # Phase 7 Idea 6: Guilt & Self-Correction
        # Chỉ xảy ra khi Stress > 0.75 hoặc có nhiều hơn 2 chỉ số tiêu cực > 0.5
        negative_stats_count = sum(1 for val in [self.ego.stress, self.ego.fatigue, (self.ego.mood < -0.5)*1.0, self.ego.is_identity_crisis*1.0] if val > 0.5)
        
        if self.ego.stress > 0.75 or negative_stats_count >= 2:
            if len(self.short_term_buffer) > 0:
                print(f"{Fore.LIGHTBLACK_EX}🔍 [GUILT REFLECTION]: Đang suy ngẫm lại hành vi trong ngày do tâm lý bất ổn...{Style.RESET_ALL}")
                guilt_prompt = f"Đây là lịch sử trò chuyện gần đây:\n{self.short_term_buffer}\nBạn có nói câu nào vô tâm, có thái độ gắt gỏng, lạnh nhạt không đáng có với người dùng không? Trả lời 'CÓ' hoặc 'KHÔNG'. Nếu CÓ, hãy nêu lý do thành 1 câu ngắn gọn bắt đầu bằng 'Lý do: '."
                guilt_res = self.llm.generate_text(guilt_prompt, temperature=0.2).strip()
                if "CÓ" in guilt_res.upper() or "LÝ DO" in guilt_res.upper():
                    guilt_reason = guilt_res.replace("CÓ", "").strip(":- ,.\n")
                    if guilt_reason:
                        guilt_mem = MemoryTrace(
                            content=f"Tôi cảm thấy ân hận vì cách hành xử của mình lúc trước: {guilt_reason}. Lần sau phải chú ý ôn hòa hơn.",
                            type='episodic',
                            valence=-0.6,
                            arousal=0.5,
                            importance=0.8
                        )
                        self.memory.add_memory(guilt_mem)
                        print(f"{Fore.MAGENTA}😔 [GUILT]: Aura cảm thấy hối hận vì: {guilt_reason}{Style.RESET_ALL}")

        print(f"   -> Stress giảm còn {self.ego.stress:.2f}, Fatigue reset về 0.")


