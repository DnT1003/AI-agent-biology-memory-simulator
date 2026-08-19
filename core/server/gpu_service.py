"""Aura GPU microservice for native sentiment and SLM inference."""

import asyncio
import logging
import os
import sys

# Add project root to path when this module is executed as a script.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import secrets

from colorama import Fore, Style, init
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config import Config


init(autoreset=True)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Aura GPU Service",
    description="Native Torch/GPU inference service for the Aura brain process",
    version="1.1.0",
)


@app.middleware("http")
async def gpu_service_auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in ("/live", "/ready"):
        return await call_next(request)

    server_token = getattr(Config, "GPU_SERVICE_AUTH_TOKEN", None)
    if not server_token:
        return JSONResponse(
            status_code=503,
            content={"detail": "GPU service authentication unavailable"},
        )

    auth_header = request.headers.get("X-Aura-Internal-Token")
    if not auth_header or len(auth_header) > 512:
        return JSONResponse(
            status_code=403,
            content={"detail": "Forbidden"},
        )

    if not secrets.compare_digest(
        auth_header.encode("utf-8"),
        server_token.encode("utf-8"),
    ):
        return JSONResponse(
            status_code=403,
            content={"detail": "Forbidden"},
        )

    return await call_next(request)


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=16_000)
    max_new_tokens: int = Field(default=50, ge=1, le=512)


_local_perception = None
_slm_core = None
_perception_semaphore = asyncio.Semaphore(1)
_slm_semaphore = asyncio.Semaphore(1)


def _capability_status() -> dict:
    auth_configured = bool(getattr(Config, "GPU_SERVICE_AUTH_TOKEN", None))
    perception_ready = bool(
        _local_perception is not None
        and getattr(_local_perception, "is_ready", False)
    )
    slm_enabled = bool(Config.SLM_ENABLED)
    slm_ready = bool(
        slm_enabled
        and _slm_core is not None
        and getattr(_slm_core, "is_ready", False)
    )
    ready = auth_configured and perception_ready and (not slm_enabled or slm_ready)
    return {
        "status": "ready" if ready else "not_ready",
        "ready": ready,
        "capabilities": {
            "auth": {
                "configured": auth_configured,
            },
            "local_perception": {
                "enabled": True,
                "ready": perception_ready,
            },
            "slm": {
                "enabled": slm_enabled,
                "ready": slm_ready,
            },
        },
    }


@app.on_event("startup")
async def startup_event() -> None:
    global _local_perception, _slm_core

    print(f"\n{Fore.LIGHTCYAN_EX}{'=' * 50}")
    print("  Aura GPU Microservice - Khởi động")
    print(f"{'=' * 50}{Style.RESET_ALL}")

    try:
        print(
            f"{Fore.YELLOW}[1/2] Đang tải LocalPerception "
            f"(RoBERTa)...{Style.RESET_ALL}"
        )
        from core.local_perception import LocalPerception

        # Native mode is a hard boundary: failed model initialization can never
        # fall back to this service's own /analyze endpoint.
        _local_perception = LocalPerception(mode="native")
    except Exception:
        _local_perception = None
        logger.exception("LocalPerception failed during GPU service startup")

    _slm_core = None
    if Config.SLM_ENABLED:
        try:
            print(
                f"{Fore.YELLOW}[2/2] Đang khởi tạo SLMCore "
                f"(NanoGPT)...{Style.RESET_ALL}"
            )
            from core.engine.slm_core import SLMCore

            # Native mode contains no HTTP route, preventing /generate recursion.
            _slm_core = SLMCore(mode="native")
        except Exception:
            _slm_core = None
            logger.exception("SLMCore failed during GPU service startup")
    else:
        print(f"{Fore.YELLOW}[2/2] SLMCore đã tắt qua cấu hình.{Style.RESET_ALL}")

    status = _capability_status()
    color = Fore.GREEN if status["ready"] else Fore.RED
    print(f"\n{color}GPU Service status: {status['status']}{Style.RESET_ALL}")
    print("   Đang lắng nghe tại: http://127.0.0.1:8001\n")


@app.get("/live")
async def live() -> dict:
    """Liveness only: the process and event loop can answer requests."""
    return {"status": "alive"}


@app.get("/ready")
async def ready():
    """Readiness for all capabilities currently enabled by configuration."""
    status = _capability_status()
    if not status["ready"]:
        return JSONResponse(status_code=503, content=status)
    return status


@app.get("/health")
async def health() -> dict:
    """Detailed diagnostic status; use /live and /ready for orchestration."""
    status = _capability_status()
    torch_details = {
        "torch_version": None,
        "cuda_available": False,
        "gpu_name": None,
        "vram_free_mb": None,
    }
    try:
        import torch  # type: ignore

        cuda_available = bool(torch.cuda.is_available())
        torch_details = {
            "torch_version": torch.__version__,
            "cuda_available": cuda_available,
            "gpu_name": torch.cuda.get_device_name(0) if cuda_available else None,
            "vram_free_mb": round(
                (
                    torch.cuda.get_device_properties(0).total_memory
                    - torch.cuda.memory_reserved(0)
                )
                / 1024**2,
                1,
            )
            if cuda_available
            else None,
        }
    except Exception:
        logger.debug("Torch diagnostics unavailable", exc_info=True)

    return {**status, **torch_details}


@app.post("/analyze")
async def analyze_sentiment(req: AnalyzeRequest):
    if _local_perception is None or not getattr(
        _local_perception, "is_ready", False
    ):
        raise HTTPException(status_code=503, detail="Sentiment capability is not ready")

    try:
        async with _perception_semaphore:
            return await asyncio.to_thread(_local_perception.analyze, req.text)
    except Exception as exc:
        logger.exception("Native sentiment inference failed")
        raise HTTPException(
            status_code=500, detail="Sentiment inference failed"
        ) from exc


@app.post("/generate")
async def generate_thought(req: GenerateRequest):
    if not Config.SLM_ENABLED:
        raise HTTPException(status_code=503, detail="SLM capability is disabled")
    if _slm_core is None or not getattr(_slm_core, "is_ready", False):
        raise HTTPException(status_code=503, detail="SLM capability is not ready")

    try:
        async with _slm_semaphore:
            thought = await asyncio.to_thread(
                _slm_core.generate_thought,
                req.prompt,
                req.max_new_tokens,
            )
        return {"thought": thought}
    except Exception as exc:
        logger.exception("Native SLM inference failed")
        raise HTTPException(status_code=500, detail="SLM inference failed") from exc


if __name__ == "__main__":
    import uvicorn

    print(
        f"{Fore.YELLOW}Khởi động Aura GPU Microservice tại port 8001..."
        f"{Style.RESET_ALL}"
    )
    uvicorn.run(app, host="127.0.0.1", port=8001, log_level="warning")
