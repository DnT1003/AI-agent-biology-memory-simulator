"""
core/logger.py — Structured Logging Layer (Phase 10, Module 3)

Thay thế toàn bộ:
  except Exception: pass          ← Che bug, che corruption
  print(f"⚠️ ...")               ← Không có timestamp, không có level

Dùng:
  from core.logger import get_logger
  logger = get_logger(__name__)
  logger.warning("mô tả lỗi")
  logger.error("lỗi nghiêm trọng", exc_info=True)
"""

import logging
import os
from logging.handlers import RotatingFileHandler

# Thư mục log
_LOG_DIR = "outputs/logs"
_LOG_FILE = os.path.join(_LOG_DIR, "aura.log")

def _setup_logger() -> logging.Logger:
    os.makedirs(_LOG_DIR, exist_ok=True)

    root = logging.getLogger("aura")
    if root.handlers:
        return root  # Đã được init rồi

    root.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # File handler — rotating, tối đa 5MB × 3 files
    fh = RotatingFileHandler(
        _LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler — chỉ WARNING trở lên để không spam
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    return root


_setup_logger()


def get_logger(name: str) -> logging.Logger:
    """Trả về child logger theo module name, kế thừa từ 'aura' root logger."""
    return logging.getLogger(f"aura.{name}")
