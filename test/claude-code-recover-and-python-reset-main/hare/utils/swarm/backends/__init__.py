"""
Swarm backend registry and executors.

Port of: src/utils/swarm/backends/
"""

from hare.utils.swarm.backends.registry import (
    detect_and_get_backend,
    get_backend_by_type,
    is_in_process_enabled,
    get_resolved_teammate_mode,
    get_teammate_executor,
    get_in_process_backend,
    reset_backend_detection,
    mark_in_process_fallback,
)
from hare.utils.swarm.backends.types import (
    PaneBackendType,
    BackendDetectionResult,
)
