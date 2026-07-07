"""
Wrap spawned subprocess with timeout, backgrounding, and TaskOutput integration.

Port of: src/utils/ShellCommand.ts (async Python variant; tree-kill → process group kill stub).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Protocol, runtime_checkable

from hare.task import generate_task_id
from hare.utils.task.disk_output import MAX_TASK_OUTPUT_BYTES, MAX_TASK_OUTPUT_BYTES_DISPLAY
from hare.utils.task.task_output import TaskOutput

SIGKILL_CODE = 137
SIGTERM_CODE = 143
SIZE_WATCHDOG_INTERVAL_MS = 5_000


def _prepend_stderr(prefix: str, stderr: str) -> str:
    return f"{prefix} {stderr}" if stderr else prefix


def _format_duration_ms(ms: int) -> str:
    if ms >= 60_000:
        return f"{ms // 60_000}m"
    if ms >= 1_000:
        return f"{ms // 1_000}s"
    return f"{ms}ms"


@dataclass
class ExecResult:
    stdout: str
    stderr: str
    code: int
    interrupted: bool
    background_task_id: str | None = None
    backgrounded_by_user: bool | None = None
    assistant_auto_backgrounded: bool | None = None
    output_file_path: str | None = None
    output_file_size: int | None = None
    output_task_id: str | None = None
    pre_spawn_error: str | None = None


async def _drain_stream(stream: asyncio.StreamReader | None, task_output: TaskOutput, is_stderr: bool) -> None:
    if stream is None:
        return
    while True:
        chunk = await stream.read(65_536)
        if not chunk:
            break
        s = chunk.decode("utf-8", errors="replace")
        if is_stderr:
            task_output.write_stderr(s)
        else:
            task_output.write_stdout(s)


@runtime_checkable
class ShellCommand(Protocol):
    background: Callable[[str], bool]
    result: Any
    kill: Callable[[], None]
    status: Literal["running", "backgrounded", "completed", "killed"]
    cleanup: Callable[[], None]
    on_timeout: Any
    task_output: TaskOutput


class ShellCommandImpl:
    """Async subprocess wrapper — mirrors ShellCommandImpl in TS."""

    def __init__(
        self,
        proc: asyncio.subprocess.Process,
        timeout_ms: int,
        task_output: TaskOutput,
        should_auto_background: bool = False,
        max_output_bytes: int = MAX_TASK_OUTPUT_BYTES,
    ) -> None:
        self._proc = proc
        self._timeout_ms = timeout_ms
        self.task_output = task_output
        self._should_auto_background = should_auto_background
        self._max_output_bytes = max_output_bytes
        self._status: Literal["running", "backgrounded", "completed", "killed"] = "running"
        self._background_task_id: str | None = None
        self._on_timeout_cb: Callable[[Callable[[str], bool], None], None] | None = None
        self._killed_for_size = False
        self._watchdog: asyncio.Task[None] | None = None
        self._result_fut: asyncio.Future[ExecResult] = asyncio.Future()
        self.on_timeout: Callable[[Callable[[Callable[[str], bool], None], None], None], None] | None = None
        if should_auto_background:

            def _ot(cb: Callable[[Callable[[str], bool], None], None]) -> None:
                self._on_timeout_cb = cb

            self.on_timeout = _ot

        self._main = asyncio.create_task(self._drive())

    @property
    def status(self) -> Literal["running", "backgrounded", "completed", "killed"]:
        return self._status

    @property
    def result(self) -> asyncio.Future[ExecResult]:
        return self._result_fut

    async def _drive(self) -> None:
        out_t = asyncio.create_task(_drain_stream(self._proc.stdout, self.task_output, False))
        err_t = asyncio.create_task(_drain_stream(self._proc.stderr, self.task_output, True))

        async def _timeout() -> None:
            await asyncio.sleep(self._timeout_ms / 1000.0)
            if self._status != "running":
                return
            if self._should_auto_background and self._on_timeout_cb is not None:
                self._on_timeout_cb(self.background)
            else:
                await self._do_kill(SIGTERM_CODE)

        timer = asyncio.create_task(_timeout())
        try:
            code = await self._proc.wait()
        finally:
            timer.cancel()
            await asyncio.gather(out_t, err_t, return_exceptions=True)

        if self._status in ("running", "backgrounded"):
            self._status = "completed"

        stdout = await self.task_output.get_stdout()
        stderr = self.task_output.get_stderr()
        exit_code = code if code is not None else 1
        res = ExecResult(
            code=int(exit_code),
            stdout=stdout,
            stderr=stderr,
            interrupted=exit_code == SIGKILL_CODE,
            background_task_id=self._background_task_id,
        )
        if self._killed_for_size:
            res.stderr = _prepend_stderr(
                f"Background command killed: output file exceeded {MAX_TASK_OUTPUT_BYTES_DISPLAY}",
                res.stderr,
            )
        elif exit_code == SIGTERM_CODE:
            res.stderr = _prepend_stderr(
                f"Command timed out after {_format_duration_ms(self._timeout_ms)}",
                res.stderr,
            )
        if not self._result_fut.done():
            self._result_fut.set_result(res)

    async def _do_kill(self, code: int) -> None:
        self._status = "killed"
        if self._proc.pid:
            try:
                self._proc.kill()
            except ProcessLookupError:
                pass
        if not self._result_fut.done():
            self._result_fut.set_result(
                ExecResult(stdout="", stderr="", code=code, interrupted=True)
            )

    def background(self, task_id: str) -> bool:
        if self._status != "running":
            return False
        self._background_task_id = task_id
        self._status = "backgrounded"
        if self.task_output.stdout_to_file:
            self._watchdog = asyncio.create_task(self._size_watchdog())
        return True

    async def _size_watchdog(self) -> None:
        path = Path(self.task_output.path)
        while self._status == "backgrounded":
            await asyncio.sleep(SIZE_WATCHDOG_INTERVAL_MS / 1000.0)
            try:
                sz = path.stat().st_size
            except OSError:
                continue
            if sz > self._max_output_bytes and self._status == "backgrounded":
                self._killed_for_size = True
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass
                return

    def kill(self) -> None:
        asyncio.create_task(self._do_kill(SIGKILL_CODE))

    def cleanup(self) -> None:
        if self._watchdog:
            self._watchdog.cancel()


async def wrap_spawn(
    proc: asyncio.subprocess.Process,
    _abort_event: asyncio.Event,
    timeout_ms: int,
    task_output: TaskOutput,
    should_auto_background: bool = False,
    max_output_bytes: int = MAX_TASK_OUTPUT_BYTES,
) -> ShellCommandImpl:
    del _abort_event
    return ShellCommandImpl(
        proc,
        timeout_ms,
        task_output,
        should_auto_background,
        max_output_bytes,
    )


def create_aborted_command(
    background_task_id: str | None = None,
    *,
    stderr: str | None = None,
    code: int | None = None,
) -> Any:
    task_output = TaskOutput(generate_task_id("local_bash"), None)
    fut: asyncio.Future[ExecResult] = asyncio.Future()
    fut.set_result(
        ExecResult(
            code=code if code is not None else 145,
            stdout="",
            stderr=stderr or "Command aborted before execution",
            interrupted=True,
            background_task_id=background_task_id,
        )
    )

    class _Aborted:
        status = "killed"
        result = fut
        task_output = task_output
        on_timeout = None

        def background(self, _task_id: str) -> bool:
            return False

        def kill(self) -> None:
            pass

        def cleanup(self) -> None:
            pass

    return _Aborted()


def create_failed_command(pre_spawn_error: str) -> Any:
    task_output = TaskOutput(generate_task_id("local_bash"), None)
    fut: asyncio.Future[ExecResult] = asyncio.Future()
    fut.set_result(
        ExecResult(
            code=1,
            stdout="",
            stderr=pre_spawn_error,
            interrupted=False,
            pre_spawn_error=pre_spawn_error,
        )
    )

    class _Failed:
        status = "completed"
        result = fut
        task_output = task_output
        on_timeout = None

        def background(self, _task_id: str) -> bool:
            return False

        def kill(self) -> None:
            pass

        def cleanup(self) -> None:
            pass

    return _Failed()
