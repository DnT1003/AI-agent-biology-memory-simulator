"""Pure canonical runtime paths plus bounded legacy metadata discovery.

``RuntimePaths.from_env`` derives paths without writes or discovery.  Explicit
legacy discovery performs only non-recursive metadata inspection; it neither
opens artifact contents nor creates, migrates, deletes, or renames data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import ntpath
import os
from os import fspath
from pathlib import Path, PureWindowsPath
import stat
from types import MappingProxyType
from typing import Mapping


class RuntimePathError(ValueError):
    """Raised when a configured durable-root value is unsafe or invalid."""


class LegacyArtifactKind(str, Enum):
    EGO = "ego"
    IDENTITY = "identity"
    WORLD = "world"
    VALUES = "values"
    MEMORY = "memory"
    JOURNAL = "journal"
    LEDGER = "ledger"
    TRANSPORTS = "transports"


def _non_empty(env: Mapping[str, str], name: str) -> str | None:
    value = env.get(name)
    if not isinstance(value, str):
        return None
    return value if value.strip() else None


_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}
_WINDOWS_ILLEGAL_CHARACTERS = frozenset('<>:"|?*')


def _validate_path_text(
    raw: str,
    *,
    label: str,
    windows: bool | None = None,
    allow_lexical_parent_components: bool = False,
) -> None:
    if not raw.strip() or "\x00" in raw:
        raise RuntimePathError(f"{label} is empty or contains NUL")
    try:
        raw.encode("utf-8", "strict")
    except UnicodeError as exc:
        raise RuntimePathError(f"{label} contains an invalid path character") from exc

    if windows is None:
        windows = os.name == "nt"
    if not windows:
        return

    drive, tail = ntpath.splitdrive(raw)
    if drive and tail and not tail.startswith(("\\", "/")):
        raise RuntimePathError(f"{label} must not be drive-relative")
    if not drive and raw.startswith(("\\", "/")):
        raise RuntimePathError(f"{label} must not be root-relative")

    windows_path = PureWindowsPath(raw)
    for component in windows_path.parts:
        structural_components = (
            windows_path.drive,
            windows_path.root,
            f"{windows_path.drive}{windows_path.root}",
            "\\",
            "/",
        )
        if component in structural_components or (
            allow_lexical_parent_components and component in {".", ".."}
        ):
            continue
        if (
            any(ord(character) < 32 for character in component)
            or any(character in _WINDOWS_ILLEGAL_CHARACTERS for character in component)
            or component.endswith((".", " "))
            or component.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES
        ):
            raise RuntimePathError(f"{label} contains an invalid Windows path component")


def _canonical_path(
    value: str | Path,
    base_dir: Path,
    *,
    label: str,
    reject_filesystem_root: bool = True,
) -> Path:
    """Normalize one configured path without consulting the process CWD."""

    try:
        raw = fspath(value)
    except TypeError as exc:
        raise RuntimePathError(f"{label} must be a path") from exc
    if not isinstance(raw, str):
        raise RuntimePathError(f"{label} must be a path")
    _validate_path_text(raw, label=label)
    try:
        # expanduser is intentionally a single Path operation.  In particular,
        # '$NAME' and '%NAME%' remain literal directory names.
        candidate = Path(raw).expanduser()
        _validate_path_text(fspath(candidate), label=label)
        if not candidate.is_absolute():
            candidate = base_dir / candidate
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError, UnicodeError) as exc:
        raise RuntimePathError(f"{label} is not a valid path") from exc
    if not resolved.is_absolute():
        raise RuntimePathError(f"{label} did not resolve to an absolute path")
    if reject_filesystem_root and resolved == resolved.parent:
        raise RuntimePathError(f"{label} must not be a filesystem root")
    return resolved


def _unresolved_absolute_path(value: str | Path, base_dir: Path, *, label: str) -> Path:
    """Make an absolute lexical path while preserving ``..`` for link checks."""

    try:
        raw = fspath(value)
    except TypeError as exc:
        raise RuntimePathError(f"{label} must be a path") from exc
    if not isinstance(raw, str):
        raise RuntimePathError(f"{label} must be a path")
    _validate_path_text(raw, label=label, allow_lexical_parent_components=True)
    try:
        candidate = Path(raw).expanduser()
        _validate_path_text(
            fspath(candidate), label=label, allow_lexical_parent_components=True
        )
        if not candidate.is_absolute():
            candidate = base_dir / candidate
    except (OSError, RuntimeError, ValueError, UnicodeError) as exc:
        raise RuntimePathError(f"{label} is not a valid path") from exc
    if not candidate.is_absolute():
        raise RuntimePathError(f"{label} did not resolve to an absolute path")
    # Do not normalize here: ``broken-link/../artifact`` must visit the link
    # during the strict walk before non-strict canonicalization later.
    return candidate


def _validate_legacy_symlink_chain(path: Path, *, label: str) -> None:
    """Strictly inspect every symlink reachable through lexical components.

    A missing component makes only its lexical descendants unknown.  A later
    ``..`` can return to the last existing prefix, at which point subsequent
    links are reachable again and must still be validated before final
    canonicalization.
    """

    current = Path(path.anchor)
    current_is_directory = True
    missing_depth = 0
    start = 1 if path.anchor else 0
    for component in path.parts[start:]:
        if component == ".":
            continue
        if component == "..":
            if missing_depth:
                missing_depth -= 1
                continue
            if not current_is_directory:
                raise RuntimePathError(
                    f"legacy artifact candidate {label} has a non-directory intermediate"
                )
            current = current.parent
            current_is_directory = True
            continue

        if missing_depth:
            missing_depth += 1
            continue
        if not current_is_directory:
            raise RuntimePathError(
                f"legacy artifact candidate {label} has a non-directory intermediate"
            )

        candidate = current / component
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            # Preserve the known prefix.  Future ``..`` components can escape
            # this unknown suffix and make later paths reachable again.
            missing_depth = 1
            continue
        except OSError as exc:
            raise RuntimePathError(
                f"cannot inspect legacy artifact candidate {label}"
            ) from exc

        if stat.S_ISLNK(metadata.st_mode):
            try:
                current = candidate.resolve(strict=True)
                target_metadata = current.stat()
            except (OSError, RuntimeError, ValueError) as exc:
                raise RuntimePathError(
                    f"legacy artifact candidate {label} has an invalid symlink"
                ) from exc
            current_is_directory = stat.S_ISDIR(target_metadata.st_mode)
        else:
            current = candidate
            current_is_directory = stat.S_ISDIR(metadata.st_mode)


def _canonical_legacy_candidate(
    value: str | Path, base_dir: Path, *, label: str
) -> Path:
    """Canonicalize one candidate while retaining strict symlink safety."""

    unresolved = _unresolved_absolute_path(value, base_dir, label=label)
    _validate_legacy_symlink_chain(unresolved, label=label)
    try:
        canonical = unresolved.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RuntimePathError(f"{label} is not a valid legacy path") from exc
    if not canonical.is_absolute():
        raise RuntimePathError(f"{label} did not resolve to an absolute path")
    if canonical == canonical.parent:
        raise RuntimePathError(f"{label} must not be a filesystem root")
    return canonical


@dataclass(frozen=True)
class RuntimePaths:
    data_dir: Path
    manifest_path: Path
    control_db_path: Path
    writer_lease_path: Path
    state_dir: Path
    state_generations_dir: Path
    state_current_path: Path
    memory_chroma_dir: Path
    chat_spool_dir: Path
    event_journal_dir: Path
    recovery_dir: Path
    logs_dir: Path
    cache_dir: Path
    temp_dir: Path
    _base_dir: Path = field(repr=False, compare=False)
    _legacy_cwd: Path = field(repr=False, compare=False)

    @classmethod
    def from_env(
        cls,
        *,
        base_dir: Path,
        env: Mapping[str, str],
        cwd: Path | None = None,
    ) -> "RuntimePaths":
        """Derive paths solely from arguments, without any side effects.

        ``cwd`` is accepted for the paired legacy-discovery API only.  It has
        no bearing on the canonical data root.
        """

        try:
            base_text = fspath(base_dir)
        except TypeError as exc:
            raise RuntimePathError("base_dir must be a path") from exc
        if not isinstance(base_text, str):
            raise RuntimePathError("base_dir must be a path")
        _validate_path_text(base_text, label="base_dir")
        base_path = Path(base_text)
        if not base_path.is_absolute():
            raise RuntimePathError("base_dir must be absolute")
        normalized_base = base_path.resolve(strict=False)
        if not normalized_base.is_absolute():
            raise RuntimePathError("base_dir did not resolve to an absolute path")
        normalized_cwd = _canonical_path(
            normalized_base if cwd is None else cwd,
            normalized_base,
            label="cwd",
            reject_filesystem_root=False,
        )
        selected = (
            _non_empty(env, "AURA_DATA_DIR")
            or _non_empty(env, "AURA_OUTPUT_DIR")
            or "outputs"
        )
        data_dir = _canonical_path(selected, normalized_base, label="data_dir")
        state_dir = data_dir / "state"
        return cls(
            data_dir=data_dir,
            manifest_path=data_dir / "manifest.json",
            control_db_path=data_dir / "ledger" / "aura-control.sqlite3",
            writer_lease_path=data_dir / "ledger" / "writer.lock",
            state_dir=state_dir,
            state_generations_dir=state_dir / "generations",
            state_current_path=state_dir / "CURRENT",
            memory_chroma_dir=data_dir / "memory" / "chroma",
            chat_spool_dir=data_dir / "transport" / "chat-spool",
            event_journal_dir=data_dir / "audit" / "event-journal",
            recovery_dir=data_dir / "recovery",
            logs_dir=data_dir / "runtime" / "logs",
            cache_dir=data_dir / "runtime" / "cache",
            temp_dir=data_dir / "runtime" / "tmp",
            _base_dir=normalized_base,
            _legacy_cwd=normalized_cwd,
        )


@dataclass(frozen=True)
class LegacyArtifactManifest:
    """Immutable candidates plus bounded metadata-only population results."""

    candidates: Mapping[LegacyArtifactKind, tuple[Path, ...]]
    populated: Mapping[LegacyArtifactKind, tuple[Path, ...]]
    conflicts: Mapping[LegacyArtifactKind, tuple[Path, ...]]

    def candidates_for(self, kind: LegacyArtifactKind | str) -> tuple[Path, ...]:
        return self.candidates[LegacyArtifactKind(kind)]

    def populated_for(self, kind: LegacyArtifactKind | str) -> tuple[Path, ...]:
        return self.populated[LegacyArtifactKind(kind)]

    @property
    def artifacts(self) -> Mapping[LegacyArtifactKind, tuple[Path, ...]]:
        """Compatibility-friendly name for candidates grouped by artifact."""
        return self.candidates

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)

    @property
    def conflict_kinds(self) -> tuple[LegacyArtifactKind, ...]:
        return tuple(self.conflicts)


_LEGACY_OVERRIDES: dict[LegacyArtifactKind, tuple[str, ...]] = {
    LegacyArtifactKind.EGO: ("AURA_EGO_PATH",),
    LegacyArtifactKind.IDENTITY: ("AURA_IDENTITY_PATH",),
    LegacyArtifactKind.WORLD: ("AURA_WORLD_PATH",),
    LegacyArtifactKind.VALUES: ("AURA_VALUES_PATH",),
    LegacyArtifactKind.MEMORY: ("AURA_MEMORY_DIR", "AURA_CHROMA_DIR", "CHROMA_DB_PATH"),
    LegacyArtifactKind.JOURNAL: ("AURA_EVENT_JOURNAL_DIR",),
    LegacyArtifactKind.LEDGER: ("AURA_OPERATION_LEDGER_FILE", "AURA_LEDGER_FILE"),
    LegacyArtifactKind.TRANSPORTS: ("AURA_CHAT_SPOOL_DIR",),
}

_FILE_ARTIFACT_KINDS = frozenset(
    {
        LegacyArtifactKind.EGO,
        LegacyArtifactKind.IDENTITY,
        LegacyArtifactKind.WORLD,
        LegacyArtifactKind.VALUES,
        LegacyArtifactKind.LEDGER,
    }
)


def _is_populated_legacy_candidate(kind: LegacyArtifactKind, path: Path) -> bool:
    """Classify one candidate with bounded, content-free metadata access."""

    try:
        metadata = path.stat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RuntimePathError(
            f"cannot inspect legacy {kind.value} artifact at {path}"
        ) from exc

    if kind in _FILE_ARTIFACT_KINDS:
        if not stat.S_ISREG(metadata.st_mode):
            raise RuntimePathError(
                f"legacy {kind.value} artifact must be a regular file: {path}"
            )
        return True

    if not stat.S_ISDIR(metadata.st_mode):
        raise RuntimePathError(
            f"legacy {kind.value} artifact must be a directory: {path}"
        )
    try:
        with os.scandir(path) as entries:
            return next(entries, None) is not None
    except OSError as exc:
        raise RuntimePathError(
            f"cannot inspect legacy {kind.value} artifact at {path}"
        ) from exc


def discover_legacy_artifacts(
    paths: RuntimePaths, env: Mapping[str, str]
) -> LegacyArtifactManifest:
    """Discover legacy locations with bounded, non-recursive metadata reads.

    Canonical paths are intentionally absent: this manifest describes only
    migration inputs.  It never reads artifact contents or writes, migrates,
    deletes, or renames data. Each tuple is canonicalized and insertion
    ordered, so equal spellings collapse to one candidate.
    """

    base_dir = paths._base_dir
    output_roots = [base_dir / "outputs"]
    configured_output = _non_empty(env, "AURA_OUTPUT_DIR")
    if configured_output is not None:
        output_roots.append(
            _unresolved_absolute_path(
                configured_output, base_dir, label="AURA_OUTPUT_DIR"
            )
        )

    historical: dict[LegacyArtifactKind, list[Path]] = {
        LegacyArtifactKind.EGO: [root / "ego_state.json" for root in output_roots],
        LegacyArtifactKind.IDENTITY: [paths._legacy_cwd / "identity.json", base_dir / "identity.json"],
        LegacyArtifactKind.WORLD: [root / "world_graph.json" for root in output_roots],
        LegacyArtifactKind.VALUES: [root / "values.json" for root in output_roots],
        LegacyArtifactKind.MEMORY: [root / "chroma_db" for root in output_roots],
        LegacyArtifactKind.JOURNAL: [root / "event_journal" for root in output_roots],
        LegacyArtifactKind.LEDGER: [root / "operation_ledger.sqlite3" for root in output_roots],
        LegacyArtifactKind.TRANSPORTS: [root / "chat_spool" for root in output_roots],
    }
    candidates: dict[LegacyArtifactKind, tuple[Path, ...]] = {}
    populated_by_kind: dict[LegacyArtifactKind, tuple[Path, ...]] = {}
    conflicts: dict[LegacyArtifactKind, tuple[Path, ...]] = {}
    for kind in LegacyArtifactKind:
        values = historical[kind]
        for name in _LEGACY_OVERRIDES[kind]:
            value = _non_empty(env, name)
            if value is not None:
                values.append(_unresolved_absolute_path(value, base_dir, label=name))
        unique: list[Path] = []
        seen: set[Path] = set()
        for value in values:
            canonical = _canonical_legacy_candidate(value, base_dir, label=kind.value)
            if canonical not in seen:
                seen.add(canonical)
                unique.append(canonical)
        candidates[kind] = tuple(unique)
        populated = tuple(
            candidate
            for candidate in unique
            if _is_populated_legacy_candidate(kind, candidate)
        )
        populated_by_kind[kind] = populated
        if len(populated) >= 2:
            conflicts[kind] = populated
    return LegacyArtifactManifest(
        candidates=MappingProxyType(candidates),
        populated=MappingProxyType(populated_by_kind),
        conflicts=MappingProxyType(conflicts),
    )
