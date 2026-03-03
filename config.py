import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    API_KEY = os.getenv("API_KEY", "")
    MODEL_NAME = os.getenv("MODEL_NAME", "gemini-1.5-flash")
    DEEP_MODEL_NAME = os.getenv("DEEP_MODEL_NAME", "gemini-1.5-pro")
    EMBEDDING_MODEL = "models/gemini-embedding-001"

    # GIỚI HẠN SINH HỌC (BOUNDED MEMORY)
    FORGETTING_RATE = 0.05  # Tốc độ quên cơ bản
    RECONSOLIDATION_RATE = 0.1  # Mức độ biến đổi ký ức khi nhớ lại
    SEMANTIC_DRIFT_CHANCE = 0.3 # Tỉ lệ bóp méo chi tiết phụ khi nhớ lại
