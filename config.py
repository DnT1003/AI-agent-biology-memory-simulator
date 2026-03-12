import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    API_KEY = os.getenv("API_KEY", "")
    MODEL_NAME = os.getenv("MODEL_NAME", "gemini-3.0-flash")
    DEEP_MODEL_NAME = os.getenv("DEEP_MODEL_NAME", "gemini-3.1-pro")
    EMBEDDING_MODEL = "models/gemini-embedding-001"
    
    # HYBRID MODE CONFIG
    USE_HYBRID = True                # Cho phép tự động chuyển đổi Cloud/Local
    USE_LOCAL_ONLY = False           # Nếu True, ngắt hoàn toàn Gemini
    FORCE_LOCAL_COMMANDS = ["/local", "offline"] # Câu lệnh ép dùng local

    # GIOI HAN SINH HOC (BOUNDED MEMORY)
    FORGETTING_RATE = 0.05          # Toc do quen co ban
    RECONSOLIDATION_RATE = 0.1      # Muc do bien doi ky uc khi nho lai
    SEMANTIC_DRIFT_CHANCE = 0.3     # Ti le bop meo chi tiet phu khi nho lai

    # DUONG DAN ĐAU RA (OUTPUT PATHS) — Phase 15: tap trung, thay vi hardcode khap noi
    OUTPUT_DIR = os.getenv("AURA_OUTPUT_DIR", "outputs")
    CHROMA_DB_PATH = os.path.join(OUTPUT_DIR, "chroma_db")
    CHROMA_SERVER_HOST = os.getenv("CHROMA_SERVER_HOST", "127.0.0.1")
    CHROMA_SERVER_PORT = int(os.getenv("CHROMA_SERVER_PORT", "8000"))
    USE_CHROMA_SERVER = os.getenv("USE_CHROMA_SERVER", "True").lower() == "true"
    STM_FILE = os.path.join(OUTPUT_DIR, "short_term.json")
    MIND_STATE_FILE = os.path.join(OUTPUT_DIR, "mind_state.json")
    EGO_STATE_FILE = os.path.join(OUTPUT_DIR, "ego_state.json")

    # HANH VI TU CHU (AUTONOMOUS BEHAVIOR THRESHOLDS) — Phase 15: khong magic number
    # Thoi gian nhan roi toi thieu de ping (giay)
    IDLE_PING_THRESHOLD: int = int(os.getenv("AURA_PING_THRESHOLD", "60"))
    # Thoi gian nhan roi de tu di doc sach (giay)
    IDLE_READ_THRESHOLD: int = int(os.getenv("AURA_READ_THRESHOLD", str(15 * 60)))
    # Thoi gian nhan roi gay ra Separation Anxiety (giay)
    ANXIETY_THRESHOLD: int = int(os.getenv("AURA_ANXIETY_THRESHOLD", "600"))
    # SO ENTRY TOI DA TRONG SHORT-TERM BUFFER
    STM_MAX_ENTRIES: int = int(os.getenv("AURA_STM_MAX", "15"))

    # LOCAL LLM (OLLAMA)
    OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api")
    LOCAL_MODEL_NAME = os.getenv("LOCAL_MODEL_NAME", "phi3:mini")
    
    # CUSTOM SLM (Aura-Flash Core)
    SLM_DIR = os.path.join(os.path.dirname(__file__), "core", "engine", "nanogpt")
    SLM_ENABLED = True
    
    # AURA-FLASH LITE CONFIG (~425M Parameters - Sweet Spot for 6GB VRAM)
    SLM_D_MODEL = 1024
    SLM_N_LAYERS = 36    # Tăng độ sâu (Lý luận tốt hơn)
    SLM_N_HEADS = 16
    SLM_N_KV_HEADS = 4   # GQA
    SLM_N_EXPERTS = 0    # Đã tháo dỡ MoE
    SLM_TOP_K = 0

    # STORAGE LIMITS (Phase 9 - Sprint D)
    MAX_STORAGE_SIZE = 500 * 1024 * 1024  # 500MB
