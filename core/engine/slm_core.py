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
        from model import AuraFlashModel as GPTLanguageModel, encode, decode, vocab_size, n_embd, n_head, n_layer, block_size, device
    else:
        GPTLanguageModel = None
except ImportError:
    # Nếu không import được trực tiếp, ta sẽ phải định nghĩa lại hoặc xử lý linh hoạt
    GPTLanguageModel = None

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
        
        if Config.SLM_ENABLED and GPTLanguageModel and TORCH_AVAILABLE:
            self.load_model()

    def load_model(self):
        try:
            from model import AuraFlashModel, vocab_size
            self.model = AuraFlashModel(vocab_size)
            self.model_path = os.path.join(Config.SLM_DIR, "aura_flash_v5.pth")
            if os.path.exists(self.model_path):
                self.model.load_state_dict(torch.load(self.model_path, map_location=self.device))
                print(f"[SLM]: Đã nạp trọng số mô hình Aura bản địa từ {self.model_path}")
            else:
                print(f"[SLM]: Chưa tìm thấy trọng số {self.model_path}. Aura sẽ bắt đầu với trạng thái nguyên thủy.")
            
            self.model.to(self.device)
            self.model.eval()
            self.is_ready = True
        except Exception as e:
            print(f"[SLM]: Lỗi khi khởi tạo mô hình nội tại: {e}")

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
                pass
            return "..."

        if not self.is_ready or not self.model:
            return "..."
            
        try:
            # Tokenize đơn giản theo ký tự (như model.py trong folder nanogpt)
            from model import encode, decode
            context = torch.tensor(encode(prompt_text), dtype=torch.long, device=self.device).unsqueeze(0)
            with torch.no_grad():
                generated_ids = self.model.generate(context, max_new_tokens=max_tokens)
                return decode(generated_ids[0].tolist())
        except Exception as e:
            return f"[SLM Error]: {e}"

    def train_on_batch(self, text_data: str):
        """
        Huấn luyện mô hình ngay lập tức trên dữ liệu mới.
        Dùng cho việc Aura tự học từ hội thoại vừa diễn ra.
        """
        if not self.is_ready or not self.model:
            return
            
        # Logic huấn luyện nhanh (Online Learning) sẽ được triển khai ở Bước 3
        pass
