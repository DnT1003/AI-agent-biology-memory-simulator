import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_KEY = os.getenv("API_KEY", "")
    MODEL_NAME = os.getenv("MODEL_NAME", "gemini-1.5-flash")
    DEEP_MODEL_NAME = os.getenv("DEEP_MODEL_NAME", "gemini-1.5-pro")
    EMBEDDING_MODEL = "models/gemini-embedding-001"

    # GIOI HAN SINH HOC (BOUNDED MEMORY)
    FORGETTING_RATE = 0.05          # Toc do quen co ban
    RECONSOLIDATION_RATE = 0.1      # Muc do bien doi ky uc khi nho lai
    SEMANTIC_DRIFT_CHANCE = 0.3     # Ti le bop meo chi tiet phu khi nho lai

    # DUONG DAN ĐAU RA (OUTPUT PATHS) — Phase 15: tap trung, thay vi hardcode khap noi
    OUTPUT_DIR = os.getenv("AURA_OUTPUT_DIR", "outputs")
    CHROMA_DB_PATH = os.path.join(OUTPUT_DIR, "chroma_db")
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

    # STORAGE LIMITS (Phase 9 - Sprint D)
    MAX_STORAGE_SIZE = 500 * 1024 * 1024  # 500MB
