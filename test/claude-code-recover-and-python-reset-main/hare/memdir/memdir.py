"""
MemDir – memory-backed directory for ephemeral file storage.

Port of: src/memdir/memdir.ts
"""

from __future__ import annotations

import os
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemDir:
    """In-memory directory for storing session artifacts."""
    base_path: str
    _files: dict[str, str] = field(default_factory=dict)

    def write(self, relative_path: str, content: str) -> None:
        full = os.path.join(self.base_path, relative_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        self._files[relative_path] = content

    def read(self, relative_path: str) -> str | None:
        if relative_path in self._files:
            return self._files[relative_path]
        full = os.path.join(self.base_path, relative_path)
        if os.path.isfile(full):
            with open(full, "r", encoding="utf-8") as f:
                content = f.read()
            self._files[relative_path] = content
            return content
        return None

    def exists(self, relative_path: str) -> bool:
        if relative_path in self._files:
            return True
        return os.path.exists(os.path.join(self.base_path, relative_path))

    def list_files(self) -> list[str]:
        result: list[str] = []
        for root, dirs, files in os.walk(self.base_path):
            for f in files:
                full = os.path.join(root, f)
                rel = os.path.relpath(full, self.base_path)
                result.append(rel.replace("\\", "/"))
        return result

    def delete(self, relative_path: str) -> bool:
        self._files.pop(relative_path, None)
        full = os.path.join(self.base_path, relative_path)
        if os.path.isfile(full):
            os.remove(full)
            return True
        return False
