"""
Bridge API client – HTTP communication with bridge service.

Port of: src/bridge/bridgeApi.ts
"""
from __future__ import annotations
import json, urllib.request, urllib.error
from dataclasses import dataclass
from typing import Any
from hare.bridge.types import BridgeConfig, WorkResponse, WorkData, WorkSecret


class BridgeFatalError(Exception):
    pass


@dataclass
class BridgeApiClient:
    config: BridgeConfig

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.config.access_token}",
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }

    def _url(self, path: str) -> str:
        return f"{self.config.base_url}{path}"

    async def poll_work(self) -> WorkResponse:
        url = self._url(f"/v1/environments/bridge/{self.config.bridge_id}/work")
        try:
            req = urllib.request.Request(url, headers=self._headers())
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            wr = WorkResponse(status=data.get("status", ""))
            if data.get("work"):
                w = data["work"]
                wr.work = WorkData(
                    work_id=w.get("work_id", ""),
                    session_id=w.get("session_id", ""),
                    prompt=w.get("prompt", ""),
                )
            return wr
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 410):
                raise BridgeFatalError(f"HTTP {e.code}: {e.reason}")
            return WorkResponse(status="error")
        except Exception:
            return WorkResponse(status="error")

    async def ack_work(self, work_id: str) -> None:
        url = self._url(f"/v1/environments/bridge/{self.config.bridge_id}/work/{work_id}/ack")
        try:
            req = urllib.request.Request(url, method="POST", headers=self._headers(), data=b"{}")
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass

    async def heartbeat(self) -> None:
        url = self._url(f"/v1/environments/bridge/{self.config.bridge_id}/heartbeat")
        try:
            req = urllib.request.Request(url, method="POST", headers=self._headers(), data=b"{}")
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass

    async def stop_session(self, session_id: str) -> None:
        url = self._url(f"/v1/environments/bridge/{self.config.bridge_id}/sessions/{session_id}/stop")
        try:
            req = urllib.request.Request(url, method="POST", headers=self._headers(), data=b"{}")
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass

    async def deregister(self) -> None:
        url = self._url(f"/v1/environments/bridge/{self.config.bridge_id}")
        try:
            req = urllib.request.Request(url, method="DELETE", headers=self._headers())
            urllib.request.urlopen(req, timeout=10)
        except Exception:
            pass


def create_bridge_api_client(config: BridgeConfig) -> BridgeApiClient:
    return BridgeApiClient(config=config)
