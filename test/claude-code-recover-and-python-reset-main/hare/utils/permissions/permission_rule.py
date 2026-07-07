"""Port of: src/utils/permissions/PermissionRule.ts + permissionRuleParser.ts"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
import re

@dataclass
class PermissionRuleValue:
    tool_name: str
    rule_content: str = ""

def parse_permission_rule(rule_string: str) -> PermissionRuleValue:
    m = re.match(r'^([^(]+)\(([^)]+)\)$', rule_string)
    if not m: return PermissionRuleValue(tool_name=rule_string)
    return PermissionRuleValue(tool_name=m.group(1), rule_content=m.group(2))

def extract_prefix(rule: str) -> Optional[str]:
    m = re.match(r'^(.+):\*$', rule)
    return m.group(1) if m else None

def normalize_legacy_tool_name(name: str) -> str:
    mapping = {"Task": "Agent", "Bash": "Bash", "Edit": "FileEdit", "Read": "FileRead", "Write": "FileWrite"}
    return mapping.get(name, name)
