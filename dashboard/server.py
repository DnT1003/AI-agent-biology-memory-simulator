from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
import os
import uvicorn
import sys
import json
import secrets
from functools import lru_cache
from pathlib import Path

# Fix paths
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from config import Config
from core.chat_spool import (
    ChatSpoolError,
    InvalidEnvelope,
    InvalidReceipt,
    PayloadTooLarge,
    QueueFull,
    create_configured_chat_spools,
    create_configured_proactive_spool,
)
from core.interaction_policy import is_explicit_private_input
from core.logger import get_logger

try:
    from core.settings_manager import settings_manager
except ImportError:
    settings_manager = None
    print("Warning: settings_manager not found")

app = FastAPI()
logger = get_logger("dashboard")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_FILE = PROJECT_ROOT / "dashboard" / "index.html"


@app.middleware("http")
async def dashboard_auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/api/") or path == "/api":
        server_token = getattr(Config, "DASHBOARD_AUTH_TOKEN", None)
        if not server_token:
            return JSONResponse(
                status_code=503,
                content={"detail": "Dashboard authentication unavailable"},
            )
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        if len(auth_header) > 512:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        parts = auth_header.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = parts[1]
        if not secrets.compare_digest(
            token.encode("utf-8"),
            server_token.encode("utf-8"),
        ):
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
                headers={"WWW-Authenticate": "Bearer"},
            )
    return await call_next(request)


@lru_cache(maxsize=1)
def _get_chat_spools():
    return create_configured_chat_spools()


@lru_cache(maxsize=1)
def _get_proactive_spool():
    return create_configured_proactive_spool()


@lru_cache(maxsize=1)
def _get_event_journal():
    """Create a dashboard writer lazily; observability never gates delivery."""

    if not getattr(Config, "EVENT_JOURNAL_ENABLED", False):
        return None
    try:
        from core.event_journal import JournalContext, RotatingEventJournal

        journal = RotatingEventJournal(
            Config.EVENT_JOURNAL_DIR,
            max_events=Config.EVENT_JOURNAL_MAX_EVENTS_PER_RUN,
            max_event_bytes=Config.EVENT_JOURNAL_MAX_EVENT_BYTES,
            lock_timeout_seconds=Config.EVENT_JOURNAL_LOCK_TIMEOUT_SECONDS,
            auth_key=Config.EVENT_JOURNAL_AUTH_KEY,
        )
        journal.append_safe(
            "journal.run_started",
            {"format": "immutable-json-v1"},
            context=JournalContext(source="dashboard"),
            outcome="started",
        )
        return journal
    except Exception:
        logger.warning("Dashboard event journal is unavailable", exc_info=True)
        return None


def _record_delivery_acks(receipts):
    try:
        journal = _get_event_journal()
        if journal is None:
            return
        from core.event_journal import JournalContext

        for receipt in receipts:
            # Receipt validation happened inside ChatSpool. Persist only its
            # public message ID prefix, never lease time or claim token.
            message_id = receipt.split(".", 1)[0]
            journal.append_safe(
                "delivery.acked",
                {"transport": "web", "message_id": message_id},
                context=JournalContext(
                    correlation_id=message_id,
                    trace_id=message_id,
                    request_id=message_id,
                    source="dashboard",
                ),
                outcome="acked",
            )
    except Exception:
        # ACK already mutated durable spool state. Observability must never
        # turn that successful protocol step into an HTTP failure.
        logger.warning("Unable to record dashboard delivery ACK", exc_info=True)

@app.get("/")
def read_root():
    return FileResponse(DASHBOARD_FILE)

@app.get("/live")
def live():
    return {"status": "alive"}

@app.get("/ready")
def ready():
    server_token = getattr(Config, "DASHBOARD_AUTH_TOKEN", None)
    if not server_token:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "detail": "Dashboard authentication unavailable"},
        )
    return {"status": "ready"}

@app.get("/api/auth/check")
def check_auth():
    return {"authenticated": True}

@app.get("/api/state")
def get_state():
    state_file = Config.MIND_STATE_FILE
    if os.path.exists(state_file):
        return FileResponse(state_file)
    return {"error": "No state found"}

@app.get("/api/settings")
def get_settings():
    if not settings_manager:
        raise HTTPException(status_code=503, detail="Settings manager unavailable")
    settings_manager.load()
    return settings_manager.get_all()

@app.post("/api/settings")
async def update_settings(request: Request):
    if not settings_manager:
        raise HTTPException(status_code=503, detail="Settings manager unavailable")
    try:
        data = await request.json()
        settings_manager.update_all(data)
        return {"status": "success", "settings": settings_manager.get_all()}
    except (TypeError, ValueError):
        # Do not reflect rejected fields or values: the payload may contain secrets.
        raise HTTPException(status_code=400, detail="Invalid public settings payload")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Unable to update settings")

@app.post("/api/chat", status_code=202)
async def send_chat(request: Request):
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    if not isinstance(data, dict) or not isinstance(data.get("message"), str):
        raise HTTPException(status_code=400, detail="message must be a string")

    message = data["message"].strip()
    # This transport is deliberately durable and shared across processes. A
    # private/ephemeral request cannot honestly use it without persisting raw
    # content, so reject before any filesystem write.
    if is_explicit_private_input(message, Config.FORCE_LOCAL_COMMANDS):
        raise HTTPException(
            status_code=409,
            detail="Private local commands require a volatile CLI transport",
        )

    try:
        requests, _ = _get_chat_spools()
        published = requests.enqueue_request(message)
        return {"status": "queued", "id": published.message_id}
    except PayloadTooLarge as exc:
        raise HTTPException(status_code=413, detail="Chat message is too large") from exc
    except InvalidEnvelope as exc:
        raise HTTPException(status_code=400, detail="Chat message is empty or invalid") from exc
    except QueueFull as exc:
        raise HTTPException(status_code=429, detail="Chat queue is full") from exc
    except ChatSpoolError as exc:
        raise HTTPException(status_code=503, detail="Chat queue unavailable") from exc

def _claim_proactive():
    """Messages Aura started herself; any open dashboard may deliver them."""
    spool = _get_proactive_spool()
    spool.recover_stale()
    spool.expire_stale_deliveries()
    return spool.claim(limit=Config.CHAT_DELIVERY_BATCH_SIZE)


def _claim_view(claim):
    return {
        "id": claim.envelope.id,
        "role": claim.envelope.role,
        "content": claim.envelope.content,
        "receipt": claim.receipt,
    }


@app.get("/api/chat")
def get_chat(request: Request):
    message_ids = list(dict.fromkeys(request.query_params.getlist("id")))
    if len(message_ids) > 100:
        raise HTTPException(status_code=400, detail="Too many chat ids")
    proactive = []
    if request.query_params.get("proactive") == "1":
        try:
            proactive = [_claim_view(claim) for claim in _claim_proactive()]
        except ChatSpoolError as exc:
            raise HTTPException(status_code=503, detail="Chat queue unavailable") from exc
    if not message_ids:
        return {"messages": proactive, "terminal": []}
    try:
        requests, responses = _get_chat_spools()
        responses.recover_stale()
        responses.expire_stale_deliveries()
        responses.promote_staged(limit=Config.CHAT_DELIVERY_BATCH_SIZE)
        claims = responses.claim(
            limit=Config.CHAT_DELIVERY_BATCH_SIZE,
            message_ids=message_ids,
        )
        claimed_ids = {claim.envelope.id for claim in claims}
        terminal = []
        for message_id in message_ids:
            if message_id in claimed_ids:
                continue
            # Read the request first. Producers make the response durable
            # before terminalizing the request, so a later response snapshot
            # can always override an older request snapshot without taking two
            # cross-spool locks at once.
            request_state = requests.message_state(message_id)
            response_state = responses.message_state(message_id)
            if response_state == "completed":
                terminal.append({"id": message_id, "state": "completed"})
            elif response_state == "dead":
                terminal.append({"id": message_id, "state": "failed"})
            elif response_state is None:
                if request_state == "dead":
                    terminal.append({"id": message_id, "state": "failed"})
                elif request_state is None and responses.retention_expired(
                    message_id
                ):
                    terminal.append({"id": message_id, "state": "expired"})
    except InvalidEnvelope as exc:
        raise HTTPException(status_code=400, detail="Invalid chat id") from exc
    except ChatSpoolError as exc:
        raise HTTPException(status_code=503, detail="Chat queue unavailable") from exc
    return {
        "messages": proactive + [_claim_view(claim) for claim in claims],
        "terminal": terminal,
    }


@app.post("/api/chat/ack")
async def acknowledge_chat(request: Request):
    try:
        data = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    receipts = data.get("receipts") if isinstance(data, dict) else None
    if (
        not isinstance(receipts, list)
        or len(receipts) > Config.CHAT_DELIVERY_BATCH_SIZE
        or any(not isinstance(receipt, str) for receipt in receipts)
    ):
        raise HTTPException(status_code=400, detail="Invalid receipt list")

    try:
        _, responses = _get_chat_spools()
        acked = []
        for receipt in receipts:
            # A receipt belongs to either a reply or a proactive message; the
            # wrong spool simply has no such claim.
            if responses.ack(receipt) or _get_proactive_spool().ack(receipt):
                acked.append(receipt)
        _record_delivery_acks(acked)
    except InvalidReceipt as exc:
        raise HTTPException(status_code=400, detail="Invalid chat receipt") from exc
    except ChatSpoolError as exc:
        raise HTTPException(status_code=503, detail="Chat queue unavailable") from exc
    return {"acked": acked, "missing": len(receipts) - len(acked)}

def run_dashboard():
    uvicorn.run(app, host="127.0.0.1", port=8050)

if __name__ == "__main__":
    run_dashboard()
