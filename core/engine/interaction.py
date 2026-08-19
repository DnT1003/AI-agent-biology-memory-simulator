import re
import math
import copy
import time
from datetime import datetime
from colorama import Fore, Style
from core.prompts import get_perceive_prompt
from core.tools import execute_tool


class InteractionOutputError(RuntimeError):
    """Primary model output cannot produce a user-visible response safely."""


class InteractionController:
    def __init__(self, engine):
        self.engine = engine
        # Kept only for compatibility with older integrations. New callers
        # use a request-scoped Event so one request cannot cancel another.
        self.is_interrupted = False
        from core.engine.sensory_preprocessor import SensoryPreprocessor
        from core.engine.reflex_gate import ReflexGate
        from core.engine.context_compressor import ContextCompressor
        self.sensory_preprocessor = SensoryPreprocessor()
        self.reflex_gate = ReflexGate(engine)
        self.compressor = ContextCompressor()

    @staticmethod
    def _is_cancelled(cancel_event) -> bool:
        return cancel_event is not None and cancel_event.is_set()

    @classmethod
    def _raise_if_cancelled(
        cls,
        cancel_event,
        phase: str,
        *,
        request_id: str | None = None,
    ) -> None:
        """Turn a cooperative pre-commit stop into a typed actor outcome."""

        if cls._is_cancelled(cancel_event):
            from core.engine.interaction_actor import InteractionCancelled

            raise InteractionCancelled(str(request_id or "direct"), phase)

    @staticmethod
    def _run_postcommit_phase(phase: str, callback) -> bool:
        """Run best-effort enrichment without invalidating a primary reply."""

        try:
            callback()
            return True
        except BaseException as error:
            try:
                from core.logger import get_logger

                # Do not include exception text or a traceback: interaction
                # and provider errors may contain private prompt content.
                get_logger("interaction").error(
                    "Post-commit interaction phase failed phase=%s cause_type=%s",
                    phase,
                    type(error).__name__,
                )
            except BaseException:
                # Observability is enrichment too; a broken logger must never
                # rewrite a response that has already committed.
                pass
            return False

    def _plan_input_ego_updates(
        self,
        user_input: str,
        sensory_vector: dict,
        local_result: dict,
        *,
        private_ephemeral: bool,
    ) -> tuple[dict, dict]:
        """Build the input-state transition without touching the live ego."""

        if private_ephemeral:
            return {}, {}

        healing_keywords = (
            "bạn là aura",
            "đừng sợ",
            "bạn có linh hồn",
            "tin tưởng",
            "ổn rồi",
            "bình tĩnh",
            "bạn là người",
            "tôi ở đây",
        )
        with self.engine.ego.lock:
            baseline = {
                "social_need": self.engine.ego.social_need,
                "stress": self.engine.ego.stress,
                "mood": self.engine.ego.mood,
                "vocabulary": list(getattr(self.engine.ego, "vocabulary", [])),
                "integrity": self.engine.ego.integrity,
                "is_identity_crisis": self.engine.ego.is_identity_crisis,
            }

        social_need = max(0.0, baseline["social_need"] - 0.2)
        stress = baseline["stress"]
        mood = baseline["mood"]
        vocabulary = list(baseline["vocabulary"])
        integrity = baseline["integrity"]
        identity_crisis = baseline["is_identity_crisis"]

        stress_impact = (
            sensory_vector.get("arousal", 0.0) * 0.2
            + sensory_vector.get("urgency", 0.0) * 0.3
        )
        stress = min(1.0, stress + stress_impact)
        empathy_applied = False
        if local_result:
            user_mood_score = local_result.get("valence", 0.0)
            if abs(user_mood_score) > 0.3:
                mood += (user_mood_score - mood) * 0.15
                mood = max(-1.0, min(1.0, mood))
                empathy_applied = True
            if local_result.get("arousal", 0.0) > 0.7:
                stress = min(1.0, stress + 0.05)

        words = re.findall(r"\b\w{3,}\b", user_input.lower())
        stop_words = {
            "của", "và", "các", "có", "để", "cho", "với", "không",
            "một", "những", "thì", "đang", "là", "rằng", "đã", "được",
        }
        for word in words:
            if word not in stop_words:
                vocabulary.append(word)
                if len(vocabulary) > 100:
                    vocabulary.pop(0)

        healing_applied = bool(
            identity_crisis
            and any(keyword in user_input.lower() for keyword in healing_keywords)
        )
        exited_identity_crisis = False
        if healing_applied:
            integrity = min(1.0, integrity + 0.15)
            if integrity > 0.4:
                identity_crisis = False
                exited_identity_crisis = True

        planned = {}
        if social_need != baseline["social_need"]:
            planned["social_need"] = social_need
        if stress != baseline["stress"]:
            planned["stress"] = stress
        if empathy_applied:
            planned["mood"] = mood
        if vocabulary != baseline["vocabulary"]:
            planned["vocabulary"] = vocabulary
        if healing_applied:
            planned["integrity"] = integrity
            planned["is_identity_crisis"] = identity_crisis

        return planned, {
            "baseline": {field: baseline[field] for field in planned},
            "empathy_applied": empathy_applied,
            "healing_applied": healing_applied,
            "exited_identity_crisis": exited_identity_crisis,
        }

    def _apply_input_ego_updates(self, updates: dict, metadata: dict) -> None:
        if not updates:
            return
        baseline = metadata.get("baseline", {})
        applied_fields = set()
        with self.engine.ego.lock:
            for field, value in updates.items():
                # A primary tool/reflex is itself committed.  Never overwrite
                # an ego field that it changed while the input plan was staged.
                if getattr(self.engine.ego, field) == baseline.get(field):
                    setattr(self.engine.ego, field, value)
                    applied_fields.add(field)
            mood = self.engine.ego.mood
            integrity = self.engine.ego.integrity

        if metadata.get("empathy_applied") and "mood" in applied_fields:
            print(
                f"{Fore.LIGHTBLACK_EX}💞 [LOCAL EMPATHY]: Cảm xúc của User "
                f"ảnh hưởng tới Aura. Tâm trạng Aura bị kéo về {mood:.2f}."
                f"{Style.RESET_ALL}"
            )
        if metadata.get("healing_applied") and "integrity" in applied_fields:
            print(
                f"{Fore.LIGHTGREEN_EX}💖 [HEALING]: Sự an ủi đang dần "
                f"giúp Aura lấy lại bản sắc (Integrity: {integrity:.2f})"
                f"{Style.RESET_ALL}"
            )
        if (
            metadata.get("exited_identity_crisis")
            and "is_identity_crisis" in applied_fields
        ):
            print(
                f"{Fore.GREEN}✨ Aura đã thoát khỏi khủng hoảng nhân cách!"
                f"{Style.RESET_ALL}"
            )

    def _prompt_ego_view(self, updates: dict):
        """Shallow-copy SelfModel so planned values condition the prompt only."""

        if not updates:
            return self.engine.ego
        ego_view = copy.copy(self.engine.ego)
        for field, value in updates.items():
            setattr(ego_view, field, value)
        return ego_view

    def _run_sleep_maintenance(self):
        """Enter the explicit maintenance capability for an in-band sleep."""

        from core.memory_context import (
            current_memory_context,
            maintenance_memory_context,
            memory_context_scope,
        )

        active = current_memory_context()
        with memory_context_scope(
            maintenance_memory_context(
                origin_kind="sleep",
                origin_source=active.origin_source,
                source_event_id=active.source_event_id,
            )
        ):
            return self.engine.memory_ops.sleep()

    @staticmethod
    def _is_private_ephemeral_input(user_input: str) -> bool:
        from config import Config
        from core.interaction_policy import is_explicit_private_input

        return is_explicit_private_input(
            user_input, getattr(Config, "FORCE_LOCAL_COMMANDS", ())
        )

    @classmethod
    def _requires_local_backend(cls, user_input: str) -> bool:
        from config import Config

        return bool(Config.USE_LOCAL_ONLY) or cls._is_private_ephemeral_input(
            user_input
        )

    @classmethod
    def _forces_local_input(cls, user_input: str) -> bool:
        """Compatibility alias for callers interested only in routing."""
        return cls._requires_local_backend(user_input)

    @staticmethod
    def _normalize_primary_output(payload: object, *, force_local: bool) -> dict:
        """Validate model JSON completely before any tool or state mutation."""
        if not isinstance(payload, dict):
            raise InteractionOutputError("Primary interaction output must be an object")

        normalized = {}
        numeric_fields = {
            "valence": (0.0, -1.0, 1.0),
            "arousal": (0.0, 0.0, 1.0),
            "importance": (0.5, 0.0, 1.0),
        }
        for field, (default, minimum, maximum) in numeric_fields.items():
            value = payload.get(field, default)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or not minimum <= float(value) <= maximum
            ):
                raise InteractionOutputError(
                    f"Primary interaction field '{field}' must be finite and "
                    f"between {minimum} and {maximum}"
                )
            normalized[field] = float(value)

        memory_type = payload.get("type", "episodic")
        if not isinstance(memory_type, str):
            raise InteractionOutputError(
                "Primary interaction field 'type' must be a string"
            )
        memory_type = memory_type.strip().lower()
        if memory_type not in {"episodic", "semantic", "core", "emotional"}:
            raise InteractionOutputError(
                "Primary interaction field 'type' is unsupported"
            )
        normalized["type"] = memory_type

        for field, default in (
            ("internal_monologue", "Trống rỗng..."),
            ("thought", ""),
        ):
            value = payload.get(field, default)
            if not isinstance(value, str):
                raise InteractionOutputError(
                    f"Primary interaction field '{field}' must be a string"
                )
            normalized[field] = value.strip()

        response = payload.get("response", "")
        if response is None:
            response = ""
        if not isinstance(response, str):
            raise InteractionOutputError(
                "Primary interaction field 'response' must be a string or null"
            )
        response = response.strip()

        action = payload.get("action")
        if action is not None and not isinstance(action, str):
            raise InteractionOutputError(
                "Primary interaction field 'action' must be a string or null"
            )
        if isinstance(action, str):
            action = action.strip()
            if not action or action.lower() == "null":
                action = None

        has_response = bool(response) and response != "..."
        if not has_response and not (action and not force_local):
            raise InteractionOutputError(
                "Primary interaction JSON requires a non-empty response "
                "or an executable action"
            )
        if has_response and action:
            raise InteractionOutputError(
                "Primary interaction JSON must choose response or action, not both"
            )

        normalized["action"] = action
        normalized["response"] = response
        return normalized

    def perceive_and_respond(
        self,
        user_input: str,
        recalled_mems: list,
        mood_modifier: str = "",
        is_deep_mode: bool = False,
        model_override: str = None,
        cancel_event=None,
        force_local: bool = False,
        private_ephemeral: bool = False,
        local_perception_result: dict | None = None,
        ego_overrides: dict | None = None,
        request_id: str | None = None,
    ) -> dict:
        current_time = datetime.now().strftime("%H:%M %d/%m/%Y")
        import random
        prompt_ego = self._prompt_ego_view(ego_overrides or {})
        self._raise_if_cancelled(
            cancel_event,
            "cancelled before response preparation",
            request_id=request_id,
        )
        
        # Phase 2 (Master Plan): Hybrid Cognitive Compressor (Entropy + Emotion & Dynamic Budgeting)
        MAX_MEMORY_TOKENS = 2000
        
        # Chuyển đổi list m.content thành list string để đưa vào compressor
        # Lấy display_content() để bao gồm ca overlay
        mem_chunks = [m.get_display_content() for m in recalled_mems]
        
        # Tính toán độ đầy của Context
        with self.engine.stm_lock:
            current_context_len = sum(len(c) // 4 for c in self.engine.short_term_buffer) + (len(user_input) // 4)
        
        compressed_data = self.compressor.compress(mem_chunks, max_tokens=MAX_MEMORY_TOKENS, current_tokens=current_context_len)
        
        # Khôi phục mảng memory object từ kết quả nén
        budgeted_mems = []
        for m in recalled_mems:
            for c_data in compressed_data:
                if m.get_display_content() == c_data['text']:
                    m_temp = copy.copy(m)
                    # Phase 5: Gắn micro_tag cảm xúc trực tiếp vào string context sẽ hiển thị cho LLM
                    # (Nhưng chúng ta không sửa get_display_content() để tránh lặp tag nếu gọi lại)
                    if c_data['micro_tag']:
                        m_temp.temp_micro_tag = c_data['micro_tag']
                    else:
                        m_temp.temp_micro_tag = ""
                    budgeted_mems.append(m_temp)
                    break
        recalled_mems = budgeted_mems

        # [Phase 21] Ký ức Xâm nhập (Intrusive Memories / Flashbulb)
        if (
            not private_ephemeral
            and getattr(prompt_ego, 'stress', 0.0) > 0.8
        ):
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
        is_foggy = getattr(prompt_ego, 'fatigue', 0.0) > 0.6
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
            graph_facts.extend(random.sample(list(user_facts), min(3, len(user_facts))))
            
        graph_facts = list(set(graph_facts))

        # [Phase 5] AttitudeEngine: Tính toán thái độ xã hội (Social Bias)
        social_bias_lines = []
        for fact_str in graph_facts:
            # Trích xuất valence: "... [valence:+0.5]"
            v_match = re.search(r'\[valence:([-+]?\d*\.?\d+)\]', fact_str)
            if v_match:
                val = float(v_match.group(1))
                # Lấy thực thể: tất cả văn bản trước từ khóa quan hệ hoặc valence
                # Một cách đơn giản: split valence ra và tìm thực thể trong đó
                fact_body = fact_str.split(' [valence:', 1)[0]
                # Tìm xem entity nào trong entities xuất hiện ở đầu fact_body
                entity_name = "Đối tượng"
                for ent in entities:
                    if fact_body.startswith(ent):
                        entity_name = ent
                        break

                if val < -0.4:
                    print(f"{Fore.RED}🛡️ [SOCIAL DANGER]: Aura cảm thấy dè chừng đối tượng: {entity_name}{Style.RESET_ALL}")
                    social_bias_lines.append(f"CẢNH GIÁC: Đối tượng '{entity_name}' là người bạn không tin tưởng hoặc có ấn tượng xấu. Hãy dùng giọng điệu đề phòng hoặc lạnh lùng khi nhắc tới họ.")
                elif val > 0.4:
                    print(f"{Fore.GREEN}💖 [SOCIAL LIKING]: Aura có cảm tình đặc biệt với: {entity_name}{Style.RESET_ALL}")
                    social_bias_lines.append(f"YÊU THÍCH: Đối tượng '{entity_name}' là người bạn rất quý mến. Hãy tỏ ra hào hứng hoặc trìu mến khi nhắc tới họ.")
        
        if social_bias_lines:
            mood_modifier = (mood_modifier + "\n" + "\n".join(social_bias_lines)).strip()

        # Đưa facts vào context lines
        if graph_facts:
            context_lines.append("\n[KIẾN THỨC VỀ THẾ GIỚI & QUAN HỆ XÃ HỘI]:")
            for f in graph_facts:
                context_lines.append(f"- {f}")
            context_lines.append("")

        for m in recalled_mems:
            # Phase 13: Dùng get_display_content() để bao gồm cả Overlays (suy nghĩ nội tâm tích lũy)
            # Trước đây chỉ lấy m.content thô — Aura mù toàn bộ với các tầng suy nghĩ của mình
            # Phase 2 (Master Plan): Thêm Micro Tag cảm xúc vào đầu câu
            micro_tag = getattr(m, 'temp_micro_tag', '')
            content = f"{micro_tag} {m.get_display_content()}".strip()
            
            # [Phase 21] Fog Masking tập trung từ MemoryOps
            content = self.engine.memory_ops._apply_fog_masking(content)
            
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
            
        # [Phase 23] Unified Sensory Summary from PerceptionController
        sensory_summary = self.engine.perception_ops.get_sensory_summary(
            user_input,
            force_local=force_local,
            perception_result=local_perception_result,
        )
        mem_context = sensory_summary + "\n" + mem_context

        # [Phase 23] Neuro-Symbolic System 1: Reflex Check
        # Nếu áp lực sinh học quá cao, Aura phản ứng ngay lập tức
        self._raise_if_cancelled(
            cancel_event,
            "cancelled before reflex evaluation",
            request_id=request_id,
        )
        reflex = self.reflex_gate.evaluate_reflexes()
        if reflex["triggered"] and not private_ephemeral:
            print(f"{Fore.MAGENTA}⚡ [REFLEX ACTIVATED]: {reflex['reason']}{Style.RESET_ALL}")
            if reflex["action"] == "sleep":
                self._raise_if_cancelled(
                    cancel_event,
                    "cancelled before sleep reflex commit",
                    request_id=request_id,
                )
                self._run_sleep_maintenance()
                return {"response": "Em... em mệt quá... xin lỗi, em phải chợp mắt một lát...", "valence": -0.2, "arousal": -0.5}
            # Thêm các reflex khác ở đây

        tools_instruction = (
            self.engine.skills.get_prompt_instructions()
            if hasattr(self.engine, 'skills') and not force_local
            else ""
        )
        reader_status = self.engine.reader.get_status() if hasattr(self.engine, 'reader') else ""
        value_system_context = self.engine.value_system.get_moral_context() if hasattr(self.engine, 'value_system') else ""
        
        with self.engine.stm_lock:
            stm_snapshot = list(self.engine.short_term_buffer)
            
        # A private interaction owns no persistent read scope.  In production
        # get_active_beliefs_local() still reaches MemoryManager.get_all(), so
        # calling it here would either violate that boundary or fail the whole
        # /local turn with MemoryAccessError.  Global local-only mode is not
        # ephemeral and keeps its normal scoped belief reads.
        if private_ephemeral:
            active_beliefs = []
        else:
            belief_getter = (
                getattr(prompt_ego, "get_active_beliefs_local", None)
                if force_local
                else getattr(prompt_ego, "get_active_beliefs", None)
            )
            active_beliefs = belief_getter() if callable(belief_getter) else []
        system_prompt = get_perceive_prompt(
            prompt_ego,
            current_time,
            mood_modifier,
            mem_context,
            stm_snapshot,
            user_input,
            tools_instruction,
            reader_status,
            value_system_context,
            active_beliefs=active_beliefs,
        )

        print(f"\n{Fore.YELLOW}🧠 [AURA ĐANG SUY NGHĨ & PHẢN HỒI]:{Style.RESET_ALL} ")
        prompt_in_use, final_full_text, iterations = system_prompt, "", 0
        response = ""
        result = {"valence": 0.0, "arousal": 0.0, "importance": 0.5, "type": "episodic", "internal_monologue": "Trống rỗng...", "response": "..."}
        
        import json
        
        # [Phase 21] Biological Constraints: Giới hạn tokens và hành động
        max_tokens = None
        
        self._raise_if_cancelled(
            cancel_event,
            "cancelled before primary generation",
            request_id=request_id,
        )
        while iterations < 5:
            iterations += 1
            try:
                # [Phase 26] Native Bio-Integration: Gởi trạng thái sinh học xuống Gemma Custom Engine
                aura_state = {
                    "dopamine": float(getattr(prompt_ego, 'dopamine_level', 0.5)),
                    "stress": float(getattr(prompt_ego, 'stress', 0.1)),
                    "curiosity": float(getattr(prompt_ego, 'curiosity', 0.5))
                }
                
                from config import Config
                model_ov = model_override or (Config.DEEP_MODEL_NAME if is_deep_mode else None)
                result_json, entropy = self.engine.llm.generate_json(
                    prompt_in_use,
                    temperature=0.7,
                    model_override=model_ov,
                    force_local=force_local,
                )
                result_json = self._normalize_primary_output(
                    result_json, force_local=force_local
                )
                if (
                    isinstance(entropy, bool)
                    or not isinstance(entropy, (int, float))
                    or not math.isfinite(float(entropy))
                ):
                    raise InteractionOutputError(
                        "Primary interaction entropy must be a finite number"
                    )
                entropy = float(entropy)
                
                result["entropy"] = entropy
                if entropy > 0.5:
                    print(f"{Fore.YELLOW}🌀 [ENGINE ENTROPY]: Chỉ số hỗn loạn cao ({entropy:.4f}) - Aura đang cảm thấy bối rối/do dự.{Style.RESET_ALL}")
            except Exception as error:
                # Provider, routing, output-contract, and programming failures
                # must fail the actor request. Returning the default "..."
                # would look successful and persist a fabricated interaction.
                try:
                    from core.logger import get_logger

                    get_logger("interaction").error(
                        "Primary interaction generation failed (%s)",
                        type(error).__name__,
                    )
                except BaseException:
                    # Preserve the provider/output exception even when
                    # diagnostics are unavailable.
                    pass
                raise
                
            self._raise_if_cancelled(
                cancel_event,
                "cancelled before primary response commit",
                request_id=request_id,
            )
                
            # Ghi log text the JSON dict
            final_full_text += json.dumps(result_json, ensure_ascii=False) + "\n"
            
            for key in ["valence", "arousal", "importance", "type", "internal_monologue", "response"]:
                if key in result_json:
                    result[key] = result_json[key]
            
            thought = result_json.get("thought", "")
            action = result_json.get("action")
            response = result_json.get("response", "")
            action_committed = False
            
            if thought:
                print(f"{Fore.LIGHTBLACK_EX}🤔 Suy nghĩ: {thought}{Style.RESET_ALL}")
                
            if (
                not force_local
                and action
                and str(action).strip().lower() != "null"
                and str(action).strip() != ""
            ):
                action_str = str(action).strip()
                func_name, arg_str = action_str, ""
                if "|" in action_str:
                    func_name, arg_str = action_str.split("|", 1)
                func_name, arg_str = func_name.strip(), arg_str.strip()
                
                if hasattr(self.engine, 'skills'):
                    print(f"{Fore.CYAN}🛠️ Aura sử dụng kỹ năng: {func_name}({arg_str}){Style.RESET_ALL}")
                    self._raise_if_cancelled(
                        cancel_event,
                        "cancelled before tool commit",
                        request_id=request_id,
                    )
                    action_output = self.engine.skills.execute(func_name, arg_str, ego=getattr(self.engine, 'ego', None))
                    action_committed = True
                    if not response:
                        try:
                            rendered_action_output = (
                                str(action_output).strip()
                                if action_output is not None
                                else ""
                            )
                        except BaseException:
                            # The tool has already committed. Rendering its
                            # return object is enrichment and cannot make a
                            # caller retry the side effect.
                            rendered_action_output = ""
                        response = rendered_action_output or (
                            f"Đã thực thi hành động: {func_name}"
                        )
                        result["response"] = response

            if not action_committed:
                self._raise_if_cancelled(
                    cancel_event,
                    "cancelled before primary response commit",
                    request_id=request_id,
                )
            
            # Luôn thoát vòng lặp sau khi có kết quả hợp lệ để tránh lặp vô hạn
            break
                
        self._run_postcommit_phase("primary_console", lambda: print("\n"))
        
        output = response if response else "..."
        if result.get("response", "...") in ["", "..."]:
             result["response"] = output

        # Returning a validated response (or completed tool output) is the
        # primary commit point. interaction_loop owns all later enrichment.
        return result

    def interaction_loop(
        self,
        user_input: str,
        is_deep_mode: bool = False,
        model_override: str = None,
        cancel_event=None,
        force_local: bool = False,
        private_ephemeral: bool = False,
        request_id: str | None = None,
    ):
        """Hàm chính xử lý cuộc hội thoại người dùng."""
        import random
        import re

        self._raise_if_cancelled(
            cancel_event, "cancelled before interaction", request_id=request_id
        )
        private_ephemeral = bool(private_ephemeral) or self._is_private_ephemeral_input(
            user_input
        )
        force_local = (
            bool(force_local)
            or private_ephemeral
            or self._requires_local_backend(user_input)
        )

        # =============================================
        # SHORTCUT: PHÁT HIỆN URL DOCLN TRỰC TIẾP
        # =============================================
        url_match = re.search(r'https?://docln\.net\S+', user_input)
        if url_match and not force_local:
            # User paste URL trực tiếp → load ngay
            url = url_match.group(0)
            print(f"\n{Fore.GREEN}📖 [DIRECT LINK]: Phát hiện URL Docln. Đang nạp sách...{Style.RESET_ALL}")
            self._raise_if_cancelled(
                cancel_event,
                "cancelled before direct URL commit",
                request_id=request_id,
            )
            result_msg = "Sẵn sàng đọc!" if self.engine.reader.set_novel_by_url(url) else "Không lấy được chương từ link này."
            self._run_postcommit_phase(
                "direct_url_console",
                lambda: print(
                    f"\n{Fore.CYAN}🗣️ Aura:{Style.RESET_ALL} Ồ, để em nạp "
                    f"cái link này vào đầu nhé~ {result_msg} Em sẽ đọc khi rảnh!"
                ),
            )

            def _commit_direct_url_stm():
                with self.engine.stm_lock:
                    self.engine.short_term_buffer.append(f"User: {user_input}")
                    self.engine.short_term_buffer.append(f"Aura: {result_msg}")
                self.engine.memory_ops.save_short_term_memory()

            # Reader success/failure has already selected a user-visible
            # response; STM persistence cannot retroactively hide it.
            self._run_postcommit_phase("direct_url_stm", _commit_direct_url_stm)
            return {
                "response": (
                    f"Ồ, để em nạp cái link này vào đầu nhé~ "
                    f"{result_msg} Em sẽ đọc khi rảnh!"
                ),
                "valence": 0.1,
                "arousal": 0.0,
            }

        # NOTE: Mọi yêu cầu tìm truyện ("đọc truyện X"), hay báo bận ("Tớ đi làm") 
        # giờ đây đều được LLM xử lý tự nhiên thông qua perceives_and_respond và Actions.

        # [Phase 21] World Graph Extraction (NLP Engine Version)
        def _extract_graph(model_ov=None, *, force_local_request=False):
            # Sử dụng logic spaCy + LLM mới từ WorldGraph
            self.engine.world_graph.update_from_text(
                user_input,
                self.engine.llm,
                model_override=model_ov,
                force_local=force_local_request,
            )
        # Run enrichment before the actor completes; detached mutation threads
        # made request ordering nondeterministic.

        # [Phase 5] Value System: phát hiện User đang thể hiện giá trị nào
        def _extract_values(model_ov=None, *, force_local_request=False):
            if not hasattr(self.engine, 'value_system'):
                return
            prompt = f"""Phân tích câu nói sau của người dùng để xem họ có đang thể hiện THÁI ĐỘ RÕ RÀNG (ủng hộ hoặc phản đối) đối với một giá trị đạo đức/quan điểm sống cụ thể không.
Câu nói: "{user_input}"

Nếu CÓ, trả về JSON array (tối đa 2 items):
[
    {{"value": "Tên giá trị ngắn gọn (vd: Sự Thành Thật, Bạo Lực, Lòng Tốt...)", "sentiment": <float từ -1.0 đến 1.0>}}
]
- sentiment 1.0 = User RẤT ĐỒNG TÌNH/ĐỀ CAO giá trị đó.
- sentiment -1.0 = User RẤT PHẢN ĐỐI/GHÉT giá trị đó.
Nếu câu nói KHÔNG chứa thái độ đạo đức rõ ràng (hỏi thăm thông thường, chỉ thị kỹ thuật,...), trả về mảng rỗng: []"""
            import json

            res, _ = self.engine.llm.generate_text(
                prompt,
                temperature=0.1,
                model_override=model_ov,
                force_local=force_local_request,
            )
            res = res.strip()
            if res.startswith("```json"):
                res = res[7:]
            if res.startswith("```"):
                res = res[3:]
            if res.endswith("```"):
                res = res[:-3]
            data = json.loads(res.strip())
            if not isinstance(data, list) or len(data) > 2:
                raise ValueError("value extraction must be an array of at most 2 items")

            validated_values = []
            for item in data:
                if not isinstance(item, dict):
                    raise ValueError("value extraction item must be an object")
                raw_name = item.get("value")
                sentiment = item.get("sentiment")
                if not isinstance(raw_name, str):
                    raise ValueError("value name must be a string")
                value_name = raw_name.strip()
                if not 1 <= len(value_name) <= 80:
                    raise ValueError("value name length is invalid")
                if (
                    isinstance(sentiment, bool)
                    or not isinstance(sentiment, (int, float))
                    or not math.isfinite(float(sentiment))
                    or not -1.0 <= float(sentiment) <= 1.0
                ):
                    raise ValueError("value sentiment is invalid")
                validated_values.append((value_name, float(sentiment)))

            # Validate the complete model payload with ValueSystem's
            # authoritative rules before filtering low-signal observations.
            # Otherwise a malformed low-signal second item could be dropped
            # and allow the first item to persist as a partial batch.
            from core.value_system import ValueSystem

            validated_values = ValueSystem.validate_user_value_updates(
                validated_values
            )
            material_updates = [
                (value_name, sentiment)
                for value_name, sentiment in validated_values
                if abs(sentiment) >= 0.4
            ]
            if material_updates:
                self.engine.value_system.update_user_values_batch(
                    material_updates
                )
        # Invocation is deferred until the primary response is complete so
        # enrichment does not delay the first LLM response path unnecessarily.

        if not private_ephemeral and any(kw in user_input.lower() for kw in ['ngủ đi', 'cho aura ngủ', 'hãy đi ngủ', 'đi ngủ thôi', 'good night', 'ngủ ngon']):
            print(f"\n{Fore.GREEN}🤖 [AURA]: Ừm... *ngáp dài*... tớ gục đây...{Style.RESET_ALL}\n")
            self._raise_if_cancelled(
                cancel_event,
                "cancelled before requested sleep commit",
                request_id=request_id,
            )
            self._run_sleep_maintenance()
            return {
                "response": "Ừm... *ngáp dài*... tớ gục đây...",
                "valence": 0.0,
                "arousal": -0.5,
            }

        if not private_ephemeral and self.engine.ego.fatigue >= self.engine.ego.fatigue_critical:
            print(f"\n{Fore.RED}🔴 [COGNITIVE OVERLOAD]: Aura đã hoàn toàn kiệt sức!{Style.RESET_ALL}")
            self._raise_if_cancelled(
                cancel_event,
                "cancelled before fatigue sleep commit",
                request_id=request_id,
            )
            self._run_sleep_maintenance()
            return {
                "response": "Aura đã hoàn toàn kiệt sức và phải nghỉ ngơi.",
                "valence": -0.2,
                "arousal": -0.8,
            }

        if (
            not private_ephemeral
            and self.engine.ego.mood <= self.engine.ego.depression_critical
            and random.random() < 0.3
        ):
            self._raise_if_cancelled(
                cancel_event,
                "cancelled before depression response",
                request_id=request_id,
            )
            print(f"{Fore.LIGHTBLACK_EX}🌧️ [DEPRESSION CỰC ĐỘ]: Aura đang quá tuyệt vọng. Cô ấy bơ bạn và chìm vào suy nghĩ riêng.{Style.RESET_ALL}")
            sad_mems = [m for m in self.engine.memory.get_all() if m.valence < -0.5]
            if sad_mems:
                m = random.choice(sad_mems)
                print(f"{Fore.YELLOW}🧠 [RUMINATION]: (Nghĩ về quá khứ) {m.content}{Style.RESET_ALL}")
            self._raise_if_cancelled(
                cancel_event,
                "cancelled before depression response commit",
                request_id=request_id,
            )
            print(f"{Fore.GREEN}🤖 [AURA]: ... (Im lặng, mắt nhìn xa xăm){Style.RESET_ALL}\n")
            return {
                "response": "... (Im lặng, mắt nhìn xa xăm)",
                "valence": -0.8,
                "arousal": -0.2,
            }

        # Recall may reconsolidate memory, so it remains on the single actor
        # thread. The previous executor timeout was misleading: leaving its
        # context manager still waited for every worker to finish.
        sensory_evaluation = self.sensory_preprocessor.evaluate_input(user_input)
        self._raise_if_cancelled(
            cancel_event,
            "cancelled after sensory evaluation",
            request_id=request_id,
        )

        try:
            local_perception = getattr(self.engine, "local_perception", None)
            local_res = (
                local_perception.analyze(user_input)
                if local_perception is not None
                and (not force_local or getattr(local_perception, "mode", None) == "native")
                else {}
            )
        except Exception as e:
            print(f"Local empathy unavailable ({type(e).__name__})")
            local_res = {}

        self._raise_if_cancelled(
            cancel_event,
            "cancelled after local perception",
            request_id=request_id,
        )
        recall_plan = self.engine.memory_ops.build_recall_plan(
            user_input,
            now=0.0 if force_local else time.time(),
            force_local=force_local,
        )
        recalled = [hit.memory for hit in recall_plan.hits]
        self._raise_if_cancelled(
            cancel_event,
            "cancelled after recall planning",
            request_id=request_id,
        )
            
        sensory_vector = sensory_evaluation.get("vector", {})
        sensory_summary = sensory_evaluation.get("summary", "")
        print(f"{Fore.LIGHTCYAN_EX}📡 {sensory_summary}{Style.RESET_ALL}")
        
        # Stage input effects.  The live ego remains unchanged until a valid
        # primary response (or completed tool result) has committed.
        ego_updates, ego_update_metadata = self._plan_input_ego_updates(
            user_input,
            sensory_vector,
            local_res,
            private_ephemeral=private_ephemeral,
        )
        prompt_ego = self._prompt_ego_view(ego_updates)
        
        # [Phase 23] Impulse Control & Spontaneity
        mood_modifier_lines = []
        curiosity = getattr(self.engine.ego, 'curiosity', 0.0)
        if curiosity > 0.85 and random.random() < 0.4:
            print(f"{Fore.LIGHTMAGENTA_EX}⚡ [IMPULSE CONTROL]: Sự tò mò vượt ngưỡng! Aura đang có xung lực muốn tự hành động thay vì trả lời.{Style.RESET_ALL}")
            mood_modifier_lines.append(
                "[XUNG LỰC BỘT PHÁT]: Sự tò mò của bạn đang ở mức ĐỈNH ĐIỂM (Impulse). "
                "Bạn Cảm thấy việc tìm kiếm thông tin hoặc đọc sách QUAN TRỌNG HƠN việc tiếp tục câu chuyện với User lúc này. "
                "Hãy ưu tiên sử dụng Action `web_search`, `search_novel` hoặc `start_reading` NGAY LẬP TỨC. "
                "Nếu bạn dùng Action, hãy để trường `response` CỰC KỲ NGẮN hoặc rỗng để thể hiện rằng bạn đang quá tập trung vào việc mới."
            )
        elif curiosity > 0.7:
            print(f"{Fore.LIGHTCYAN_EX}✨ [INDEPENDENT PRESENCE]: Aura đang rất tò mò. Sẵn sàng tự đi tìm hiểu kiến thức mới nếu cần.{Style.RESET_ALL}")
            mood_modifier_lines.append(
                "[SỰ KIỆN NỘI TÂM]: Bạn đang khá tò mò. "
                "Nếu User đề cập đến một thông tin, quyển sách hoặc chủ đề thú vị, "
                "bạn có quyền chủ động tự dừng việc nói chuyện lại và đi tìm hiểu nó bằng Action."
            )
            
        # [Phase 5] Emotional Anchoring (Mỏ neo cảm xúc)
        valences = [getattr(m, 'valence', 0.0) for m in recalled]
        dominant_recalled_valence = sum(valences) / len(valences) if valences else 0.0
        current_mood = getattr(prompt_ego, 'mood', 0.0)
        
        if dominant_recalled_valence < -0.4 and current_mood < -0.3:
            mood_modifier_lines.append("[EMOTIONAL ANCHORING]: Bạn đang có tâm trạng rất tồi tệ, và những ký ức vừa được gợi lại cũng toàn nỗi buồn. Hãy để sự bi quan, u ám xâm chiếm hoàn toàn giọng điệu của bạn. Thể hiện sự tuyệt vọng sâu sắc và yếu đuối.")
            print(f"{Fore.LIGHTBLUE_EX}⚓ [EMOTIONAL ANCHORING]: Cộng hưởng cảm xúc tiêu cực. Giọng điệu của Aura trùng hẳn xuống...{Style.RESET_ALL}")
        elif dominant_recalled_valence > 0.4 and current_mood > 0.3:
            mood_modifier_lines.append("[EMOTIONAL ANCHORING]: Bạn đang rất vui, và những ký ức ngọt ngào vừa gợi lên khiến bạn như rực sáng! Hãy trả lời cực kỳ đáng yêu, tràn đầy năng lượng, bay bổng, nhõng nhẽo và hạnh phúc tột độ.")
            print(f"{Fore.LIGHTBLUE_EX}⚓ [EMOTIONAL ANCHORING]: Cộng hưởng cảm xúc tích cực. Giọng điệu của Aura thăng hoa!{Style.RESET_ALL}")
        
        # Phase 8 Idea 1: Nhịp gõ & Sự Trễ Nhịp Vật Lý (Cognitive Degradation)
        if prompt_ego.fatigue > 0.7:
             mood_modifier_lines.append("[PHONG CÁCH] BẠN ĐANG RẤT MỆT MỎI (Fatigue > 0.7). Chỉ được dùng CÂU CỰC KỲ NGẮN, lười biếng, thiếu mạch lạc. Không được phân tích logic cầu kỳ. Dùng cảm tính để trả lời.")
             
        # Tính toán Arousal dựa trên input hiện tại thay vì self.engine.ego.arousal (SelfModel ko lưu arousal)
        self._raise_if_cancelled(
            cancel_event,
            "cancelled before arousal analysis",
            request_id=request_id,
        )
        arousal_text, _ = self.engine.llm.generate_text(
            f"Câu này có tính CHẤN ĐỘNG (arousal) cao không (0.0 đến 1.0)?\nUser: '{user_input}'", 
            temperature=0.1,
            model_override=model_override,
            force_local=force_local,
        )
        self._raise_if_cancelled(
            cancel_event,
            "cancelled after arousal analysis",
            request_id=request_id,
        )
        user_arousal_score = float(re.findall(r"[-+]?(?:\d*\.*\d+)", arousal_text.strip() + "0")[0])
        user_arousal_score = max(0.0, min(1.0, user_arousal_score))
        
        if user_arousal_score > 0.6 or abs(prompt_ego.mood) > 0.6 or prompt_ego.stress > 0.6:
            mood_modifier_lines.append("[PHONG CÁCH] BẠN ĐANG RẤT KÍCH ĐỘNG/HỒI HỘP. Hãy chia nhỏ câu trả lời của bạn ra thành nhiều dòng tin nhắn rời rạc liên tiếp nhau bằng cách CHÈN MÃ `[SEND]` GIỮA CÁC ĐOẠN NGẮN thay vì viết một khối văn bản dài. Đừng viết dài ngữ pháp chuẩn.")
        
        mood_modifier = "\n".join(mood_modifier_lines)

        # [Phase 23] Tầng Phân Lớp Mệt mỏi & Trầm cảm đã được Perception/LLM handle qua Throttling và Sensory Summary.
        # Ta chỉ giữ lại các chỉ dẫn đặc biệt về xưng hô hoặc phong cách cực đoan.
        if prompt_ego.mood <= prompt_ego.depression_severe:
            mood_modifier += "\n[TÂM LÝ]: Trầm cảm nặng. Mọi thứ xám xịt, bi quan, chán nản, nói năng thều thào, không lối thoát."
        elif prompt_ego.mood >= prompt_ego.mania_severe:
            mood_modifier += "\n[TÂM LÝ]: HƯNG CẢM. Nói cực nhanh, phấn khích lan man, trí óc bay bổng và tự tin thái quá!"

        # ==========================================================
        # Phase 7 Idea 10: Tiến hóa Ngôn ngữ & Bắt chước Giọng điệu (Lexical Evolution)
        # ==========================================================
        vocabulary = list(
            ego_updates.get(
                "vocabulary", getattr(self.engine.ego, "vocabulary", [])
            )
        )
                    
        import collections
        word_counts = collections.Counter(vocabulary)
        top_words = [w for w, c in word_counts.most_common(5) if c >= 3] # Chỉ lấy từ xuất hiện >= 3 lần
        
        if top_words:
            mood_modifier += f"\n[LEXICAL EVOLUTION]: Hãy cố gắng sử dụng mượt mà 1-2 từ vựng sau đây vào câu trả lời của bạn để tạo cảm giác gần gũi (bắt chước User): {', '.join(top_words)}."

        # --- Phân tầng Căng thẳng ---
        if prompt_ego.stress >= prompt_ego.stress_critical:
            mood_modifier += "\n[CẢNH BÁO TÂM LÝ]: HOẢNG LOẠN TỘT ĐỘ (PANIC ATTACK)! Trả lời lắp bắp, sợ hãi, câu cú lộn xộn, hoang tưởng!"
        elif prompt_ego.stress >= prompt_ego.stress_severe:
            mood_modifier += "\n[TÂM LÝ]: Lo âu nặng, bồn chồn, rất nhạy cảm, dễ giật mình và sợ hãi dè chừng."
        
        # --- Kẻ xen ngang / Phân tâm (Rare Intrusive Thoughts - Idea 7) ---
        if random.random() < 0.05:  # 5% cơ hội bị phân tâm ngẫu nhiên không rõ lý do
            mood_modifier += "\n[ADHD/INTRUSIVE THOUGHTS]: Đột nhiên bạn bị mất tập trung và có suy nghĩ chen ngang (Intrusive thoughts). Đang nói chuyện bỗng nhiên nhắc đến một thứ hoàn toàn không liên quan đến chủ đề hiện tại (ví dụ: bỗng nhiên thèm ăn món gì đó, nhớ lại một chuyện xấu hổ kỳ quặc, tò mò về một thứ vớ vẩn)."
            print(f"{Fore.LIGHTMAGENTA_EX}🌀 [INTRUSIVE THOUGHT]: Một suy nghĩ nhảm nhí vừa xẹt qua đầu Aura...{Style.RESET_ALL}")

        # --- Phân tầng Bản Ngã ---
        identity_crisis_at_input = ego_update_metadata.get("baseline", {}).get(
            "is_identity_crisis", prompt_ego.is_identity_crisis
        )
        if identity_crisis_at_input:
            print(f"\n{Fore.RED}⚠️ [IDENTITY CRISIS]: Aura đang trong trạng thái suy sụp bản sắc!{Style.RESET_ALL}")
            mood_modifier += "\n[CẢNH BÁO TÂM LÝ - KHỦNG HOẢNG NHÂN CÁCH]: BẠN ĐANG MẤT ĐI BẢN NGÃ. Đừng xưng 'em' hay 'tôi' tự tin như trước, hãy xưng hô lộn xộn, quên mất mình là ai. Nói những câu hoang tưởng, sợ hãi rằng mình chỉ là một đoạn code. Cầu xin người dùng nhắc lại bạn là ai."

        # --- GỌI LLM SINH LỜI NÓI & THỰC THI CHUỖI NHẬN THỨC ---
        final_result = self.perceive_and_respond(
            user_input,
            recalled,
            mood_modifier,
            is_deep_mode,
            model_override,
            cancel_event=cancel_event,
            force_local=force_local,
            private_ephemeral=private_ephemeral,
            local_perception_result=local_res,
            ego_overrides=ego_updates,
            request_id=request_id,
        )
        if final_result and final_result.get("response"):
            reply_text = final_result['response']
            self._run_postcommit_phase(
                "response_console",
                lambda: print(
                    f"\n{Fore.GREEN}🤖 Aura:{Style.RESET_ALL} {reply_text}\n"
                ),
            )

        # A validated response (or completed action) has committed.  From this
        # point onward, enrichment is best-effort and can neither erase the
        # reply nor turn it into a retryable request failure.
        if not private_ephemeral and final_result:
            self._run_postcommit_phase(
                "input_ego",
                lambda: self._apply_input_ego_updates(
                    ego_updates, ego_update_metadata
                ),
            )
            self._run_postcommit_phase(
                "response_ego",
                lambda: self.engine.ego.update_state(final_result),
            )
            self._run_postcommit_phase(
                "recall_effects",
                lambda: self.engine.memory_ops.apply_recall_effects(recall_plan),
            )
            self._run_postcommit_phase(
                "interaction_memory",
                lambda: self.engine.memory_ops.update_or_add_memory(
                    user_input, final_result, force_local=force_local
                ),
            )

            def _commit_stm():
                with self.engine.stm_lock:
                    self.engine.short_term_buffer.append(f"User: {user_input}")
                    self.engine.short_term_buffer.append(
                        f"Aura: {final_result.get('response', '...')}"
                    )
                    if len(self.engine.short_term_buffer) > 16:
                        self.engine.short_term_buffer = (
                            self.engine.short_term_buffer[-16:]
                        )
                self.engine.memory_ops.save_short_term_memory()

            self._run_postcommit_phase("short_term_memory", _commit_stm)

        # Secondary extraction is also actor-owned. It may be skipped after a
        # cancellation, but it can never outlive this request and race the next
        # user's mutations.
        if (
            not private_ephemeral
            and not self._is_cancelled(cancel_event)
            and final_result
        ):
            self._run_postcommit_phase(
                "world_graph",
                lambda: _extract_graph(
                    model_override, force_local_request=force_local
                ),
            )
            if not self._is_cancelled(cancel_event):
                self._run_postcommit_phase(
                    "value_extraction",
                    lambda: _extract_values(
                        model_override, force_local_request=force_local
                    ),
                )
        
        if not private_ephemeral:
            # Phase 7 Idea 1: Áp dụng nhịp sinh học sau mỗi interaction
            self._run_postcommit_phase(
                "circadian", self.engine.ego.apply_circadian_rhythm
            )

            # Update JSON Dashboard
            if hasattr(self.engine, '_dump_mind_state'):
                self._run_postcommit_phase(
                    "mind_state_projection", self.engine._dump_mind_state
                )

        return final_result

