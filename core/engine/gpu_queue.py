"""
GPU Serialization Queue – ngăn CUDA context collision giữa
SLM inference thread và SLM training thread.

Mọi tác vụ cần GPU phải submit qua GPUQueue.submit() thay vì
gọi trực tiếp hàm inference/training.

Dùng threading.Lock để đảm bảo chỉ 1 tác vụ GPU chạy tại 1 thời điểm.
"""
import threading
import queue
import time
import logging
from typing import Callable, Any

logger = logging.getLogger("gpu_queue")


class GPUQueue:
    """Singleton serialization queue cho mọi tác vụ GPU (inference + training)."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._gpu_lock = threading.Lock()
        self._task_queue: queue.Queue = queue.Queue()
        self._worker = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="gpu-queue-worker"
        )
        self._worker.start()
        logger.info("[GPU Queue] Worker started – GPU access serialized.")

    # ──────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────

    def submit(self, fn: Callable, *args, timeout: float = 120.0, **kwargs) -> Any:
        """
        Submit một task GPU và BLOCK cho đến khi có kết quả.
        Đảm bảo không bao giờ có 2 CUDA op cùng chạy.

        Args:
            fn: hàm cần gọi (inference hoặc training step)
            *args, **kwargs: tham số truyền vào fn
            timeout: thời gian tối đa chờ (giây)

        Returns:
            Kết quả của fn(*args, **kwargs)

        Raises:
            TimeoutError: nếu chờ quá timeout
            Exception: exception từ fn được re-raise
        """
        result_event = threading.Event()
        result_container: dict = {}

        def task():
            try:
                result_container["value"] = fn(*args, **kwargs)
            except Exception as e:
                result_container["error"] = e
            finally:
                result_event.set()

        self._task_queue.put(task)

        if not result_event.wait(timeout=timeout):
            raise TimeoutError(
                f"[GPU Queue] Task {fn.__name__} timed out after {timeout}s. "
                "Có thể training đang chiếm GPU quá lâu."
            )

        if "error" in result_container:
            raise result_container["error"]
        return result_container["value"]

    def submit_async(self, fn: Callable, *args, **kwargs) -> None:
        """
        Submit task GPU không blocking (fire-and-forget).
        Dùng cho training background — không cần kết quả ngay.
        """
        def task():
            try:
                fn(*args, **kwargs)
            except Exception as e:
                logger.error(f"[GPU Queue] Async task {fn.__name__} failed: {e}")

        self._task_queue.put(task)

    # ──────────────────────────────────────────────────────────────
    # INTERNAL
    # ──────────────────────────────────────────────────────────────

    def _worker_loop(self):
        """Worker thread: chạy từng task GPU tuần tự, có GPU lock."""
        while True:
            try:
                task = self._task_queue.get(timeout=1.0)
                with self._gpu_lock:   # ← chỉ 1 task/lúc, tránh CUDA collision
                    task()
                self._task_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"[GPU Queue] Worker loop error: {e}")


# Global singleton
gpu_queue = GPUQueue()
