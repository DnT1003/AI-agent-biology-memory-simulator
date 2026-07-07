import os
import sys
import importlib.util
from config import Config

try:
    import torch  # type: ignore
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

# Make NanoGPT SLM directory importable (model.py, tokenizer.py, config.py live there)
if Config.SLM_DIR not in sys.path:
    sys.path.append(Config.SLM_DIR)


def _load_nanogpt_config():
    cfg_path = os.path.join(Config.SLM_DIR, "config.py")
    spec = importlib.util.spec_from_file_location("aura_nanogpt_config", cfg_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load SLM config at {cfg_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


try:
    if TORCH_AVAILABLE:
        from model import AuraFlashModel, block_size  # type: ignore
        from tokenizer import BPETokenizer  # type: ignore
    else:
        AuraFlashModel = None
        BPETokenizer = None
        block_size = 0
except Exception:
    AuraFlashModel = None
    BPETokenizer = None
    block_size = 0


class SLMCore:
    """Native SLM inference wrapper for the local NanoGPT core."""

    def __init__(self):
        self.device = "cuda" if TORCH_AVAILABLE and torch.cuda.is_available() else "cpu"
        custom_path = os.path.join(Config.SLM_DIR, "aura_moe_700m.pth")
        default_path = os.path.join(Config.SLM_DIR, "aura_flash_v5.pth")
        self.model_path = custom_path if os.path.exists(custom_path) else default_path
        self.model = None
        self.is_ready = False
        self.use_gpu_service = True
        self.tokenizer = None

        if Config.SLM_ENABLED and AuraFlashModel and TORCH_AVAILABLE:
            self._init_tokenizer()
            self.load_model()

    def _init_tokenizer(self):
        if BPETokenizer is None:
            return
        try:
            vocab_path = os.path.join(Config.SLM_DIR, "vocab.json")
            tok = BPETokenizer()
            if os.path.exists(vocab_path):
                tok.load(vocab_path)
            self.tokenizer = tok
        except Exception as e:
            from core.logger import get_logger

            get_logger("slm_core").error(f"[SLM Tokenizer Init Error]: {e}")

    def load_model(self):
        if AuraFlashModel is None:
            return
        import logging

        try:
            if not self.tokenizer:
                self._init_tokenizer()

            if self.tokenizer and getattr(self.tokenizer, "vocab_size", None):
                model_vocab_size = int(self.tokenizer.vocab_size)
            else:
                model_vocab_size = int(_load_nanogpt_config().vocab_size)

            self.model = AuraFlashModel(model_vocab_size)

            if os.path.exists(self.model_path):
                try:
                    state = torch.load(self.model_path, map_location=self.device, weights_only=True)
                except TypeError:
                    state = torch.load(self.model_path, map_location=self.device)

                try:
                    state = {k.replace(".moe.", ".mlp."): v for k, v in state.items()}
                    self.model.load_state_dict(state, strict=False)
                except Exception as ex:
                    logging.warning(f"Could not load state dict cleanly: {ex}")

            dtype = torch.bfloat16 if self.device == "cuda" else torch.float32
            self.model.to(device=self.device, dtype=dtype)
            self.model.eval()
            self.is_ready = True
        except Exception as e:
            logging.error(f"[SLM Model Load Error]: {e}", exc_info=True)
            self.is_ready = False

    def generate_thought(self, prompt_text: str, max_tokens: int = 50):
        """Generate a short local thought sequence."""

        if self.use_gpu_service:
            import requests

            try:
                # Thay vì local loopback, sử dụng service URL từ Config (hỗ trợ K8s)
                resp = requests.post(
                    f"{Config.GPU_SERVICE_URL}/generate",
                    json={"prompt": prompt_text, "max_new_tokens": max_tokens},
                    timeout=20,
                )
                if resp.status_code == 200:
                    return resp.json().get("thought", "...")
            except Exception as e:
                import logging

                logging.error(f"[SLM GPU API Error]: {e}", exc_info=True)
            return "..."

        if not self.is_ready or not self.model or not self.tokenizer:
            return "..."

        try:
            encoded = self.tokenizer.encode(prompt_text)
            if not encoded:
                return "..."

            context = torch.tensor(encoded, dtype=torch.long, device=self.device).unsqueeze(0)
            context = context[:, -block_size:]

            device_type = "cuda" if self.device == "cuda" else "cpu"
            autocast_enabled = device_type == "cuda"

            with torch.no_grad(), torch.amp.autocast(
                device_type, dtype=torch.bfloat16, enabled=autocast_enabled
            ):
                out = self.model.generate(context, max_new_tokens=max_tokens)

            if self.device == "cuda":
                torch.cuda.empty_cache()

            return self.tokenizer.decode(out[0].tolist())
        except Exception as e:
            import logging

            logging.error(f"[SLM Native Inference Error]: {e}", exc_info=True)
            if self.device == "cuda":
                torch.cuda.empty_cache()
            return f"[SLM Error]: {e}"

    def log_experience_for_finetuning(self, text_data: str):
        """Append data to a finetune queue for offline training."""

        try:
            log_path = os.path.join(Config.BASE_DIR, "outputs", "slm_finetune_data.txt")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(text_data.strip() + "\n\n")
            print("[SLM]: Logged finetune experience.")
        except Exception as e:
            import logging

            logging.error(f"[SLM Finetune Logging Error]: {e}", exc_info=True)
