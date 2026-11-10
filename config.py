import math
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


_CANONICAL_CONFIG_ATTRIBUTES = frozenset(
    {
        "RUNTIME_PATHS",
        "DATA_DIR",
        "CONTROL_DB_PATH",
        "WRITER_LEASE_PATH",
    }
)


def _canonical_runtime_paths(base_dir: Path, env: dict[str, str], legacy_cwd: Path):
    """Load pure canonical paths only in images that package the runtime module.

    The dashboard image intentionally retains its released, minimal core payload.
    It imports ``Config`` for legacy dashboard settings but never consumes the
    canonical API.  Do not hide failures from a present runtime module: only
    its own absence is translated into a clear boundary error.
    """

    try:
        from core.runtime_paths import RuntimePaths
    except ModuleNotFoundError as error:
        if error.name != "core.runtime_paths":
            raise
        raise RuntimeError(
            "Canonical runtime paths are unavailable in this minimal image."
        ) from error

    return RuntimePaths.from_env(base_dir=base_dir, env=env, cwd=legacy_cwd)


def _canonical_runtime_value(paths, name: str):
    if name == "RUNTIME_PATHS":
        return paths
    return os.fspath(
        getattr(
            paths,
            {
                "DATA_DIR": "data_dir",
                "CONTROL_DB_PATH": "control_db_path",
                "WRITER_LEASE_PATH": "writer_lease_path",
            }[name],
        )
    )


def _legacy_artifact_manifest(base_dir: Path, env: dict[str, str], legacy_cwd: Path):
    """Perform legacy inspection only for the explicit manifest property."""

    paths = _canonical_runtime_paths(base_dir, env, legacy_cwd)
    try:
        from core.runtime_paths import discover_legacy_artifacts
    except ModuleNotFoundError as error:
        if error.name != "core.runtime_paths":
            raise
        raise RuntimeError(
            "Canonical runtime paths are unavailable in this minimal image."
        ) from error
    return discover_legacy_artifacts(paths, env)


class _ConfigMeta(type):
    """Lazily bind canonical paths without changing legacy Config projections."""

    def __getattribute__(cls, name: str):
        if name in _CANONICAL_CONFIG_ATTRIBUTES:
            base_dir = type.__getattribute__(cls, "_CANONICAL_BASE_DIR")
            env = type.__getattribute__(cls, "_CANONICAL_ENV")
            legacy_cwd = type.__getattribute__(cls, "_CANONICAL_CWD")
            paths = _canonical_runtime_paths(base_dir, env, legacy_cwd)
            return _canonical_runtime_value(paths, name)
        if name == "LEGACY_ARTIFACT_MANIFEST":
            base_dir = type.__getattribute__(cls, "_CANONICAL_BASE_DIR")
            env = type.__getattribute__(cls, "_CANONICAL_ENV")
            legacy_cwd = type.__getattribute__(cls, "_CANONICAL_CWD")
            return _legacy_artifact_manifest(base_dir, env, legacy_cwd)
        return type.__getattribute__(cls, name)


def _bounded_env_int(name: str, default: int, minimum: int) -> int:
    """Parse optional operational limits without making module import fatal."""

    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    return max(minimum, value)


def _bounded_env_float(name: str, default: float, minimum: float) -> float:
    """Return a finite optional timeout, falling back on invalid input."""

    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    if not math.isfinite(value):
        return default
    return max(minimum, value)


def _optional_discord_snowflake(value) -> str | None:
    """Return a canonical Discord snowflake or ``None`` for unsafe input."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        number = value
    elif isinstance(value, str):
        candidate = value.strip()
        if not candidate or not candidate.isascii() or not candidate.isdigit():
            return None
        try:
            number = int(candidate, 10)
        except (TypeError, ValueError, OverflowError):
            return None
    else:
        return None
    if number <= 0 or number > (2**64 - 1):
        return None
    return str(number)


def _optional_service_auth_token(value) -> str | None:
    """Return a validated service bearer/header token or ``None`` for unsafe input.

    Valid tokens must be ASCII strings of length 32..256 composed of
    token68 / base64url-safe characters with no whitespace or control characters.
    """
    if not isinstance(value, str):
        return None
    if len(value) < 32 or len(value) > 256:
        return None
    if not value.isascii():
        return None
    allowed = set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.~+/="
    )
    if not set(value).issubset(allowed):
        return None
    return value


def _optional_dashboard_auth_token(value) -> str | None:
    """Backwards-compatible wrapper for dashboard token validation."""
    return _optional_service_auth_token(value)


class Config(metaclass=_ConfigMeta):
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    _CANONICAL_BASE_DIR = Path(BASE_DIR)
    # Capture the post-dotenv import environment so a Config load has one
    # deterministic canonical view, while the legacy compatibility fields
    # retain their released import-time behaviour below.
    _CANONICAL_ENV = dict(os.environ)
    _CANONICAL_CWD = Path.cwd()
    # GEMINI_API_KEY is the documented name. Keep API_KEY as a compatibility
    # fallback for existing local deployments and Kubernetes secrets.
    API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("API_KEY", "")
    MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3-flash-preview")
    # Any OpenAI-compatible chat endpoint for provider "openai": OpenAI itself,
    # OpenRouter, Groq, or a local Ollama/LM Studio server
    # (e.g. http://localhost:11434/v1). Local servers need no API key.
    OPENAI_BASE_URL = (
        os.getenv("AURA_OPENAI_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1"
    ).rstrip("/")
    OPENAI_MODEL = os.getenv("AURA_OPENAI_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-4o-mini"
    # How Aura refers to herself and to her owner, kept consistent in every reply.
    SELF_PRONOUN = os.getenv("AURA_SELF_PRONOUN", "em").strip() or "em"
    OWNER_PRONOUN = os.getenv("AURA_OWNER_PRONOUN", "anh").strip() or "anh"
    DEEP_MODEL_NAME = os.getenv("DEEP_MODEL_NAME", "gemini-3.1-pro-preview")
    EMBEDDING_MODEL = "models/gemini-embedding-001"
    
    # HYBRID MODE CONFIG
    USE_HYBRID = os.getenv("AURA_USE_HYBRID", "true").lower() == "true"
    USE_LOCAL_ONLY = os.getenv("AURA_USE_LOCAL_ONLY", "false").lower() == "true"
    FORCE_LOCAL_COMMANDS = ["/local", "offline"] # Câu lệnh ép dùng local

    # Discord inbound is single-owner and fail-closed. Keep the identifier as
    # a canonical string to avoid accidental use of mutable display names.
    _DISCORD_OWNER_RAW = os.getenv("AURA_DISCORD_OWNER_USER_ID")
    if _DISCORD_OWNER_RAW is None:
        _DISCORD_OWNER_RAW = os.getenv("DISCORD_OWNER_USER_ID")
    DISCORD_OWNER_USER_ID: str | None = _optional_discord_snowflake(
        _DISCORD_OWNER_RAW
    )
    del _DISCORD_OWNER_RAW

    # Dashboard Bearer Authentication (M4.1a) — fail-closed service token
    _DASHBOARD_AUTH_TOKEN_RAW = os.getenv("AURA_DASHBOARD_AUTH_TOKEN")
    DASHBOARD_AUTH_TOKEN: str | None = _optional_dashboard_auth_token(
        _DASHBOARD_AUTH_TOKEN_RAW
    )
    del _DASHBOARD_AUTH_TOKEN_RAW

    # GPU Microservice Authentication (M4.1b) — fail-closed service token
    _GPU_SERVICE_AUTH_TOKEN_RAW = os.getenv("AURA_GPU_SERVICE_AUTH_TOKEN")
    GPU_SERVICE_AUTH_TOKEN: str | None = _optional_service_auth_token(
        _GPU_SERVICE_AUTH_TOKEN_RAW
    )
    del _GPU_SERVICE_AUTH_TOKEN_RAW

    # GIOI HAN SINH HOC (BOUNDED MEMORY)
    FORGETTING_RATE = 0.05          # Toc do quen co ban
    RECONSOLIDATION_RATE = 0.1      # Muc do bien doi ky uc khi nho lai
    SEMANTIC_DRIFT_CHANCE = 0.3     # Ti le bop meo chi tiet phu khi nho lai

    # Compatibility consumers remain on the released layout until an explicit
    # migration/promotion switches their authority to the canonical paths.
    OUTPUT_DIR = os.getenv("AURA_OUTPUT_DIR", "outputs")
    _OUTPUT_DIR_ABSOLUTE = (
        OUTPUT_DIR
        if os.path.isabs(OUTPUT_DIR)
        else os.path.join(BASE_DIR, OUTPUT_DIR)
    )
    MEMORY_WRITER_LEASE_FILE = os.path.join(
        os.path.abspath(_OUTPUT_DIR_ABSOLUTE),
        ".aura-memory-writer.lock",
    )
    OPERATION_LEDGER_FILE = os.path.join(
        os.path.abspath(_OUTPUT_DIR_ABSOLUTE),
        "operation_ledger.sqlite3",
    )
    # PATH is retained as a descriptive alias for callers that deal in DB
    # paths rather than files.  Both names deliberately identify one DB.
    OPERATION_LEDGER_PATH = OPERATION_LEDGER_FILE
    del _OUTPUT_DIR_ABSOLUTE
    CHROMA_DB_PATH = os.path.join(OUTPUT_DIR, "chroma_db")
    MAX_STORAGE_SIZE = int(os.getenv("AURA_MAX_STORAGE_MB", "1024")) * 1024 * 1024
    CHROMA_SERVER_HOST = os.getenv("CHROMA_SERVER_HOST", "127.0.0.1")
    CHROMA_SERVER_PORT = int(os.getenv("CHROMA_SERVER_PORT", "8000"))
    USE_CHROMA_SERVER = os.getenv("USE_CHROMA_SERVER", "True").lower() == "true"
    GPU_SERVICE_URL = os.getenv("GPU_SERVICE_URL", "http://127.0.0.1:8001")
    # Mo hinh cam xuc cua LocalPerception (GPU service, mode native).
    # XLM-R multilingual chuyen giao tot sang tieng Viet (19/20 cau thu nghiem);
    # 5CD-AI/Vietnamese-Sentiment-visobert khong nap dung tokenizer voi
    # transformers 5.x va dao nguoc cuc tinh nhieu cau tieu cuc.
    LOCAL_PERCEPTION_MODEL = os.getenv(
        "AURA_LOCAL_PERCEPTION_MODEL",
        "cardiffnlp/twitter-xlm-roberta-base-sentiment-multilingual",
    )
    STM_FILE = os.path.join(OUTPUT_DIR, "short_term.json")
    MIND_STATE_FILE = os.path.join(OUTPUT_DIR, "mind_state.json")
    EGO_STATE_FILE = os.path.join(OUTPUT_DIR, "ego_state.json")
    SKILLS_FILE = os.path.join(OUTPUT_DIR, "skills.json")
    # Same OUTPUT_DIR layout as every other consumer (honours AURA_OUTPUT_DIR);
    # runtime_paths.discover_legacy_artifacts() already lists these candidates.
    VALUES_FILE = os.path.join(OUTPUT_DIR, "values.json")
    WORLD_GRAPH_FILE = os.path.join(OUTPUT_DIR, "world_graph.json")
    # Owner events to follow up on and Aura's own promises (P1.2).
    PROSPECTIVE_MEMORY_FILE = os.path.join(OUTPUT_DIR, "prospective_memory.json")
    # Moments Aura and the owner laughed at together (P3.3).
    INSIDE_JOKES_FILE = os.path.join(OUTPUT_DIR, "inside_jokes.json")
    # Leave non-urgent messages waiting while Aura sleeps instead of waking
    # her; she answers when she wakes up (urgent ones still wake her).
    DEFER_REPLIES_WHILE_ASLEEP: bool = os.getenv(
        "AURA_DEFER_REPLIES_WHILE_ASLEEP", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    # Hang doi du lieu huan luyen SLM tu ContextCompressor (Entropy Wall).
    # SLMTrainer gom va xoa file nay moi lan ngu; tran thi ngung ghi them.
    SLM_FINETUNE_QUEUE_FILE = os.path.join(OUTPUT_DIR, "slm_finetune_data.txt")
    SLM_FINETUNE_QUEUE_MAX_BYTES: int = int(
        os.getenv("AURA_SLM_FINETUNE_QUEUE_MAX_BYTES", str(2 * 1024 * 1024))
    )

    # DOC SACH THAT (components/book_sources.py). Aura khong bao gio doc noi
    # dung do LLM tu bia. Thu tu uu tien nguon, cach nhau bang dau phay.
    READER_SOURCES: tuple = tuple(
        name.strip()
        for name in os.getenv("AURA_READER_SOURCES", "local,wikisource,gutenberg").split(",")
        if name.strip()
    )
    # docln.net: tat mac dinh (vuot Cloudflare + ban dich fan co ban quyen).
    READER_ENABLE_DOCLN: bool = os.getenv("AURA_READER_ENABLE_DOCLN", "false").lower() == "true"
    # Thu muc ebook mien phi (.txt/.epub) do chu nhan tu bo vao.
    READER_LIBRARY_DIR = os.getenv("AURA_READER_LIBRARY_DIR", os.path.join(OUTPUT_DIR, "library"))
    READER_PROGRESS_FILE = os.path.join(OUTPUT_DIR, "reader_progress.json")
    # Moi phien doc ~6000 ky tu (~20 phut doc cua nguoi).
    READER_SEGMENT_CHARS: int = int(os.getenv("AURA_READER_SEGMENT_CHARS", "6000"))

    # HANH VI TU CHU (AUTONOMOUS BEHAVIOR THRESHOLDS) — Phase 15: khong magic number
    # Thoi gian nhan roi toi thieu de ping (giay)
    IDLE_PING_THRESHOLD: int = int(os.getenv("AURA_PING_THRESHOLD", "60"))
    # Thoi gian nhan roi de tu di doc sach (giay)
    IDLE_READ_THRESHOLD: int = int(os.getenv("AURA_READ_THRESHOLD", str(15 * 60)))
    # Thoi gian vang mat gay Separation Anxiety lan 1 (giay); lan 2 o 4x.
    # Moi moc chi kich hoat mot lan cho moi dot vang mat.
    ANXIETY_THRESHOLD: int = int(os.getenv("AURA_ANXIETY_THRESHOLD", str(6 * 3600)))

    # NHIP HANH VI TU CHU "GIONG NGUOI" (core/engine/autonomous_pacing.py).
    # Moi quyet dinh la xac suat theo thoi gian thuc, khong theo so vong lap.
    # Ky uc tu troi day: trung binh 45 phut/lan khi binh thuong (stress cao,
    # mood thap lam nhanh toi 4x), cach nhau toi thieu 5 phut.
    MIND_WANDER_MEAN_MINUTES: float = float(os.getenv("AURA_MIND_WANDER_MEAN_MINUTES", "45"))
    MIND_WANDER_MIN_GAP_MINUTES: float = float(os.getenv("AURA_MIND_WANDER_MIN_GAP_MINUTES", "5"))
    # Nhan tin chu dong: trung binh 3h/lan o social_need=0.6 (45 phut o 1.0),
    # cach nhau toi thieu 45 phut, gap doi sau moi tin chua duoc tra loi
    # (toi da 8h), dung han sau 3 tin chua tra loi cho toi khi User quay lai.
    PING_MEAN_HOURS: float = float(os.getenv("AURA_PING_MEAN_HOURS", "3"))
    PING_MIN_GAP_MINUTES: float = float(os.getenv("AURA_PING_MIN_GAP_MINUTES", "45"))
    PING_MAX_UNANSWERED: int = int(os.getenv("AURA_PING_MAX_UNANSWERED", "3"))
    PING_BACKOFF_CAP_HOURS: float = float(os.getenv("AURA_PING_BACKOFF_CAP_HOURS", "8"))
    # Doc sach tu phat: trung binh 2h/lan o curiosity=0.7 (30 phut o 1.0),
    # cach nhau toi thieu 30 phut.
    READING_MEAN_HOURS: float = float(os.getenv("AURA_READING_MEAN_HOURS", "2"))
    READING_MIN_GAP_MINUTES: float = float(os.getenv("AURA_READING_MIN_GAP_MINUTES", "30"))
    # Gio yen lang (khong nhan tin, khong lo au): "bat_dau-ket_thuc" theo gio.
    QUIET_HOURS: tuple = tuple(
        int(part) for part in os.getenv("AURA_QUIET_HOURS", "23-7").split("-", 1)
    )
    # SO ENTRY TOI DA TRONG SHORT-TERM BUFFER
    STM_MAX_ENTRIES: int = int(os.getenv("AURA_STM_MAX", "15"))
    # Nhịp sinh học chạy độc lập với vòng poll sự kiện (giây).
    COGNITIVE_TICK_INTERVAL_SECONDS: float = float(
        os.getenv("AURA_COGNITIVE_TICK_INTERVAL_SECONDS", "30")
    )
    # Bao tri ky uc (decay mau + GC) doc toan bo kho ky uc. Decay da tinh
    # theo dong ho rieng cua tung ky uc nen chay thua hon khong mat gi.
    MEMORY_MAINTENANCE_INTERVAL_SECONDS: float = float(
        os.getenv("AURA_MEMORY_MAINTENANCE_INTERVAL_SECONDS", "600")
    )

    # M0 RUNTIME: every user-facing request is serialized through one actor.
    # Queue capacity is pending work only; the active request is separate.
    INTERACTION_QUEUE_MAX: int = max(
        1, int(os.getenv("AURA_INTERACTION_QUEUE_MAX", "16"))
    )
    INTERACTION_STATE_WAIT_SECONDS: float = max(
        0.1, float(os.getenv("AURA_INTERACTION_STATE_WAIT_SECONDS", "30"))
    )
    INTERACTION_SHUTDOWN_TIMEOUT_SECONDS: float = max(
        0.1, float(os.getenv("AURA_INTERACTION_SHUTDOWN_TIMEOUT_SECONDS", "5"))
    )
    AUTONOMOUS_SHUTDOWN_TIMEOUT_SECONDS: float = max(
        0.1, float(os.getenv("AURA_AUTONOMOUS_SHUTDOWN_TIMEOUT_SECONDS", "5"))
    )

    # Durable dashboard <-> brain hand-off. This path is absolute so the two
    # processes agree even when launched with different working directories.
    _CHAT_SPOOL_OVERRIDE = os.getenv("AURA_CHAT_SPOOL_DIR", "").strip()
    CHAT_SPOOL_DIR: str = os.path.abspath(
        _CHAT_SPOOL_OVERRIDE
        or os.path.join(BASE_DIR, OUTPUT_DIR, "chat_spool")
    )
    # Messages Aura starts herself (pings, voiced rumination) for the dashboard.
    CHAT_PROACTIVE_SPOOL_DIR: str = os.path.join(CHAT_SPOOL_DIR, "proactive")
    CHAT_REQUEST_MAX_BYTES: int = max(
        256, int(os.getenv("AURA_CHAT_REQUEST_MAX_BYTES", str(16 * 1024)))
    )
    CHAT_RESPONSE_MAX_BYTES: int = max(
        256, int(os.getenv("AURA_CHAT_RESPONSE_MAX_BYTES", str(64 * 1024)))
    )
    CHAT_SPOOL_MAX_MESSAGES: int = max(
        1, int(os.getenv("AURA_CHAT_SPOOL_MAX_MESSAGES", "1000"))
    )
    CHAT_SPOOL_LEASE_SECONDS: float = max(
        1.0, float(os.getenv("AURA_CHAT_SPOOL_LEASE_SECONDS", "300"))
    )
    CHAT_RESPONSE_RETENTION_SECONDS: float = max(
        60.0,
        float(os.getenv("AURA_CHAT_RESPONSE_RETENTION_SECONDS", "86400")),
    )
    CHAT_DELIVERY_BATCH_SIZE: int = min(
        100, max(1, int(os.getenv("AURA_CHAT_DELIVERY_BATCH_SIZE", "50")))
    )

    # M1 EVENT JOURNAL: immutable, privacy-aware runtime traces. Keep the
    # directory absolute so replay and the brain agree across working dirs.
    EVENT_JOURNAL_ENABLED: bool = (
        os.getenv("AURA_EVENT_JOURNAL_ENABLED", "true").lower() == "true"
    )
    _EVENT_JOURNAL_OVERRIDE = os.getenv("AURA_EVENT_JOURNAL_DIR", "").strip()
    EVENT_JOURNAL_DIR: str = os.path.abspath(
        _EVENT_JOURNAL_OVERRIDE
        or os.path.join(BASE_DIR, OUTPUT_DIR, "event_journal")
    )
    EVENT_JOURNAL_MAX_EVENTS: int = _bounded_env_int(
        "AURA_EVENT_JOURNAL_MAX_EVENTS", 100_000, 1
    )
    EVENT_JOURNAL_MAX_EVENT_BYTES: int = _bounded_env_int(
        "AURA_EVENT_JOURNAL_MAX_EVENT_BYTES", 64 * 1024, 1024
    )
    EVENT_JOURNAL_LOCK_TIMEOUT_SECONDS: float = _bounded_env_float(
        "AURA_EVENT_JOURNAL_LOCK_TIMEOUT_SECONDS", 1.0, 0.05
    )
    _EVENT_JOURNAL_HMAC_TEXT = os.getenv("AURA_EVENT_JOURNAL_HMAC_KEY", "")
    EVENT_JOURNAL_HMAC_KEY: bytes | None = (
        _EVENT_JOURNAL_HMAC_TEXT.encode("utf-8")
        if _EVENT_JOURNAL_HMAC_TEXT
        else None
    )
    # Compatibility names used by transport-side journal hooks.
    EVENT_JOURNAL_MAX_EVENTS_PER_RUN = EVENT_JOURNAL_MAX_EVENTS
    EVENT_JOURNAL_AUTH_KEY = EVENT_JOURNAL_HMAC_KEY
    del _EVENT_JOURNAL_HMAC_TEXT

    # LOCAL LLM (GEMMA 4 E4B — Unsloth, 4-bit, offline)
    LOCAL_LLM_ENABLED = os.getenv("AURA_LOCAL_LLM_ENABLED", "true").lower() == "true"
    GEMMA_MODEL_PATH = os.getenv("GEMMA_MODEL_PATH", r"d:\python\PythonProject19\Gemma4_E4B")
    
    # CUSTOM SLM (Aura-Flash Core)
    SLM_DIR = os.getenv(
        "SLM_CODE_DIR",
        os.path.join(os.path.dirname(__file__), "core", "engine", "nanogpt"),
    )
    # Tách mã NanoGPT (nằm trong image) khỏi model assets (có thể mount bằng PVC).
    SLM_MODEL_DIR = os.getenv("SLM_MODEL_DIR", SLM_DIR)
    SLM_MODEL_PATH = os.getenv(
        "SLM_MODEL_PATH", os.path.join(SLM_MODEL_DIR, "aura_flash_v5.pth")
    )
    SLM_ENABLED = os.getenv("AURA_SLM_ENABLED", "false").lower() == "true"
    SLM_TRAINING_ENABLED = (
        os.getenv("AURA_SLM_TRAINING_ENABLED", "false").lower() == "true"
    )
    
    # AURA-FLASH LITE CONFIG (~425M Parameters - Sweet Spot for 6GB VRAM)
    SLM_D_MODEL = 1024
    SLM_N_LAYERS = 36    # Tăng độ sâu (Lý luận tốt hơn)
    SLM_N_HEADS = 16
    SLM_N_KV_HEADS = 4   # GQA
    SLM_N_EXPERTS = 0    # Đã tháo dỡ MoE
    SLM_TOP_K = 0

    # ── SECURITY: Dynamic Skills Self-Evolution ──────────────────────────────
    # False = tắt hoàn toàn workshop và loader kỹ năng động.
    # True  = loader chỉ chạy file đã được operator duyệt trong core/dynamic_skills;
    #         code do LLM sinh chỉ được ghi vào quarantine, không tự kích hoạt.
    ALLOW_DYNAMIC_SKILLS: bool = os.getenv("AURA_ALLOW_DYNAMIC_SKILLS", "false").lower() == "true"

    # ── STABILITY: ChromaDB mode (chỉ 1 trong 2, không được dùng đồng thời) ──
    # "rest"     = dùng REST server (K8s, Docker) — USE_CHROMA_SERVER phải True
    # "embedded" = dùng embedded PersistentClient (local dev, non-K8s)
    # Nếu để trống, tự suy ra từ USE_CHROMA_SERVER và Python version
    CHROMA_MODE: str = os.getenv("CHROMA_MODE", "")  # "" = auto-detect
