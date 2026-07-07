"""Model capability flags (vision, tools, etc.).

Port of: src/utils/model/modelCapabilities.ts
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelCapabilities:
    vision: bool = False
    tools: bool = True
    computer_use: bool = False
    max_output_tokens: int | None = None


def get_capabilities_for_model(model: str) -> ModelCapabilities:
    del model
    return ModelCapabilities()
