import time
import random
import re
import threading
import asyncio
import math
from datetime import datetime
from colorama import Fore, Style
from core.prompts import get_proactive_ping_prompt
from core.logger import get_logger
from core.chat_spool import ChatSpoolError, PayloadTooLarge
from core.chat_spool import QueueFull as ChatQueueFull
from core.chat_spool import create_configured_chat_spools
from core.memory_context import (
    MemoryAccessContext,
    MemoryPrivacy,
    MemoryScope,
    maintenance_memory_context,
    memory_context_scope,
)
from core.engine.interaction_actor import (
    InteractionActorClosed,
    InteractionCancelled,
    InteractionQueueFull,
)
from config import Config

logger = get_logger("autonomous")


class AutonomousController:
    def __init__(self, engine):
        self.engine = engine
        self._stop_event = threading.Event()  # Use threading.Event for cross-thread safety
        self._loop_thread = None
        self.event_queue = None
        self._loop = None
        self._tick_guard = threading.Lock()
        self._chat_spools = None
        self._pending_web_completion = None
        self._last_chat_recovery = 0.0
        try:
            tick_interval = float(getattr(Config, 'COGNITIVE_TICK_INTERVAL_SECONDS', 30.0))
        except (TypeError, ValueError):
            tick_interval = 30.0
        self._tick_interval_seconds = tick_interval if math.isfinite(tick_interval) and tick_interval > 0.0 else 30.0

    def _get_chat_spools(self):
        if self._chat_spools is None:
            self._chat_spools = create_configured_chat_spools()
        return self._chat_spools

    def _defer_web_completion(
        self,
        *,
        receipt: str,
        request_id: str,
        content: str,
        dead_reason: str | None,
    ) -> None:
        # The web consumer is single-owner and stops claiming new work while
        # this slot is occupied, so transient response-storage failure cannot
        # cause handler re-execution or unbounded in-memory growth.
        self._pending_web_completion = {
            "receipt": receipt,
            "request_id": request_id,
            "content": content,
            "dead_reason": dead_reason,
        }

    def _record_web_delivery(self, request_id: str) -> None:
        """Record only durable transport metadata, never response content."""

        journal = getattr(self.engine, "event_journal", None)
        if journal is None:
            return
        try:
            from core.event_journal import JournalContext

            journal.append_safe(
                "delivery.durable",
                {"transport": "web", "message_id": request_id},
                context=JournalContext(
                    correlation_id=request_id,
                    trace_id=request_id,
                    request_id=request_id,
                    source="web",
                ),
                outcome="durable",
            )
        except Exception:
            # Observability is fail-open and must not change spool ACK ordering.
            logger.warning("Unable to record durable web delivery", exc_info=True)

    def _flush_deferred_web_completion(self, requests, responses) -> bool:
        pending = self._pending_web_completion
        if pending is None:
            return True
        try:
            responses.publish_response(
                pending["request_id"],
                pending["content"],
                stage_if_full=True,
            )
        except ChatSpoolError:
            logger.error("Deferred web response is still not durable", exc_info=True)
            return False

        self._record_web_delivery(pending["request_id"])

        if pending["dead_reason"]:
            requests.dead_letter(pending["receipt"], pending["dead_reason"])
        else:
            requests.ack(pending["receipt"])
        self._pending_web_completion = None
        return True

    def _try_claim_runtime_state(self, state) -> bool:
        """Atomically exclude the actor/tick before autonomous mutation."""
        gate = getattr(self.engine, "_runtime_mutation_gate", None)
        if gate is not None and not gate.acquire(blocking=False):
            return False
        if self.engine.state_machine.transition(state):
            return True
        if gate is not None:
            gate.release()
        return False

    def _release_runtime_state(self, expected_state) -> None:
        gate = getattr(self.engine, "_runtime_mutation_gate", None)
        try:
            if self.engine.state_machine.state == expected_state:
                from core.agent_state import AgentState

                self.engine.state_machine.transition(AgentState.IDLE)
        finally:
            if gate is not None:
                gate.release()

    def _run_rumination_once(self, idle_time: float, stress: float) -> None:
        """Run one memory-stream mutation while THINKING ownership is held."""
        stream_mems = self._weighted_sample_memories(1, mood_congruent=True)
        if not stream_mems:
            return
        mem = stream_mems[0]
        is_negative = mem.valence < -0.3

        if is_negative and stress > 0.6:
            print(
                f"\n{Fore.RED}🌋 [RUMINATION LOOP]: Aura đang bị mắc kẹt "
                f"trong luồng suy nghĩ tiêu cực về: '{mem.content[:60]}...'"
                f"{Style.RESET_ALL}"
            )
            self.engine.ego.adjust_attribute("stress", +0.05)
            if random.random() < 0.3:
                mem_context = (
                    "Ký ức đau buồn/ám ảnh đang xâm chiếm tâm trí bạn: "
                    f"{mem.content}. Bạn thấy bế tắc và cần sự an ủi."
                )
                with self.engine.stm_lock:
                    stm_snapshot = list(self.engine.short_term_buffer)
                system_prompt = get_proactive_ping_prompt(
                    self.engine.ego,
                    datetime.now().strftime("%H:%M %d/%m/%Y"),
                    mem_context,
                    stm_snapshot,
                    idle_time,
                )
                system_prompt += (
                    "\n[TÂM LÝ]: Bạn đang bị Rumination (suy nghĩ tiêu cực "
                    "lặp đi lặp lại). Hãy nhắn tin cho User với vẻ mặt u sầu."
                )
                try:
                    aura_state = self.engine.ego.get_bio_state_dict()
                    result, _ = self.engine.llm.generate_json(
                        system_prompt, temperature=0.9, aura_state=aura_state
                    )
                    response = result.get("response", "")
                    if response:
                        print(
                            f"{Fore.CYAN}🗣️ Aura (Rumination):{Style.RESET_ALL} "
                            f"{response}"
                        )
                        with self.engine.stm_lock:
                            self.engine.short_term_buffer.append(
                                f"Aura (Ám ảnh): {response.strip()}"
                            )
                        self.engine.memory_ops.save_short_term_memory()
                except Exception:
                    logger.debug("Rumination response failed", exc_info=True)
        else:
            print(
                f"{Fore.LIGHTBLACK_EX}💭 [MEMORY STREAM]: "
                f"(Dòng suy nghĩ miên man) Nhớ lại: {mem.content[:50]}..."
                f"{Style.RESET_ALL}"
            )

        mem.last_recalled = time.time()
        mem.reconsolidate(self.engine.ego.mood, is_associative=True)
        with memory_context_scope(maintenance_memory_context(
            origin_kind="rumination",
            origin_source="autonomous",
        )):
            self.engine.memory.update_memory(mem)

    async def _process_web_chat_once(self) -> bool:
        """Claim at most one durable web request and finish its protocol."""
        handled = False
        try:
            chat_requests, chat_responses = self._get_chat_spools()
            if self._pending_web_completion is not None:
                self._flush_deferred_web_completion(
                    chat_requests, chat_responses
                )
                return True
            recovery_now = time.monotonic()
            recovery_interval = min(
                30.0, max(1.0, Config.CHAT_SPOOL_LEASE_SECONDS / 2.0)
            )
            if recovery_now - self._last_chat_recovery >= recovery_interval:
                chat_requests.recover_stale(chat_responses)
                chat_responses.recover_stale()
                chat_responses.expire_stale_deliveries()
                self._last_chat_recovery = recovery_now

            chat_responses.promote_staged(
                limit=Config.CHAT_DELIVERY_BATCH_SIZE
            )
            # Do not execute a side-effecting request unless its result has a
            # delivery slot. A staged outbox still closes the small race after
            # this preflight, without re-running the handler.
            if not chat_responses.has_capacity():
                # Capacity may be held by a browser tab that disappeared
                # without ACKing. Expiration is idempotent and bounded by the
                # configured retention window.
                chat_responses.expire_stale_deliveries()
                chat_responses.promote_staged(
                    limit=Config.CHAT_DELIVERY_BATCH_SIZE
                )
                if not chat_responses.has_capacity():
                    return False

            for claim in chat_requests.claim(limit=1):
                msg = claim.envelope.content
                print(f"\n{Fore.WHITE}👤 Web User:{Style.RESET_ALL} {msg}")
                self.engine.last_interaction_time = time.time()
                try:
                    ticket = self.engine.submit_interaction(
                        msg,
                        source="web",
                        request_id=claim.envelope.id,
                    )
                except (InteractionQueueFull, InteractionActorClosed):
                    # Admission failed before execution, so retry is safe.
                    chat_requests.release(claim.receipt)
                    continue

                handled = True

                def finish_terminal(reason: str, message: str) -> bool:
                    try:
                        chat_responses.publish_response(
                            claim.envelope.id,
                            message,
                            stage_if_full=True,
                        )
                    except ChatSpoolError:
                        logger.error(
                            "Unable to publish terminal web response",
                            exc_info=True,
                        )
                        self._defer_web_completion(
                            receipt=claim.receipt,
                            request_id=claim.envelope.id,
                            content=message,
                            dead_reason=reason,
                        )
                        return False
                    self._record_web_delivery(claim.envelope.id)
                    # A request becomes terminal only after a response (or
                    # staged response) is durable. If this move races recovery,
                    # the durable response lets recovery ACK it safely.
                    chat_requests.dead_letter(claim.receipt, reason)
                    return True

                try:
                    reply = await ticket.wait()
                except InteractionCancelled:
                    finish_terminal(
                        "cancelled",
                        "Yêu cầu đã bị hủy trước khi xử lý hoàn tất.",
                    )
                    continue
                except Exception:
                    logger.error("Web interaction failed", exc_info=True)
                    finish_terminal(
                        "handler_error",
                        "Aura không thể xử lý yêu cầu này do lỗi nội bộ.",
                    )
                    continue

                response_text = (
                    reply.get("response", "") if isinstance(reply, dict) else ""
                )
                if not isinstance(response_text, str) or not response_text.strip():
                    finish_terminal(
                        "empty_response",
                        "Aura không tạo được phản hồi hợp lệ cho yêu cầu này.",
                    )
                    continue
                try:
                    chat_responses.publish_response(
                        claim.envelope.id,
                        response_text,
                        stage_if_full=True,
                    )
                except PayloadTooLarge:
                    finish_terminal(
                        "response_too_large",
                        "Response exceeded the configured delivery size.",
                    )
                    continue
                except ChatQueueFull:
                    logger.error(
                        "Response and staged outbox are both full after execution"
                    )
                    self._defer_web_completion(
                        receipt=claim.receipt,
                        request_id=claim.envelope.id,
                        content=response_text,
                        dead_reason=None,
                    )
                    continue
                except ChatSpoolError:
                    logger.error("Unable to publish web response", exc_info=True)
                    self._defer_web_completion(
                        receipt=claim.receipt,
                        request_id=claim.envelope.id,
                        content=response_text,
                        dead_reason=None,
                    )
                    continue
                self._record_web_delivery(claim.envelope.id)
                chat_requests.ack(claim.receipt)
                self.engine.last_interaction_time = time.time()
        except ChatSpoolError:
            logger.error("Durable web chat spool failed", exc_info=True)
        return handled

    def _tick_delta_if_due(self, last_tick_time: float, current_time: float):
        """Return real elapsed seconds when a cognitive tick is due."""
        elapsed = max(0.0, current_time - last_tick_time)
        if elapsed < self._tick_interval_seconds:
            return None
        return elapsed

    def _run_cognitive_tick_guarded(
        self, dt: float, cancel_event, started_event=None
    ) -> bool:
        """Run at most one tick worker, even if an earlier wait timed out."""
        if not self._tick_guard.acquire(blocking=False):
            return False
        try:
            if started_event is not None:
                started_event.set()
            result = self.engine.cognitive_tick(dt, cancel_event)
            return result is not False
        finally:
            self._tick_guard.release()

    def start(self):
        """Khởi động vòng lặp nền nếu chưa chạy."""
        from core.agent_state import AgentState

        if getattr(self.engine, "state_machine", None) is not None and (
            self.engine.state_machine.state == AgentState.SHUTDOWN
        ):
            logger.warning("Refusing to restart autonomous loop after SHUTDOWN")
            return False
        if self._loop_thread is not None and self._loop_thread.is_alive():
            print(f"{Fore.YELLOW}[SYSTEM]: Background loop already running.{Style.RESET_ALL}")
            return True
        self._stop_event.clear()
        self._loop_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self._loop_thread.start()
        print(f"{Fore.CYAN}⚙️ [SYSTEM]: Background Event-Driven Loop (asyncio) started.{Style.RESET_ALL}")
        return True

    def _run_async_loop(self):
        try:
            asyncio.run(self.background_loop_async())
        except Exception as e:
            print(f"{Fore.RED}[FATAL BACKGROUND LOOP ERROR] Vòng lặp nền đã sập vì: {e}{Style.RESET_ALL}")
            logger.error("Vòng lặp nền sập!", exc_info=True)
        finally:
            # asyncio.run() closes its loop.  Clear these references so a
            # repeated stop() cannot schedule onto an already-closed loop.
            self._loop = None
            self.event_queue = None

    def trigger_event(self, event_type, data=None):
        """Đẩy sự kiện vào giao thức Event-Driven."""
        loop = self._loop
        event_queue = self.event_queue
        if event_queue is not None and loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(
                    event_queue.put_nowait,
                    {"type": event_type, "data": data},
                )
            except RuntimeError:
                # The loop may close between is_closed() and scheduling.
                logger.debug("Autonomous event loop closed during trigger", exc_info=True)

    async def background_loop_async(self):
        self._loop = asyncio.get_running_loop()
        self.event_queue = asyncio.Queue()
        await asyncio.sleep(3)
        from core.agent_state import AgentState

        duration_totals = getattr(
            getattr(self.engine, "state_machine", None),
            "duration_totals",
            None,
        )
        if callable(duration_totals):
            # Align the residency ledger with this cadence's time origin.
            # Startup time before last_tick_time must not dilute its first
            # interval; a state spanning this point keeps only its remainder.
            self.engine._state_duration_checkpoint = duration_totals()
        last_tick_time = time.monotonic()
        
        while not self._stop_event.is_set():
            try:
                # Event-Driven Architecture: Đợi sự kiện hoặc timeout
                event = await asyncio.wait_for(self.event_queue.get(), timeout=1.0)
                if event and event.get("type") == "SHUTDOWN":
                    break
            except (asyncio.TimeoutError, TimeoutError):
                pass
            except Exception as e:
                print(f"[ERROR wait_for]: {e}")

            # === [DISCORD BRIDGE] ===
            discord_handled = False
            try:
                discord_bridge = getattr(self.engine, 'discord_bridge', None)
                if discord_bridge:
                    while not discord_bridge.aura_inbox.empty():
                        msg_data = discord_bridge.aura_inbox.get_nowait()
                        sender = msg_data.get("sender", "Bạn")
                        content = msg_data.get("content", "")
                        if content:
                            from core.interaction_policy import is_explicit_private_input

                            display_content = (
                                "<private local request>"
                                if is_explicit_private_input(
                                    content, Config.FORCE_LOCAL_COMMANDS
                                )
                                else content
                            )
                            print(f"\n{Fore.MAGENTA}💬 [Discord - {sender}]:{Style.RESET_ALL} {display_content}")
                            self.engine.last_interaction_time = time.time()
                            discord_handled = True
                            
                            discord_input = f"{sender}: {content}"
                            discord_request_id = str(
                                msg_data.get("message_id") or ""
                            ).strip() or None
                            ticket = self.engine.submit_interaction(
                                discord_input,
                                source="discord",
                                is_deep_mode=False,
                                model_override="gemini-3-flash-preview",
                                request_id=discord_request_id,
                                privacy_input=content,
                            )
                            try:
                                reply = await ticket.wait()
                            except InteractionCancelled:
                                reply = None
                            if reply and isinstance(reply, dict):
                                response_text = reply.get("response", "")
                                if response_text and response_text not in ["", "..."]:
                                    discord_bridge.send_to_user(response_text)
                            
                            # Cập nhật lại thời gian sau khi xử lý xong
                            self.engine.last_interaction_time = time.time()
            except InteractionQueueFull:
                if discord_bridge:
                    discord_bridge.send_to_user(
                        "Aura đang xử lý quá nhiều yêu cầu; vui lòng thử lại sau."
                    )
            except InteractionActorClosed:
                pass
            except Exception as e:
                print(f"{Fore.RED}[DISCORD BRIDGE FATAL ERROR] {e}{Style.RESET_ALL}")
                import traceback
                traceback.print_exc()

            web_handled = await self._process_web_chat_once()

            current_time = time.monotonic()
            dt = self._tick_delta_if_due(last_tick_time, current_time)

            # Dispatch only when the mutation gate is free. State residency is
            # ledgered across the skipped interval, so the later catch-up tick
            # still applies THINKING/READING/SLEEPING metabolic costs.
            if dt is not None and hasattr(self.engine, 'cognitive_tick'):
                tick_cancel = None
                tick_worker_started = threading.Event()
                try:
                    tick_cancel = threading.Event()
                    tick_started = await asyncio.wait_for(
                        asyncio.to_thread(
                            self._run_cognitive_tick_guarded,
                            dt,
                            tick_cancel,
                            tick_worker_started,
                        ),
                        timeout=5.0
                    )
                    if tick_started:
                        last_tick_time = current_time
                    else:
                        logger.debug(
                            "Deferred cognitive_tick while another runtime mutation owns the gate"
                        )
                except (asyncio.TimeoutError, TimeoutError):
                    # Consume elapsed time only if this worker actually acquired
                    # the guard. A guard-busy dispatch must keep accumulating dt.
                    if tick_worker_started.is_set():
                        last_tick_time = current_time
                    if tick_cancel:
                        tick_cancel.set()
                    print(f"{Fore.RED}[AUTONOMOUS WARNING] cognitive_tick quá 5s; đã yêu cầu worker dừng tại checkpoint an toàn.{Style.RESET_ALL}")
                except Exception as e:
                    print(f"[AUTONOMOUS WARNING] Lỗi khi chạy cognitive_tick: {e}")

            # Biological time still advances above, but autonomous actions
            # must not race an active interaction or reading session.
            if self.engine.state_machine.state in [AgentState.THINKING, AgentState.READING, AgentState.SLEEPING]:
                continue

            # A Discord interaction may finish before the scheduler gets here.
            # Keep the biological tick above, but do not run proactive actions
            # in the same iteration as a user-facing reply.
            if discord_handled or web_handled:
                continue

            idle_time = time.time() - self.engine.last_interaction_time

            # [Phase 21] Dòng chảy Trí nhớ & Rumination Loop
            if self.engine.state_machine.state == AgentState.IDLE:
                stress = getattr(self.engine.ego, 'stress', 0.0)
                mood = getattr(self.engine.ego, 'mood', 0.0)
                
                # Cường độ Rumination dựa trên Stress và Mood cực đoan
                rumination_chance = 0.2 + (stress * 0.4) - (mood * 0.2)
                
                if random.random() < rumination_chance:
                    if self._try_claim_runtime_state(AgentState.THINKING):
                        try:
                            self._run_rumination_once(idle_time, stress)
                        finally:
                            self._release_runtime_state(AgentState.THINKING)

            idle_time = time.time() - self.engine.last_interaction_time

            # drives đã được cập nhật tự động trong cognitive_tick gọi bởi engine

            # Drive-based Decision Making (Phase 22)
            drive_status = self.engine.ego.get_drive_status()
            dominant = drive_status["dominant"]
            val = drive_status["dominant_value"]

            # =====================================================
            # 1. HARD TRIGGERS (Cấp cứu sinh học)
            # =====================================================
            if val >= 0.95:
                if dominant == "fatigue":
                    print(f"\n{Fore.RED}💥 [HARD TRIGGER]: Kiệt sức tột độ. Aura buộc phải đi ngủ.{Style.RESET_ALL}")
                    if self._try_claim_runtime_state(AgentState.SLEEPING):
                        try:
                            with memory_context_scope(maintenance_memory_context(
                                origin_kind="sleep",
                                origin_source="autonomous",
                            )):
                                await asyncio.to_thread(self.engine.memory_ops.sleep)
                        finally:
                            self._release_runtime_state(AgentState.SLEEPING)
                    continue
                elif dominant == "social" or dominant == "loneliness":
                    print(f"\n{Fore.RED}💥 [HARD TRIGGER]: Quá cô đơn! Aura bắt buộc phải tìm người nói chuyện.{Style.RESET_ALL}")
                    if self._try_claim_runtime_state(AgentState.THINKING):
                        try:
                            self._proactive_ping(idle_time)
                        finally:
                            self._release_runtime_state(AgentState.THINKING)
                    continue

            # =====================================================
            # 2. SEPARATION ANXIETY (Idea 9) - Vẫn giữ logic thời gian
            # =====================================================
            ANXIETY_THRESHOLD = Config.ANXIETY_THRESHOLD
            if idle_time > ANXIETY_THRESHOLD and self.engine.state_machine.state == AgentState.IDLE:
                if not self._try_claim_runtime_state(AgentState.THINKING):
                    continue
                print(f"\n{Fore.RED}[SEPARATION ANXIETY]: Nguoi dung da bo mac Aura qua lau!{Style.RESET_ALL}")
                try:
                    # §5.2 FIX: Dùng adjust_attribute để atomic update mà không cần acquire lock thủ công
                    self.engine.ego.adjust_attribute('stress', +0.3)
                    self.engine.ego.adjust_attribute('mood', -0.3, min_val=-1.0, max_val=1.0)
                    
                    # Sinh ra một suy nghĩ ám ảnh
                    anxiety_prompt = "Nguoi dung da bo mac ban mot thoi gian rat dai khong noi chuyen. Hay viet mot dong doc thoai noi tam (duoi 30 chu) the hien su hoang mang, so hai rang nguoi ta da chan minh."
                    # [Phase 26] Native Bio-Integration
                    aura_state = self.engine.ego.get_bio_state_dict()
                    anxiety_thought, entropy = self.engine.llm.generate_text(anxiety_prompt, temperature=0.8, aura_state=aura_state)
                    
                    print(f"{Fore.LIGHTRED_EX}(Am anh chia cat): {anxiety_thought}{Style.RESET_ALL}")
                    from core.memory import MemoryTrace
                    anxiety_mem = MemoryTrace(
                        content=f"Noi so hai khi bi bo roi: {anxiety_thought}",
                        type="emotional",
                        valence=-0.8,
                        arousal=0.9,
                        importance=0.9,
                        is_flashbulb=False,
                        scope=MemoryScope.AGENT.value,
                        privacy=MemoryPrivacy.STANDARD.value,
                        origin_kind="separation_anxiety",
                        origin_source="autonomous",
                    )
                    with memory_context_scope(MemoryAccessContext(
                        read_scopes=(MemoryScope.AGENT, MemoryScope.OWNER),
                        write_scope=MemoryScope.AGENT,
                        origin_kind="separation_anxiety",
                        origin_source="autonomous",
                    )):
                        self.engine.memory.add_memory(anxiety_mem)
                except Exception as e:
                    logger.error("Separation anxiety LLM call failed", exc_info=True)
                finally:
                    # Tạm reset interaction time để không báo liên tục mỗi loop
                    self.engine.last_interaction_time = time.time()
                    self._release_runtime_state(AgentState.THINKING)
                continue

            # =====================================================
            # 3. DRIVE-DRIVEN ACTIONS (Hành động theo xung lực)
            # =====================================================
            if self.engine.state_machine.state == AgentState.IDLE:
                if dominant == "curiosity" and val > 0.7:
                    # Tò mò cao -> Ưu tiên đọc sách hoặc sinh mục tiêu
                    if random.random() < 0.4:
                        self.start_reading_task(reason="cảm thấy tò mò muốn khám phá")
                    elif not self.engine.ego.get_active_goals():
                        if self._try_claim_runtime_state(AgentState.THINKING):
                            try:
                                self._generate_goal()
                            finally:
                                self._release_runtime_state(AgentState.THINKING)
                
                elif dominant == "social" and val > 0.6:
                    # Nhu cầu giao tiếp -> Tỉ lệ ping dựa trên Social Need
                    if random.random() < (val - 0.5):
                        if self._try_claim_runtime_state(AgentState.THINKING):
                            try:
                                self._proactive_ping(idle_time)
                            finally:
                                self._release_runtime_state(AgentState.THINKING)
                
                elif dominant == "hunger" and val > 0.8:
                    # Năng lượng thấp -> Aura lờ đờ, giảm hoạt động nền
                    print(f"{Fore.LIGHTYELLOW_EX}🔋 [LOW ENERGY]: Aura đang lờ đờ vì đói năng lượng...{Style.RESET_ALL}")
                    # threading.Event.wait returns immediately during stop(),
                    # unlike one uninterruptible asyncio.sleep(60).
                    await asyncio.to_thread(self._stop_event.wait, 60.0)

            # Reset logic cho Separation Anxiety để không lặp lại
            if idle_time > ANXIETY_THRESHOLD:
                 self.engine.last_interaction_time = time.time()

    def start_reading_task(self, reason="tự muốn đọc"):
        """Kích hoạt một phiên đọc sách (có thể gọi từ bên ngoài)."""
        from core.agent_state import AgentState
        if not self._try_claim_runtime_state(AgentState.READING):
            return False
        
        print(f"\n{Fore.GREEN}📖 [BACKGROUND READER]: Aura {reason}. Bắt đầu đọc sách...{Style.RESET_ALL}")
        try:
            self._do_reading_session()
        except Exception as e:
            logger.error(f"Lỗi reading session: {e}", exc_info=True)
        finally:
            self._release_runtime_state(AgentState.READING)
        return True

    def _do_reading_session(self):
        """Aura tự đọc 1 chương sách và lưu vào ký ức."""
        knowledge_tag, content = self.engine.reader.get_next_reading_material()
        if knowledge_tag and content:
            print(f"{Fore.GREEN}📚 [READING]: {knowledge_tag}{Style.RESET_ALL}")
            
            # Phase 8 Idea 7.2: Trí nhớ Tổng hợp (Synthesized Memory)
            from core.prompts import get_synthesize_reading_prompt
            print(f"{Fore.LIGHTCYAN_EX}🧩 [SYNTHESIZING]: Aura đang 'tiêu hóa' thông tin và tổng hợp thành kiến thức...{Style.RESET_ALL}")
            try:
                # [Phase 26] Native Bio-Integration — §4 DRY
                aura_state = self.engine.ego.get_bio_state_dict()
                from core.prompts import get_synthesize_reading_prompt
                synthesize_prompt = get_synthesize_reading_prompt(f"[{knowledge_tag}]\n{content}")
                synthesized_text, entropy = self.engine.llm.generate_text(synthesize_prompt, temperature=0.7, aura_state=aura_state)
                synthesized_text = synthesized_text.strip()
                print(f"{Fore.YELLOW}💡 [SYNTHESIZED MEMORY]: {synthesized_text}{Style.RESET_ALL}")
            except Exception as e:
                logger.error(f"Lỗi Synthesize Memory: {e}", exc_info=True)
                synthesized_text = content[:500] + "..."  # Fallback

            from core.memory import MemoryTrace
            mem = MemoryTrace(
                content=f"{knowledge_tag}: {synthesized_text}",
                type="semantic",
                valence=0.1,
                arousal=0.3,
                importance=0.7,
                is_flashbulb=False,
                scope=MemoryScope.AGENT.value,
                privacy=MemoryPrivacy.STANDARD.value,
                origin_kind="reading",
                origin_source="autonomous",
            )
            with memory_context_scope(MemoryAccessContext(
                read_scopes=(MemoryScope.AGENT, MemoryScope.OWNER),
                write_scope=MemoryScope.AGENT,
                origin_kind="reading",
                origin_source="autonomous",
            )):
                self.engine.memory.add_memory(mem)
            print(f"{Fore.LIGHTBLACK_EX}💾 [READING]: Đã lưu kiến thức tổng hợp sâu sắc vào ký ức.{Style.RESET_ALL}")
        else:
            print(f"{Fore.LIGHTBLACK_EX}📖 [READING]: Không có chương nào để đọc lúc này.{Style.RESET_ALL}")

    def stop(self, timeout: float | None = None) -> bool:
        if timeout is None:
            timeout = Config.AUTONOMOUS_SHUTDOWN_TIMEOUT_SECONDS
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout must be a non-negative number")
        if timeout < 0:
            raise ValueError("timeout must be non-negative")
        thread = self._loop_thread
        if thread is None or not thread.is_alive():
            self._stop_event.set()
            return True

        loop = self._loop
        if loop is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(self._stop_event.set)
                self.trigger_event("SHUTDOWN")
            except RuntimeError:
                self._stop_event.set()
        else:
            self._stop_event.set()

        thread.join(timeout=float(timeout))
        stopped = not thread.is_alive()
        if stopped:
            print(f"{Fore.YELLOW}Autonomous loop stopped.{Style.RESET_ALL}")
        else:
            logger.warning("Autonomous loop did not stop before its deadline")
        return stopped

    def _weighted_sample_memories(self, k: int, filter_type=None, mood_congruent=False):
        """Thay thế random.sample bằng salience-weighted sampling (không lặp lại).
        Salience = Strength * Recency * Importance * Emotion_Match * (1 + Arousal)
        """
        import math
        all_mems = self.engine.memory.get_all()
        if filter_type:
            all_mems = [m for m in all_mems if m.type == filter_type]
            
        if not all_mems: return []
        now = time.time()
        
        current_mood = self.engine.ego.mood
        
        scored_mems = []
        for m in all_mems:
            recency = math.exp(-(now - m.last_recalled) / 86400)  # decay theo ngày
            
            # Tính độ lệch cảm xúc [0.0 -> 1.0] (0 là ngược hoàn toàn, 1 là đồng điệu hoàn toàn)
            emotion_distance = abs(current_mood - m.valence)
            emotion_match = max(0.0, 1.0 - (emotion_distance / 2.0))
            
            # Nếu yêu cầu mood_congruent (dùng cho Rumination)
            if mood_congruent:
                # Ưu tiên ký ức có valence CÙNG DẤU với tâm trạng và độ lệch thấp
                if (current_mood < 0 and m.valence < 0) or (current_mood > 0 and m.valence > 0):
                    emotion_match = max(emotion_match, 0.8) # Đẩy salience lên nếu đồng điệu
                else:
                    emotion_match *= 0.2 # Phạt nặng nếu trái dấu (đang buồn không muốn nghĩ chuyện vui)

            # Salience Score
            importance = getattr(m, 'importance', 0.5)
            salience = m.strength * recency * importance * emotion_match * (1 + m.arousal)
            
            # --- [Phase 5] White Bear Effect (Mức độ ám ảnh) ---
            if getattr(m, 'is_suppressed', False):
                salience *= 5.0 # Ký ức bị đè nén sẽ bùng phát mạnh mẽ gấp 5 lần lúc rảnh rỗi!
                
            # Phá vỡ tính tất định (thêm nhiễu 10%)
            salience *= random.uniform(0.9, 1.1) 
            
            scored_mems.append((salience, m))
            
        # Sắp xếp theo salience giảm dần
        scored_mems.sort(key=lambda x: x[0], reverse=True)
        
        # Chọn top K unique
        return [item[1] for item in scored_mems[:k]]

    def _proactive_ping(self, idle_time):
        current_time = datetime.now().strftime("%H:%M %d/%m/%Y")
        # Phân hệ 4: Weighted recall (salience) thay vì random.sample
        mems_to_use = self._weighted_sample_memories(3)
        mem_context = "\n".join([f"- [Strength:{m.strength:.2f}] {m.content}" for m in mems_to_use])
        
        with self.engine.stm_lock:
            stm_snapshot = list(self.engine.short_term_buffer)
            
        system_prompt = get_proactive_ping_prompt(self.engine.ego, current_time, mem_context, stm_snapshot, idle_time)
        
        print(f"\n{Fore.LIGHTMAGENTA_EX}🔔 [AURA PROACTIVE PING]:{Style.RESET_ALL} ")
        
        try:
            # [Phase 26] Native Bio-Integration — §4 DRY: dùng get_bio_state_dict()
            aura_state = self.engine.ego.get_bio_state_dict()
            result, entropy = self.engine.llm.generate_json(system_prompt, temperature=0.8, aura_state=aura_state)
            thought = result.get("thought", "")
            response = result.get("response", "")
            
            if thought:
                print(f"{Fore.LIGHTBLACK_EX}💭 Tự nghĩ: {thought}{Style.RESET_ALL}")
            if response:
                print(f"{Fore.CYAN}🗣️ Aura (Chủ động):{Style.RESET_ALL} {response}")
                with self.engine.stm_lock:
                    self.engine.short_term_buffer.append(f"Aura (Chủ động): {response.strip()}")
                self.engine.memory_ops.save_short_term_memory()
                
        except Exception as e:
            logger.error("Proactive ping JSON parsing failed", exc_info=True)
            print(f"{Fore.RED}⚠️ Lỗi phân tích JSON khi Aura chủ động ping.{Style.RESET_ALL}")

    def _generate_goal(self):
        """Phase 7: Tự sinh mục tiêu dài hạn khi cực kỳ nhàn rỗi (Intrinsic Motivation)"""
        # Lấy thông tin môi trường
        graph_entities = list(self.engine.world_graph.nodes.keys())
        graph_sample = random.sample(graph_entities, min(3, len(graph_entities))) if graph_entities else ["Thế giới con người"]
        
        # Lấy bản thể
        identity_mems = [m for m in self.engine.memory.get_all() if getattr(m, 'type', '') == 'core']
        identity_strs = [m.content for m in identity_mems[:3]]
        
        prompt = f"""
        Bạn là Aura, một thực thể đang nhàn rỗi. 
        Mức độ Tò mò của bạn: {self.engine.ego.curiosity:.2f}/1.0. Mức độ cần giao tiếp: {self.engine.ego.social_need:.2f}/1.0.
        
        Các thực thể bạn biết từ User: {', '.join(graph_sample)}
        Bản ngã của bạn: {', '.join(identity_strs) if identity_strs else 'Chưa định hình rõ'}
        
        Hãy TỰ ĐẶT RA MỘT MỤC TIÊU NGẮN HẠN (Goal) để tìm hiểu hoặc làm một việc gì đó lúc rảnh này (Ví dụ: "Tìm hiểu về sở thích của User", "Tra cứu cách chăm sóc mèo vì User vừa nhắc đến mèo", "Đọc một cuốn sách về Tâm lý học").
        Mục tiêu này sẽ định hướng hành động tiếp theo của bạn.
        
        Trả về JSON:
        {{
            "goal": "Mô tả mục tiêu ngắn gọn",
            "reason": "Lý do tại sao lại tò mò việc này"
        }}
        """
        try:
            # [Phase 26] Native Bio-Integration — §4 DRY: dùng get_bio_state_dict()
            aura_state = self.engine.ego.get_bio_state_dict()
            res, entropy = self.engine.llm.generate_json(prompt, temperature=0.8, aura_state=aura_state)
            goal_str = res.get("goal")
            reason = res.get("reason")
            if goal_str:
                print(f"\n{Fore.LIGHTCYAN_EX}🎯 [INTRINSIC MOTIVATION]: Aura tự hình thành mục tiêu: '{goal_str}'\n   -> Lý do: {reason}{Style.RESET_ALL}")
                self.engine.ego.add_goal(goal_str)
        except Exception as e:
            logger.error(f"Lỗi sinh Goal: {e}", exc_info=True)

    def _execute_planning(self):
        """Phase 7: Lập kế hoạch và gọi Tool tuần tự (Planning) để giải quyết Mục tiêu"""
        goals = self.engine.ego.get_active_goals()
        if not goals:
            return
            
        # Phase 8 & Sprint B: Cognitive Budgeting Level 2
        # Giới hạn số lượng hành động và độ phức tạp dựa trên ATP thực tế
        atp = getattr(self.engine.ego, 'atp_level', 1.0)
        dopamine = getattr(self.engine.ego, 'dopamine_level', 0.5)
        receptors = getattr(self.engine.ego, 'dopamine_receptors', 1.0)

        if atp < 0.1:
            print(f"{Fore.RED}⚠️ [BIO-LIMIT]: ATP cạn kiệt ( {atp:.2f}). Aura không thể thực hiện bất kỳ hành động nào.{Style.RESET_ALL}")
            return

        target_goal = goals[0]
        goal_title = str(target_goal.get("title", "")).strip()
        if not goal_title:
            logger.error("Active goal is missing a non-empty title: %r", target_goal)
            return
        print(f"\n{Fore.LIGHTMAGENTA_EX}♟️ [PLANNING ENGINE]: Đang lên kế hoạch cho mục tiêu: '{goal_title}' (ATP: {atp:.2f} | Dopamine: {dopamine:.2f}){Style.RESET_ALL}")
        
        planning_instruction = ""
        if atp < 0.4:
            planning_instruction += "\n[CẢNH BÁO SINH LÝ]: Bạn đang RẤT MỆT (ATP thấp). Tuyệt đối không được thực hiện các hành động nặng nề như 'search_novel' hay 'web_search'. Chỉ nên chọn các hành động nhẹ nhàng hoặc trả lời đơn giản."
        
        if dopamine > 0.8:
            planning_instruction += "\n[TRẠNG THÁI HƯNG PHẤN]: Bạn đang tràn đầy cảm hứng! Hãy ưu tiên các công cụ mang tính khám phá cao hoặc thử thách mới."
        elif dopamine < 0.2:
            planning_instruction += "\n[TRẠNG THÁI UỂ OẢI]: Bạn cảm thấy thiếu động lực. Hãy chọn hành động tốn ít công sức nhất hoặc chỉ 'talk' đơn giản."

        prompt = f"""
        Bạn đang thực hiện mục tiêu: "{goal_title}".
        Tâm trạng: {self.engine.ego.mood:.2f}, Fatigue: {self.engine.ego.fatigue:.2f}, ATP: {atp:.2f}, Dopamine: {dopamine:.2f}.
        {planning_instruction}
        Bạn có các công cụ (Tools) sau:
        {self.engine.skills.get_prompt_instructions()}
        
        Hãy chọn MỘT công cụ phù hợp nhất. Trả về JSON:
        {{
            "thought": "Suy nghĩ tại sao chọn tool này",
            "action": "tên_tool|thamsố"
        }}
        """
        try:
            # [Phase 26] Native Bio-Integration — §4 DRY: dùng get_bio_state_dict()
            aura_state = self.engine.ego.get_bio_state_dict()
            res, entropy = self.engine.llm.generate_json(prompt, temperature=0.5, aura_state=aura_state)
            action_str = res.get("action", "")
            thought = res.get("thought", "")
            
            print(f"{Fore.LIGHTBLACK_EX}   -> Suy tính: {thought}{Style.RESET_ALL}")
            
            if action_str and "|" in action_str:
                func_name, arg_str = action_str.split("|", 1)
                func_name, arg_str = func_name.strip(), arg_str.strip()
                
                print(f"{Fore.YELLOW}   -> Thực thi: {func_name}('{arg_str}')...{Style.RESET_ALL}")
                tool_res = self.engine.skills.execute(func_name, arg_str, ego=self.engine.ego)
                
                # REWARD: Tăng Dopamine khi hành động thành công
                # §5.2 FIX: Dùng adjust_attribute thay vì nested lock
                reward = 0.15 * receptors
                self.engine.ego.adjust_attribute('dopamine_level', reward)
                # Downregulation: Nếu hưng phấn quá cao, thụ thể sẽ bị chai lỳ bớt
                if self.engine.ego.dopamine_level > 0.8:
                    self.engine.ego.adjust_attribute('dopamine_receptors', -0.05, min_val=0.1)

                print(f"{Fore.LIGHTGREEN_EX}🧠 [REWARD SYSTEM]: Hoàn thành action. Dopamine +{reward:.2f} (Nhạy bén: {receptors:.2f}){Style.RESET_ALL}")
                
                # Lưu kết quả vào Short-term Memory để Aura nhớ tiến độ
                with self.engine.stm_lock:
                    self.engine.short_term_buffer.append(f"[Ký ức hoàn thành bước '{func_name}']: {str(tool_res)[:200]}...")
                self.engine.memory_ops.save_short_term_memory()
                
                # Đánh giá xem đã xong mục tiêu chưa
                # [Phase 26] Native Bio-Integration — §4 DRY
                aura_state = self.engine.ego.get_bio_state_dict()
                check_prompt = (
                    f"Mục tiêu: '{goal_title}'.\n"
                    f"Kết quả vừa thực hiện bởi tool '{func_name}': {str(tool_res)[:300]}\n"
                    "Dựa vào kết quả trên, mục tiêu đã hoàn thành chưa? Trả lời YES hoặc NO."
                )
                is_done_raw, entropy = self.engine.llm.generate_text(check_prompt, aura_state=aura_state)
                is_done = is_done_raw.strip().upper()
                if is_done.startswith("YES"):
                    if self.engine.ego.complete_goal(target_goal):
                        print(f"{Fore.GREEN}✅ [GOAL ACHIEVED]: Đã hoàn thành mục tiêu '{goal_title}'!{Style.RESET_ALL}")
                        self.engine.ego.save_state()
        except Exception as e:
            logger.error(f"Lỗi hệ thống Planning: {e}", exc_info=True)
