"""YOLO / fast-path classifier for auto mode. Port of yoloClassifier.ts."""

from __future__ import annotations

from dataclasses import dataclass


YOLO_CLASSIFIER_TOOL_NAME = "YoloClassifier"


@dataclass
class YoloClassifierResult:
    should_block: bool
    reason: str
    model: str = "stub"


async def run_yolo_classifier(
    _tool_name: str,
    _tool_input: dict[str, object],
) -> YoloClassifierResult:
    return YoloClassifierResult(should_block=False, reason="stub")
