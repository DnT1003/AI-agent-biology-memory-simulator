"""
Session runner – spawn and manage CLI child processes.

Port of: src/bridge/sessionRunner.ts
"""
from __future__ import annotations
import asyncio, json, os, re
from typing import Any
from hare.bridge.types import WorkData, SessionHandle


def safe_filename_id(s: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_-]', '_', s)[:64]


class _ProcessSessionHandle:
    def __init__(self, proc: asyncio.subprocess.Process):
        self._proc = proc

    async def send(self, message: str) -> None:
        if self._proc.stdin:
            self._proc.stdin.write((message + "\n").encode())
            await self._proc.stdin.drain()

    async def stop(self) -> None:
        self._proc.terminate()
        try:
            await asyncio.wait_for(self._proc.wait(), 5)
        except asyncio.TimeoutError:
            self._proc.kill()

    @property
    def is_running(self) -> bool:
        return self._proc.returncode is None


class SessionSpawnerImpl:
    def __init__(self, cli_path: str = ""):
        self._cli = cli_path

    async def spawn(self, work: WorkData) -> SessionHandle:
        cmd = self._cli or "claude"
        proc = await asyncio.create_subprocess_exec(
            cmd, "--session-id", work.session_id,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        return _ProcessSessionHandle(proc)


def create_session_spawner(cli_path: str = "") -> SessionSpawnerImpl:
    return SessionSpawnerImpl(cli_path)
