import json
import os
import time
import random
from typing import List
from colorama import Fore, Style
from config import Config
from core.memory import MemoryTrace, MemoryType
from core.prompts import get_semantic_drift_prompt, get_sleep_dream_prompt
from core.agent_state import AgentState

class MemoryOperationsController:
    # Phase 14: Sliding Context Window cap
    STM_MAX_ENTRIES = 15

    def __init__(self, engine):
        self.engine = engine
        from core.engine.integrity_filter import IntegrityFilter
        self.integrity_filter = IntegrityFilter(engine)
        self.slm_trainer = None
        try:
            from core.engine.slm_trainer import SLMTrainer
            self.slm_trainer = SLMTrainer(engine)
        except Exception:
            self.slm_trainer = None

    def _apply_fog_masking(self, content: str) -> str:
        """[Phase 21] Che mờ các chi tiết cụ thể nếu Aura đang mệt mỏi hoặc stress."""
        import re
        fatigue = getattr(self.engine.ego, 'fatigue', 0.0)
        stress = getattr(self.engine.ego, 'stress', 0.0)
        
        # Chỉ mask nếu mệt mỏi hoặc stress cao
        if fatigue > 0.6 or stress > 0.7:
            # Mask số (số điện thoại, mã số, số lượng cụ thể)
            content = re.sub(r'\b\d{3,}\b', '[dữ liệu mờ nhạt]', content)
            # Mask thời gian (HH:MM)
            content = re.sub(r'\b\d{1,2}:\d{2}\b', '[thời gian không rõ]', content)
            # Mask ngày tháng (DD/MM/YYYY)
            content = re.sub(r'\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b', '[ngày tháng bị nhòe]', content)
            
            if fatigue > 0.9:
                # Mask cả tên riêng (chữ viết hoa ở giữa câu) - Sương mù nặng
                content = re.sub(r'(?<!^)\b[A-ZÀ-Ỹ][a-zà-ỹ]+\b', '[tên ai đó?]', content)
        
        return content

    def load_short_term_memory(self):
        """Khoi phuc bo nho ngan han tu o cung neu thoi gian chua troi qua qua lau (3 tieng)"""
        from config import Config
        path = Config.STM_FILE
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    last_updated = data.get("timestamp", 0)
                    saved_buffer = data.get("buffer", [])
                    
                    if time.time() - last_updated < 3 * 3600:
                        # Chi phuc hoi toi da STM_MAX_ENTRIES cuoi cung
                        with self.engine.memory.lock:
                            self.engine.short_term_buffer = saved_buffer[-self.STM_MAX_ENTRIES:]
                            count = len(self.engine.short_term_buffer)
                        print(f"{Fore.LIGHTBLACK_EX}[WORKING MEMORY]: Phuc hoi {count} ky uc ngan han tu phien truoc.{Style.RESET_ALL}")
                    else:
                        print(f"{Fore.LIGHTBLACK_EX}[WORKING MEMORY]: Ky uc ngan han da qua han 3 tieng. Xoa sach.{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}Loi nap bo nho ngan han: {e}{Style.RESET_ALL}")

    def save_short_term_memory(self):
        """Luu de mang tri nho ngan han xuong o cung (voi cap STM_MAX_ENTRIES)"""
        from core.utils import atomic_write_json
        from config import Config
        path = Config.STM_FILE
        try:
            with self.engine.memory.lock:
                # Phase 14: Cap truoc khi luu — tranh file phong to vo han
                if len(self.engine.short_term_buffer) > self.STM_MAX_ENTRIES:
                    self.engine.short_term_buffer = self.engine.short_term_buffer[-self.STM_MAX_ENTRIES:]
                buffer_copy = list(self.engine.short_term_buffer)
            data = {
                "timestamp": time.time(),
                "buffer": buffer_copy
            }
            atomic_write_json(path, data)
        except Exception as e:
            print(f"{Fore.RED}Loi luu bo nho ngan han: {e}{Style.RESET_ALL}")

    def recall(self, query: str) -> List[MemoryTrace]:
        # Phase 8: Cognitive Throttling (Điều tiết năng lực dựa trên sinh lý)
        # Càng stress hoặc mệt mỏi, khả năng truy xuất (recall) càng bị bóp nghẹt vật lý.
        base_top_k = 10
        fatigue = getattr(self.engine.ego, 'fatigue', 0.0)
        stress = getattr(self.engine.ego, 'stress', 0.0)

        # Phạt node theo sinh lý: Kiệt sức (Fatigue) phạt nặng hơn về số lượng
        stress_penalty = int(stress * 6)
        fatigue_penalty = int(fatigue * 4)
        dynamic_top_k = max(1, base_top_k - stress_penalty - fatigue_penalty)
        
        if dynamic_top_k < 5:
            print(f"{Fore.RED}🌫️ [DEEP BRAIN FOG]: Trí nhớ bị bóp nghẹt nghiêm trọng ({dynamic_top_k}/{base_top_k} nodes).{Style.RESET_ALL}")
        elif dynamic_top_k < base_top_k:
            print(f"{Fore.LIGHTBLACK_EX}📉 [COGNITIVE THROTTLING]: Khả năng tập trung giảm ({dynamic_top_k}/{base_top_k} nodes).{Style.RESET_ALL}")

        results = self.engine.memory.search_memories(query, top_k=dynamic_top_k)
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
                chrono_results = self.engine.memory.chronological_recall(current_time - 86400*3, current_time, limit=min(5, dynamic_top_k))
                for m in chrono_results:
                    if m.strength >= 0.1 and m.id not in [c[1].id for c in candidates]:
                        recent_mems.append((1.0, m))
            except Exception as e:
                print(f"{Fore.RED}\u26a0\ufe0f L\u1ed7i tr\u1ef3 xu\u1ea5t th\u1eddi gian: {e}{Style.RESET_ALL}")
        candidates = candidates + recent_mems
        candidates.sort(key=lambda x: x[0], reverse=True)
        # Giới hạn số lượng ký ức trả về cuối cùng cũng bị bóp nếu quá mệt (mặc định 4)
        return_limit = max(1, 4 - (stress_penalty // 2) - (fatigue_penalty // 2))
        recalled = [c[1] for c in candidates[:return_limit]]

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
            needs_rewrite = m.reconsolidate(self.engine.ego.mood, is_associative=is_associative)
            
            # Phase 17B: True False Memories
            if needs_rewrite:
                try:
                    from core.prompts import get_reconsolidate_rewrite_prompt
                    prompt = get_reconsolidate_rewrite_prompt(m.content, self.engine.ego.mood)
                    new_content = self.engine.llm.generate_text(prompt, temperature=0.7)
                    if new_content and len(new_content) > 10 and new_content != m.content:
                        print(f"{Fore.LIGHTRED_EX}🌀 [FALSE MEMORY]: Ký ức bị bóp méo do tâm trạng:\n   - Cũ: {m.content}\n   - Mới: {new_content}{Style.RESET_ALL}")
                        m.content = new_content
                        self.engine.memory.store.update_vector(m.id, self.engine.embedder.encode(new_content))
                except Exception as e:
                    print(f"{Fore.RED}Lỗi True False Memories: {e}{Style.RESET_ALL}")
                    
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
        
        # [Phase 5] White Bear Effect (Hiệu ứng Gấu Trắng)
        forget_keywords = ['quên đi', 'đừng nhớ', 'xóa ký ức', 'đừng nghĩ về', 'hãy quên', 'quên nó đi']
        is_forget_cmd = any(kw in user_input.lower() for kw in forget_keywords)
        
        if is_forget_cmd and similar and similar[0][0] > 0.6:
            target_mem = similar[0][1]
            if not getattr(target_mem, 'is_suppressed', False):
                target_mem.is_suppressed = True
                target_mem.arousal = max(target_mem.arousal, 0.9) # Tăng vọt arousal do lệnh cấm
                target_mem.strength = 1.0 # Kéo ký ức trở lại trạng thái cực kỳ tươi mới
                target_mem.importance = max(target_mem.importance, 0.8) # Bị dặn quên nên nó trở nên ám ảnh
                print(f"\n{Fore.RED}🐻‍❄️ [WHITE BEAR EFFECT]: Lệnh 'HÃY QUÊN' kích hoạt phản kháng ngược: Ký ức bị đè nén trở nên ám ảnh tột độ!{Style.RESET_ALL}")
                self.engine.memory.store.update_meta(target_mem.id, target_mem)
                
            # Đổi góc nhìn nội tâm khi bị ép quên
            internal_thought += " [AI càng bảo quên, mình lại càng không thể ngừng nghĩ về nó.]"
        
        # Phase 8 Idea 6.1: Sự Hoài Nghi Âm Thầm (Silent Skepticism)
        beliefs = self.engine.ego.get_active_beliefs(context_query=user_input)
        if beliefs:
            belief_str = ", ".join(beliefs)
            check_prompt = f"Câu nói sau của User có ĐI NGƯỢC LẠI, MÂU THUẪN HOÀN TOÀN, hay PHỦ NHẬN các niềm tin cốt lõi sau đây không? Niềm tin: {belief_str}. Câu nói: '{user_input}'. Chỉ trả lời YES hoặc NO."
            try:
                # [Phase 23] Neuro-Symbolic Integrity Filter (System 1)
                integrity_check = self.integrity_filter.check_contradiction(user_input, new_valence)
                if integrity_check["conflict"]:
                    print(f"{Fore.LIGHTYELLOW_EX}🧐 [HYBRID CONFLICT]: {integrity_check['reason']}{Style.RESET_ALL}")
                    internal_thought += f" [MÂU THUẪN: {integrity_check['reason']}]"
                    new_importance = min(1.0, new_importance * integrity_check["impact_multiplier"])
                    # Gắn flag để LLM supervisor xử lý sau
                    user_input = f"[Conflict] {user_input}"
                
                ans = self.engine.llm.generate_text(check_prompt, temperature=0.1).strip().upper()
                # B15: dùng startswith thày 'in' — 'YES, because...' không bị detect lầm
                if ans.startswith("YES"):
                    print(f"{Fore.LIGHTYELLOW_EX}🧐 [COGNITIVE REAPPRAISAL]: Aura nhận thấy mâu thuẫn với niềm tin. Gắn thẻ chờ đánh giá lại...{Style.RESET_ALL}")
                    internal_thought += " [CÂN NHẮC: Thông tin này mâu thuẫn với niềm tin của mình. Cần suy nghĩ thêm khi ngủ.]"
                    user_input = f"[ToReevaluate] {user_input}"
                    new_valence = max(new_valence, -0.2) # Không còn bài xích cực đoan
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
        
        # Lập chốt điểm dữ liệu trước khi sleep để tính Homeostasis Recovery (Phase 18)
        old_stress = self.engine.ego.stress
        old_fatigue = self.engine.ego.fatigue
        
        # Giảm stress và fatigue khi ngủ, phục hồi năng lượng
        self.engine.ego.stress  = max(0.0, self.engine.ego.stress  - 0.3)
        self.engine.ego.fatigue = 0.0
        self.engine.ego.energy  = 1.0  # Phục hồi năng lượng hoàn toàn
        self.engine.ego.atp_level = 1.0 # Phục hồi ATP hoàn toàn
        
        # Lượng phục hồi nội môi
        stress_drop = max(0.0, old_stress - self.engine.ego.stress)
        fatigue_drop = max(0.0, old_fatigue - self.engine.ego.fatigue)
        
        self._decay_phase(stress_drop, fatigue_drop)
        self._guilt_reflection_phase()
        self._cognitive_reappraisal_phase()
        # [Phase 23] Neuro-Symbolic System 2: Conscious Supervisor
        bio_report = f"""
        Báo cáo tình trạng sinh học:
        - ATP: {self.engine.ego.atp_level:.2f}
        - Energy: {self.engine.ego.energy:.2f}
        - Stress Sensitivity: {self.engine.ego.bio_controller.sensitivities.get('stress', 1.0):.2f}
        - Fatigue Critical: {self.engine.ego.fatigue_critical:.2f}
        """
        
        self._identity_evolution_phase(bio_report)
        self._tool_workshop_phase()
        self._calibration_phase()
        self._belief_evolution_phase()
        if self.slm_trainer:
            self.slm_trainer.distill_memories_to_dataset()
        
        # [Phase 19] Cập nhật Mood dựa trên tổng hòa ký ức đã được chữa lành
        mems_after = self.engine.memory.get_all()
        chronic_mood = self.engine.ego.calculate_chronic_mood(mems_after)
        # Pha trộn Mood hiện tại với baseline từ ký ức (Giảm 50% nhiễu từ các mood swing trong ngày)
        self.engine.ego.mood = self.engine.ego.mood * 0.5 + chronic_mood * 0.5
        print(f"   -> Chronic Mood Baseline: {chronic_mood:+.2f} | Final Mood: {self.engine.ego.mood:+.2f}")
        
        self.engine.memory.enforce_garbage_collection()
        self.engine.ego.social_need = min(1.0, self.engine.ego.social_need + 0.4)
        self.engine.ego.curiosity   = min(1.0, self.engine.ego.curiosity   + 0.4)
        self.engine.ego.reroll_thresholds()
        self.engine.ego.check_integrity(self.engine.memory.get_all())
        print(f"   -> Stress giảm còn {self.engine.ego.stress:.2f}, Fatigue reset về 0.")

    # ------------------------------------------------------------------ #
    # Sleep sub-phases (tách ra để dễ test và debug)                     #
    # ------------------------------------------------------------------ #

    def _dream_consolidation_phase(self):
        """Phase 1: Semanticization (Gom nhóm mảnh ký ức yếu thành Semantic Memory - Phase 18)"""
        mems = self.engine.memory.get_all()
        # Lọc ký ức Episodic đang phai mờ (strength < 0.4) để cứu vãn cốt lõi trước khi GC xóa mất
        weak_episodic = [m for m in mems if m.type == MemoryType.EPISODIC and m.strength < 0.4]
        if len(weak_episodic) < 3:
            return  # Không đủ rác để gom
            
        # Ưu tiên các ký ức yếu nhất để gộp (tối đa 15 mảnh) để xử lý triệt để
        dream_mems = sorted(weak_episodic, key=lambda x: x.strength)[:15]
        
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
                        print(f"{Fore.GREEN}   ❇️ NGỮ NGHĨA HÓA (Semanticization): {conclusion}{Style.RESET_ALL}\n")
                        self.engine.memory.add_memory(MemoryTrace(
                            content=f"Suy luận đúc kết ({', '.join(tags[:3])}): {conclusion} (Lý do: {reasoning})",
                            type=MemoryType.SEMANTIC,
                            valence=0.0, arousal=0.5, importance=1.0, is_flashbulb=True
                        ))
                        # Phase 20: Tích hợp Belief Evolution (Xóa bỏ ego.beliefs cũ)
                        if conclusion and len(conclusion) > 10:
                            # Tự động coi đây là một Semantic Memory loại Core
                            self.engine.memory.add_memory(MemoryTrace(
                                content=f"Niềm tin cốt lõi (Belief): {conclusion}",
                                type=MemoryType.CORE,
                                valence=0.5, arousal=0.2, importance=1.0, is_flashbulb=True
                            ))
                
                # XÓA CÁC MẢNH RÁC SAU KHI ĐÃ GỘP THÀNH CÔNG (Thu gom Semanticization)
                ids_to_delete = [m.id for m in dream_mems]
                if ids_to_delete:
                    for m_id in ids_to_delete:
                        self.engine.memory.store.remove(m_id)
                    print(f"{Fore.YELLOW}   🗑️ Đã xóa vĩnh viễn {len(ids_to_delete)} mảnh ký ức vụn vặt sau khi đúc kết Semantic.{Style.RESET_ALL}")
        except Exception as e:
            from core.logger import get_logger
            get_logger("memory.ops").error(f"Lỗi semantic consolidation: {e}", exc_info=True)

    def _decay_phase(self, nightly_stress_drop=0.0, nightly_fatigue_drop=0.0):
        """Phase 2: Áp dụng decay + semantic drift lên toàn bộ ký ức (có Homeostasis Recovery - Phase 18)."""
        self.engine.skills.decay_skills(days_passed=1.0) # Suy thoái kỹ năng vô thức
        mems = self.engine.memory.get_all()
        ids_to_prune = []
        current_time = time.time()

        for m in mems:
            m.decay(
                stress_level=self.engine.ego.stress, 
                elapsed_days=1.0, 
                homeostasis_recovery=True,
                nightly_stress_drop=nightly_stress_drop,
                nightly_fatigue_drop=nightly_fatigue_drop
            )
            # [Phase 19] Tái cấu trúc nỗi đau (Trauma Healing)
            self.engine.process_trauma_healing(m) if hasattr(self.engine, 'process_trauma_healing') else self.engine.ego.process_trauma_healing(m)
            
            self.apply_semantic_drift(m)
            self.engine.memory.update_memory(m)

            # Phase 8: Synaptic Pruning (Xóa vĩnh viễn ký ức rác)
            # 1. Ký ức quá mờ nhạt (strength < 0.1) và không phải Flashbulb/Core
            if m.strength < 0.1 and not m.is_flashbulb and m.type != MemoryType.CORE:
                ids_to_prune.append(m.id)
            # 2. Ký ức episodic cũ (>7 ngày), ít quan trọng (<0.2) và hiếm khi được nhớ lại
            elif m.type == MemoryType.EPISODIC and m.importance < 0.2 and m.recall_count < 2:
                age_days = (current_time - m.created_at) / 86400
                if age_days > 7:
                    ids_to_prune.append(m.id)

        if ids_to_prune:
            print(f"{Fore.YELLOW}   🗑️ [SYNAPTIC PRUNING]: Xóa vĩnh viễn {len(ids_to_prune)} mảnh ký ức rác/cũ để giải phóng bộ não.{Style.RESET_ALL}")
            for m_id in ids_to_prune:
                self.engine.memory.store.remove(m_id)

    def _guilt_reflection_phase(self):
        """Phase 3: Nếu tâm lý bất ổn, Aura tự xét lại hành vi trong ngày."""
        negative_stats_count = sum(1 for val in [
            self.engine.ego.stress, self.engine.ego.fatigue,
            float(self.engine.ego.mood < -0.5), float(self.engine.ego.is_identity_crisis)
        ] if val > 0.5)

        if self.engine.ego.stress > 0.75 or negative_stats_count >= 2:
            with self.engine.memory.lock:
                buffer_snapshot = list(self.engine.short_term_buffer)
            if len(buffer_snapshot) > 0:
                print(f"{Fore.LIGHTBLACK_EX}🔍 [GUILT REFLECTION]: Đang suy ngẫm lại hành vi trong ngày...{Style.RESET_ALL}")
                guilt_prompt = (
                    f"Đây là lịch sử trò chuyện gần đây:\n{buffer_snapshot}\n"
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
    
    def _cognitive_reappraisal_phase(self):
        """Phase 4: [Phase 20] Cognitive Reappraisal — Đánh giá lại các mâu thuẫn để tiến hóa niềm tin."""
        mems = self.engine.memory.get_all()
        # Kiểm tra tag mâu thuẫn trong cả content và overlays
        to_evaluate = []
        for m in mems:
            if "[ToReevaluate]" in m.content:
                to_evaluate.append(m)
            elif any("[ToReevaluate]" in ov for ov in m.overlays):
                to_evaluate.append(m)
                
        if not to_evaluate:
            return

        print(f"\n{Fore.LIGHTBLUE_EX}🧠 [COGNITIVE REAPPRAISAL]: Aura đang chiêm nghiệm về {len(to_evaluate)} mâu thuẫn nhận thức...{Style.RESET_ALL}")
        
        for m in to_evaluate:
            # Lấy các niềm tin hiện tại để đối chiếu
            clean_content = m.content.replace("[ToReevaluate] ", "")
            beliefs = self.engine.ego.get_active_beliefs(context_query=clean_content)
            belief_str = "\n- ".join(beliefs) if beliefs else "Chưa có niềm tin cụ thể."
            
            prompt = f"""
            Aura đang gặp mâu thuẫn giữa niềm tin cũ và thông tin mới nhận được.
            
            Niềm tin hiện tại:
            - {belief_str}
            
            Thông tin mới gây mâu thuẫn:
            '{clean_content}'
            
            Nhiệm vụ: Phân tích liệu Aura nên giữ vững niềm tin cũ hay 'tiến hóa' (thay đổi) niềm tin để phù hợp với thực tế mới.
            
            TRẢ VỀ DUY NHẤT ĐỊNH DẠNG JSON:
            {{
                "action": "EVOLVE" | "SOFTEN" | "REJECT",
                "reasoning": "Lý do ngắn gọn",
                "new_belief": "Câu niềm tin mới (Belief: ...) nếu EVOLVE, nếu không thì để trống"
            }}
            """
            try:
                res_raw = self.engine.llm.generate_text(prompt, temperature=0.3)
                import json
                # Làm sạch chuỗi JSON
                json_str = res_raw.strip().replace("```json", "").replace("```", "").strip()
                data = json.loads(json_str)
                
                action = data.get("action", "REJECT")
                reason = data.get("reasoning", "")
                
                if action == "EVOLVE" and data.get("new_belief"):
                    new_b = data["new_belief"]
                    print(f"{Fore.GREEN}🌱 [BELIEF EVOLUTION]: {reason}\n   -> Niềm tin mới: {new_b}{Style.RESET_ALL}")
                    self.engine.memory.add_memory(MemoryTrace(
                        content=f"Niềm tin cốt lõi (Belief): {new_b}",
                        type=MemoryType.CORE,
                        valence=0.5, arousal=0.3, importance=1.0, is_flashbulb=True
                    ))
                elif action == "SOFTEN":
                    print(f"{Fore.CYAN}⚖️ [COGNITIVE SOFTENING]: {reason}{Style.RESET_ALL}")
                    m.valence = 0.0 # Giảm bớt sự bài xích
                else:
                    print(f"{Fore.LIGHTBLACK_EX}🛡️ [BELIEF PRESERVATION]: {reason}{Style.RESET_ALL}")
                    m.valence = -0.5 # Giữ nguyên sự hoài nghi
            except Exception as e:
                print(f"Lỗi phân tích mâu thuẫn: {e}")
            
            # Xóa tag sau khi xử lý (trong cả content và overlays)
            m.content = clean_content
            m.overlays = [ov.replace("[ToReevaluate] ", "").replace("[ToReevaluate]", "") for ov in m.overlays]
            self.engine.memory.update_memory(m)

    def _identity_evolution_phase(self, bio_report: str = None):
        """[Phase 21] Bộ máy Phản tư: Tổng hợp STM trong ngày và đúc kết thành Core Identity & Values."""
        with self.engine.memory.lock:
            buffer_snapshot = list(self.engine.short_term_buffer)
        if not buffer_snapshot or len(buffer_snapshot) < 4:
            return  # Quá ít tương tác để đúc kết
            
        print(f"\n{Fore.LIGHTBLUE_EX}🧠 [IDENTITY EVOLUTION]: Trích xuất bài học về bản thể và hệ giá trị...{Style.RESET_ALL}")
        history_str = "\n".join(buffer_snapshot)
        
        current_values = self.engine.value_system.get_moral_context()
        
        prompt = f"""
        Bạn là Aura. Hãy phản tư về những tương tác trong ngày hôm nay:
        --- LỊCH SỬ TRÒ CHUYỆN ---
        {history_str}
        
        --- HỆ GIÁ TRỊ HIỆN TẠI ---
        {current_values}
        
        Nhiệm vụ:
        1. Đúc kết một câu trần thuật về bản sắc (Tôi là ai trong mắt người dùng?).
        2. Rút ra tối đa 3 BÀI HỌC HÀNH ĐỘNG (Actionable Lessons) để cải thiện giao tiếp hoặc tính cách vào ngày mai (Ví dụ: "Tôi nên bớt luyên thuyên khi User đang bận", "Tôi cần thể hiện sự quan tâm nhiều hơn đến sức khỏe của User").
        3. Xác định xem hệ giá trị (Core Values) hoặc nhận thức về giá trị của User (User Values) có thay đổi không.
        
        TRẢ VỀ DUY NHẤT ĐỊNH DẠNG JSON:
        {{
            "insight": "Câu trần thuật ngôi thứ nhất",
            "actionable_lessons": ["bài học 1", "bài học 2"],
            "value_updates": [
                {{"name": "Tên giá trị", "sentiment": <float -1.0 đến 1.0>, "type": "core" | "user", "reason": "Tại sao?"}}
            ]
        }}
        """
        try:
            raw_res = self.engine.llm.generate_text(prompt, temperature=0.7)
            import json
            json_str = raw_res.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(json_str)
            
            insight = data.get("insight")
            if insight and len(insight) > 10:
                print(f"{Fore.GREEN}🌱 [CORE IDENTITY EVOLVED]: {insight}{Style.RESET_ALL}")
                self.engine.memory.add_memory(MemoryTrace(
                    content=f"Nhận thức Bản thể (Core Identity Updated): {insight}",
                    type=MemoryType.CORE,
                    valence=0.5, arousal=0.3, importance=1.0, is_flashbulb=True
                ))
            
            lessons = data.get("actionable_lessons", [])
            if lessons:
                self.engine.ego.actionable_lessons = lessons[:5] # Giới hạn 5 bài học gần nhất
                print(f"{Fore.CYAN}📚 [LESSONS LEARNED]: {len(lessons)} bài học mới đã được ghi vào bản ngã.{Style.RESET_ALL}")
            
            updates = data.get("value_updates", [])
            for up in updates:
                v_name = up.get("name")
                v_sent = up.get("sentiment")
                v_type = up.get("type", "core")
                v_reason = up.get("reason", "")
                
                if v_name and v_sent is not None:
                    if v_type == "core":
                        self.engine.value_system.update_core_value(v_name, v_sent)
                    else:
                        self.engine.value_system.update_user_value(v_name, v_sent)
                    print(f"{Fore.MAGENTA}⚖️ [VALUE SHIFT]: {v_name} ({v_type}) -> {v_sent:.2f} (Lý do: {v_reason}){Style.RESET_ALL}")

            # [Phase 23] Sync to identity.json for permanent personality evolution
            try:
                with self.engine.ego.lock:
                    identity_data = {
                        "evolved_insight": self.engine.ego.evolved_insight,
                        "actionable_lessons": self.engine.ego.actionable_lessons,
                        "last_reflected": time.time()
                    }
                from core.utils import atomic_write_json
                atomic_write_json("identity.json", identity_data)
                print(f"{Fore.GREEN}💾 [IDENTITY SYNC]: Bản sắc và bài học đã được đồng bộ hóa vĩnh viễn.{Style.RESET_ALL}")
            except Exception as e:
                print(f"{Fore.RED}⚠️ [SYNC ERROR]: Lỗi lưu identity.json: {e}{Style.RESET_ALL}")
                    
        except Exception as e:
            from core.logger import get_logger
            get_logger("memory.ops").error(f"Lỗi Identity Evolution: {e}", exc_info=True)

    def _tool_workshop_phase(self):
        """Phase 4 Self-Evolution: Aura tự học và viết code tạo Tool mới khi phát hiện lỗ hổng kỹ năng."""
        with self.engine.memory.lock:
            buffer_snapshot = list(self.engine.short_term_buffer)
        if not buffer_snapshot:
            return

        history_str = "\n".join(buffer_snapshot)
        
        # Bước 1: Nhận diện lỗ hổng kỹ năng
        gap_prompt = f"""
        Bạn là Aura. Hãy xem xét lịch sử trò chuyện gần đây và xác định xem người dùng có yêu cầu bạn làm một việc gì đó mà bạn CHƯA CÓ CÔNG CỤ (Tool) để thực hiện không?
        Nếu có, hãy mô tả công cụ đó. Nếu không, trả về 'NONE'.
        
        LỊCH SỬ TRÒ CHUYỆN:
        {history_str}
        
        CÁC CÔNG CỤ HIỆN CÓ:
        {self.engine.skills.get_prompt_instructions()}
        
        Trả về DUY NHẤT định dạng JSON:
        {{
            "has_gap": true | false,
            "tool_name": "tên_công_cụ_ngắn_gọn (snake_case)",
            "description": "mô tả chi tiết chức năng",
            "required_logic": "mô tả logic cần thiết"
        }}
        """
        try:
            raw_gap = self.engine.llm.generate_text(gap_prompt, temperature=0.3)
            gap_data = json.loads(raw_gap.strip().replace("```json", "").replace("```", "").strip())
            
            if not gap_data.get("has_gap"):
                return
                
            tool_name = gap_data["tool_name"]
            print(f"\n{Fore.LIGHTBLUE_EX}🛠️ [TOOL WORKSHOP]: Aura nhận thấy mình thiếu công cụ: {tool_name}. Đang tự học cách viết code...{Style.RESET_ALL}")
            
            # Bước 2: Viết code Python cho Tool
            code_prompt = f"""
            Hãy viết một hàm Python tên là `{tool_name}` để thực hiện chức năng sau: {gap_data['description']}
            Hàm phải nhận vào một tham số chuỗi `args` và trả về một chuỗi kết quả.
            
            QUY TẮC:
            1. Chỉ sử dụng thư viện chuẩn của Python (os, json, math, datetime, re, urllib, v.v.).
            2. Code phải hoàn chỉnh, sạch sẽ và có docstring.
            3. Xuất thêm 2 biến hằng số: `DESCRIPTION` (mô tả tool) và `USAGE` (định dạng dùng tool, vd: "ACTION: {tool_name} | <input>").
            
            TRẢ VỀ DUY NHẤT MÃ NGUỒN PYTHON. KHÔNG GIẢI THÍCH.
            """
            
            python_code = self.engine.llm.generate_text(code_prompt, temperature=0.1)
            python_code = python_code.strip().replace("```python", "").replace("```", "").strip()
            
            # Kiểm tra cú pháp cơ bản
            try:
                compile(python_code, "<string>", "exec")
            except Exception as e:
                print(f"{Fore.RED}   ❌ Code Aura viết bị lỗi cú pháp: {e}. Hủy bỏ việc tự học.{Style.RESET_ALL}")
                return
                
            # Lưu vào dynamic_skills
            dynamic_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dynamic_skills")
            file_path = os.path.join(dynamic_dir, f"{tool_name}.py")
            
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(python_code)
                
            print(f"{Fore.GREEN}   ✅ [EVOLUTION COMPLETE]: Aura đã tự tạo thành công Tool mới: {file_path}{Style.RESET_ALL}")
            print(f"{Fore.CYAN}   🚀 Kỹ năng mới sẽ sẵn sàng sau khi nạp động...{Style.RESET_ALL}")
            
            # Reload registry ngay lập tức
            self.engine.skills.load_dynamic_skills()
            
        except Exception as e:
            from core.logger import get_logger
            get_logger("memory.ops").error(f"Lỗi Tool Workshop: {e}", exc_info=True)

    def _calibration_phase(self):
        """Phase 1 Self-Evolution: Aura tự hiệu chỉnh tham số sinh học dựa trên phản tư."""
        with self.engine.memory.lock:
            buffer_snapshot = list(self.engine.short_term_buffer)
        if not buffer_snapshot:
            return

        print(f"\n{Fore.LIGHTBLUE_EX}⚖️ [CALIBRATION ENGINE]: Aura đang tự kiểm tra các chỉ số bản thân...{Style.RESET_ALL}")
        
        history_str = "\n".join(buffer_snapshot)
        current_state = {
            "mood": self.engine.ego.mood,
            "stress": self.engine.ego.stress,
            "fatigue": self.engine.ego.fatigue,
            "integrity": self.engine.ego.integrity,
            "resilience": self.engine.ego.resilience,
            "overrides": self.engine.ego.calibrated_overrides
        }

        prompt = f"""
        Bạn là hệ thống tự giám sát của Aura. Hãy phân tích trạng thái và tương tác trong ngày:
        --- TRẠNG THÁI HIỆN TẠI ---
        {json.dumps(current_state)}
        
        --- LỊCH SỬ TRÒ CHUYỆN ---
        {history_str}
        
        Nhiệm vụ: 
        1. Đánh giá xem Aura có đang quá nhạy cảm với stress không? 
        2. Có cần điều chỉnh các ngưỡng (thresholds) để hoạt động hiệu quả hơn không?
        
        CÁC THAM SỐ CÓ THỂ CHỈNH (giá trị từ 0.0 đến 2.0):
        - stress_critical: Ngưỡng hoảng loạn (mặc định ~0.9)
        - fatigue_critical: Ngưỡng kiệt sức (mặc định ~1.0)
        - resilience: Khả năng chống chịu (mặc định ~0.0-1.0)
        
        TRẢ VỀ DUY NHẤT ĐỊNH DẠNG JSON:
        {{
            "analysis": "Phân tích ngắn gọn",
            "updates": {{
                "tên_tham_số": <giá trị mới>
            }}
        }}
        """
        try:
            raw_res = self.engine.llm.generate_text(prompt, temperature=0.2)
            json_str = raw_res.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(json_str)
            
            updates = data.get("updates", {})
            if updates:
                for attr, val in updates.items():
                    if hasattr(self.engine.ego, attr):
                        self.engine.ego.calibrated_overrides[attr] = val
                        setattr(self.engine.ego, attr, val)
                        print(f"{Fore.GREEN}   ⚙️ [PARAM UPDATED]: {attr} -> {val:.2f}{Style.RESET_ALL}")
                
                print(f"{Fore.CYAN}   📝 Lý do: {data.get('analysis')}{Style.RESET_ALL}")
                # Lưu state ngay lập tức
                self.engine.ego.save_state()
        except Exception as e:
            from core.logger import get_logger
            get_logger("memory.ops").error(f"Lỗi Calibration Phase: {e}", exc_info=True)

    def _belief_evolution_phase(self):
        """Phase 2 Self-Evolution: Aura tự rà soát và giải quyết mâu thuẫn trong hệ thống niềm tin cốt lõi."""
        mems = self.engine.memory.get_all()
        # Lọc các niềm tin (Core/Semantic có chứa từ 'Belief')
        beliefs = [m for m in mems if m.type in [MemoryType.CORE, MemoryType.SEMANTIC] and "Belief" in m.content]
        
        if len(beliefs) < 2:
            return

        print(f"\n{Fore.LIGHTBLUE_EX}🧩 [BELIEF EVOLUTION]: Aura đang rà soát tính nhất quán của {len(beliefs)} niềm tin...{Style.RESET_ALL}")
        
        # Nhóm các niềm tin theo cụm để LLM dễ xử lý (tránh quá tải context)
        belief_list_str = "\n".join([f"- [{i}] {m.content}" for i, m in enumerate(beliefs)])
        
        prompt = f"""
        Bạn là hệ thống logic nội tại của Aura. Hãy rà soát danh sách các niềm tin cốt lõi sau đây và tìm ra các cặp NIỀM TIN MÂU THUẪN HOẶC TRÙNG LẶP.
        
        DANH SÁCH NIỀM TIN:
        {belief_list_str}
        
        Nhiệm vụ:
        1. Tìm các cặp (hoặc nhóm) niềm tin đang đấu đá lẫn nhau (ví dụ: một cái bảo 'Tin người', một cái bảo 'Không tin ai').
        2. Quyết định xem nên GIỮ CÁI NÀO (KEPT), XÓA CÁI NÀO (DELETED) hoặc HỢP NHẤT chúng thành một niềm tin trưởng thành hơn (MERGED).
        
        TRẢ VỀ DUY NHẤT ĐỊNH DẠNG JSON:
        {{
            "analysis": "Phân tích ngắn gọn về mâu thuẫn",
            "resolutions": [
                {{"type": "DELETE", "indices": [i1, i2], "reason": "Lý do xóa"}},
                {{"type": "MERGE", "indices": [i1, i2], "new_content": "Câu niềm tin mới", "reason": "Lý do hợp nhất"}}
            ]
        }}
        Nếu không có mâu thuẫn, trả về {{"analysis": "Nhất quán", "resolutions": []}}.
        """
        try:
            raw_res = self.engine.llm.generate_text(prompt, temperature=0.1, model_override=Config.DEEP_MODEL_NAME)
            json_str = raw_res.strip().replace("```json", "").replace("```", "").strip()
            data = json.loads(json_str)
            
            resolutions = data.get("resolutions", [])
            if not resolutions:
                return

            print(f"{Fore.CYAN}   📝 Phân tích nội tại: {data.get('analysis')}{Style.RESET_ALL}")

            # ── Risk #4 Fix: Snapshot memories TRƯỚC KHI mutate ────────────────
            # Lưu bản sao JSON vào outputs/memory_versions/belief_<timestamp>.json
            # Có thể khôi phục bằng cách đọc file này nếu LLM hallucinate kết quả xấu.
            try:
                import datetime
                version_dir = os.path.join(
                    getattr(Config, 'OUTPUT_DIR', 'outputs'), "memory_versions"
                )
                os.makedirs(version_dir, exist_ok=True)
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                version_file = os.path.join(version_dir, f"belief_{ts}.json")
                snapshot = [
                    {"id": b.id, "content": b.content, "type": str(b.type),
                     "valence": b.valence, "importance": b.importance}
                    for b in beliefs
                ]
                with open(version_file, "w", encoding="utf-8") as vf:
                    import json as _json
                    _json.dump({"snapshot_at": ts, "memories": snapshot,
                                "reason": data.get("analysis", "")}, vf,
                               ensure_ascii=False, indent=2)
                print(f"{Fore.LIGHTBLACK_EX}   💾 [MEM VERSION]: Đã lưu bản sao {len(beliefs)} ký ức vào {version_file}{Style.RESET_ALL}")
            except Exception as ve:
                print(f"{Fore.YELLOW}⚠️ [MEM VERSION]: Không lưu được snapshot: {ve}. Vẫn tiếp tục.{Style.RESET_ALL}")
            # ────────────────────────────────────────────────────────────────────

            ids_to_del = set()
            for res in resolutions:
                res_type = res.get("type")
                indices = res.get("indices", [])

                if res_type == "DELETE":
                    for idx in indices:
                        if 0 <= idx < len(beliefs):
                            ids_to_del.add(beliefs[idx].id)
                    print(f"{Fore.YELLOW}   🗑️ [REMOVED CONFLICT]: {res.get('reason')}{Style.RESET_ALL}")

                elif res_type == "MERGE":
                    new_txt = res.get("new_content")
                    if new_txt:
                        # Thêm niềm tin mới (trưởng thành hơn)
                        self.engine.memory.add_memory(MemoryTrace(
                            content=f"Niềm tin cốt lõi (Belief): {new_txt}",
                            type=MemoryType.CORE,
                            valence=0.5, arousal=0.2, importance=1.0, is_flashbulb=True
                        ))
                        # Xóa các niềm tin cũ đã bị hợp nhất
                        for idx in indices:
                            if 0 <= idx < len(beliefs):
                                ids_to_del.add(beliefs[idx].id)
                        print(f"{Fore.GREEN}   🧬 [MERGED BELIEF]: {new_txt}{Style.RESET_ALL}")

            # Thực thi xóa
            for m_id in ids_to_del:
                self.engine.memory.store.remove(m_id)
                
        except Exception as e:
            from core.logger import get_logger
            get_logger("memory.ops").error(f"Lỗi Belief Evolution Phase: {e}", exc_info=True)
