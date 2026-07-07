"""
Bridge main loop – poll for work and dispatch sessions.

Port of: src/bridge/bridgeMain.ts
"""
from __future__ import annotations
import asyncio, time
from typing import Any
from hare.bridge.types import BridgeConfig, SessionSpawner, SessionHandle
from hare.bridge.bridge_api import BridgeApiClient, BridgeFatalError, create_bridge_api_client


class BackoffConfig:
    def __init__(self, initial_ms: int = 1000, max_ms: int = 60000, multiplier: float = 2.0):
        self.initial_ms = initial_ms
        self.max_ms = max_ms
        self.multiplier = multiplier
        self._current = initial_ms

    def next_delay(self) -> float:
        delay = self._current / 1000.0
        self._current = min(int(self._current * self.multiplier), self.max_ms)
        return delay

    def reset(self) -> None:
        self._current = self.initial_ms


async def run_bridge_loop(
    config: BridgeConfig,
    spawner: SessionSpawner,
    on_error: Any = None,
) -> None:
    client = create_bridge_api_client(config)
    backoff = BackoffConfig()
    sessions: dict[str, SessionHandle] = {}
    running = True
    heartbeat_task: asyncio.Task | None = None

    async def heartbeat_loop() -> None:
        while running:
            await asyncio.sleep(config.heartbeat_interval_ms / 1000)
            await client.heartbeat()

    heartbeat_task = asyncio.create_task(heartbeat_loop())
    try:
        while running:
            try:
                response = await client.poll_work()
                if response.work:
                    work = response.work
                    await client.ack_work(work.work_id)
                    handle = await spawner.spawn(work)
                    sessions[work.session_id] = handle
                    backoff.reset()
                else:
                    await asyncio.sleep(config.poll_interval_ms / 1000)
            except BridgeFatalError:
                running = False
                break
            except Exception:
                await asyncio.sleep(backoff.next_delay())
    finally:
        running = False
        if heartbeat_task:
            heartbeat_task.cancel()
        for sid, handle in sessions.items():
            try:
                await handle.stop()
            except Exception:
                pass
        await client.deregister()
