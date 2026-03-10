import torch
import torch.nn as nn
from torch.nn import functional as F
import os
import math
import sys

# Hỗ trợ chạy trực tiếp và import từ engine
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
try:
    from config import Config
except ImportError:
    class Config:
        SLM_D_MODEL = 1024
        SLM_N_LAYERS = 24
        SLM_N_HEADS = 16
        SLM_N_KV_HEADS = 4
        SLM_N_EXPERTS = 8
        SLM_TOP_K = 2

# --- Aura-Flash V5.4 (Ring Attention) Hyperparameters ---
batch_size = 8          # Giảm batch size để bù cho Context cực dài
block_size = 4096       # NÂNG CẤP: Context 4096 nhờ Ring-Blockwise Attention
max_iters = 5000
eval_interval = 500
learning_rate = 1e-4    
device = 'cuda' if torch.cuda.is_available() else 'cpu'
eval_iters = 50
n_embd = Config.SLM_D_MODEL
n_layer = Config.SLM_N_LAYERS
n_head = Config.SLM_N_HEADS
n_kv_head = Config.SLM_N_KV_HEADS
n_experts = Config.SLM_N_EXPERTS
top_k = Config.SLM_TOP_K
window_size = 512       # Tăng cửa sổ trượt
attn_block_size = 512   # Kích thước khối khi tính Ring Attention
dropout = 0.0          
# ------------

torch.manual_seed(1337)

# --- MODERN COMPONENTS ---

class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-6):
        super().__init__()
        self.eps = eps
        self.weight = nn.Parameter(torch.ones(dim))
    def _norm(self, x):
        return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
    def forward(self, x):
        return self._norm(x.float()).type_as(x) * self.weight

class RotaryEmbedding(nn.Module):
    def __init__(self, dim, max_position_embeddings=8192, base=10000):
        super().__init__()
        inv_freq = 1.0 / (base ** (torch.arange(0, dim, 2).float() / dim))
        self.register_buffer("inv_freq", inv_freq)
        self.max_seq_len_cached = max_position_embeddings
        t = torch.arange(self.max_seq_len_cached).type_as(self.inv_freq)
        freqs = torch.einsum("i,j->ij", t, self.inv_freq)
        emb = torch.cat((freqs, freqs), dim=-1)
        self.register_buffer("cos_cached", emb.cos()[None, None, :, :])
        self.register_buffer("sin_cached", emb.sin()[None, None, :, :])
    def forward(self, x, seq_len=None):
        return self.cos_cached[:, :, :seq_len, :], self.sin_cached[:, :, :seq_len, :]

def rotate_half(x):
    x1, x2 = x[..., : x.shape[-1] // 2], x[..., x.shape[-1] // 2 :]
    return torch.cat((-x2, x1), dim=-1)

def apply_rotary_pos_emb(q, k, cos, sin):
    q_embed = (q * cos) + (rotate_half(q) * sin)
    k_embed = (k * cos) + (rotate_half(k) * sin)
    return q_embed, k_embed

# --- MIXTURE OF EXPERTS (MoE) ---

class AuraExpert(nn.Module):
    def __init__(self, n_embd):
        super().__init__()
        hidden_dim = int(2 * 4 * n_embd / 3) 
        self.w1 = nn.Linear(n_embd, hidden_dim, bias=False)
        self.w2 = nn.Linear(hidden_dim, n_embd, bias=False)
        self.w3 = nn.Linear(n_embd, hidden_dim, bias=False)
    def forward(self, x):
        return self.w2(F.silu(self.w1(x)) * self.w3(x))

class AuraMoE(nn.Module):
    def __init__(self, n_embd, n_experts, top_k):
        super().__init__()
        self.experts = nn.ModuleList([AuraExpert(n_embd) for _ in range(n_experts)])
        self.router = nn.Linear(n_embd, n_experts, bias=False)
        self.top_k = top_k
    def forward(self, x):
        B, T, C = x.shape
        x_flat = x.view(-1, C) 
        logits = self.router(x_flat) 
        probs = F.softmax(logits, dim=-1)
        scores, indices = torch.topk(probs, self.top_k, dim=-1) 
        
        scores = scores / scores.sum(dim=-1, keepdim=True)
        
        output = torch.zeros_like(x_flat)
        
        # --- Chunk-based MoE Processing to prevent OOM ---
        chunk_size = 1024
        num_tokens = x_flat.size(0)
        
        for start_idx in range(0, num_tokens, chunk_size):
            end_idx = min(start_idx + chunk_size, num_tokens)
            
            chunk_x = x_flat[start_idx:end_idx]
            chunk_indices = indices[start_idx:end_idx]
            chunk_scores = scores[start_idx:end_idx]
            
            for i, expert in enumerate(self.experts):
                mask = (chunk_indices == i).any(dim=-1)
                if mask.any():
                    expert_out = expert(chunk_x[mask]) * chunk_scores[chunk_indices == i].unsqueeze(-1)
                    out_view = output[start_idx:end_idx]
                    out_view[mask] += expert_out
                    
        return output.view(B, T, C)

# --- RING-INSPIRED BLOCKWISE ATTENTION ---

class AuraAttention(nn.Module):
    """Attention với Ring-Blockwise để mở rộng Context cực đại mà không nổ VRAM"""
    def __init__(self, n_embd, n_head, n_kv_head, window_size=512):
        super().__init__()
        self.n_head = n_head
        self.n_kv_head = n_kv_head
        self.head_dim = n_embd // n_head
        self.kv_group_size = n_head // n_kv_head
        self.window_size = window_size
        
        self.wq = nn.Linear(n_embd, n_embd, bias=False)
        self.wk = nn.Linear(n_embd, n_kv_head * self.head_dim, bias=False)
        self.wv = nn.Linear(n_embd, n_kv_head * self.head_dim, bias=False)
        self.wo = nn.Linear(n_embd, n_embd, bias=False)
        
        self.rope = RotaryEmbedding(self.head_dim)
        
        # Sliding Window Mask
        # Sử dụng trễ (lazy) để tiết kiệm memory cho mask lớn
        self.register_buffer('sliding_mask', None, persistent=False)

    def forward(self, x):
        B, T, C = x.shape
        q = self.wq(x).view(B, T, self.n_head, self.head_dim).transpose(1, 2)
        k = self.wk(x).view(B, T, self.n_kv_head, self.head_dim).transpose(1, 2)
        v = self.wv(x).view(B, T, self.n_kv_head, self.head_dim).transpose(1, 2)
        
        cos, sin = self.rope(v, seq_len=T)
        q, _ = apply_rotary_pos_emb(q, q, cos, sin)
        k = k.repeat_interleave(self.kv_group_size, dim=1)
        v = v.repeat_interleave(self.kv_group_size, dim=1)
        _, k = apply_rotary_pos_emb(k, k, cos, sin)
        
        # --- BLOCKWISE RING ATTENTION LOGIC ---
        # Thay vì tính Full Matrix (T, T), ta tính theo từng block (attn_block_size)
        out = torch.zeros_like(q)
        
        # Nếu sequence ngắn, chạy Full Attention cho nhanh
        if T <= attn_block_size:
            wei = (q @ k.transpose(-2, -1)) * (self.head_dim ** -0.5)
            # Causal mask + Sliding Window
            mask = torch.tril(torch.ones(T, T, device=x.device))
            for i in range(T):
                for j in range(T):
                    if i - j > self.window_size: mask[i, j] = 0
            wei = wei.masked_fill(mask == 0, float('-inf'))
            wei = F.softmax(wei, dim=-1)
            out = wei @ v
        else:
            # Blockwise processing (Ring-style)
            # Để đơn giản hóa cho Single-GPU, ta dùng phân mảnh dọc Query
            for i in range(0, T, attn_block_size):
                end_i = min(i + attn_block_size, T)
                q_block = q[:, :, i:end_i, :] # (B, H, BS, D)
                
                # Biến tích lũy cho Safe Softmax
                block_out = torch.zeros_like(q_block)
                l = torch.zeros((B, self.n_head, end_i - i, 1), device=x.device)
                m = torch.fill_(torch.empty((B, self.n_head, end_i - i, 1), device=x.device), float('-inf'))
                
                # Duyệt qua các blocks Key/Value (Giới hạn bởi Sliding Window cho hiệu suất)
                start_j = max(0, i - self.window_size)
                for j in range(start_j, end_i, attn_block_size): # Causal: j không vượt quá end_i
                    end_j = min(j + attn_block_size, end_i)
                    k_block = k[:, :, j:end_j, :]
                    v_block = v[:, :, j:end_j, :]
                    
                    attn_scores = (q_block @ k_block.transpose(-2, -1)) * (self.head_dim ** -0.5)
                    
                    # Apply causal mask nội bộ block nếu j == i
                    if i == j:
                        curr_bs = end_i - i
                        m_causal = torch.tril(torch.ones(curr_bs, curr_bs, device=x.device))
                        attn_scores = attn_scores.masked_fill(m_causal == 0, float('-inf'))
                    
                    # Flash-Attention style online softmax
                    m_new = torch.max(m, torch.max(attn_scores, dim=-1, keepdim=True)[0])
                    p = torch.exp(attn_scores - m_new)
                    l = l * torch.exp(m - m_new) + torch.sum(p, dim=-1, keepdim=True)
                    block_out = block_out * torch.exp(m - m_new) + (p @ v_block)
                    m = m_new
                
                out[:, :, i:end_i, :] = block_out / l
        
        out = out.transpose(1, 2).contiguous().view(B, T, C)
        return self.wo(out)

class AuraBlock(nn.Module):
    def __init__(self, n_embd, n_head, n_kv_head, n_experts, top_k):
        super().__init__()
        self.attention = AuraAttention(n_embd, n_head, n_kv_head, window_size=window_size)
        self.moe = AuraMoE(n_embd, n_experts, top_k)
        self.attention_norm = RMSNorm(n_embd)
        self.ffn_norm = RMSNorm(n_embd)
    def forward(self, x):
        # Chúng ta wrap toàn bộ block này để checkpoint nếu cần
        x = x + self.attention(self.attention_norm(x))
        x = x + self.moe(self.ffn_norm(x))
        return x

class AuraFlashModel(nn.Module):
    def __init__(self, vocab_size, use_checkpoint=False):
        super().__init__()
        self.use_checkpoint = use_checkpoint
        self.token_embedding = nn.Embedding(vocab_size, n_embd)
        self.layers = nn.ModuleList([AuraBlock(n_embd, n_head, n_kv_head, n_experts, top_k) for _ in range(n_layer)])
        self.norm = RMSNorm(n_embd)
        self.output = nn.Linear(n_embd, vocab_size, bias=False)
        self.apply(self._init_weights)
    def _init_weights(self, module):
        if isinstance(module, nn.Linear):
            torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)
        elif isinstance(module, nn.Embedding):
            torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)
    def forward(self, idx, targets=None):
        B, T = idx.shape
        x = self.token_embedding(idx)
        
        for layer in self.layers:
            if self.use_checkpoint and self.training:
                from torch.utils.checkpoint import checkpoint
                x = checkpoint(layer, x, use_reentrant=False)
            else:
                x = layer(x)
                
        x = self.norm(x)
        logits = self.output(x)
        if targets is None:
            loss = None
        else:
            B, T, C = logits.shape
            logits = logits.view(B*T, C)
            targets = targets.view(B*T)
            loss = F.cross_entropy(logits, targets)
        return logits, loss
    def generate(self, idx, max_new_tokens):
        for _ in range(max_new_tokens):
            idx_cond = idx[:, -block_size:]
            logits, _ = self(idx_cond)
            logits = logits[:, -1, :] 
            probs = F.softmax(logits, dim=-1) 
            idx_next = torch.multinomial(probs, num_samples=1) 
            idx = torch.cat((idx, idx_next), dim=1) 
        return idx

# --- TOKENIZATION (BPE Compression) ---
# Tạm thời dùng Character-level tokenizer cơ bản nếu chưa train BPE
# Trong thực tế slm_trainer sẽ train BPE và lưu lại
input_path = os.path.join(os.path.dirname(__file__), 'input.txt')
if not os.path.exists(input_path):
    with open(input_path, 'w', encoding='utf-8') as f:
        f.write("Aura core initialization.")
with open(input_path, 'r', encoding='utf-8') as f:
    text = f.read()

chars = sorted(list(set(text)))
vocab_size = len(chars)
stoi = { ch:i for i,ch in enumerate(chars) }
itos = { i:ch for i,ch in enumerate(chars) }
encode = lambda s: [stoi[c] for c in s if c in stoi] 
decode = lambda l: ''.join([itos[i] for i in l]) 

# DATA SPLITTING
data = torch.tensor(encode(text), dtype=torch.long)
n = int(0.9 * len(data))
train_data = data[:n]
val_data = data[n:]

def get_batch(split):
    data_split = train_data if split == 'train' else val_data
    # Đảm bảo không bị out of bounds
    if len(data_split) <= block_size:
        # Padded batch for small data
        x = torch.zeros((batch_size, block_size), dtype=torch.long)
        y = torch.zeros((batch_size, block_size), dtype=torch.long)
        return x.to(device), y.to(device)
    
    ix = torch.randint(len(data_split) - block_size, (batch_size,))
    x = torch.stack([data_split[i:i+block_size] for i in ix])
    y = torch.stack([data_split[i+1:i+block_size+1] for i in ix])
    return x.to(device), y.to(device)

# --- AURA-TINY (DRAFT MODEL FOR SPECULATIVE DECODING) ---

class AuraTinyModel(nn.Module):
    """Mô hình phản xạ siêu nhỏ (~30M params) để dự đoán nhanh"""
    def __init__(self, vocab_size):
        super().__init__()
        # Thu gọn tối đa để đạt tốc độ cao
        d_tiny = 256
        n_lay_tiny = 4
        n_head_tiny = 4
        self.token_embedding = nn.Embedding(vocab_size, d_tiny)
        self.layers = nn.ModuleList([
            AuraBlock(d_tiny, n_head_tiny, n_head_tiny, n_experts=1, top_k=1) # Không dùng MoE cho Tiny
            for _ in range(n_lay_tiny)
        ])
        self.norm = RMSNorm(d_tiny)
        self.output = nn.Linear(d_tiny, vocab_size, bias=False)
        
    def forward(self, idx, targets=None):
        x = self.token_embedding(idx)
        for layer in self.layers:
            x = layer(x)
        x = self.norm(x)
        logits = self.output(x)
        loss = F.cross_entropy(logits.view(-1, logits.size(-1)), targets.view(-1)) if targets is not None else None
        return logits, loss

# --- SPECULATIVE DECODING ENGINE ---

@torch.no_grad()
def speculative_generate(tiny_model, flash_model, idx, max_new_tokens, k=5):
    """
    Kỹ thuật Speculative Decoding: 
    Tiny (Draft) dự đoán 'k' bước, Flash (Target) kiểm tra song song.
    """
    T_total = idx.shape[1] + max_new_tokens
    while idx.shape[1] < T_total:
        # 1. Draft sinh ra k tokens tiềm năng
        curr_idx = idx
        draft_tokens = []
        for _ in range(k):
            logits, _ = tiny_model(curr_idx[:, -block_size:])
            next_token = torch.argmax(logits[:, -1, :], dim=-1, keepdim=True)
            draft_tokens.append(next_token)
            curr_idx = torch.cat([curr_idx, next_token], dim=1)
        
        # 2. Target kiểm tra song song k tokens đó
        # Chúng ta chạy Target qua toàn bộ chuỗi (original + draft)
        full_logits, _ = flash_model(curr_idx[:, -block_size:])
        
        # Lấy logits tương ứng với các vị trí draft đã dự đoán
        # Flash cung cấp logits cho vị trí T-1 đến T+k-1
        target_probs = F.softmax(full_logits[:, -(k+1):-1, :], dim=-1)
        
        # 3. So sánh và chấp nhận
        accepted_count = 0
        for i in range(k):
            draft_token = draft_tokens[i].item()
            # Lấy token có xác suất cao nhất từ Target tại vị trí đó
            target_token = torch.argmax(target_probs[:, i, :], dim=-1).item()
            
            if draft_token == target_token:
                accepted_count += 1
            else:
                # Nếu sai, ta lấy token xịn từ Target và dừng lại
                idx = torch.cat([idx, torch.tensor([[target_token]], device=device)], dim=1)
                break
        else:
            # Nếu tất cả k tokens đều đúng, ta lấy thêm 1 token bonus từ Target
            bonus_token = torch.argmax(full_logits[:, -1, :], dim=-1, keepdim=True)
            idx = torch.cat([curr_idx, bonus_token], dim=1)
            continue
            
        # Nếu có token được chấp nhận trước khi lỗi
        if accepted_count > 0:
            idx = torch.cat([idx, curr_idx[:, idx.shape[1]:idx.shape[1]+accepted_count]], dim=1)
            
    return idx[:, :T_total]

if __name__ == "__main__":
    # Demo thông số
    model = AuraFlashModel(vocab_size)
    tiny = AuraTinyModel(vocab_size)
    m = model.to(device)
    t = tiny.to(device)
    
    total_params = sum(p.numel() for p in m.parameters())
    tiny_params = sum(p.numel() for p in t.parameters())
    
    print(f"--- Aura-Flash V5.5 (Speculative Ready) ---")
    print(f"Target Model (Flash): {total_params/1e6:.2f} M params")
    print(f"Draft Model (Tiny)  : {tiny_params/1e6:.2f} M params")
    print(f"Speedup Mechanism   : Speculative Decoding (k=5)")
