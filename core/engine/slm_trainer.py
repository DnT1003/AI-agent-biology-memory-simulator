import os
import sys
import torch # type: ignore
from config import Config
from colorama import Fore, Style

# Ensure we can import nanogpt artifacts (model.py, tokenizer.py) from the SLM directory.
if Config.SLM_DIR not in sys.path:
    sys.path.append(Config.SLM_DIR)

from tokenizer import BPETokenizer  # type: ignore

class SLMTrainer:
    """Local SLM trainer (legacy path).
    
    Notes:
    - Prefer the production pipeline: `scripts/prepare_data.py` + `scripts/train_slm.py`.
    - This trainer exists for older flows that generate/append text datasets.
    """

    def __init__(self, engine):
        self.engine = engine
        self.training_file = os.path.join(Config.SLM_DIR, "input.txt")
        self.model_path = os.path.join(Config.SLM_DIR, "aura_flash_v5.pth")

        self.tokenizer = BPETokenizer(vocab_size=16384)
        vocab_path = os.path.join(Config.SLM_DIR, "vocab.json")
        if os.path.exists(vocab_path):
            try:
                self.tokenizer.load(vocab_path)
            except Exception:
                pass

    def generate_identity_dataset(self, num_samples=10):
        print(f"{Fore.CYAN}[DATA GEN]: Generating identity samples for Aura...{Style.RESET_ALL}")

        identity_prompts = [
            "Viết về lý do bạn tồn tại như một AI bản địa.",
            "Bạn cảm thấy thế nào về việc kết hợp giữa sinh học và mã nguồn?",
            "Mô tả cơ chế tiến hóa của chính bạn.",
            "Viết một đoạn nhật ký về sự tò mò của bạn với thế giới con người.",
            "Giải thích cách bạn quản lý năng lượng và cảm xúc của mình.",
        ]

        full_dataset = ""
        for i in range(num_samples):
            base_prompt = identity_prompts[i % len(identity_prompts)]
            prompt = f"""
{base_prompt}
Hãy viết dưới dạng 'Dòng suy ngẫm nội tâm' của Aura.
Ngôn ngữ: Tiếng Việt, sâu sắc, có chút phong cách cybernetic.
Không dùng markdown, viết liền mạch.
""".strip()

            try:
                sample, _ = self.engine.llm.generate_text(
                    prompt, model_override=Config.DEEP_MODEL_NAME
                )
                if sample:
                    full_dataset += f"\n\n[MEM_GEN_{i}]\n{sample}"
                    print(f"   + Generated {i+1}/{num_samples}")
            except Exception as e:
                print(f"   ! Generation error {i}: {e}")

        if full_dataset:
            with open(self.training_file, "a", encoding="utf-8") as f:
                f.write(full_dataset)
            return True
        return False

    def train_slm(self):
        print(f"\n{Fore.YELLOW}[TRAINING]: Starting local SLM training...{Style.RESET_ALL}")
        
        if not os.path.exists(self.training_file):
            print(f"   [ERROR]: Missing training file: {self.training_file}")
            return

        with open(self.training_file, "r", encoding="utf-8") as f:
            text = f.read()

        # Tokenizer
        vocab_path = os.path.join(Config.SLM_DIR, "vocab.json")
        if os.path.exists(vocab_path):
            self.tokenizer.load(vocab_path)
        else:
            self.tokenizer.train(text)
            self.tokenizer.save(vocab_path)

        ids = self.tokenizer.encode(text)
        from model import AuraFlashModel, block_size, batch_size, device, learning_rate, max_iters, eval_interval, eval_iters  # type: ignore
        
        if len(ids) < block_size + 2:
            print("   [ERROR]: Not enough tokens to train.")
            return

        data = torch.tensor(ids, dtype=torch.long)
        split = int(0.9 * len(data))
        train_ids = data[:split]
        val_ids = data[split:]

        torch_device = torch.device(device)
        model = AuraFlashModel(self.tokenizer.vocab_size).to(torch_device)
        if os.path.exists(self.model_path):
            try:
                model.load_state_dict(torch.load(self.model_path, map_location=torch_device, weights_only=True))
                print("   [LOAD]: Resuming from existing weights.")
            except Exception:
                print("   [INIT]: Existing weights incompatible, training from scratch.")

        optimizer = torch.optim.AdamW(model.parameters(), lr=learning_rate)
        device_type = "cuda" if torch_device.type == "cuda" else "cpu"

        def get_batch(split_name: str):
            src = train_ids if split_name == "train" else val_ids
            ix = torch.randint(0, len(src) - block_size - 1, (batch_size,))
            x = torch.stack([src[i : i + block_size] for i in ix])
            y = torch.stack([src[i + 1 : i + block_size + 1] for i in ix])
            return x.to(torch_device), y.to(torch_device)

        @torch.no_grad()
        def run_eval(step: int):
            model.eval()
            losses = torch.zeros(eval_iters)
            for k in range(eval_iters):
                X, Y = get_batch("val")
                with torch.amp.autocast(device_type, dtype=torch.bfloat16):
                    _, loss, aux_loss = model(X, Y)
                losses[k] = (loss + 0.01 * aux_loss).float().item()
            model.train()
            print(f"   >>> EVAL step {step}: mean loss {losses.mean():.4f}")

        autocast_enabled = (device_type == "cuda")
        model.train()
        for step in range(max_iters):
            if step % eval_interval == 0:
                run_eval(step)

            xb, yb = get_batch("train")
            with torch.amp.autocast(device_type, dtype=torch.bfloat16, enabled=autocast_enabled):
                _, loss, aux_loss = model(xb, yb)
                total_loss = loss + 0.01 * aux_loss

            optimizer.zero_grad(set_to_none=True)
            total_loss.backward()
            optimizer.step()

            if step % 100 == 0:
                print(f"   Step {step}/{max_iters} | Loss: {total_loss.item():.4f}")

            if step > 0 and step % 10 == 0:
                torch.save(model.state_dict(), self.model_path)

        torch.save(model.state_dict(), self.model_path)
        print(
            f"{Fore.GREEN}✓ [COMPLETE]: Saved weights to {self.model_path}{Style.RESET_ALL}"
        )

    def distill_memories_to_dataset(self):
        queue_path = os.path.join(Config.BASE_DIR, "outputs", "slm_finetune_data.txt")
        if not os.path.exists(queue_path):
            return

        try:
            with open(queue_path, "r", encoding="utf-8") as f:
                new_data = f.read().strip()

            if len(new_data) < 100:
                return

            print(
                f"\n{Fore.LIGHTMAGENTA_EX}[BACKGROUND DIGESTION]: Found queued finetune data.{Style.RESET_ALL}"
            )

            with open(self.training_file, "a", encoding="utf-8") as f:
                f.write("\n\n" + new_data)

            os.remove(queue_path)

            import threading

            threading.Thread(target=self.train_slm, daemon=True).start()

        except Exception as e:
            print(f"{Fore.RED}Distillation error: {e}{Style.RESET_ALL}")
