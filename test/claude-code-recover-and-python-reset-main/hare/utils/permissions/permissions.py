"""
Permission engine — orchestration for tool permission checks.

The TypeScript `permissions.ts` is very large; Python splits logic across
`hare.utils.permissions.*` and `hare.types.permissions`. This module holds
additional stubs and re-exports for parity with the TS barrel name.

Port of: src/utils/permissions/permissions.ts (deferred — extend incrementally).
"""

from __future__ import annotations

__all__: list[str] = []
