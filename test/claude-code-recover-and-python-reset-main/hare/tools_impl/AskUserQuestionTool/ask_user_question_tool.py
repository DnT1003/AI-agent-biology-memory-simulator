"""
AskUserQuestionTool – ask user multiple-choice questions.

Port of: src/tools/AskUserQuestionTool/ (prompt-only in TS; implementation in TSX)
"""
from __future__ import annotations
from typing import Any

TOOL_NAME = "AskUserQuestion"

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "question": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}},
                        "multiSelect": {"type": "boolean"},
                    },
                    "required": ["id", "question", "options"],
                },
            },
        },
        "required": ["questions"],
    }

async def call(questions: list[dict[str, Any]] | None = None, **kwargs: Any) -> dict[str, Any]:
    if not questions:
        return {"error": "No questions provided"}
    answers: list[dict[str, Any]] = []
    for q in questions:
        answers.append({
            "id": q.get("id", ""),
            "question": q.get("question", ""),
            "answer": "(awaiting user input)",
        })
    return {"questions": answers, "status": "pending"}
