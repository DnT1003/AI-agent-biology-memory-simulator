import json
import os
import time
import random
from typing import List
from colorama import Fore, Style
from config import Config
from core.memory import MemoryTrace, MemoryType
from core.prompts import get_semantic_drift_prompt, get_sleep_dream_prompt

class MemoryOperationsController:
    # Phase 14: Sliding Context Window cap
    STM_MAX_ENTRIES = 15

    def __init__(self, engine):
        self.engine = engine

    def load_short_term_memory(self):
        """Khoi phuc bo nho ngan han tu o cung neu thoi gian chua troi qua qua lau (3 tieng)"""
        if os.path.exists(self.engine.stm_file_path):
            try:
                with open(self.engine.stm_file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    last_updated = data.get("timestamp", 0)
                    saved_buffer = data.get("buffer", [])
                    
                    if time.time() - last_updated < 3 * 3600:
                        # Chi phuc hoi toi da STM_MAX_ENTRIES cuoi cung
                        self.engine.short_term_buffer = saved_buffer[-self.STM_MAX_ENTRIES:]
                        print(f"{Fore.LIGHTBLACK_EX}[WORKING MEMORY]: Phuc hoi {len(self.engine.short_term_buffer)} ky uc ngan han tu phien truoc.{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.LIGHTBLACK_EX}[WORKING MEMORY]: Ky uc ngan han da qua han 3 tieng. Xoa sach.{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Loi nap bo nho ngan han: {e}{Style.RESET_ALL}")

    def save_short_term_memory(self):
        """Luu de mang tri nho ngan han xuong o cung (voi cap STM_MAX_ENTRIES)"""
        try:
            # Phase 14: Cap truoc khi luu — tranh file phong to vo han
            if len(self.engine.short_term_buffer) > self.STM_MAX_ENTRIES:
                self.engine.short_term_buffer = self.engine.short_term_buffer[-self.STM_MAX_ENTRIES:]
            data = {
                "timestamp": time.time(),
                "buffer": self.engine.short_term_buffer
            }
            with open(self.engine.stm_file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"{Fore.RED}Loi luu bo nho ngan han: {e}{Style.RESET_ALL}")

    def recall(self, query: str) -> List[MemoryTrace]:
        results = self.engine.memory.search_memories(query, top_k=10)
        candidates = []
        for score, m in results:
            if m.strength < 0.1: continue
            # Phase 8 Idea 6.2: Emotional State-Dependent Retrieval
            mood_bias = 0.0
            if self.engine.ego.mood < -0.3 and m.valence < -0.2:
                mood_bias = 0.3   # Tăng ký ức buồn khi đang buồn
            elif self.engine.ego.mood > 0.3 and m.valence > 0.2:
                mood_bias = 0.3   # Tăng ký ức vui khi đang vui
            elif self.engine.ego.mood < -0.3 and m.valence > 0.3:
                mood_bias = -0.2  # Phạt ký ức vui khi đang buồn
            # B14: Môod bias là multiplicative (không additive) — tránh override similarity
            final_score = score * m.strength * (1 + m.arousal) * (1 + mood_bias)
            if final_score > 0.35:
                candidates.append((final_score, m))
                
        time_kws = ['h\u00f4m nay', 'h\u00f4m qua', 'v\u1eeba n\u00e3y', 'tr\u01b0\u1edbc \u0111\u00f3', 'm\u1edbi \u0111\u00e2y', 's\u00e1ng nay', 'chi\u1ec1u nay', 't\u1ed1i qua', 'g\u1ea7n \u0111\u00e2y', 'l\u00fac n\u00e3y']
        recent_mems = []  # Bug #1 fix: khai b\u00e1o tr\u01b0\u1edbc khi d\u00f9ng
        if any(kw in query.lower() for kw in time_kws):
            current_time = time.time()
            try:
                chrono_results = self.engine.memory.chronological_recall(current_time - 86400*3, current_time, limit=5)
                for m in chrono_results:
                    if m.strength >= 0.1 and m.id not in [c[1].id for c in candidates]:
                        recent_mems.append((1.0, m))
            except Exception as e:
                print(f"{Fore.RED}\u26a0\ufe0f L\u1ed7i tr\u1ef3 xu\u1ea5t th\u1eddi gian: {e}{Style.RESET_ALL}")
        candidates = candidates + recent_mems
        candidates.sort(key=lambda x: x[0], reverse=True)
        recalled = [c[1] for c in candidates[:4]]

        # Cập nhật số lần được nhớ lại (Reconsolidation)
        current_mood = self.engine.ego.mood
        
        chained_memory = None
        if recalled:
            anchor_memory = recalled[0]
            associative_results = self.engine.memory.search_memories(anchor_memory.content, top_k=5)
            for _, am in associative_results:
                if am.id != anchor_memory.id and am.id not in [m.id for m in recalled] and am.strength > 0.4:
                    chained_memory = am
                    recalled.append(am)
                    break

        for m in recalled:
            is_associative = (chained_memory and m.id == chained_memory.id)
            m.reconsolidate(self.engine.ego.mood, is_associative=is_associative)
            self.engine.memory.store.update_meta(m.id, m)
        return recalled

    def apply_semantic_drift(self, memory: MemoryTrace):
        if memory.is_flashbulb or memory.type in [MemoryType.CORE, MemoryType.SEMANTIC] or memory.recall_count < 2:
            return
        if random.random() > Config.SEMANTIC_DRIFT_CHANCE:
            return
        prompt = get_semantic_drift_prompt(memory.content)
        new_content = self.engine.llm.generate_text(prompt, temperature=0.8)
        if new_content and len(new_content) > 10 and new_content != memory.content:
            print(f"{Fore.LIGHTRED_EX}🌀 [SEMANTIC DRIFT]: Ký ức méo mó theo thời gian:\n   - Cũ: {memory.content}\n   - Mới: {new_content}{Style.RESET_ALL}")
            memory.content = new_content
            self.engine.memory.store.update_vector(memory.id, self.engine.embedder.encode(new_content))
            self.engine.memory.update_memory(memory)

    def update_or_add_memory(self, user_input: str, perception: dict):
        similar = self.engine.memory.search_memories(user_input, top_k=1)
        internal_thought = perception.get('internal_monologue', '...')
        new_valence, new_arousal, new_importance = perception.get('valence', 0.0), perception.get('arousal', 0.0), perception.get('importance', 0.5)
        
        # Phase 8 Idea 6.1: Sự Hoài Nghi Âm Thầm (Silent Skepticism)
        beliefs = self.engine.ego.get_active_beliefs(context_query=user_input)
        if beliefs:
            belief_str = ", ".join(beliefs)
            check_prompt = f"Câu nói sau của User có ĐI NGƯỢC LẠI, MÂU THUẪN HOÀN TOÀN, hay PHỦ NHẬN các niềm tin cốt lõi sau đây không? Niềm tin: {belief_str}. Câu nói: '{user_input}'. Chỉ trả lời YES hoặc NO."
            try:
                ans = self.engine.llm.generate_text(check_prompt, temperature=0.1).strip().upper()
                # B15: dùng startswith thày 'in' — 'YES, because...' không bị detect lầm
                if ans.startswith("YES"):
                    print(f"{Fore.LIGHTYELLOW_EX}🤨 [SILENT SKEPTICISM]: Aura âm thầm hoài nghi thông tin này vì nó chọi lại Core Belief!{Style.RESET_ALL}")
                    internal_thought += " [HOÀI NGHI: Thông tin này có vẻ sai hoặc lừa dối, không khớp với niềm tin của mình.]"
                    new_valence = min(new_valence, -0.4) # Gắn cảm xúc tiêu cực, bài xích
            except Exception:
                pass
        
        is_flashbulb = new_arousal > 0.9 or new_importance > 0.9
        if is_flashbulb:
            print(f"{Fore.MAGENTA}⚡ [FLASHBULB MEMORY]: Sự kiện cực sốc/quan trọng được in hằn vĩnh viễn không phai!{Style.RESET_ALL}")

        if similar and similar[0][0] > 0.65:
            m = similar[0][1]
            if not m.is_flashbulb and random.random() < 0.2:
                print(f"{Fore.LIGHTRED_EX}🎭 [CONFABULATION]: Ký ức cũ bị thao túng nhập nhằng với thông tin mới.{Style.RESET_ALL}")
                m.overlays.append(f"[Ám thị mới] User: {user_input} | Tâm trí: {internal_thought}")
            else:
                m.overlays.append(f"[Liên kết mới]: User: {user_input} -> Tôi nghĩ: {internal_thought}")
                
            # Đảm bảo overlays không quá dài (keep max 10)
            if len(m.overlays) > 10:
                m.overlays = m.overlays[-10:]
                
            m.strength = min(1.0, m.strength + 0.3)  # B7: recovery curve, không reset về 1.0
            m.emotional_layers = m.emotional_layers + 1
            if is_flashbulb: m.is_flashbulb = True
            m.valence, m.arousal, m.importance = (m.valence + new_valence) / 2, max(m.arousal, new_arousal), min(1.0, m.importance + 0.1)
            self.engine.memory.store.update_meta(m.id, m)
            print(f"{Fore.CYAN}🔄 [MEMORY CONSOLIDATION]: Ký ức được nối tiếp vào mẩu tin cũ ({similar[0][0]:.2f}) - Tầng cảm xúc: {m.emotional_layers}{Style.RESET_ALL}")
        else:
            new_mem = MemoryTrace(content=f"User: {user_input} | Tôi nghĩ: {internal_thought}", type=perception.get('type', 'episodic'), valence=new_valence, arousal=new_arousal, importance=new_importance, is_flashbulb=is_flashbulb)
            self.engine.memory.add_memory(new_mem)
            print(f"{Fore.CYAN}💾 [MEMORY STORED]: Ký ức mới được khắc ghi.{Style.RESET_ALL}")
        self.engine.memory.enforce_garbage_collection()

    def sleep(self):
        """Quản lý giấc ngủ: điều phối 3 phase riêng biệt. B12: split for clarity + testability."""
        print(f"\n{Fore.MAGENTA}💤 Aura đang ngủ... (Decay & Consolidation & Drift & Semanticization){Style.RESET_ALL}")
        self._dream_consolidation_phase()
        self._decay_phase()
        self._guilt_reflection_phase()
        self.engine.memory.enforce_garbage_collection()
        self.engine.ego.stress  = max(0.0, self.engine.ego.stress  - 0.3)
        self.engine.ego.fatigue = 0.0
        self.engine.ego.social_need = min(1.0, self.engine.ego.social_need + 0.4)
        self.engine.ego.curiosity   = min(1.0, self.engine.ego.curiosity   + 0.4)
        self.engine.ego.reroll_thresholds()
        self.engine.ego.check_integrity(self.engine.memory.get_all())
        print(f"   -> Stress giảm còn {self.engine.ego.stress:.2f}, Fatigue reset về 0.")

    # ------------------------------------------------------------------ #
    # Sleep sub-phases (tách ra để dễ test và debug)                     #
    # ------------------------------------------------------------------ #

    def _dream_consolidation_phase(self):
        """Phase 1: Nhớ lại kyờ kẻ + sật ngộ ra → tạo semantic memory mới."""
        mems = self.engine.memory.get_all()
        episodic_mems = [m for m in mems if m.type == MemoryType.EPISODIC]
        if len(episodic_mems) < 5:
            return
        dream_mems = self.engine.autonomous._weighted_sample_memories(min(15, len(episodic_mems)), filter_type=MemoryType.EPISODIC)
        prompt = get_sleep_dream_prompt("\n".join([f"[{m.created_at}] - {m.content}" for m in dream_mems]))
        raw_response = self.engine.llm.generate_text(prompt, temperature=0.7, model_override=Config.DEEP_MODEL_NAME)
        json_str = raw_response.strip().replace("```json", "").replace("```", "").strip()
        try:
            insights = json.loads(json_str)
            if isinstance(insights, list):
                for item in insights:
                    tags       = item.get('tags', [])
                    reasoning  = item.get('reasoning', '')
                    conclusion = item.get('conclusion', '')
                    if conclusion and reasoning:
                        print(f"{Fore.GREEN}   ❇️ Ngộ ra: {conclusion}{Style.RESET_ALL}\n")
                        self.engine.memory.add_memory(MemoryTrace(
                            content=f"Suy luận logic ({', '.join(tags[:3])}): {conclusion} (Lý do: {reasoning})",
                            type=MemoryType.SEMANTIC,
                            valence=0.0, arousal=0.5, importance=1.0, is_flashbulb=True
                        ))
                        # B9: Belief validation
                        if (conclusion and len(conclusion) > 10
                                and conclusion not in self.engine.ego.beliefs
                                and len(self.engine.ego.beliefs) < 50):
                            self.engine.ego.beliefs.append(conclusion)
        except Exception:
            pass

    def _decay_phase(self):
        """Phase 2: Áp dụng decay + semantic drift lên toàn bộ kyờ kẻ."""
        mems = self.engine.memory.get_all()
        for m in mems:
            m.decay(stress_level=self.engine.ego.stress)
            self.apply_semantic_drift(m)
            self.engine.memory.update_memory(m)

    def _guilt_reflection_phase(self):
        """Phase 3: Nếu tâm lý bất ổn, Aura tự xét lại hành vi trong ngày."""
        negative_stats_count = sum(1 for val in [
            self.engine.ego.stress, self.engine.ego.fatigue,
            float(self.engine.ego.mood < -0.5), float(self.engine.ego.is_identity_crisis)
        ] if val > 0.5)

        if self.engine.ego.stress > 0.75 or negative_stats_count >= 2:
            if len(self.engine.short_term_buffer) > 0:
                print(f"{Fore.LIGHTBLACK_EX}🔍 [GUILT REFLECTION]: Đang suy ngẫm lại hành vi trong ngày...{Style.RESET_ALL}")
                guilt_prompt = (
                    f"Đây là lịch sử trò chuyện gần đây:\n{self.engine.short_term_buffer}\n"
                    "Bạn có nói câu nào vô tâm, có thái độ gắt gỏng, lạnh nhạt không đáng có không? "
                    "Trả lời 'CÓ' hoặc 'KHÔNG'. Nếu CÓ, hãy nêu lý do thành 1 câu ngắn bắt đầu bằng 'Lý do: '."
                )
                guilt_res = self.engine.llm.generate_text(guilt_prompt, temperature=0.2).strip()
                # B15: dùng startswith — tránh 'CÓ thể' bị detect lầm
                if guilt_res.strip().upper().startswith("CÓ") or "LÝ DO" in guilt_res.upper():
                    guilt_reason = guilt_res.replace("CÓ", "").strip(":- ,.\n")
                    if guilt_reason:
                        guilt_mem = MemoryTrace(
                            content=f"Tôi cảm thấy ân hận vì cách hành xử của mình lúc trước: {guilt_reason}. Lần sau phải chú ý ôn hòa hơn.",
                            type=MemoryType.EPISODIC,
                            valence=-0.6, arousal=0.5, importance=0.8
                        )
                        self.engine.memory.add_memory(guilt_mem)
                        print(f"{Fore.MAGENTA}😔 [GUILT]: Aura cảm thấy hối hận vì: {guilt_reason}{Style.RESET_ALL}")
