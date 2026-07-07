"""Port of: src/utils/plans.ts"""
from __future__ import annotations
import os
from typing import Any, Optional

def get_plan_file_path(project_dir: str = "") -> str:
    base = project_dir or os.getcwd()
    return os.path.join(base, ".claude", "plan.md")

def get_plan(project_dir: str = "") -> Optional[str]:
    path = get_plan_file_path(project_dir)
    if not os.path.exists(path): return None
    with open(path, "r") as f: return f.read()

def save_plan(content: str, project_dir: str = "") -> None:
    path = get_plan_file_path(project_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f: f.write(content)
