from hare.utils.model.model_full import (
    get_main_loop_model, get_default_opus_model,
    get_default_sonnet_model, get_default_haiku_model,
    get_small_fast_model, get_runtime_main_loop_model,
    get_user_specified_model_setting, get_best_model,
)

try:
    from hare.utils.model_strings import normalize_model_string_for_api
except ImportError:
    def normalize_model_string_for_api(model: str) -> str:
        model = model.strip()
        if model.endswith("[1m]"):
            model = model[:-4]
        return model


def get_canonical_name(model: str) -> str:
    """Get canonical model name."""
    return normalize_model_string_for_api(model).lower()


def get_public_model_display_name(model: str) -> str:
    """Get human-friendly display name for a model."""
    canonical = get_canonical_name(model)
    display_map = {
        "claude-sonnet-4-20250514": "Claude Sonnet 4",
        "claude-opus-4-20250514": "Claude Opus 4",
        "claude-3-5-sonnet-20241022": "Claude 3.5 Sonnet",
        "claude-3-5-haiku-20241022": "Claude 3.5 Haiku",
    }
    return display_map.get(canonical, model)
