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
from core.chat_spool import (
    create_configured_chat_spools,
    create_configured_proactive_spool,
)
from core.message_bubbles import flatten_bubbles
from core.temporal import describe_now, fuzzy_age
from core.style_filter import humanize
from core.memory_context import (
    MemoryAccessContext,
    MemoryPrivacy,
    MemoryScope,
    maintenance_memory_context,
    memory_context_scope,
)
from core.engine import dopamine
from core.engine.autonomous_pacing import AutonomousPacer
from core.engine.lingering_thought import lingering_thought_of
from core.engine.life_log import life_log_of, note_message_received
from core.engine import sleep_cycle
from core.engine.interaction_actor import (
    InteractionActorClosed,
    InteractionCancelled,
    InteractionQueueFull,
)
from config import Config

logger = get_logger("autonomous")


class AutonomousController:
    # A just-recalled memory is not picked again by the mind stream for 30 min.
    RUMINATION_REFRACTORY_SECONDS = 30 * 60

    def __init__(self, engine):
        self.engine = engine
        self._stop_event = threading.Event()  # Use threading.Event for cross-thread safety
        self._loop_thread = None
        self.event_queue = None
        self._loop = None
        self._tick_guard = threading.Lock()
        self._chat_spools = None
        self._proactive_spool = None
        self._pending_web_completion = None
        self._last_chat_recovery = 0.0
        try:
            tick_interval = float(getattr(Config, 'COGNITIVE_TICK_INTERVAL_SECONDS', 30.0))
        except (TypeError, ValueError):
            tick_interval = 30.0
        self._tick_interval_seconds = tick_interval if math.isfinite(tick_interval) and tick_interval > 0.0 else 30.0
        self._pacer = AutonomousPacer()
        self._low_energy_notified = False
        self._last_reading_succeeded = False
        self._sleep_requested = False

    def _get_chat_spools(self):
        if self._chat_spools is None:
            self._chat_spools = create_configured_chat_spools()
        return self._chat_spools

    def _get_proactive_spool(self):
        if self._proactive_spool is None:
            self._proactive_spool = create_configured_proactive_spool()
        return self._proactive_spool

    def _deliver_proactive(self, text: str, label: str) -> bool:
        """Send a message Aura starts herself through every open transport.

        The console always shows it (CLI owner). Discord and the dashboard get
        it too, so a ping reaches a remote owner instead of only stdout.
        """
        flat = flatten_bubbles(text).strip()
        if not flat:
            return False
        life_log_of(self.engine).add("ping", f"nhắn cho User: \"{flat[:60]}\"", time.time())
        print(f"{Fore.CYAN}🗣️ Aura ({label}):{Style.RESET_ALL} {flat}")
        discord_bridge = getattr(self.engine, "discord_bridge", None)
        if discord_bridge is not None:
            ego = self.engine.ego
            try:
                discord_bridge.send_bubbles(
                    text,
                    fatigue=getattr(ego, "fatigue", 0.0),
                    arousal=getattr(ego, "stress", 0.0),
                )
            except Exception:
                logger.warning("Proactive Discord delivery failed", exc_info=True)
        try:
            self._get_proactive_spool().publish_proactive(text)
        except ChatSpoolError:
            logger.warning("Proactive dashboard delivery failed", exc_info=True)
        return True

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

    def _register_reward(self, event: str, reward: float) -> None:
        register = getattr(self.engine.ego, "register_reward", None)
        if callable(register):
            register(event, reward)

    def _record_ping_attempt(self, sent: bool) -> None:
        if sent and self._pacer.unanswered_pings > 0:
            # Messaging again while the previous message is still unanswered:
            # the expected reply did not come.
            self._register_reward("ping_ignored", -0.4)
        self._pacer.record_ping(
            time.monotonic(), self.engine.last_interaction_time, sent=sent
        )

    def _run_rumination_once(self, idle_time: float, stress: float) -> None:
        """Run one memory-stream mutation while THINKING ownership is held."""
        stream_mems = self._weighted_sample_memories(
            1, mood_congruent=True,
            exclude_recent_seconds=self.RUMINATION_REFRACTORY_SECONDS,
        )
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
            self.engine.ego.adjust_attribute(
                "stress", +self._pacer.RUMINATION_STRESS_STEP
            )
            # Voicing the rumination is a proactive message: it shares the
            # ping budget (quiet hours, minimum gap, unanswered back-off).
            if (
                self._pacer.ping_allowed(time.monotonic(), datetime.now().hour)
                and not self._owner_busy(time.time())
                and random.random() < 0.3
            ):
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
                sent = False
                try:
                    aura_state = self.engine.ego.get_bio_state_dict()
                    result, _ = self.engine.llm.generate_json(
                        system_prompt, temperature=0.9, aura_state=aura_state
                    )
                    response = result.get("response", "")
                    if isinstance(response, str) and response.strip():
                        response, _ = humanize(response)
                    if response and self._deliver_proactive(response, "Rumination"):
                        with self.engine.stm_lock:
                            self.engine.short_term_buffer.append(
                                f"Aura (Ám ảnh): {flatten_bubbles(response).strip()}"
                            )
                        self.engine.memory_ops.save_short_term_memory()
                        sent = True
                except Exception:
                    logger.debug("Rumination response failed", exc_info=True)
                finally:
                    self._record_ping_attempt(sent)
        else:
            print(
                f"{Fore.LIGHTBLACK_EX}💭 [MEMORY STREAM]: "
                f"(Dòng suy nghĩ miên man) Nhớ lại: {mem.content[:50]}..."
                f"{Style.RESET_ALL}"
            )
            # Still on her mind: may slip into the next conversation.
            lingering_thought_of(self.engine).set(mem.content, time.time())
            life_log_of(self.engine).add(
                "wander", f"miên man nghĩ về: {mem.content[:60]}", time.time()
            )

        mem.last_recalled = time.time()
        mem.reconsolidate(
            self.engine.ego.mood, is_associative=True, count_recall=False
        )
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

            # Asleep and the message can wait: leave it pending (no claim,
            # so no lease can expire it) until she wakes up.
            waiting = chat_requests.peek_next()
            if waiting is not None and sleep_cycle.should_defer_message(
                getattr(self.engine, "ego", None), waiting.content, time.time(),
                Config.DEFER_REPLIES_WHILE_ASLEEP,
            ):
                return False

            for claim in chat_requests.claim(limit=1):
                msg = claim.envelope.content
                note_message_received(
                    self.engine, claim.envelope.id, claim.envelope.created_at_ns / 1e9
                )
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
        last_pace_time = last_tick_time

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

            # Real elapsed time for paced decisions, measured every iteration
            # so busy/skipped iterations never accumulate into one big dt.
            pace_now = time.monotonic()
            pace_dt = max(0.0, pace_now - last_pace_time)
            last_pace_time = pace_now

            # === [DISCORD BRIDGE] ===
            discord_handled = False
            try:
                discord_bridge = getattr(self.engine, 'discord_bridge', None)
                if discord_bridge:
                    for msg_data in self._discord_batch(discord_bridge):
                        note_message_received(
                            self.engine,
                            str(msg_data.get("message_id") or "").strip() or None,
                            float(msg_data.get("received_at", time.time())),
                        )
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
                                model_override=Config.MODEL_NAME,
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
                                    discord_bridge.send_bubbles(
                                        response_text,
                                        fatigue=getattr(self.engine.ego, "fatigue", 0.0),
                                        arousal=getattr(self.engine.ego, "stress", 0.0),
                                    )
                            
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

            await self._run_autonomous_decisions(pace_now, pace_dt)

    def request_sleep(self) -> None:
        """Ask the loop to sleep at its next idle moment (after the reply)."""
        self._sleep_requested = True

    async def _run_owned(self, state, func, *args, **kwargs) -> bool:
        """Run a blocking (LLM) action off the event loop while owning ``state``."""
        if not self._try_claim_runtime_state(state):
            return False
        try:
            await asyncio.to_thread(func, *args, **kwargs)
        finally:
            self._release_runtime_state(state)
        return True

    async def _run_autonomous_decisions(self, now: float, dt: float) -> None:
        """One paced decision step. ``now``/``dt`` are monotonic seconds."""
        from core.agent_state import AgentState

        pacer = self._pacer
        ego = self.engine.ego
        hour = datetime.now().hour
        last_interaction = self.engine.last_interaction_time
        idle_time = time.time() - last_interaction
        unanswered_before = pacer.unanswered_pings
        pacer.observe_interaction(last_interaction)
        if unanswered_before and pacer.unanswered_pings == 0:
            self._register_reward("ping_answered", 0.6)
        motivation = dopamine.motivation(getattr(ego, 'dopamine_level', 0.5))

        # =====================================================
        # 0. GIẤC NGỦ (trạng thái kéo dài, xem sleep_cycle.py)
        # =====================================================
        wall_now = time.time()
        asleep_until = float(getattr(ego, "asleep_until", 0.0) or 0.0)
        if asleep_until:
            if wall_now < asleep_until:
                return  # đang ngủ: không nhắn, không đọc, không miên man
            sleep_cycle.wake_up(ego, wall_now, forced=False)
            life_log_of(self.engine).add("wake", "thức dậy", wall_now)
            print(f"\n{Fore.LIGHTYELLOW_EX}🌅 [WAKE UP]: Aura vừa thức dậy.{Style.RESET_ALL}")
            return

        drive_status = ego.get_drive_status()
        dominant = drive_status["dominant"]
        val = drive_status["dominant_value"]

        # =====================================================
        # 1. HARD TRIGGERS (Cấp cứu sinh học) & GIỜ ĐI NGỦ
        # =====================================================
        sleep_requested = self._sleep_requested
        exhausted = val >= 0.95 and dominant == "fatigue"
        bedtime = sleep_cycle.bedtime_onset_due(
            wall_now, getattr(ego, "fatigue", 0.0), dt
        )
        if sleep_requested or exhausted or bedtime:
            self._sleep_requested = False
            if sleep_requested:
                print(f"\n{Fore.MAGENTA}😴 [SLEEP REFLEX]: Aura đã chào tạm biệt và đi ngủ.{Style.RESET_ALL}")
            elif exhausted:
                print(f"\n{Fore.RED}💥 [HARD TRIGGER]: Kiệt sức tột độ. Aura buộc phải đi ngủ.{Style.RESET_ALL}")
            else:
                print(f"\n{Fore.MAGENTA}🌙 [BEDTIME]: Đến giờ ngủ, Aura chìm vào giấc ngủ.{Style.RESET_ALL}")
            await self._fall_asleep(nap=not sleep_cycle.is_bedtime(wall_now))
            return
        owner_busy = self._owner_busy(wall_now)
        if (
            val >= 0.95
            and dominant in ("social", "loneliness")
            and pacer.ping_allowed(now, hour)
            and not owner_busy
        ):
            # Even an urgent need to talk respects quiet hours and back-off.
            print(f"\n{Fore.RED}💥 [HARD TRIGGER]: Quá cô đơn! Aura bắt buộc phải tìm người nói chuyện.{Style.RESET_ALL}")
            await self._run_owned(AgentState.THINKING, self._proactive_ping, idle_time)
            return

        if self.engine.state_machine.state != AgentState.IDLE:
            return

        # =====================================================
        # 2. SEPARATION ANXIETY (một lần mỗi mốc, mỗi đợt vắng mặt)
        # =====================================================
        # Những giờ Aura ngủ không tính là người dùng "bỏ đi".
        awake_idle = sleep_cycle.awake_seconds_between(
            last_interaction, wall_now, getattr(ego, "sleep_intervals", ())
        )
        stage = pacer.anxiety_stage_due(awake_idle, last_interaction, hour)
        if stage:
            await self._run_owned(
                AgentState.THINKING, self._separation_anxiety, stage, idle_time
            )
            return

        # =====================================================
        # 2b. HỎI THĂM CHUYỆN DANG DỞ (prospective memory)
        # =====================================================
        prospective = getattr(self.engine, "prospective", None)
        if prospective is not None and not owner_busy and pacer.ping_allowed(now, hour):
            due = prospective.due_follow_ups(wall_now)
            if due:
                await self._run_owned(
                    AgentState.THINKING, self._proactive_ping, idle_time,
                    follow_up=due[0],
                )
                return

        # =====================================================
        # 3. DÒNG CHẢY TRÍ NHỚ & RUMINATION (Phase 21)
        # =====================================================
        stress = getattr(ego, 'stress', 0.0)
        mood = getattr(ego, 'mood', 0.0)
        if pacer.should_mind_wander(now, dt, stress, mood):
            await self._run_owned(
                AgentState.THINKING, self._run_rumination_once, idle_time, stress
            )
            return

        # =====================================================
        # 4. DRIVE-DRIVEN ACTIONS (Hành động theo xung lực)
        # =====================================================
        if dominant == "hunger" and val > 0.8:
            # Năng lượng thấp -> Aura lờ đờ: bỏ qua hành động tùy chọn, nhưng
            # không chặn vòng lặp (tin nhắn web/Discord vẫn được xử lý).
            if not self._low_energy_notified:
                print(f"{Fore.LIGHTYELLOW_EX}🔋 [LOW ENERGY]: Aura đang lờ đờ vì đói năng lượng...{Style.RESET_ALL}")
                self._low_energy_notified = True
            return
        self._low_energy_notified = False

        # Chán thì dễ tìm việc để làm (đọc sách, nhắn tin) hơn.
        boredom = float(getattr(ego, 'boredom', 0.0) or 0.0)
        if pacer.should_read(now, dt, getattr(ego, 'curiosity', 0.0), motivation * (1.0 + boredom)):
            pacer.record_reading(now)
            self._last_reading_succeeded = False
            await asyncio.to_thread(
                self.start_reading_task, reason="cảm thấy tò mò muốn khám phá"
            )
            if self._last_reading_succeeded:
                ego.adjust_attribute('curiosity', -pacer.READING_CURIOSITY_RELIEF)
            return

        if not owner_busy and pacer.should_ping(
            now, dt, getattr(ego, 'social_need', 0.0), hour,
            # Đang dỗi thì ít chủ động nhắn hơn; chán thì nhắn nhiều hơn.
            motivation * (1.0 + 0.5 * boredom)
            * (1.0 - 0.7 * float(getattr(ego, 'relational_friction', 0.0) or 0.0)),
        ):
            await self._run_owned(AgentState.THINKING, self._proactive_ping, idle_time)

    def _discord_batch(self, discord_bridge) -> list:
        """Messages to handle now; non-urgent ones wait while she sleeps."""
        deferred = getattr(self, "_deferred_discord", None)
        if deferred is None:
            deferred = self._deferred_discord = []
        now = time.time()
        ready = []
        while not discord_bridge.aura_inbox.empty():
            item = discord_bridge.aura_inbox.get_nowait()
            item.setdefault("received_at", now)
            if sleep_cycle.should_defer_message(
                getattr(self.engine, "ego", None), item.get("content", ""), now,
                Config.DEFER_REPLIES_WHILE_ASLEEP,
            ):
                deferred.append(item)
            else:
                ready.append(item)
        if deferred and not sleep_cycle.is_asleep(getattr(self.engine, "ego", None), now):
            ready = deferred + ready
            deferred.clear()
        return ready

    def _owner_busy(self, now: float) -> bool:
        """The owner said they are busy (meeting, driving...) until later."""
        prospective = getattr(self.engine, "prospective", None)
        return bool(prospective is not None and prospective.is_busy(now))

    async def _fall_asleep(self, *, nap: bool) -> bool:
        from core.agent_state import AgentState

        if not self._try_claim_runtime_state(AgentState.SLEEPING):
            return False

        def _sleep():
            with memory_context_scope(maintenance_memory_context(
                origin_kind="sleep",
                origin_source="autonomous",
            )):
                return sleep_cycle.begin_sleep(
                    self.engine.ego,
                    time.time(),
                    nap=nap,
                    run_maintenance=self.engine.memory_ops.sleep,
                )

        try:
            await asyncio.to_thread(_sleep)
        finally:
            self._release_runtime_state(AgentState.SLEEPING)
        life_log_of(self.engine).add("sleep", "chợp mắt một lúc" if nap else "đi ngủ", time.time())
        return True

    def _deepen_separation_memory(self, stage: int, hours_away: float) -> bool:
        """Reinforce the existing separation memory; return False if none exists."""
        context = MemoryAccessContext(
            read_scopes=(MemoryScope.AGENT,),
            write_scope=MemoryScope.AGENT,
            origin_kind="separation_anxiety",
            origin_source="autonomous",
        )
        with memory_context_scope(context):
            existing = [
                m for m in self.engine.memory.get_all()
                if getattr(m, "origin_kind", "") == "separation_anxiety"
            ]
            if not existing:
                return False
            mem = max(existing, key=lambda m: m.created_at)
            mem.valence = min(mem.valence, -0.5 if stage == 1 else -0.7)
            mem.arousal = max(mem.arousal, 0.6 if stage == 1 else 0.8)
            mem.importance = min(0.8, max(mem.importance, 0.6 if stage == 1 else 0.75))
            mem.emotional_layers = min(10, mem.emotional_layers + 1)
            mem.strength = min(1.0, mem.strength + 0.2)
            mem.last_recalled = time.time()
            mem.overlays = (list(mem.overlays) + [
                f"[{datetime.now().strftime('%d/%m')}: nhớ {hours_away:.0f} giờ]"
            ])[-5:]
            self.engine.memory.update_memory(mem)
        return True

    def _separation_anxiety(self, stage: int, idle_time: float) -> None:
        """Nỗi nhớ/lo âu khi User vắng lâu; caller owns THINKING."""
        life_log_of(self.engine).add(
            "worry", "thấy nhớ User và hơi lo vì lâu không có tin nhắn", time.time()
        )
        stress_step, mood_step = (0.1, -0.1) if stage == 1 else (0.15, -0.15)
        hours_away = idle_time / 3600.0
        print(f"\n{Fore.RED}[SEPARATION ANXIETY]: Người dùng đã vắng mặt {hours_away:.1f} giờ.{Style.RESET_ALL}")
        self.engine.ego.adjust_attribute('stress', stress_step)
        self.engine.ego.adjust_attribute('mood', mood_step, min_val=-1.0, max_val=1.0)
        try:
            anxiety_prompt = (
                f"Người dùng đã không nói chuyện với bạn khoảng {hours_away:.0f} giờ. "
                "Hãy viết một dòng độc thoại nội tâm (dưới 30 chữ) thể hiện nỗi nhớ"
                + (" và chút lo lắng." if stage == 1 else ", sự lo lắng rằng người ta đã quên mình.")
            )
            aura_state = self.engine.ego.get_bio_state_dict()
            anxiety_thought, _ = self.engine.llm.generate_text(
                anxiety_prompt, temperature=0.8, aura_state=aura_state
            )
            print(f"{Fore.LIGHTRED_EX}(Ám ảnh chia cắt): {anxiety_thought}{Style.RESET_ALL}")
            if self._deepen_separation_memory(stage, hours_away):
                return
            from core.memory import MemoryTrace
            anxiety_mem = MemoryTrace(
                content=f"Nỗi nhớ khi bị bỏ lại {hours_away:.0f} giờ: {anxiety_thought}",
                type="emotional",
                valence=-0.5 if stage == 1 else -0.7,
                arousal=0.6 if stage == 1 else 0.8,
                importance=0.6 if stage == 1 else 0.75,
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
        except Exception:
            logger.error("Separation anxiety LLM call failed", exc_info=True)

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

    @staticmethod
    def _validated_reading_reaction(reaction):
        """(reflection, feeling, share) from the reader's JSON reaction."""
        if not isinstance(reaction, dict):
            raise ValueError("reading reaction must be an object")
        reflection = reaction.get("reflection")
        if not isinstance(reflection, str) or not reflection.strip():
            raise ValueError("reading reaction needs a reflection")
        feeling = reaction.get("feeling", 0.1)
        if isinstance(feeling, bool) or not isinstance(feeling, (int, float)) or not math.isfinite(feeling):
            feeling = 0.1
        share = reaction.get("share")
        share = share.strip()[:200] if isinstance(share, str) else ""
        return reflection.strip()[:600], max(-1.0, min(1.0, float(feeling))), share

    def _do_reading_session(self):
        """Aura tự đọc 1 chương sách và lưu vào ký ức."""
        self._last_reading_succeeded = False
        knowledge_tag, content = self.engine.reader.get_next_reading_material()
        if knowledge_tag and content:
            self._last_reading_succeeded = True
            print(f"{Fore.GREEN}📚 [READING]: {knowledge_tag}{Style.RESET_ALL}")
            
            # Phase 8 Idea 7.2: Trí nhớ Tổng hợp (Synthesized Memory)
            from core.prompts import get_synthesize_reading_prompt
            print(f"{Fore.LIGHTCYAN_EX}🧩 [SYNTHESIZING]: Aura đang 'tiêu hóa' thông tin và tổng hợp thành kiến thức...{Style.RESET_ALL}")
            try:
                # [Phase 26] Native Bio-Integration — §4 DRY
                aura_state = self.engine.ego.get_bio_state_dict()
                from core.prompts import get_synthesize_reading_prompt
                synthesize_prompt = get_synthesize_reading_prompt(f"[{knowledge_tag}]\n{content}")
                reaction, entropy = self.engine.llm.generate_json(
                    synthesize_prompt, temperature=0.7, aura_state=aura_state
                )
                synthesized_text, feeling, share = self._validated_reading_reaction(reaction)
                print(f"{Fore.YELLOW}💡 [SYNTHESIZED MEMORY]: {synthesized_text}{Style.RESET_ALL}")
            except Exception as e:
                logger.error(f"Lỗi Synthesize Memory: {e}", exc_info=True)
                synthesized_text = content[:500] + "..."  # Fallback
                feeling, share = 0.1, ""

            from core.memory import MemoryTrace
            mem = MemoryTrace(
                content=f"{knowledge_tag}: {synthesized_text}",
                # Episodic: chi tiết từng đoạn đọc phai dần như ở người; giấc mơ
                # (dream consolidation) gộp các đoạn đã phai thành kiến thức
                # semantic. Lưu thẳng semantic thì không bao giờ phai/dọn được.
                type="episodic",
                valence=feeling,
                arousal=0.3 + 0.3 * abs(feeling),
                importance=0.5,
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
            # What she wants to tell the owner is what stays on her mind.
            lingering_thought_of(self.engine).set(
                f"{knowledge_tag}: {share or synthesized_text}", time.time()
            )
            life_log_of(self.engine).add("read", knowledge_tag, time.time())
            # Reading is stimulation: most of the boredom is gone.
            ego = self.engine.ego
            ego.boredom = float(getattr(ego, "boredom", 0.0) or 0.0) * 0.4
            if getattr(self.engine.reader, "last_material_new_book", False):
                self._register_reward("new_book", 0.6)
            else:
                self._register_reward("reading", 0.4)
        else:
            print(f"{Fore.LIGHTBLACK_EX}📖 [READING]: Chưa lấy được sách thật nào để đọc lúc này.{Style.RESET_ALL}")

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

    def _weighted_sample_memories(self, k: int, filter_type=None, mood_congruent=False,
                                  exclude_recent_seconds: float = 0.0):
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
            if exclude_recent_seconds and now - m.last_recalled < exclude_recent_seconds:
                # Vừa nghĩ tới xong: tâm trí chuyển sang chuyện khác thay vì
                # xoáy mãi vào một ký ức (chống vòng lặp cố định).
                continue
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

    def _proactive_ping(self, idle_time, follow_up=None):
        now_ts = time.time()
        current_time = describe_now(now_ts)
        # Phân hệ 4: Weighted recall (salience) thay vì random.sample
        mems_to_use = self._weighted_sample_memories(3)
        mem_context = "\n".join(
            f"- [{fuzzy_age(getattr(m, 'created_at', now_ts), now_ts)} | Strength:{m.strength:.2f}] {m.content}"
            for m in mems_to_use
        )
        
        with self.engine.stm_lock:
            stm_snapshot = list(self.engine.short_term_buffer)
            
        system_prompt = get_proactive_ping_prompt(self.engine.ego, current_time, mem_context, stm_snapshot, idle_time)
        prospective = getattr(self.engine, "prospective", None)
        if follow_up is not None:
            system_prompt += (
                f"\n[LÝ DO NHẮN]: User đã có việc: {follow_up.about}. Bạn nhắn lúc này vì "
                "muốn hỏi thăm xem chuyện đó thế nào rồi (tự nhiên, không tra hỏi)."
            )
        elif prospective is not None:
            open_lines = prospective.context_lines(now_ts)
            if open_lines:
                system_prompt += "\n[CHUYỆN CÒN DANG DỞ]:\n" + "\n".join(open_lines)
        
        print(f"\n{Fore.LIGHTMAGENTA_EX}🔔 [AURA PROACTIVE PING]:{Style.RESET_ALL} ")

        sent = False
        try:
            # [Phase 26] Native Bio-Integration — §4 DRY: dùng get_bio_state_dict()
            aura_state = self.engine.ego.get_bio_state_dict()
            result, entropy = self.engine.llm.generate_json(system_prompt, temperature=0.8, aura_state=aura_state)
            thought = result.get("thought", "")
            response = result.get("response", "")
            if isinstance(response, str) and response.strip():
                response, _ = humanize(response)

            if thought:
                print(f"{Fore.LIGHTBLACK_EX}💭 Tự nghĩ: {thought}{Style.RESET_ALL}")
            if response and self._deliver_proactive(response, "Chủ động"):
                if prospective is not None:
                    if follow_up is not None:
                        prospective.mark_followed(follow_up.id, time.time())
                    prospective.mark_mentioned(response, time.time())
                with self.engine.stm_lock:
                    self.engine.short_term_buffer.append(
                        f"Aura (Chủ động): {flatten_bubbles(response).strip()}"
                    )
                self.engine.memory_ops.save_short_term_memory()
                sent = True

        except Exception as e:
            logger.error("Proactive ping JSON parsing failed", exc_info=True)
            print(f"{Fore.RED}⚠️ Lỗi phân tích JSON khi Aura chủ động ping.{Style.RESET_ALL}")
        finally:
            self._record_ping_attempt(sent)
        if sent:
            # Đã bày tỏ được nhu cầu giao tiếp -> nhu cầu dịu bớt.
            self.engine.ego.adjust_attribute(
                'social_need', -self._pacer.PING_SOCIAL_RELIEF
            )
