from typing import List, Dict, Callable

import ast
import keyword
import math
import time
import random
import os
import importlib.util
import inspect
import uuid
from pathlib import Path

from config import Config
from core.event_journal import record_current_event
from core.tool_result import ToolFailure


DYNAMIC_SKILLS_DIR = Path(__file__).resolve().parent / "dynamic_skills"
DYNAMIC_SKILL_CANDIDATES_DIR = Path(Config.OUTPUT_DIR) / "dynamic_skill_candidates"
DYNAMIC_SKILL_ALLOWED_IMPORTS = frozenset({
    "math", "json", "re", "datetime", "collections",
    "itertools", "functools", "string", "textwrap", "random",
    "time", "decimal", "fractions", "statistics", "hashlib",
    "base64", "uuid", "copy", "dataclasses", "enum", "typing",
})
DYNAMIC_SKILL_DANGEROUS_NAMES = frozenset({
    "exec", "eval", "open", "__import__", "compile", "breakpoint",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "help", "input", "exit", "quit",
})
DYNAMIC_SKILL_DANGEROUS_ATTRIBUTES = frozenset({
    "os", "sys", "subprocess", "builtins", "importlib", "modules",
    "environ", "system", "popen", "fork", "startfile", "socket",
})


def _record_skill_event(event_type: str, payload: dict, *, outcome: str) -> None:
    """Tool instrumentation must never change the tool's runtime contract."""

    try:
        record_current_event(event_type, payload, outcome=outcome)
    except Exception:
        # ``record_current_event`` is already fail-open. Keep this second
        # boundary so a future recorder implementation cannot break tools.
        return


def _report_skill_accounting_failure(
    *,
    tool_name: str,
    phase: str,
    error: Exception,
    call_id: str | None = None,
) -> None:
    """Expose degraded accounting without leaking tool inputs or error text."""

    payload = {
        "tool_name": tool_name,
        "phase": phase,
        "error_type": type(error).__name__,
    }
    if call_id is not None:
        payload["call_id"] = call_id
    _record_skill_event("tool.accounting_warning", payload, outcome="failed")

    try:
        from core.logger import get_logger

        get_logger("skills").warning(
            "Skill accounting persistence failed during %s (%s); "
            "in-memory accounting was restored",
            phase,
            type(error).__name__,
        )
    except Exception:
        # Reporting must not replace either a committed tool result or the
        # original pre-execution failure contract.
        return


def resolve_dynamic_skills_dir() -> Path:
    """Resolve the skills directory without following it outside core/."""
    configured_dir = Path(DYNAMIC_SKILLS_DIR)
    expected_parent = configured_dir.parent.resolve()
    resolved_dir = configured_dir.resolve()
    if resolved_dir.parent != expected_parent:
        raise ValueError("Thư mục kỹ năng động trỏ ra ngoài thư mục core")
    return resolved_dir


def resolve_dynamic_skill_candidates_dir() -> Path:
    """Resolve the quarantine directory without following it outside OUTPUT_DIR."""
    output_dir = Path(Config.OUTPUT_DIR).resolve()
    configured_dir = Path(DYNAMIC_SKILL_CANDIDATES_DIR)
    resolved_dir = configured_dir.resolve()
    if resolved_dir.parent != output_dir:
        raise ValueError("Thư mục quarantine trỏ ra ngoài OUTPUT_DIR")
    return resolved_dir


def validate_dynamic_skill_name(name: object) -> tuple[bool, str]:
    """Accept only a small, portable Python module/function name."""
    import re

    if not isinstance(name, str):
        return False, "Tên kỹ năng phải là chuỗi"
    if not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", name, flags=re.ASCII):
        return False, "Tên kỹ năng phải là ASCII snake_case và dài tối đa 64 ký tự"
    if name == "__init__" or keyword.iskeyword(name):
        return False, f"Tên kỹ năng '{name}' không được phép"
    return True, "OK"


def validate_dynamic_skill_source(source: object) -> tuple[bool, str]:
    """Statically reject source outside the deliberately small skill subset."""
    if not isinstance(source, str):
        return False, "Mã nguồn kỹ năng phải là chuỗi"
    if len(source) > 50_000:
        return False, "Mã nguồn kỹ năng vượt quá giới hạn 50 KB"
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError) as exc:
        return False, f"Lỗi cú pháp: {exc}"

    nodes = list(ast.walk(tree))
    if len(nodes) > 2_000:
        return False, "Mã nguồn kỹ năng quá phức tạp"

    # Importing a candidate must not execute arbitrary top-level statements.
    for statement in tree.body:
        if isinstance(statement, (ast.Import, ast.ImportFrom, ast.FunctionDef)):
            if isinstance(statement, ast.FunctionDef) and statement.decorator_list:
                return False, "Decorator không được phép trong kỹ năng động"
            continue
        if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str):
            continue  # module docstring
        if isinstance(statement, ast.Assign):
            if not all(
                isinstance(target, ast.Name) and target.id in {"DESCRIPTION", "USAGE"}
                for target in statement.targets
            ):
                return False, "Chỉ DESCRIPTION và USAGE được khai báo ở cấp module"
            try:
                value = ast.literal_eval(statement.value)
            except (ValueError, TypeError):
                return False, "Metadata kỹ năng phải là hằng chuỗi"
            if not isinstance(value, str):
                return False, "Metadata kỹ năng phải là hằng chuỗi"
            continue
        return False, f"Câu lệnh cấp module không được phép: {type(statement).__name__}"

    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_level = alias.name.split(".")[0]
                if top_level not in DYNAMIC_SKILL_ALLOWED_IMPORTS:
                    return False, f"Module '{alias.name}' không được phép"
                if alias.asname in DYNAMIC_SKILL_DANGEROUS_ATTRIBUTES:
                    return False, f"Bí danh import '{alias.asname}' không được phép"
        elif isinstance(node, ast.ImportFrom):
            top_level = (node.module or "").split(".")[0]
            if top_level not in DYNAMIC_SKILL_ALLOWED_IMPORTS:
                return False, f"Import từ '{node.module}' không được phép"
            for alias in node.names:
                if (
                    alias.name.startswith("_")
                    or alias.name in DYNAMIC_SKILL_DANGEROUS_ATTRIBUTES
                    or alias.asname in DYNAMIC_SKILL_DANGEROUS_ATTRIBUTES
                ):
                    return False, f"Biểu tượng import '{alias.name}' không được phép"
        elif isinstance(node, ast.Name):
            if node.id in DYNAMIC_SKILL_DANGEROUS_NAMES or node.id.startswith("__"):
                return False, f"Tên nguy hiểm: '{node.id}'"
        elif isinstance(node, ast.Attribute):
            if (
                node.attr in DYNAMIC_SKILL_DANGEROUS_NAMES
                or node.attr in DYNAMIC_SKILL_DANGEROUS_ATTRIBUTES
                or node.attr in {"import_module", "exec_module"}
                or node.attr.startswith("_")
            ):
                return False, f"Thuộc tính nguy hiểm: '{node.attr}'"

    return True, "OK"

class Skill:
    def __init__(self, name: str, description: str, usage_format: str, func: Callable):
        self.name = name
        self.description = description
        self.usage_format = usage_format
        self.func = func
        self.mastery = 0.5      # Độ tinh thông: 0.0 -> 1.0
        self.rust_level = 0.0   # Sự mai một: 0.0 -> 1.0
        self.last_used = time.time()

class SkillRegistry:
    """Procedural memory registry with durable proficiency state."""

    _STATE_META_KEY = "__meta__"
    _DECAY_CHECKPOINT_KEY = "skill_decay_checkpoint_at"
    _STATE_VERSION = 1

    def __init__(self):
        import threading
        self.skills: Dict[str, Skill] = {}
        self.lock = threading.Lock()
        self.engine = None # Will be set by CognitiveEngine
        # ``None`` identifies a legacy state with no durable clock baseline.
        self._skill_decay_checkpoint_at = None

    def _ego_action(self, arg, action_type):
        if not self.engine: return ToolFailure("Engine not connected.")
        if action_type == "add_goal":
            self.engine.ego.add_goal(arg)
            return f"Mục tiêu '{arg}' đã được thiết lập."
        return ToolFailure("Unknown ego action.")

    def _reader_action(self, arg, action_type):
        if not self.engine: return ToolFailure("Engine not connected.")
        if action_type == "search_novel":
            # The interaction actor owns this call. Returning only after the
            # reader mutation finishes prevents a detached thread from racing
            # the next request or reporting success before failure is known.
            result = self.engine.reader.search_and_set_novel(arg)
            return result or ToolFailure(f"Không tìm thấy truyện '{arg}'.")
        return ToolFailure("Unknown reader action.")

    def _autonomous_action(self, arg, action_type):
        if not self.engine: return ToolFailure("Engine not connected.")
        if action_type == "start_reading":
            actor = getattr(self.engine, "interaction_actor", None)
            if actor is not None and actor.is_owner_thread:
                self.engine.autonomous._do_reading_session()
                return "Đã hoàn tất phiên đọc theo yêu cầu."
            if self.engine.autonomous.start_reading_task("User request"):
                return "Đã hoàn tất phiên đọc theo yêu cầu."
            return ToolFailure("Không thể bắt đầu đọc vì runtime đang bận.")
        return ToolFailure("Unknown autonomous action.")

    def register(self, skill: Skill):
        self.skills[skill.name] = skill

    @staticmethod
    def _skill_accounting_snapshot_unsafe(skill: Skill):
        return (skill.mastery, skill.rust_level, skill.last_used)

    @staticmethod
    def _restore_skill_accounting_snapshot_unsafe(skill: Skill, snapshot) -> None:
        skill.mastery, skill.rust_level, skill.last_used = snapshot

    def execute(self, name: str, args: str, ego=None) -> str:
        if name in self.skills:
            skill = self.skills[name]
            
            from colorama import Fore, Style
            import random, time
            
            with self.lock:
                # Áp dụng penalty nếu độ thông thạo thấp (lóng ngóng)
                if ego and skill.mastery < 0.4:
                    ego_lock = getattr(ego, "lock", None)
                    if ego_lock is None:
                        ego.fatigue = min(1.0, ego.fatigue + 0.05)
                        ego.stress = min(1.0, ego.stress + 0.05)
                    else:
                        with ego_lock:
                            ego.fatigue = min(1.0, ego.fatigue + 0.05)
                            ego.stress = min(1.0, ego.stress + 0.05)
                    print(f"{Fore.YELLOW}⚠️ [PROCEDURAL MEMORY]: Dùng tool '{name}' khi thông thạo thấp ({skill.mastery:.2f}). Aura tốn gấp đôi công sức và hơi căng thẳng.{Style.RESET_ALL}")
                
                # Nếu skill quá rỉ sét, có khả năng Aura bị "quên" cách dùng
                if skill.rust_level > 0.5 and random.random() < (skill.rust_level - 0.3):
                    accounting_snapshot = self._skill_accounting_snapshot_unsafe(skill)
                    try:
                        skill.rust_level = max(0.0, skill.rust_level - 0.2) # Thất bại nhưng cũng là một lần luyện tập (nhớ lại)
                        skill.mastery = max(0.0, skill.mastery - 0.05)
                        skill.last_used = time.time()
                        self._save_unsafe()
                    except Exception as accounting_error:
                        self._restore_skill_accounting_snapshot_unsafe(
                            skill, accounting_snapshot
                        )
                        _report_skill_accounting_failure(
                            tool_name=name,
                            phase="rust_no_call",
                            error=accounting_error,
                        )
                        return (
                            "[SYSTEM]: Skill accounting persistence failed; "
                            "the tool was not executed. Please retry later."
                        )
                    return f"[HỆ THỐNG]: Bạn đã quên cú pháp chính xác hoặc lóng ngóng khi dùng tool '{name}'. Vui lòng thử lại sau."
                
            try:
                # Phân tích tham số truyền vào nếu kỹ năng yêu cầu (Thực thi NGOÀI Lock để chạy song song)
                call_id = uuid.uuid4().hex
                tool_started_at = time.monotonic()
                _record_skill_event(
                    "tool.started",
                    {"call_id": call_id, "tool_name": name},
                    outcome="started",
                )
                result = skill.func(args)
                if isinstance(result, ToolFailure):
                    # Reported failure: no mastery gain, no rust reset, no reward.
                    _record_skill_event(
                        "tool.finished",
                        {
                            "call_id": call_id,
                            "tool_name": name,
                            "duration_ms": max(
                                0.0, (time.monotonic() - tool_started_at) * 1000.0
                            ),
                            "error_type": "ToolFailure",
                        },
                        outcome="failed",
                    )
                    return result

                accounting_error = None
                with self.lock:
                    accounting_snapshot = self._skill_accounting_snapshot_unsafe(skill)
                    # Cập nhật độ nhuần nhuyễn
                    # Dùng tool thành công sẽ tăng proficiency nhanh
                    try:
                        skill.mastery = min(1.0, skill.mastery + 0.1)
                        skill.rust_level = 0.0
                        skill.last_used = time.time()
                        self._save_unsafe()
                    except Exception as exc:
                        self._restore_skill_accounting_snapshot_unsafe(
                            skill, accounting_snapshot
                        )
                        accounting_error = exc

                if accounting_error is not None:
                    _report_skill_accounting_failure(
                        tool_name=name,
                        phase="post_success",
                        error=accounting_error,
                        call_id=call_id,
                    )

                register_reward = getattr(ego, "register_reward", None)
                if callable(register_reward):
                    # Dopamine: a user-requested tool that worked is rewarding.
                    try:
                        register_reward("tool_success", 0.3)
                    except Exception:
                        pass

                _record_skill_event(
                    "tool.finished",
                    {
                        "call_id": call_id,
                        "tool_name": name,
                        "duration_ms": max(
                            0.0, (time.monotonic() - tool_started_at) * 1000.0
                        ),
                    },
                    outcome="succeeded",
                )
                return result
            except Exception as e:
                if "call_id" in locals():
                    _record_skill_event(
                        "tool.finished",
                        {
                            "call_id": call_id,
                            "tool_name": name,
                            "duration_ms": max(
                                0.0,
                                (time.monotonic() - tool_started_at) * 1000.0,
                            ),
                            "error_type": type(e).__name__,
                        },
                        outcome="failed",
                    )
                return f"Lỗi khi thực thi kỹ năng '{name}': {e}"
        return f"Tôi không biết cách dùng công cụ '{name}'."
        
    def decay_skills(self, days_passed: float):
        """Hàm được gọi khi Aura đi ngủ, làm rỉ sét các kỹ năng ít dùng"""
        with self.lock:
            now = time.time()
            snapshot = self._skill_decay_snapshot_unsafe()
            try:
                self._apply_skill_decay_unsafe(days_passed, now=now)
                self._save_unsafe()
            except Exception:
                self._restore_skill_decay_snapshot_unsafe(snapshot)
                raise

    def decay_skills_by_clock(self, now=None):
        """Decay by the durable skill clock, independent from memory state.

        A legacy state first persists ``now`` without retroactive decay. Skill
        changes and the advanced checkpoint share one atomic write. A failed
        write rolls both back so retrying observes the exact same interval.
        """
        current_time = time.time() if now is None else now
        if (
            isinstance(current_time, bool)
            or not isinstance(current_time, (int, float))
            or not math.isfinite(float(current_time))
        ):
            raise ValueError("now must be a finite Unix timestamp")
        current_time = float(current_time)

        with self.lock:
            snapshot = self._skill_decay_snapshot_unsafe()
            checkpoint = self._skill_decay_checkpoint_at
            if checkpoint is None:
                self._skill_decay_checkpoint_at = current_time
                try:
                    self._save_unsafe()
                except Exception:
                    self._restore_skill_decay_snapshot_unsafe(snapshot)
                    raise
                return 0.0

            elapsed_seconds = current_time - checkpoint
            if elapsed_seconds <= 0.0:
                return 0.0

            elapsed_days = elapsed_seconds / 86400.0
            try:
                self._apply_skill_decay_unsafe(elapsed_days, now=current_time)
                self._skill_decay_checkpoint_at = current_time
                self._save_unsafe()
            except Exception:
                self._restore_skill_decay_snapshot_unsafe(snapshot)
                raise
            return elapsed_days

    def _apply_skill_decay_unsafe(self, days_passed: float, *, now: float):
        if (
            isinstance(days_passed, bool)
            or not isinstance(days_passed, (int, float))
            or not math.isfinite(float(days_passed))
            or days_passed < 0.0
        ):
            raise ValueError("days_passed must be a finite non-negative number")
        days_passed = float(days_passed)
        for skill in self.skills.values():
            days_since_last_use = (now - skill.last_used) / 86400.0
            if days_since_last_use > 1.0:
                skill.rust_level = min(1.0, skill.rust_level + 0.1 * days_passed)
                skill.mastery = max(0.0, skill.mastery - 0.05 * days_passed)

    def _skill_decay_snapshot_unsafe(self):
        return (
            self._skill_decay_checkpoint_at,
            {
                name: (skill.mastery, skill.rust_level)
                for name, skill in self.skills.items()
            },
        )

    def _restore_skill_decay_snapshot_unsafe(self, snapshot):
        checkpoint, skill_values = snapshot
        self._skill_decay_checkpoint_at = checkpoint
        for name, (mastery, rust_level) in skill_values.items():
            skill = self.skills.get(name)
            if skill is not None:
                skill.mastery = mastery
                skill.rust_level = rust_level

    def get_prompt_instructions(self) -> str:
        if not self.skills:
            return "HỆ THỐNG CÔNG CỤ (ACTION SYSTEM): Hiện tại không có công cụ nào."
            
        lines = ["HỆ THỐNG CÔNG CỤ (ACTION SYSTEM):", "Nếu cần dùng Tool, xuất ra ĐÚNG 1 dòng ACTION: <tên_tool> | <tham số>. Lưu ý: Độ thông thạo càng thấp, dùng Tool càng tốn sức và dễ lỗi."]
        for s in self.skills.values():
            level = "Chưa quen" if s.mastery < 0.4 else ("Khá quen" if s.mastery < 0.8 else "Rất thành thạo")
            lines.append(f"- Tool \"{s.name}\": {s.description}. VD: {s.usage_format}. [Độ thông thạo: Chọn ở mức {level} ({s.mastery:.2f}/1.0)]")
        return "\n".join(lines)

    def _state_unsafe(self):
        meta = {"version": self._STATE_VERSION}
        if self._skill_decay_checkpoint_at is not None:
            meta[self._DECAY_CHECKPOINT_KEY] = self._skill_decay_checkpoint_at
        data = {
            k: {
                "mastery": s.mastery,
                "rust_level": s.rust_level,
                "last_used": s.last_used,
            }
            for k, s in self.skills.items()
        }
        data[self._STATE_META_KEY] = meta
        return data

    def _save_unsafe(self):
        from core.utils import atomic_write_json
        from config import Config
        atomic_write_json(Config.SKILLS_FILE, self._state_unsafe())

    def save(self):
        with self.lock:
            self._save_unsafe()

    def load_dynamic_skills(self):
        """Nạp kỹ năng đã được operator duyệt, rồi cô lập mỗi lần gọi trong subprocess."""
        import subprocess, json, sys
        from config import Config
        from colorama import Fore, Style
        
        if not getattr(Config, 'ALLOW_DYNAMIC_SKILLS', False):
            return

        try:
            dynamic_dir_path = resolve_dynamic_skills_dir()
        except ValueError as exc:
            print(f"{Fore.RED}   ❌ BLOCK: {exc}{Style.RESET_ALL}")
            return
        dynamic_dir = os.fspath(dynamic_dir_path)
        if not os.path.exists(dynamic_dir):
            return

        print(f"{Fore.CYAN}🔌 [DYNAMISM]: Đang kiểm tra an toàn và nạp kỹ năng tại {dynamic_dir}...{Style.RESET_ALL}")

        def create_sandbox_executor(f_path, f_name):
            def executor(args_str):
                snippet = """
import importlib.util, json, sys
file_path, function_name, function_arg = sys.argv[1:4]
spec = importlib.util.spec_from_file_location("approved_dynamic_skill", file_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
try:
    res = getattr(mod, function_name)(function_arg)
    print(json.dumps({"result": res}))
except Exception as e:
    print(json.dumps({"error": str(e)}))
"""
                try:
                    proc = subprocess.run(
                        [sys.executable, "-I", "-c", snippet, f_path, f_name, args_str],
                        capture_output=True, text=True, timeout=5.0
                    )
                    if proc.returncode != 0:
                        return f"[SANDBOX FATAL]: {proc.stderr.strip()}"
                    
                    return_lines = [l for l in proc.stdout.strip().split('\\n') if l]
                    if not return_lines:
                        return "[SANDBOX EMPTY]"
                    try:
                        data = json.loads(return_lines[-1])
                        if "error" in data: return f"[SKILL ERROR]: {data['error']}"
                        return data.get("result", str(return_lines[-1]))
                    except json.JSONDecodeError:
                        return f"[SKILL OUTPUT]: {proc.stdout.strip()}"
                except subprocess.TimeoutExpired:
                    return f"{Fore.RED}[SANDBOX BLOCKED]: Kỹ năng '{f_name}' chạy quá 5 giây (Nguy cơ Infinite Loop) và đã bị ngắt!{Style.RESET_ALL}"
                except Exception as e:
                    return f"[SANDBOX FAULT]: {e}"
            return executor

        for filename in os.listdir(dynamic_dir):
            if filename.endswith(".py") and filename != "__init__.py":
                module_name = filename[:-3]
                valid_name, invalid_reason = validate_dynamic_skill_name(module_name)
                if not valid_name:
                    print(f"{Fore.RED}   ❌ BLOCK: Tên kỹ năng {filename} bị từ chối — {invalid_reason}{Style.RESET_ALL}")
                    continue
                file_path_obj = (dynamic_dir_path / filename).resolve()
                if file_path_obj.parent != dynamic_dir_path:
                    print(f"{Fore.RED}   ❌ BLOCK: {filename} trỏ ra ngoài thư mục kỹ năng{Style.RESET_ALL}")
                    continue
                file_path = os.fspath(file_path_obj)
                
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        source = f.read()
                    
                    is_safe, block_reason = validate_dynamic_skill_source(source)
                    if not is_safe:
                        print(f"{Fore.RED}   ❌ BLOCK: Kỹ năng {filename} bị từ chối — {block_reason}{Style.RESET_ALL}")
                        continue
                    
                    import ast
                    tree = ast.parse(source)
                        
                    desc = "Kỹ năng tự học hệ thống."
                    usage = "ACTION: func | <tham số>"
                    funcs = []

                    for node in tree.body:
                        if isinstance(node, ast.Assign):
                            for target in node.targets:
                                if isinstance(target, ast.Name):
                                    if target.id == 'DESCRIPTION' and isinstance(node.value, ast.Constant):
                                        desc = str(node.value.value)
                                    elif target.id == 'USAGE' and isinstance(node.value, ast.Constant):
                                        usage = str(node.value.value)
                        elif isinstance(node, ast.FunctionDef):
                            if not node.name.startswith('_'):
                                funcs.append(node.name)

                    for name in funcs:
                        if name not in self.skills:
                            self.register(Skill(
                                name=name,
                                description=desc,
                                usage_format=usage,
                                func=create_sandbox_executor(file_path, name)
                            ))
                            print(f"{Fore.GREEN}   🛡️ Đã nạp Sandbox an toàn cho kỹ năng: {name}{Style.RESET_ALL}")
                            
                except Exception as e:
                    print(f"{Fore.RED}   ❌ Lỗi khi phân tích Sandbox {filename}: {e}{Style.RESET_ALL}")

    def load(self):
        from core.utils import atomic_read_json
        from config import Config
        if not os.path.exists(Config.SKILLS_FILE):
            return
        try:
            with self.lock:
                data = atomic_read_json(Config.SKILLS_FILE)
                meta = data.get(self._STATE_META_KEY, {})
                checkpoint = (
                    meta.get(self._DECAY_CHECKPOINT_KEY)
                    if isinstance(meta, dict)
                    else None
                )
                if (
                    not isinstance(checkpoint, bool)
                    and isinstance(checkpoint, (int, float))
                    and math.isfinite(float(checkpoint))
                ):
                    self._skill_decay_checkpoint_at = float(checkpoint)
                else:
                    self._skill_decay_checkpoint_at = None
                for k, v in data.items():
                    if k == self._STATE_META_KEY or not isinstance(v, dict):
                        continue
                    if k in self.skills:
                        self.skills[k].mastery = v.get("mastery", 0.5)
                        self.skills[k].rust_level = v.get("rust_level", 0.0)
                        self.skills[k].last_used = v.get("last_used", time.time())
        except Exception as e:
            print(f"Lỗi load skills: {e}")
