import torch
import torch.nn as nn
from torch.nn import functional as F
import os
import math
import sys

# Hỗ trợ chạy trực tiếp và import từ engine
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../")))
import slm_params as slm_config

# --- Aura-MoE 700M (Pocket AI) Hyperparameters ---
batch_size = slm_config.batch_size
block_size = slm_config.block_size
max_iters = slm_config.max_iters
eval_interval = slm_config.eval_interval
learning_rate = slm_config.learning_rate    
device = slm_config.device
eval_iters = slm_config.eval_iters

n_embd = slm_config.d_model
n_layer = slm_config.n_layers
n_head = slm_config.n_heads
n_kv_head = slm_config.n_kv_heads
n_experts = slm_config.n_experts
top_k = slm_config.top_k
window_size = 512       
attn_block_size = 512   
dropout = slm_config.dropout          
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
        return self._norm(x) * self.weight

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

# --- MIXTURE OF EXPERTS (AuraMoE Pocket AI) ---

class AuraExpert(nn.Module):
    def __init__(self, n_embd):
        super().__init__()
        # SwiGLU hidden dim
        hidden_dim = int(2 * 4 * n_embd / 3) 
        # Survival Mode: bias=False bắt buộc
        self.w1 = nn.Linear(n_embd, hidden_dim, bias=False)
        self.w2 = nn.Linear(hidden_dim, n_embd, bias=False)
        self.w3 = nn.Linear(n_embd, hidden_dim, bias=False)
    def forward(self, x):
        return self.w2(F.silu(self.w1(x)) * self.w3(x))

class AuraMoE(nn.Module):
    def __init__(self, n_embd, n_experts, top_k):
        super().__init__()
        self.n_experts = n_experts
        self.top_k = top_k
        self.router = nn.Linear(n_embd, n_experts, bias=False)
        self.experts = nn.ModuleList([AuraExpert(n_embd) for _ in range(n_experts)])
        
    def forward(self, x):
        # x shape: (B, T, C)
        B, T, C = x.shape
        x_flat = x.view(-1, C) # (B*T, C)
        
        # Routing logits
        router_logits = self.router(x_flat) # (B*T, n_experts)
        routing_probs = F.softmax(router_logits, dim=1)
        
        # Chọn top_k expert
        routing_weights, selected_experts = torch.topk(routing_probs, self.top_k, dim=-1) # (B*T, top_k)
        routing_weights /= routing_weights.sum(dim=-1, keepdim=True) # Normalize top_k weights
        
        # Tạo output tensor rỗng
        final_output = torch.zeros_like(x_flat)
        
        # Tính toán trên từng Expert (Tối ưu bằng cách lọc mask)
        for i, expert in enumerate(self.experts):
            # Tìm các vị trí (tokens) mà expert `i` được chọn (nằm trong cột top_k nào đó)
            expert_mask = (selected_experts == i)
            token_indices = expert_mask.any(dim=-1) # Boolean mask những tokens gọi expert i
            
            if token_indices.any():
                # Lấy dữ liệu của các token đó
                expert_input = x_flat[token_indices]
                
                # Forward qua expert i
                expert_output = expert(expert_input)
                
                # Tìm ra các trọng số (weight) tương ứng của expert i cho các token đó
                # extract weight from routing_weights matching expert `i`
                weight_indices = expert_mask[token_indices].nonzero(as_tuple=True)[1]
                weights = routing_weights[token_indices, weight_indices].unsqueeze(1)
                
                # Cộng dồn kết quả vào final_output
                final_output[token_indices] += expert_output * weights
                
        # --- EXPERT LOAD BALANCING (AUXILIARY LOSS) ---
        aux_loss = torch.tensor(0.0, device=x.device, dtype=x.dtype)
        if self.training:
            expert_mask = F.one_hot(selected_experts, num_classes=self.n_experts).float() 
            f_i = expert_mask.sum(dim=1).mean(dim=0)          
            p_i = routing_probs.mean(dim=0)            
            aux_loss = self.n_experts * torch.sum(f_i * p_i)
                
        return final_output.view(B, T, C), aux_loss

class AuraMLP(nn.Module):
    """Tiêu chuẩn LLaMA-like Feed-Forward Network (SwiGLU) dùng khi n_experts = 0"""
    def __init__(self, n_embd):
        super().__init__()
        hidden_dim = int(2 * 4 * n_embd / 3) 
        self.w1 = nn.Linear(n_embd, hidden_dim, bias=False)
        self.w2 = nn.Linear(hidden_dim, n_embd, bias=False)
        self.w3 = nn.Linear(n_embd, hidden_dim, bias=False)
        
    def forward(self, x):
        out = self.w2(F.silu(self.w1(x)) * self.w3(x))
        # Tuân thủ chung return API: (output, aux_loss)
        aux_loss = torch.tensor(0.0, device=x.device, dtype=x.dtype)
        return out, aux_loss

# --- RING-INSPIRED BLOCKWISE ATTENTION ---

class AuraAttention(nn.Module):
    """Attention với Ring-Blockwise để mở rộng Context cực đại mà không nổ VRAM"""
    def __init__(self, n_embd, n_head, n_kv_head, max_batch_size=8, max_seq_len=2048):
        super().__init__()
        self.n_head = n_head
        self.n_kv_head = n_kv_head
        self.head_dim = n_embd // n_head
        self.kv_group_size = n_head // n_kv_head
        self.max_batch_size = max_batch_size
        self.max_seq_len = max_seq_len
        
        self.wq = nn.Linear(n_embd, n_embd, bias=False)
        self.wk = nn.Linear(n_embd, n_kv_head * self.head_dim, bias=False)
        self.wv = nn.Linear(n_embd, n_kv_head * self.head_dim, bias=False)
        self.wo = nn.Linear(n_embd, n_embd, bias=False)
        
        self.rope = RotaryEmbedding(self.head_dim)
        
        self.register_buffer('k_cache', torch.zeros(max_batch_size, n_kv_head, max_seq_len, self.head_dim), persistent=False)
        self.register_buffer('v_cache', torch.zeros(max_batch_size, n_kv_head, max_seq_len, self.head_dim), persistent=False)

    def forward(self, x, start_pos=None, use_cache=False):
        B, T, C = x.shape
        q = self.wq(x).view(B, T, self.n_head, self.head_dim).transpose(1, 2)
        k = self.wk(x).view(B, T, self.n_kv_head, self.head_dim).transpose(1, 2)
        v = self.wv(x).view(B, T, self.n_kv_head, self.head_dim).transpose(1, 2)
        
        seq_offset = start_pos if start_pos is not None else 0
        
        cos, sin = self.rope(v, seq_len=T + seq_offset)
        cos_curr = cos[:, :, seq_offset:seq_offset+T, :]
        sin_curr = sin[:, :, seq_offset:seq_offset+T, :]
        
        q, _ = apply_rotary_pos_emb(q, q, cos_curr, sin_curr)
        _, k = apply_rotary_pos_emb(k, k, cos_curr, sin_curr)

        if use_cache and start_pos is not None:
            fetch_len = min(start_pos, self.max_seq_len)
            past_k = self.k_cache[:B, :, :fetch_len, :]
            past_v = self.v_cache[:B, :, :fetch_len, :]
            
            k_out = torch.cat([past_k, k], dim=2)
            v_out = torch.cat([past_v, v], dim=2)
            
            positions = torch.arange(start_pos, start_pos + T, device=x.device)
            wrap_mask = positions >= self.max_seq_len
            positions[wrap_mask] = 16 + ((positions[wrap_mask] - 16) % (self.max_seq_len - 16))
            
            for b in range(B):
                for t_idx, pos in enumerate(positions):
                    self.k_cache[b, :, pos, :] = k[b, :, t_idx, :]
                    self.v_cache[b, :, pos, :] = v[b, :, t_idx, :]
            
            k_out = k_out.repeat_interleave(self.kv_group_size, dim=1)
            v_out = v_out.repeat_interleave(self.kv_group_size, dim=1)
            
            out = F.scaled_dot_product_attention(q, k_out, v_out, attn_mask=None, dropout_p=0.0, is_causal=(T > 1))
        else:
            k_out = k.repeat_interleave(self.kv_group_size, dim=1)
            v_out = v.repeat_interleave(self.kv_group_size, dim=1)
            out = F.scaled_dot_product_attention(q, k_out, v_out, attn_mask=None, dropout_p=0.0, is_causal=True)
            
        out = out.transpose(1, 2).contiguous().view(B, T, C)
        return self.wo(out)

class AuraBlock(nn.Module):
    def __init__(self, n_embd, n_head, n_kv_head, n_experts=8, top_k=2):
        super().__init__()
        self.attention = AuraAttention(n_embd, n_head, n_kv_head)
        if n_experts > 0:
            self.mlp = AuraMoE(n_embd, n_experts, top_k)
        else:
            self.mlp = AuraMLP(n_embd)
        self.attention_norm = RMSNorm(n_embd)
        self.ffn_norm = RMSNorm(n_embd)
    def forward(self, x, start_pos=None, use_cache=False):
        attn_out = self.attention(self.attention_norm(x), start_pos=start_pos, use_cache=use_cache)
        x = x + attn_out
        ffn_out, aux_loss = self.mlp(self.ffn_norm(x))
        x = x + ffn_out
        return x, aux_loss

class AuraFlashModel(nn.Module):
    def __init__(self, vocab_size, use_checkpoint=False):
        super().__init__()
        self.use_checkpoint = use_checkpoint
        self.token_embedding = nn.Embedding(vocab_size, n_embd)
        # Sử dụng MoE Pocket AI (700M) để cân bằng tốc độ / trí tuệ trên 6GB VRAM
        self.layers = nn.ModuleList([AuraBlock(n_embd, n_head, n_kv_head, n_experts, top_k) for _ in range(n_layer)])
        self.norm = RMSNorm(n_embd)
        self.output = nn.Linear(n_embd, vocab_size, bias=False)
        self.apply(self._init_weights)
    def _init_weights(self, module):
        if isinstance(module, nn.Linear):
            torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)
        elif isinstance(module, nn.Embedding):
            torch.nn.init.normal_(module.weight, mean=0.0, std=0.02)
    def forward(self, idx, targets=None, start_pos=None, use_cache=False):
        B, T = idx.shape
        x = self.token_embedding(idx)
        
        total_aux_loss = torch.tensor(0.0, device=x.device, dtype=x.dtype)
        for layer in self.layers:
            if self.use_checkpoint and self.training:
                from torch.utils.checkpoint import checkpoint
                x, aux_loss = checkpoint(layer, x, use_reentrant=False)
            else:
                x, aux_loss = layer(x, start_pos=start_pos, use_cache=use_cache)
            total_aux_loss = total_aux_loss + aux_loss
                
        x = self.norm(x)
        logits = self.output(x)
        if targets is None:
            loss = None
        else:
            B, T, C = logits.shape
            logits = logits.view(B*T, C)
            targets = targets.view(B*T)
            loss = F.cross_entropy(logits, targets)
            
        return logits, loss, total_aux_loss
        
    def configure_optimizers(self, weight_decay, learning_rate, betas, device_type):
        """
        Implementation of nanoGPT's smart optimizer configuration:
        - Tách riêng parameters cần và không cần weight decay (bias, layernorm không cần)
        - Kích hoạt fused AdamW nếu chạy trên CUDA để tăng tốc tính toán.
        """
        import inspect
        
        # Bắt đầu phân loại parameters
        param_dict = {pn: p for pn, p in self.named_parameters()}
        # Chỉ tối ưu những param yêu cầu gradients
        param_dict = {pn: p for pn, p in param_dict.items() if p.requires_grad}
        
        # Bất kỳ Tensor nào là ma trận từ 2 chiều trở lên thì sẽ áp dụng weight decay
        # VD: weight của nn.Linear hay nn.Embedding
        decay_params = [p for n, p in param_dict.items() if p.dim() >= 2]
        # Các Tensor 1 chiều (như bias và trọng số của RMSNorm) sẽ không bị weight decay
        nodecay_params = [p for n, p in param_dict.items() if p.dim() < 2]
        
        optim_groups = [
            {'params': decay_params, 'weight_decay': weight_decay},
            {'params': nodecay_params, 'weight_decay': 0.0}
        ]
        
        num_decay = sum(p.numel() for p in decay_params)
        num_nodecay = sum(p.numel() for p in nodecay_params)
        print(f"num decayed parameter tensors: {len(decay_params)}, with {num_decay:,} parameters")
        print(f"num non-decayed parameter tensors: {len(nodecay_params)}, with {num_nodecay:,} parameters")
        
        # Nếu đang sử dụng CUDA, ta bật 'fused' để tăng tốc thuật toán học gấp rưỡi (Dành cho bản Fallback)
        fused_available = 'fused' in inspect.signature(torch.optim.AdamW).parameters
        use_fused = fused_available and device_type == 'cuda'
        extra_args = dict(fused=True) if use_fused else dict()
        
        # ─── POCKET AI SURVIVAL MODE: BITSANDBYTES 8-BIT OPTIMIZER ───
        # Native AdamW ngốn 14 bytes/param (32-bit state). 8-bit AdamW chỉ khoảng 6 bytes/param.
        try:
            import bitsandbytes as bnb
            optimizer = bnb.optim.AdamW8bit(optim_groups, lr=learning_rate, betas=betas)
            print("using optimizer: bitsandbytes 8-bit AdamW (VRAM Savior!)")
        except ImportError:
            print(f"using optimizer: PyTorch Native AdamW (fused={use_fused}). LƯU Ý: VRAM SẼ CAO HƠN ĐỂ LƯU 32-BIT STATES.")
            optimizer = torch.optim.AdamW(optim_groups, lr=learning_rate, betas=betas, **extra_args)
            
        return optimizer

    def generate(self, idx, max_new_tokens):
        start_pos = 0
        for _ in range(max_new_tokens):
            if start_pos > 0:
                idx_cond = idx[:, -1:]
            else:
                idx_cond = idx
                
            logits, _, _ = self(idx_cond, start_pos=start_pos, use_cache=True)
            logits = logits[:, -1, :] 
            probs = F.softmax(logits, dim=-1) 
            idx_next = torch.multinomial(probs, num_samples=1) 
            idx = torch.cat((idx, idx_next), dim=1) 
            start_pos += idx_cond.shape[1]
        return idx

# --- DELETED SIDE EFFECTS (Phần này đã được dọn sang scripts/train_slm.py hoặc prepare_data.py) ---
