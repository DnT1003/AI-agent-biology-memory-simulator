import os
import sys
import json
from config import Config

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

# Thêm folder 1 vào path để import được GPTLanguageModel nếu cần
sys.path.append(Config.SLM_DIR)

try:
    if TORCH_AVAILABLE:
        from model import AuraFlashModel, vocab_size, block_size
        # Tokenizer độc lập, không tái sử dụng encode thủ công từ model.py
        from tokenizer import BPETokenizer
    else:
        AuraFlashModel = None
except ImportError:
    AuraFlashModel = None

class SLMCore:
    """
    Hạt nhân trí tuệ bản địa (Native Intelligence) dựa trên NanoGPT.
    Aura sử dụng lớp này để thực hiện "suy nghĩ nội tâm" không thông qua mảng thần kinh lớn.
    """
    def __init__(self):
        self.device = 'cuda' if TORCH_AVAILABLE and torch.cuda.is_available() else 'cpu'
        self.model_path = os.path.join(Config.SLM_DIR, "aura_slm.pt")
        self.model = None
        self.is_ready = False
        self.use_gpu_service = not TORCH_AVAILABLE
        self.tokenizer = None
        
        if Config.SLM_ENABLED and AuraFlashModel and TORCH_AVAILABLE:
            self._init_tokenizer()
            self.load_model()

    def _init_tokenizer(self):
        """Khởi tạo Tokenizer độc lập để không dính tới model.py"""
        try:
            vocab_path = os.path.join(Config.SLM_DIR, 'vocab.json')
            self.tokenizer = BPETokenizer()
            if os.path.exists(vocab_path):
                self.tokenizer.load(vocab_path)
            else:
                # Nếu không có vocab BPE, tạm thời khởi tạo bảng Token byte trống.
                # Khi train_slm chạy, nó sẽ ghi đè file vocab.json chuẩn.
                pass
        except Exception as e:
            from core.logger import get_logger
            get_logger("slm_core").error(f"[SLM Tokenizer Init Error]: {e}")

    def load_model(self):
        import logging
        try:
            from model import AuraFlashModel, vocab_size
            self.model = AuraFlashModel(vocab_size)
            self.model_path = os.path.join(Config.SLM_DIR, "aura_flash_v5.pth")
            if os.path.exists(self.model_path):
                # Fix lỗi 1: Ép map_location và chuyển ngay sang bfloat16 để cứu 50% VRAM
                self.model.load_state_dict(torch.load(self.model_path, map_location=self.device, weights_only=True))
                # Ép kiểu bfloat16 tương thích phần cứng RTX 3060
                self.model.to(device=self.device, dtype=torch.bfloat16)
                print(f"[SLM]: Đã nạp trọng số mô hình Aura bản địa ({self.model_path}) với bfloat16")
            else:
                print(f"[SLM]: Chưa tìm thấy trọng số {self.model_path}. Aura sẽ bắt đầu với trạng thái nguyên thủy.")
                self.model.to(self.device, dtype=torch.bfloat16)
            
            self.model.eval()
            self.is_ready = True
        except Exception as e:
            logging.error(f"[SLM Model Load Error]: Lỗi khi khởi tạo mô hình nội tại: {e}", exc_info=True)

    def generate_thought(self, prompt_text: str, max_tokens: int = 50):
        """Sinh ra một 'luồng suy nghĩ' bản địa ngắn."""
        if self.use_gpu_service:
            import requests
            try:
                resp = requests.post("http://127.0.0.1:8001/generate", json={"prompt": prompt_text, "max_new_tokens": max_tokens}, stream=True, timeout=10)
                if resp.status_code == 200:
                    lines = []
                    for chunk in resp.iter_lines():
                        if chunk:
                            lines.append(chunk.decode('utf-8'))
                    return "".join(lines)
            except Exception as e:
                import logging
                logging.error(f"[SLM GPU API Error]: {e}", exc_info=True)
            return "..."

        if not self.is_ready or not self.model or not getattr(self, 'tokenizer', None):
            return "..."
            
        try:
            import logging
            # Encode bằng Tokenizer độc lập
            encoded_text = self.tokenizer.encode(prompt_text)
            context = torch.tensor(encoded_text, dtype=torch.long, device=self.device).unsqueeze(0)
            
            # Khắc phục lỗi 3: Cắt gọt Context Window để không bị văng Index Out Of Bounds
            context = context[:, -block_size:] 

            # Khi generate cũng phải xài bfloat16 context
            with torch.no_grad(), torch.amp.autocast('cuda', dtype=torch.bfloat16):
                generated_ids = self.model.generate(context, max_new_tokens=max_tokens)
                
            # Pocket AI Survival Mode: Explicit Garbage Collection
            if str(self.device) == 'cuda':
                torch.cuda.empty_cache()
                
            return self.tokenizer.decode(generated_ids[0].tolist())
        except Exception as e:
            import logging
            logging.error(f"[SLM Native Inference Error]: {e}", exc_info=True)
            if str(self.device) == 'cuda':
                torch.cuda.empty_cache()
            return f"[SLM Error]: {e}"

    def log_experience_for_finetuning(self, text_data: str):
        """
        Khắc phục lỗi 4: Thay thế Online Learning rủi ro cao bằng Local Finetune theo mảng.
        Ghi lại lịch sử đoạn thoại để sau này dùng train_slm.py huấn luyện một lần trọn vẹn.
        """
        try:
            log_path = os.path.join(Config.BASE_DIR, "outputs", "slm_finetune_data.txt")
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(text_data.strip() + "\n\n")
            print(f"[SLM]: Đã ghi nhớ kinh nghiệm để dành Finetune ngoại tuyến.")
        except Exception as e:
            import logging
            logging.error(f"[SLM Finetune Logging Error]: {e}", exc_info=True)
