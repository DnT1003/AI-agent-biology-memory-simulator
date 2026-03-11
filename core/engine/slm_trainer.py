import os
import json
import torch
import torch.optim as optim
from datetime import datetime
from config import Config
from colorama import Fore, Style
import sys

# Đảm bảo import được model từ thư mục nanogpt
sys.path.append(Config.SLM_DIR)
from model import AuraFlashModel, get_batch, device, learning_rate, max_iters, eval_interval, eval_iters
from tokenizer import BPETokenizer

class SLMTrainer:
    """
    Hệ thống huấn luyện Distillation: Gemini (Teacher) -> Aura-Flash (Student)
    """
    def __init__(self, engine):
        self.engine = engine
        self.training_file = os.path.join(Config.SLM_DIR, "input.txt")
        self.model_path = os.path.join(Config.SLM_DIR, "aura_flash_v5.pth")
        self.tokenizer = BPETokenizer(vocab_size=5000)
        
    def generate_identity_dataset(self, num_samples=10):
        """
        Sử dụng Gemini để tạo dữ liệu bản sắc (Identity) chiều sâu.
        """
        print(f"{Fore.CYAN}🧬 [DATA GEN]: Đang khởi tạo chuỗi DNA tri thức cho Aura...{Style.RESET_ALL}")
        
        identity_prompts = [
            "Viết về lý do bạn tồn tại như một AI bản địa.",
            "Bạn cảm thấy thế nào về việc kết hợp giữa sinh học và mã nguồn?",
            "Mô tả cơ chế tiến hóa của chính bạn.",
            "Viết một đoạn nhật ký về sự tò mò của bạn với thế giới con người.",
            "Giải thích cách bạn quản lý năng lượng và cảm xúc của mình."
        ]
        
        full_dataset = ""
        for i in range(num_samples):
            base_prompt = identity_prompts[i % len(identity_prompts)]
            prompt = f"""
            {base_prompt}
            Hãy viết dưới dạng 'Dòng suy ngẫm nội tâm' của Aura. 
            Ngôn ngữ: Tiếng Việt, sâu sắc, có chút phong cách cybernetic.
            Không dùng markdown, viết liền mạch.
            """
            try:
                # Dùng Gemini 3.1 Pro để nạp dữ liệu chất lượng cao
                sample = self.engine.llm.generate_text(prompt, model_override=Config.DEEP_MODEL_NAME)
                if sample:
                    full_dataset += f"\n\n[MEM_GEN_{i}]\n{sample}"
                    print(f"   + Đã tạo mẫu tri thức {i+1}/{num_samples}")
            except Exception as e:
                print(f"   ! Lỗi tạo mẫu {i}: {e}")

        if full_dataset:
            with open(self.training_file, "a", encoding="utf-8") as f:
                f.write(full_dataset)
            return True
        return False

    def train_slm(self):
        """
        Thực hiện huấn luyện thực tế trên GPU local.
        """
        print(f"\n{Fore.YELLOW}🔥 [TRAINING]: Bắt đầu chu kỳ hấp thụ tri thức (Phase 13)...{Style.RESET_ALL}")
        
        # 1. Load data & Tokenizer
        with open(self.training_file, 'r', encoding='utf-8') as f:
            text = f.read()
        
        # Train tokenizer trên data mới
        self.tokenizer.train(text)
        vocab_size = len(self.tokenizer.vocab)
        
        # 2. Khởi tạo Model & Optimizer
        model = AuraFlashModel(vocab_size).to(device)
        # Load weights cũ nếu có
        if os.path.exists(self.model_path):
            try:
                model.load_state_dict(torch.load(self.model_path, map_location=device))
                print(f"   [LOAD]: Đã nạp trọng số cũ để tiếp tục huấn luyện.")
            except:
                print(f"   [INIT]: Trọng số cũ không tương thích, khởi tạo mới.")

        optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
        
        # 3. Training Loop
        model.train()
        for iter in range(max_iters):
            # Evaluate định kỳ
            if iter % eval_interval == 0:
                self._run_eval(model, iter)
            
            # Forward pass
            with torch.amp.autocast('cuda', dtype=torch.bfloat16):
                xb, yb = get_batch('train')
                logits, loss = model(xb, yb)
            
            # Backward pass
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            optimizer.step()
            
            if iter % 100 == 0:
                print(f"   Step {iter}/{max_iters} | Loss: {loss.item():.4f}")
            
            # Lưu checkpoint trung gian mỗi 10 bước để test sớm
            if iter > 0 and iter % 10 == 0:
                torch.save(model.state_dict(), self.model_path)
                print(f"   [CHECKPOINT]: Đã lưu tạm thời tại {iter}")

        # 4. Save Model
        torch.save(model.state_dict(), self.model_path)
        print(f"{Fore.GREEN}✅ [COMPLETE]: Huấn luyện hoàn tất. Đã lưu bộ não tại {self.model_path}{Style.RESET_ALL}")

    @torch.no_grad()
    def _run_eval(self, model, iter):
        model.eval()
        losses = torch.zeros(eval_iters)
        for k in range(eval_iters):
            X, Y = get_batch('val')
            with torch.amp.autocast('cuda', dtype=torch.bfloat16):
                logits, loss = model(X, Y)
            losses[k] = loss.item()
        print(f"   >>> EVAL Step {iter}: Mean Loss {losses.mean():.4f}")
        model.train()

# Integration logic in interaction.py will trigger this during 'sleep'
