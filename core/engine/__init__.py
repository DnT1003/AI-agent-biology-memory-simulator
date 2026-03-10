from .cognitive_engine import CognitiveEngine
from .slm_core import SLMCore

try:
    from .slm_trainer import SLMTrainer
except ImportError:
    pass
