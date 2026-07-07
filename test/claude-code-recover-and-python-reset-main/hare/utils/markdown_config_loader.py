"""Load commands/agents/skills markdown — port of `markdownConfigLoader.ts` (subset)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from hare.utils.env_utils import get_claude_config_home_dir
from hare.utils.frontmatter_parser import parse_frontmatter

CLAUDE_CONFIG_DIRECTORIES: tuple[str, ...] = (
    "commands",
    "agents",
    "output-styles",
    "skills",
    "workflows",
)
SettingSource = Literal["policySettings", "userSettings", "projectSettings"]


@dataclass
class MarkdownFile:
    file_path: str
    base_dir: str
    frontmatter: dict[str, Any]
    content: str
    source: SettingSource


def extract_description_from_markdown(content: str, default_description: str = "Custom item") -> str:
    for line in content.split("\n"):
        t = line.strip()
        if not t:
            continue
        hm = re.match(r"^#+\s+(.+)$", t)
        text = hm.group(1) if hm else t
        return text[:100] + ("..." if len(text) > 100 else "")
    return default_description


def _parse_tool_list_string(tools_value: Any) -> list[str] | None:
    if tools_value is None:
        return None
    if not tools_value:
        return []
    if isinstance(tools_value, str):
        arr = [tools_value]
    elif isinstance(tools_value, list):
        arr = [x for x in tools_value if isinstance(x, str)]
    else:
        return []
    try:
        from hare.utils.permissions.permission_setup import parse_tool_list_from_cli  # type: ignore[import-not-found]

        parsed = parse_tool_list_from_cli(arr)
    except ImportError:
        parsed = arr
    if "*" in parsed:
        return ["*"]
    return parsed


def parse_agent_tools_from_frontmatter(tools_value: Any) -> list[str] | None:
    parsed = _parse_tool_list_string(tools_value)
    if parsed is None:
        return None if tools_value is None else []
    if "*" in parsed:
        return None
    return parsed


def parse_slash_command_tools_from_frontmatter(tools_value: Any) -> list[str]:
    parsed = _parse_tool_list_string(tools_value)
    if parsed is None:
        return []
    return parsed


async def load_markdown_files_for_subdir(subdir: str, cwd: str) -> list[MarkdownFile]:
    """Discover and parse `.md` under managed/user/project `.claude/{subdir}` — stub I/O."""
    user_dir = Path(get_claude_config_home_dir()) / subdir
    out: list[MarkdownFile] = []
    if user_dir.is_dir():
        for p in user_dir.glob("*.md"):
            try:
                raw = p.read_text(encoding="utf-8")
                parsed = parse_frontmatter(raw, str(p))
                fm = parsed.get("frontmatter") or {}
                body = parsed.get("content") or ""
                out.append(
                    MarkdownFile(
                        file_path=str(p),
                        base_dir=str(user_dir),
                        frontmatter=fm if isinstance(fm, dict) else {},
                        content=body,
                        source="userSettings",
                    )
                )
            except OSError:
                pass
    proj = Path(cwd) / ".claude" / subdir
    if proj.is_dir():
        for p in proj.glob("*.md"):
            try:
                raw = p.read_text(encoding="utf-8")
                parsed = parse_frontmatter(raw, str(p))
                fm = parsed.get("frontmatter") or {}
                body = parsed.get("content") or ""
                out.append(
                    MarkdownFile(
                        file_path=str(p),
                        base_dir=str(proj),
                        frontmatter=fm if isinstance(fm, dict) else {},
                        content=body,
                        source="projectSettings",
                    )
                )
            except OSError:
                pass
    return out


def get_project_dirs_up_to_home(subdir: str, cwd: str) -> list[str]:
    """Walk parents until git root — simplified stub."""
    dirs: list[str] = []
    cur = Path(cwd).resolve()
    home = Path.home().resolve()
    for _ in range(64):
        cl = cur / ".claude" / subdir
        if cl.is_dir():
            dirs.append(str(cl))
        if cur == home:
            break
        if (cur / ".git").exists():
            break
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return dirs
