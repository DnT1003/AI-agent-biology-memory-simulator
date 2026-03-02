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
            mood_bias = 0.2 if (self.ego.mood < -0.3 and m.valence < -0.2) else 0
            final_score = score * m.strength * (1 + m.arousal) + mood_bias
            if final_score > 0.35:
                candidates.append((final_score, m))
                
        time_kws = ['hôm nay', 'hôm qua', 'vừa nãy', 'trước đó', 'mới đây', 'sáng nay', 'chiều nay', 'tối qua', 'gần đây', 'lúc nãy']
        if any(kw in query.lower() for kw in time_kws):
            current_time = time.time()
            try:
                chrono_results = self.memory.chronological_recall(current_time - 86400*3, current_time, limit=5)
                for m in chrono_results:
                    if m.strength >= 0.1 and m.id not in [c[1].id for c in candidates]:
                        recent_mems.append((1.0, m))
            except Exception as e:
                print(f"{Fore.RED}⚠️ Lỗi truy xuất thời gian: {e}{Style.RESET_ALL}")
                
        candidates.sort(key=lambda x: x[0], reverse=True)
        recalled = [c[1] for c in candidates[:4]]
        
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
            raw_response = self.llm.generate_text(prompt, temperature=0.7)
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
        print(f"   -> Stress giảm còn {self.ego.stress:.2f}, Fatigue reset về 0.")
