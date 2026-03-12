import unittest
import torch
import torch.nn as nn
from unittest.mock import MagicMock, patch
import os
import sys

# Thêm đường dẫn để import các module của dự án
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../core/engine/nanogpt")))

# Mock Config hoàn chỉnh hơn
class MockConfig:
    SLM_D_MODEL = 32
    SLM_N_LAYERS = 1
    SLM_N_HEADS = 4
    SLM_N_KV_HEADS = 2
    SLM_N_EXPERTS = 4
    SLM_TOP_K = 2
    SLM_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../core/engine/nanogpt"))
    OUTPUT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../outputs"))

with patch('config.Config', MockConfig):
    # Import model trễ để đảm bảo patch có hiệu lực
    from core.engine.nanogpt.model import AuraFlashModel, AuraMoE, AuraAttention, RMSNorm
    from core.engine.nanogpt.tokenizer import BPETokenizer

# --- MOCK ENVIRONMENT COMPONENTS ---

class MockVirtualDatabase:
    """Giả lập Database ảo (Mock DB)"""
    def __init__(self):
        self.storage = {}
    def query(self, key):
        return self.storage.get(key, None)
    def insert(self, key, value):
        self.storage[key] = value
        return True

class MockVirtualMachine:
    """Giả lập môi trường VM cô lập"""
    def __init__(self):
        self.is_isolated = True
    def run_inference(self, model, input_tensor):
        with torch.no_grad():
            return model(input_tensor)

# --- COMPREHENSIVE TEST SUITE ---

class TestAuraFlashV5(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Khởi tạo các thông số test cực nhỏ
        cls.vocab_size = 50
        cls.n_embd = 32
        cls.n_head = 4
        cls.n_kv_head = 2
        cls.n_layer = 1
        cls.n_experts = 4
        cls.top_k = 2
        cls.window_size = 8
        cls.block_size = 32
        cls.device = 'cpu'
        
        # Override module variables manually to be safe
        import core.engine.nanogpt.model as model_mod
        model_mod.n_embd = cls.n_embd
        model_mod.n_layer = cls.n_layer
        model_mod.n_head = cls.n_head
        model_mod.n_kv_head = cls.n_kv_head
        model_mod.n_experts = cls.n_experts
        model_mod.top_k = cls.top_k
        model_mod.block_size = cls.block_size
        model_mod.window_size = cls.window_size
        
        cls.model = AuraFlashModel(cls.vocab_size).to(cls.device)

    # 1. TEST TOKENIZER (BPE)
    def test_tokenizer_efficiency(self):
        tokenizer = BPETokenizer(vocab_size=100)
        sample_text = "Aura is a neuro-symbolic AI agent."
        tokenizer.train(sample_text)
        
        encoded = tokenizer.encode(sample_text)
        decoded = tokenizer.decode(encoded)
        
        print(f"\nOriginal: [{sample_text}]")
        print(f"Decoded : [{decoded}]")
        self.assertEqual(sample_text.strip(), decoded.replace('\x00', '').strip())

    # 2. TEST MOE ARCHITECTURE
    def test_moe_routing(self):
        moe = AuraMoE(self.n_embd, self.n_experts, self.top_k).to(self.device)
        x = torch.randn(1, 4, self.n_embd)
        output, aux_loss = moe(x)
        self.assertEqual(output.shape, x.shape)
        self.assertFalse(torch.isnan(output).any())

    # 3. TEST ATTENTION (SLIDING WINDOW)
    def test_sliding_window_mask(self):
        attention = AuraAttention(self.n_embd, self.n_head, self.n_kv_head).to(self.device)
        x = torch.randn(1, 16, self.n_embd)
        
        output = attention(x)
        self.assertEqual(output.shape, (1, 16, self.n_embd))

    # 4. TEST MODEL FORWARD & GENERATION
    def test_model_inference(self):
        idx = torch.randint(0, self.vocab_size, (1, 5))
        logits, loss, aux_loss = self.model(idx)
        self.assertEqual(logits.shape, (1, 5, self.vocab_size))
        
        # Test sinh text ngắn
        generated = self.model.generate(idx, max_new_tokens=2)
        self.assertEqual(generated.shape, (1, 7))

    # 5. TEST MOCK DB & VM INTEGRATION
    def test_mock_environment(self):
        db = MockVirtualDatabase()
        vm = MockVirtualMachine()
        db.insert("status", "ok")
        self.assertEqual(db.query("status"), "ok")
        
        idx = torch.randint(0, self.vocab_size, (1, 4))
        logits, _, _ = vm.run_inference(self.model, idx)
        self.assertEqual(logits.shape, (1, 4, self.vocab_size))

if __name__ == "__main__":
    unittest.main()
