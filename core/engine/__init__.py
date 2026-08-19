"""Engine package with lazy public exports.

Importing a lightweight submodule such as ``core.engine.slm_core`` must not
initialize the entire cognitive engine (reader, vector DB and trainer).
"""

from typing import TYPE_CHECKING

__all__ = ["CognitiveEngine", "SLMCore", "SLMTrainer"]

if TYPE_CHECKING:
    from .cognitive_engine import CognitiveEngine
    from .slm_core import SLMCore
    from .slm_trainer import SLMTrainer


def __getattr__(name):
    if name == "CognitiveEngine":
        from .cognitive_engine import CognitiveEngine
        globals()[name] = CognitiveEngine
        return CognitiveEngine
    if name == "SLMCore":
        from .slm_core import SLMCore
        globals()[name] = SLMCore
        return SLMCore
    if name == "SLMTrainer":
        from .slm_trainer import SLMTrainer
        globals()[name] = SLMTrainer
        return SLMTrainer
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
