import os
import sys
import json
import threading

# Add parent path to sys path to import Config
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import Config

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
            
            # Default settings
            self.settings = {
                "provider": "local", # local, gemini, openai, anthropic
                "local_model": getattr(Config, "LOCAL_MODEL_NAME", "phi3:mini"),
                "gemini_model": getattr(Config, "MODEL_NAME", "gemini-3.0-flash"),
                "openai_model": "gpt-4o-mini",
                "anthropic_model": "claude-3-haiku-20240307",
                "gemini_api_key": getattr(Config, "API_KEY", ""),
                "openai_api_key": "",
                "anthropic_api_key": "",
                "system_prompt": "You are Aura, an AI assistant."
            }
            self.initialized = True
            self.load()
        
    def load(self):
        with self.lock:
            if os.path.exists(self.settings_file):
                try:
                    with open(self.settings_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        self.settings.update(data)
                except Exception as e:
                    print(f"Failed to load settings: {e}")
                    
    def save(self):
        with self.lock:
            try:
                os.makedirs(os.path.dirname(self.settings_file), exist_ok=True)
                with open(self.settings_file, "w", encoding="utf-8") as f:
                    json.dump(self.settings, f, indent=4, ensure_ascii=False)
            except Exception as e:
                print(f"Failed to save settings: {e}")
                
    def get(self, key, default=None):
        return self.settings.get(key, default)
        
    def update(self, key, value):
        self.settings[key] = value
        self.save()
        
    def get_all(self):
        return self.settings.copy()
        
    def update_all(self, new_settings):
        self.settings.update(new_settings)
        self.save()

# Global instance
settings_manager = SettingsManager()
