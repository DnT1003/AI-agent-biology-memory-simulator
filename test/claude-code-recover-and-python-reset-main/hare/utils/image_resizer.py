"""Port of: src/utils/imageResizer.ts (stub)"""
from __future__ import annotations
from typing import Any

def maybe_resize_image(image_data: bytes, max_size: int = 1_000_000) -> bytes:
    if len(image_data) <= max_size: return image_data
    return image_data  # stub

def create_image_metadata_text(path: str) -> str:
    import os
    if not os.path.exists(path): return ""
    size = os.path.getsize(path)
    return f"Image: {os.path.basename(path)} ({size:,} bytes)"
