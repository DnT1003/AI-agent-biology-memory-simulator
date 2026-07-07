"""Port of: src/cli/print.ts"""
from __future__ import annotations
import json
from typing import Any

def print_json(data: Any) -> None:
    print(json.dumps(data, indent=2, default=str))

def print_ndjson(data: Any) -> None:
    print(json.dumps(data, default=str))
