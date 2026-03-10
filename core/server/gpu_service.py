"""
Aura GPU Microservice - Python 3.12 / Torch
============================================
Chạy trong: .venv_aura (Python 3.12)
Port: 8001

Cung cấp 2 endpoints:
- POST /analyze  → LocalPerception (RoBERTa sentiment)
- POST /generate → SLMCore (NanoGPT thought generation)
- GET  /health   → Kiểm tra trạng thái service
"""
import asyncio
import sys
import os

# ⚠️ Fix: PostgreSQL override SSL globally, gây lỗi Transformers model download
os.environ.pop('CURL_CA_BUNDLE', None)
os.environ.pop('REQUESTS_CA_BUNDLE', None)

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from colorama import init, Fore, Style

init(autoreset=True)

app = FastAPI(
    title="Aura GPU Service",
    description="Python 3.12 microservice cho Torch/GPU — bridge tới Python 3.14 main engine",
    version="1.0.0"
)

# ─── Request Models ───────────────────────────────────────────
class AnalyzeRequest(BaseModel):
    text: str

class GenerateRequest(BaseModel):
    prompt: str
    max_new_tokens: int = 50

# ─── Global model instances ────────────────────────────────────
_local_perception = None
_slm_core = None

# ─── Startup: load models ─────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    global _local_perception, _slm_core

    print(f"\n{Fore.LIGHTCYAN_EX}{'='*50}")
    print(f"  Aura GPU Microservice - Khởi động")
    print(f"{'='*50}{Style.RESET_ALL}")

    try:
        print(f"{Fore.YELLOW}[1/2] Đang tải LocalPerception (RoBERTa)...{Style.RESET_ALL}")
        from core.local_perception import LocalPerception
        _local_perception = LocalPerception()
    except Exception as e:
        print(f"{Fore.RED}[1/2] LocalPerception FAILED: {e}{Style.RESET_ALL}")

    try:
        print(f"{Fore.YELLOW}[2/2] Đang khởi tạo SLMCore (NanoGPT)...{Style.RESET_ALL}")
        from core.engine.slm_core import SLMCore
        _slm_core = SLMCore()
    except Exception as e:
        print(f"{Fore.RED}[2/2] SLMCore FAILED: {e}{Style.RESET_ALL}")

    lp_ok = _local_perception is not None and getattr(_local_perception, 'sentiment_analyzer', None) is not None
    slm_ok = _slm_core is not None

    print(f"\n{Fore.GREEN}✅ GPU Service sẵn sàng!{Style.RESET_ALL}")
    print(f"   LocalPerception: {'✅ GPU' if lp_ok else '⚠️ Fallback (không có model)'}")
    print(f"   SLMCore:         {'✅ CUDA ready' if slm_ok else '⚠️ Không tải được'}")
    print(f"   Đang lắng nghe tại: http://127.0.0.1:8001\n")


# ─── Endpoints ────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Kiểm tra trạng thái service."""
    import torch
    return {
        "status": "ok",
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "gpu_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "vram_free_mb": round((torch.cuda.get_device_properties(0).total_memory - torch.cuda.memory_reserved(0)) / 1024**2, 1) if torch.cuda.is_available() else None,
        "local_perception_ready": _local_perception is not None and getattr(_local_perception, 'sentiment_analyzer', None) is not None,
        "slm_core_ready": _slm_core is not None and getattr(_slm_core, 'is_ready', False),
    }


@app.post("/analyze")
async def analyze_sentiment(req: AnalyzeRequest):
    """
    Phân tích cảm xúc văn bản bằng RoBERTa.
    Trả về: {valence, arousal, importance, raw_label, confidence}
    """
    if _local_perception is None:
        raise HTTPException(status_code=503, detail="LocalPerception chưa được tải")
    try:
        # Chạy blocking I/O trong thread riêng để không block event loop
        result = await asyncio.to_thread(_local_perception.analyze, req.text)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi phân tích: {str(e)}")


@app.post("/generate")
async def generate_thought(req: GenerateRequest):
    """
    Sinh ra 'luồng suy nghĩ' bằng SLMCore (NanoGPT).
    Trả về: {thought: str}
    """
    if _slm_core is None:
        raise HTTPException(status_code=503, detail="SLMCore chưa được tải")
    try:
        # generate_thought() là blocking — chạy trong thread pool
        thought = await asyncio.to_thread(
            _slm_core.generate_thought,  # ← Đúng tên method
            req.prompt,
            req.max_new_tokens
        )
        return {"thought": thought}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Lỗi sinh thought: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    print(f"{Fore.YELLOW}Khởi động Aura GPU Microservice tại port 8001...{Style.RESET_ALL}")
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
