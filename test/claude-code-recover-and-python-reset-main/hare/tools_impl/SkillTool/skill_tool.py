"""
SkillTool – invoke a slash-command skill.

Port of: src/tools/SkillTool/SkillTool.ts
"""
from __future__ import annotations
from typing import Any

TOOL_NAME = "Skill"

def input_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "skill": {"type": "string", "description": "Skill name to invoke"},
            "args": {"type": "string", "description": "Optional arguments"},
        },
        "required": ["skill"],
    }

async def call(
    skill: str,
    args: str = "",
    context: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    from hare.commands_impl import find_command
    cmd = find_command(skill)
    if cmd and "call" in cmd:
        arg_list = args.split() if args else []
        result = await cmd["call"](arg_list, context)
        return {"data": result}
    return {"error": f"Skill '{skill}' not found"}
