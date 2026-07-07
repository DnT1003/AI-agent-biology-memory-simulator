"""Port of: src/skills/bundledSkills.ts"""
from __future__ import annotations
from hare.skills.bundled import get_all_bundled_skills, BundledSkill

def get_bundled_skill_names() -> list[str]:
    return [s.name for s in get_all_bundled_skills()]

def get_bundled_skill_content(name: str) -> str:
    from hare.skills.bundled import get_bundled_skill
    skill = get_bundled_skill(name)
    return skill.content if skill else ""
