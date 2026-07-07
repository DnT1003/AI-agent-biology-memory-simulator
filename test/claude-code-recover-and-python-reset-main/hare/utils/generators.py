"""Port of: src/utils/generators.ts"""
from __future__ import annotations
from typing import Any, AsyncIterator, TypeVar
T = TypeVar("T")

async def to_array(gen: AsyncIterator[T]) -> list[T]:
    result = []
    async for item in gen:
        result.append(item)
    return result
