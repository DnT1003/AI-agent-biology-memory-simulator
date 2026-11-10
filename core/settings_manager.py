import os
import json
import threading

from config import Config


PUBLIC_SETTING_KEYS = frozenset({
    "provider",
    "local_model",
    "gemini_model",
    "openai_model",
    "openai_base_url",
    "anthropic_model",
    "system_prompt",
})
SECRET_SETTING_KEYS = frozenset({
    "gemini_api_key",
    "openai_api_key",
    "anthropic_api_key",
})
ALLOWED_PROVIDERS = frozenset({"local", "gemini", "openai", "anthropic"})

class SettingsManager:
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SettingsManager, cls).__new__(cls)
            return cls._instance
            
    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.settings_file = os.path.join(Config.OUTPUT_DIR, "settings.json")
            self.lock = threading.Lock()
            self._settings_file_signature = None
            self._loaded = False
            
            # Default settings
            self.settings = {
                "provider": "local", # local, gemini, openai, anthropic
                "local_model": getattr(Config, "LOCAL_MODEL_NAME", "phi3:mini"),
                "gemini_model": getattr(Config, "MODEL_NAME", "gemini-3.0-flash"),
                "openai_model": getattr(Config, "OPENAI_MODEL", "gpt-4o-mini"),
                "openai_base_url": getattr(Config, "OPENAI_BASE_URL", "https://api.openai.com/v1"),
                "anthropic_model": "claude-3-haiku-20240307",
                "gemini_api_key": getattr(Config, "API_KEY", ""),
                "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
                "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY", ""),
                "system_prompt": "You are Aura, an AI assistant."
            }
            self.initialized = True

    def _file_signature_unsafe(self):
        """Return a cheap cross-process change detector for settings.json."""
        try:
            stat = os.stat(self.settings_file)
            return (stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            return None

    def _load_unsafe(self):
        """Load settings while ``self.lock`` is held by the caller."""
        if not os.path.exists(self.settings_file):
            self._settings_file_signature = None
            return

        disk_signature = self._file_signature_unsafe()
        unsafe_keys = set()
        try:
            with open(self.settings_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("Settings file must contain a JSON object")

            # Secrets always remain sourced from environment/in-memory state. Any
            # legacy secret or unsupported field is removed from disk immediately.
            unsafe_keys = set(data) - PUBLIC_SETTING_KEYS
            public_data = {
                key: value for key, value in data.items() if key in PUBLIC_SETTING_KEYS
            }
            self.settings.update(self._validate_public_updates(public_data))

            if unsafe_keys:
                self._save_unsafe()
            else:
                self._settings_file_signature = disk_signature
        except Exception as e:
            # Even if a public value is invalid, do not leave recognized legacy
            # secrets or unknown fields persisted. Fall back to current validated
            # public settings while preserving all in-memory secret values.
            if unsafe_keys:
                try:
                    self._save_unsafe()
                except Exception as scrub_error:
                    print(f"Failed to scrub settings: {scrub_error}")
            else:
                # Avoid reparsing the same invalid snapshot on every get(). A later
                # external replacement changes the signature and will be retried.
                self._settings_file_signature = disk_signature
            print(f"Failed to load settings: {e}")

    def _reload_if_changed_unsafe(self):
        """Reload an externally replaced settings file while the lock is held."""
        current_signature = self._file_signature_unsafe()
        if current_signature != getattr(self, "_settings_file_signature", None):
            self._load_unsafe()

    def _ensure_loaded_unsafe(self):
        """Perform the compatibility load only after a public operation."""
        if not getattr(self, "_loaded", False):
            self._load_unsafe()
            self._loaded = True

    def load(self):
        with self.lock:
            self._load_unsafe()
            self._loaded = True

    def _public_settings_unsafe(self):
        return {key: self.settings[key] for key in PUBLIC_SETTING_KEYS if key in self.settings}

    def _save_unsafe(self):
        from core.utils import atomic_write_json

        atomic_write_json(self.settings_file, self._public_settings_unsafe())
        self._settings_file_signature = self._file_signature_unsafe()

    @staticmethod
    def _validate_public_updates(new_settings):
        if not isinstance(new_settings, dict):
            raise ValueError("Settings payload must be a JSON object")

        unknown_keys = set(new_settings) - PUBLIC_SETTING_KEYS
        if unknown_keys:
            raise ValueError(f"Unsupported settings: {', '.join(sorted(unknown_keys))}")

        validated = {}
        for key, value in new_settings.items():
            if not isinstance(value, str):
                raise ValueError(f"Setting '{key}' must be a string")
            max_length = 10_000 if key == "system_prompt" else 256
            if len(value) > max_length:
                raise ValueError(f"Setting '{key}' is too long")
            validated[key] = value

        provider = validated.get("provider")
        if provider is not None and provider not in ALLOWED_PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}")
        return validated

    def save(self):
        with self.lock:
            try:
                self._ensure_loaded_unsafe()
                self._save_unsafe()
            except Exception as e:
                print(f"Failed to save settings: {e}")

    def get(self, key, default=None):
        with self.lock:
            self._ensure_loaded_unsafe()
            self._reload_if_changed_unsafe()
            return self.settings.get(key, default)

    def update(self, key, value):
        updates = self._validate_public_updates({key: value})
        with self.lock:
            self._ensure_loaded_unsafe()
            self._reload_if_changed_unsafe()
            self.settings.update(updates)
            self._save_unsafe()

    def get_all(self):
        with self.lock:
            self._ensure_loaded_unsafe()
            self._reload_if_changed_unsafe()
            return self._public_settings_unsafe()

    def update_all(self, new_settings):
        updates = self._validate_public_updates(new_settings)
        with self.lock:
            self._ensure_loaded_unsafe()
            self._reload_if_changed_unsafe()
            self.settings.update(updates)
            self._save_unsafe()

# Global instance
settings_manager = SettingsManager()
