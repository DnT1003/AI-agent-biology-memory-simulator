"""Port of: src/bridge/trustedDevice.ts"""
from __future__ import annotations
import os, json

_TOKEN_FILE = os.path.join(os.path.expanduser("~"), ".claude", "trusted_device.json")

def get_trusted_device_token() -> str | None:
    if not os.path.isfile(_TOKEN_FILE):
        return None
    try:
        with open(_TOKEN_FILE, "r") as f:
            data = json.load(f)
        return data.get("token")
    except Exception:
        return None

def clear_trusted_device() -> None:
    try:
        os.remove(_TOKEN_FILE)
    except OSError:
        pass

def enroll_trusted_device(token: str) -> None:
    os.makedirs(os.path.dirname(_TOKEN_FILE), exist_ok=True)
    with open(_TOKEN_FILE, "w") as f:
        json.dump({"token": token}, f)
