"""Single-owner execution for user-facing interactions.

The actor intentionally depends only on the Python standard library.  It can
therefore sit between producers running on different asyncio loops (or plain
threads) and a synchronous interaction handler without binding the engine to
one particular transport.

Only :meth:`InteractionActor.submit` puts work into the bounded queue.  The
handler and lifecycle hooks always run on the actor's one worker thread.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Generic, Mapping, TypeVar


ResultT = TypeVar("ResultT")


class InteractionActorError(RuntimeError):
    """Base class for actor-specific failures."""


class InteractionQueueFull(InteractionActorError):
    """Raised when the bounded pending queue cannot accept another request."""

    def __init__(self, capacity: int):
        self.capacity = capacity
        super().__init__(f"interaction queue is full (capacity={capacity})")


class InteractionActorClosed(InteractionActorError):
    """Raised when work is submitted after shutdown has begun."""


class InteractionCancelled(InteractionActorError):
    """Terminal result of cooperative per-request cancellation."""

    def __init__(self, request_id: str, reason: str = "cancelled"):
        self.request_id = request_id
        self.reason = reason
        super().__init__(f"interaction {request_id} cancelled: {reason}")


class InteractionReentrantCall(InteractionActorError):
    """Raised when the actor worker tries to synchronously wait on itself."""


@dataclass(frozen=True, slots=True)
class InteractionRequest:
    """Immutable request metadata handed to the actor-owned handler.

    ``payload`` is deliberately generic so this module does not need to know
    about CLI, Discord, web, or CognitiveEngine argument shapes.  Long-running
    handlers should call :meth:`raise_if_cancelled` at safe phase boundaries.
    """

    request_id: str
    payload: Any
    source: str
    cancel_event: threading.Event
    submitted_at: float
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def raise_if_cancelled(self, reason: str = "cancelled") -> None:
        if self.cancel_event.is_set():
            raise InteractionCancelled(self.request_id, reason)


@dataclass(frozen=True, slots=True)
class InteractionTicket(Generic[ResultT]):
    """A request handle safe to use from synchronous or asyncio callers."""

    request: InteractionRequest
    future: concurrent.futures.Future[ResultT]
    _cancel_callback: Callable[[str], bool] = field(repr=False, compare=False)

    @property
    def request_id(self) -> str:
        return self.request.request_id

    @property
    def cancel_event(self) -> threading.Event:
        return self.request.cancel_event

    def cancel(self, reason: str = "cancelled by caller") -> bool:
        """Request cooperative cancellation.

        Queued work is completed immediately with ``InteractionCancelled``.
        Active work receives the cancellation signal, but the handler owns the
        cooperative boundary: raising before it returns cancels the request,
        while a normal return commits the result even if cancellation raced
        with the handler.  This avoids reporting a completed side effect as a
        cancellation and inducing an unsafe retry.
        """

        return self._cancel_callback(reason)

    def result(self, timeout: float | None = None) -> ResultT:
        return self.future.result(timeout=timeout)

    async def wait(self, timeout: float | None = None) -> ResultT:
        """Await without blocking the caller's event loop.

        Shielding prevents asyncio from applying native ``Future.cancel()`` to
        the cross-thread future; cancellation always travels through the
        request's explicit cooperative event.
        """

        wrapped = asyncio.wrap_future(self.future)
        try:
            if timeout is None:
                return await asyncio.shield(wrapped)
            return await asyncio.wait_for(asyncio.shield(wrapped), timeout)
        except asyncio.TimeoutError:
            self.cancel("async wait timed out")
            raise
        except asyncio.CancelledError:
            self.cancel("async waiter cancelled")
            raise


@dataclass(frozen=True, slots=True)
class InteractionActorSnapshot:
    """A lock-consistent operational snapshot for health and tests."""

    capacity: int
    queued: int
    submitted: int
    started: int
    succeeded: int
    failed: int
    cleanup_failed: int
    cancelled: int
    rejected_full: int
    active_request_id: str | None
    accepting: bool
    worker_started: bool
    worker_alive: bool
    closing: bool
    closed: bool


@dataclass(slots=True)
class _Envelope(Generic[ResultT]):
    request: InteractionRequest
    future: concurrent.futures.Future[ResultT]
    lock: threading.Lock = field(default_factory=threading.Lock)
    state: str = "queued"  # queued -> running -> committed -> terminal
    cancel_reason: str = "cancelled"


class InteractionActor(Generic[ResultT]):
    """Bounded, single-threaded interaction executor.

    Parameters
    ----------
    handler:
        Synchronous callable invoked exactly once for each non-cancelled
        request.  It receives the full :class:`InteractionRequest`.
    capacity:
        Maximum number of *pending* requests. The currently active request is
        not counted.
    before_request / after_request:
        Optional engine-neutral lifecycle hooks.  A CognitiveEngine adapter can
        transition IDLE -> THINKING in ``before_request`` and restore IDLE in
        ``after_request`` without this module importing the state machine.
        ``after_request`` always runs.  Once the handler result is committed,
        cleanup failure is counted but cannot replace that committed result.
    """

    def __init__(
        self,
        handler: Callable[[InteractionRequest], ResultT],
        *,
        capacity: int = 16,
        before_request: Callable[[InteractionRequest], None] | None = None,
        after_request: Callable[[InteractionRequest, BaseException | None], None]
        | None = None,
        thread_name: str = "aura-interaction-actor",
    ) -> None:
        if not callable(handler):
            raise TypeError("handler must be callable")
        if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 1:
            raise ValueError("capacity must be a positive integer")

        self._handler = handler
        self._before_request = before_request
        self._after_request = after_request
        self._capacity = capacity
        self._thread_name = thread_name
        # A deque + Condition lets queued cancellation remove its exact
        # envelope. Both live work and physical storage remain truly bounded;
        # queue.Queue cannot safely remove a specific pending item.
        self._queue: deque[_Envelope[ResultT]] = deque()
        self._queue_condition = threading.Condition()

        self._lifecycle_lock = threading.Lock()
        self._stats_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._owner_ident: int | None = None
        self._closing = False
        self._closed = False
        self._drain_on_close = True
        self._closed_event = threading.Event()
        self._active: _Envelope[ResultT] | None = None

        self._submitted = 0
        self._started = 0
        self._succeeded = 0
        self._failed = 0
        self._cleanup_failed = 0
        self._cancelled = 0
        self._rejected_full = 0

    @property
    def is_owner_thread(self) -> bool:
        return self._owner_ident == threading.get_ident()

    def start(self) -> bool:
        """Start the daemon worker once; normally first submission does this."""

        with self._lifecycle_lock:
            if self._closing or self._closed:
                raise InteractionActorClosed("interaction actor is closed")
            return self._start_locked()

    def _start_locked(self) -> bool:
        if self._thread is not None:
            return False
        thread = threading.Thread(
            target=self._worker_main,
            name=self._thread_name,
            daemon=True,
        )
        self._thread = thread
        thread.start()
        return True

    def submit(
        self,
        payload: Any,
        *,
        source: str = "unknown",
        request_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> InteractionTicket[ResultT]:
        """Submit without blocking; raise ``InteractionQueueFull`` on pressure."""

        request_id = str(request_id or uuid.uuid4().hex)
        if not request_id:
            raise ValueError("request_id must not be empty")
        source = str(source or "unknown")
        request = InteractionRequest(
            request_id=request_id,
            payload=payload,
            source=source,
            cancel_event=threading.Event(),
            submitted_at=time.monotonic(),
            metadata=MappingProxyType(dict(metadata or {})),
        )
        envelope: _Envelope[ResultT] = _Envelope(
            request=request,
            future=concurrent.futures.Future(),
        )

        # The lifecycle lock closes the otherwise dangerous race in which a
        # shutdown marker could overtake a just-accepted request.
        with self._lifecycle_lock:
            if self._closing or self._closed:
                raise InteractionActorClosed("interaction actor is closed")
            self._start_locked()
            with self._queue_condition:
                if len(self._queue) >= self._capacity:
                    with self._stats_lock:
                        self._rejected_full += 1
                    raise InteractionQueueFull(self._capacity)
                self._queue.append(envelope)
                with self._stats_lock:
                    self._submitted += 1
                self._queue_condition.notify()

        return InteractionTicket(
            request=request,
            future=envelope.future,
            _cancel_callback=lambda reason: self._cancel_envelope(envelope, reason),
        )

    def interact_sync(
        self,
        payload: Any,
        *,
        source: str = "sync",
        timeout: float | None = None,
        request_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ResultT:
        """Submit and synchronously wait; never legal on the owner thread."""

        if self.is_owner_thread:
            raise InteractionReentrantCall(
                "the interaction actor cannot synchronously wait on itself"
            )
        ticket = self.submit(
            payload,
            source=source,
            request_id=request_id,
            metadata=metadata,
        )
        try:
            return ticket.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            ticket.cancel("sync wait timed out")
            raise

    async def interact_async(
        self,
        payload: Any,
        *,
        source: str = "async",
        timeout: float | None = None,
        request_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> ResultT:
        """Submit and await using the caller's current asyncio loop."""

        ticket = self.submit(
            payload,
            source=source,
            request_id=request_id,
            metadata=metadata,
        )
        return await ticket.wait(timeout=timeout)

    def _cancel_envelope(self, envelope: _Envelope[ResultT], reason: str) -> bool:
        reason = str(reason or "cancelled")
        complete_now = False
        with envelope.lock:
            if envelope.state in ("committed", "terminal"):
                return False
            envelope.cancel_reason = reason
            # Publish the reason before waking a cooperative handler so it
            # cannot observe the event with a stale reason.
            envelope.request.cancel_event.set()
            if envelope.state == "queued":
                envelope.state = "terminal"
                complete_now = True

        if complete_now:
            # Remove the exact queued envelope so cancelled requests consume
            # neither logical capacity nor unbounded physical tombstone space.
            # If the worker already popped it, it will observe terminal state.
            with self._queue_condition:
                try:
                    self._queue.remove(envelope)
                except ValueError:
                    pass
            self._record_cancelled()
            self._set_exception_if_pending(
                envelope.future,
                InteractionCancelled(envelope.request.request_id, reason),
            )
        return True

    def _worker_main(self) -> None:
        self._owner_ident = threading.get_ident()
        try:
            while True:
                with self._lifecycle_lock:
                    closing = self._closing
                    drain = self._drain_on_close
                with self._queue_condition:
                    queue_empty = not self._queue
                if closing and (not drain or queue_empty):
                    break

                with self._queue_condition:
                    if not self._queue:
                        self._queue_condition.wait(timeout=0.05)
                        continue
                    envelope = self._queue.popleft()

                with self._lifecycle_lock:
                    reject_for_close = self._closing and not self._drain_on_close
                if reject_for_close:
                    self._cancel_envelope(envelope, "actor shutting down")
                    continue
                self._execute(envelope)
        finally:
            # A fatal hook/handler bug must not strand accepted queued futures.
            self._cancel_pending("actor stopped")
            with self._stats_lock:
                self._active = None
            with self._lifecycle_lock:
                self._closed = True
            self._owner_ident = None
            self._closed_event.set()

    def _execute(self, envelope: _Envelope[ResultT]) -> None:
        native_cancelled = False
        # Publish queued -> active while holding the same lifecycle lock used
        # by shutdown.  Therefore shutdown can never miss an envelope that has
        # left the queue but has not yet become visible as ``_active``.
        with self._lifecycle_lock:
            reject_for_close = self._closing and not self._drain_on_close
            if reject_for_close:
                cancellation = InteractionCancelled(
                    envelope.request.request_id, "actor shutting down"
                )
                with envelope.lock:
                    if envelope.state == "terminal":
                        return
                    envelope.cancel_reason = "actor shutting down"
                    envelope.request.cancel_event.set()
                    envelope.state = "terminal"
            else:
                with envelope.lock:
                    if envelope.state == "terminal":
                        return
                    if envelope.request.cancel_event.is_set():
                        envelope.state = "terminal"
                        cancellation = InteractionCancelled(
                            envelope.request.request_id, envelope.cancel_reason
                        )
                    elif not envelope.future.set_running_or_notify_cancel():
                        envelope.state = "terminal"
                        native_cancelled = True
                        cancellation = None
                    else:
                        envelope.state = "running"
                        cancellation = None
                        with self._stats_lock:
                            self._active = envelope
                            self._started += 1

        if native_cancelled:
            self._record_cancelled()
            return
        if cancellation is not None:
            self._record_cancelled()
            self._set_exception_if_pending(envelope.future, cancellation)
            return

        result: ResultT | None = None
        error: BaseException | None = None
        result_committed = False
        try:
            envelope.request.raise_if_cancelled(envelope.cancel_reason)
            if self._before_request is not None:
                self._before_request(envelope.request)
            envelope.request.raise_if_cancelled(envelope.cancel_reason)
            result = self._handler(envelope.request)
            # A normal handler return is the commit point.  The handler may
            # have completed a non-idempotent side effect before a racing
            # cancellation signal arrived, so cancellation must not rewrite
            # that committed success into a failure and invite a retry.  This
            # lock is also used by Ticket.cancel(), making the arbitration
            # deterministic: cancel either signals a still-running handler or
            # observes the committed result and returns False.
            #
            # M2.3b/M3 still needs a durable idempotency-receipt ledger keyed
            # by a stable operation/request ID.  This in-process commit
            # boundary prevents false retries after late cancellation, but it
            # cannot prove whether a side effect committed across process loss.
            with envelope.lock:
                envelope.state = "committed"
                result_committed = True
        except BaseException as exc:  # keep every accepted Future terminal
            error = exc
        finally:
            if (
                not result_committed
                and envelope.request.cancel_event.is_set()
                and not isinstance(error, InteractionCancelled)
            ):
                error = InteractionCancelled(
                    envelope.request.request_id, envelope.cancel_reason
                )
            if self._after_request is not None:
                try:
                    self._after_request(envelope.request, error)
                except BaseException as hook_error:
                    with self._stats_lock:
                        self._cleanup_failed += 1
                    # Cleanup must stay observable, but it cannot rewrite a
                    # successfully returned handler into a retryable failure.
                    # Before commit, retain the old failure behavior.
                    if not result_committed and error is None:
                        error = hook_error
            # Cancellation may arrive while a failure/cancellation cleanup
            # hook is running.  It can still win before terminalization, but a
            # successfully returned handler is already committed above.
            if (
                not result_committed
                and envelope.request.cancel_event.is_set()
                and not isinstance(error, InteractionCancelled)
            ):
                error = InteractionCancelled(
                    envelope.request.request_id, envelope.cancel_reason
                )

        # Make the last pre-commit cancellation decision and terminal state
        # change under the same lock used by Ticket.cancel().  A committed
        # handler result is deliberately immune to late cancellation.
        with envelope.lock:
            if (
                not result_committed
                and envelope.request.cancel_event.is_set()
                and not isinstance(error, InteractionCancelled)
            ):
                error = InteractionCancelled(
                    envelope.request.request_id, envelope.cancel_reason
                )
            envelope.state = "terminal"
        with self._stats_lock:
            self._active = None

        if isinstance(error, InteractionCancelled):
            self._record_cancelled()
            self._set_exception_if_pending(envelope.future, error)
        elif error is not None:
            with self._stats_lock:
                self._failed += 1
            self._set_exception_if_pending(envelope.future, error)
        else:
            with self._stats_lock:
                self._succeeded += 1
            self._set_result_if_pending(envelope.future, result)

    @staticmethod
    def _set_result_if_pending(
        future: concurrent.futures.Future[ResultT], result: ResultT | None
    ) -> None:
        try:
            if not future.done():
                future.set_result(result)  # type: ignore[arg-type]
        except concurrent.futures.InvalidStateError:
            # A caller may use Future.cancel() directly instead of Ticket.cancel().
            pass

    @staticmethod
    def _set_exception_if_pending(
        future: concurrent.futures.Future[Any], error: BaseException
    ) -> None:
        try:
            if not future.done():
                future.set_exception(error)
        except concurrent.futures.InvalidStateError:
            pass

    def _record_cancelled(self) -> None:
        with self._stats_lock:
            self._cancelled += 1

    def _cancel_pending(self, reason: str) -> None:
        while True:
            with self._queue_condition:
                if not self._queue:
                    return
                envelope = self._queue.popleft()
            self._cancel_envelope(envelope, reason)

    def shutdown(self, *, drain: bool = True, timeout: float = 5.0) -> bool:
        """Stop accepting work and wait at most ``timeout`` seconds.

        ``drain=False`` cancels queued and active work immediately.  A draining
        shutdown that exceeds its deadline escalates to cooperative
        cancellation and returns ``False`` if an uncooperative handler is still
        alive.  Python cannot safely kill such a thread.
        """

        if self.is_owner_thread:
            raise InteractionReentrantCall(
                "the interaction actor cannot join its own worker thread"
            )
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout must be a non-negative number")
        if timeout < 0:
            raise ValueError("timeout must be non-negative")

        with self._lifecycle_lock:
            if self._closed:
                return True
            self._closing = True
            self._drain_on_close = bool(drain)
            thread = self._thread
            if thread is None:
                self._closed = True
                self._closed_event.set()
                return True

        with self._queue_condition:
            self._queue_condition.notify_all()

        if not drain:
            self._cancel_active("actor shutting down")
            self._cancel_pending("actor shutting down")

        deadline = time.monotonic() + float(timeout)
        thread.join(timeout=max(0.0, deadline - time.monotonic()))
        if not thread.is_alive():
            return True

        # A drain deadline is also the cancellation deadline.
        with self._lifecycle_lock:
            self._drain_on_close = False
        with self._queue_condition:
            self._queue_condition.notify_all()
        self._cancel_active("shutdown deadline exceeded")
        self._cancel_pending("shutdown deadline exceeded")
        return not thread.is_alive()

    def _cancel_active(self, reason: str) -> None:
        with self._stats_lock:
            active = self._active
        if active is not None:
            self._cancel_envelope(active, reason)

    def wait_closed(self, timeout: float | None = None) -> bool:
        return self._closed_event.wait(timeout)

    def snapshot(self) -> InteractionActorSnapshot:
        with self._lifecycle_lock:
            thread = self._thread
            closing = self._closing
            closed = self._closed
        with self._queue_condition:
            queued = len(self._queue)
        with self._stats_lock:
            active_request_id = (
                self._active.request.request_id if self._active is not None else None
            )
            submitted = self._submitted
            started = self._started
            succeeded = self._succeeded
            failed = self._failed
            cleanup_failed = self._cleanup_failed
            cancelled = self._cancelled
            rejected_full = self._rejected_full
        return InteractionActorSnapshot(
            capacity=self._capacity,
            queued=queued,
            submitted=submitted,
            started=started,
            succeeded=succeeded,
            failed=failed,
            cleanup_failed=cleanup_failed,
            cancelled=cancelled,
            rejected_full=rejected_full,
            active_request_id=active_request_id,
            accepting=not closing and not closed,
            worker_started=thread is not None,
            worker_alive=bool(thread and thread.is_alive()),
            closing=closing,
            closed=closed,
        )


__all__ = [
    "InteractionActor",
    "InteractionActorClosed",
    "InteractionActorError",
    "InteractionActorSnapshot",
    "InteractionCancelled",
    "InteractionQueueFull",
    "InteractionReentrantCall",
    "InteractionRequest",
    "InteractionTicket",
]
