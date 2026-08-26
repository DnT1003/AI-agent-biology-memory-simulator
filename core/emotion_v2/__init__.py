"""Small public surface for the pure, deterministic Emotion V2 kernel."""

from .engine import canonical_reduction_hash, reduce_emotion_v2
from .parameters import EmotionParametersV2
from .types import (
    APPRAISAL_ORDER, COMPONENT_ORDER, DRIVE_ORDER, MEMORY_SUMMARY_ORDER, TRAIT_ORDER,
    AppraisalInputV2, EmotionStateV2, EmotionTransitionV2, EmotionValidationError,
)

__all__ = [
    "APPRAISAL_ORDER", "COMPONENT_ORDER", "DRIVE_ORDER", "MEMORY_SUMMARY_ORDER", "TRAIT_ORDER",
    "AppraisalInputV2", "EmotionParametersV2", "EmotionStateV2", "EmotionTransitionV2",
    "EmotionValidationError", "canonical_reduction_hash", "reduce_emotion_v2",
]
