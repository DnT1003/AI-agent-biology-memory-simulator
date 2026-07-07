"""Select relevant memories via side query (port of src/memdir/findRelevantMemories.ts)."""

from __future__ import annotations

from dataclasses import dataclass

from hare.memdir.memory_scan import MemoryHeader, format_memory_manifest, scan_memory_files


@dataclass
class RelevantMemory:
    path: str
    mtime_ms: float


async def find_relevant_memories(
    query: str,
    memory_dir: str,
    signal: object | None = None,
    recent_tools: tuple[str, ...] = (),
    already_surfaced: frozenset[str] | set[str] = frozenset(),
) -> list[RelevantMemory]:
    memories = [
        m
        for m in await scan_memory_files(memory_dir)
        if m.file_path not in already_surfaced
    ]
    if not memories:
        return []
    # Stub: wire to side_query + Sonnet when integrating
    _ = (query, signal, recent_tools, format_memory_manifest(memories))
    return [RelevantMemory(path=m.file_path, mtime_ms=m.mtime_ms) for m in memories[:5]]
