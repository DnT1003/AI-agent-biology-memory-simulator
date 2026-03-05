import torch
from transformers import pipeline, AutoTokenizer, AutoModelForSequenceClassification
from core.gpu_config import get_max_memory_map
import os
from colorama import Fore, Style

class LocalPerception:
    """
    Local Perception Engine - Phase 8 & 12
    Sử dụng các mô hình nhỏ (Encoder-only) chạy trên GPU RTX 3060 để phân tích 
    cảm xúc và sắc thái ngay lập tức mà không cần gọi LLM API.
    """
    def __init__(self, model_name="cardiffnlp/twitter-roberta-base-sentiment"):
        self.model_name = model_name
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.sentiment_analyzer = None
        
        print(f"{Fore.LIGHTCYAN_EX}👁️ [LOCAL PERCEPTION]: Đang khởi tạo mô hình {model_name} trên {self.device.upper()} (Sử dụng nhân Tensor)...{Style.RESET_ALL}")
        try:
            # Khởi tạo pipeline sentiment phân tích sắc thái với Device Map CUDA
            # device_map="cuda" tự động tối ưu hóa nhân Tensor (FP16/INT8 nếu được cấu hình)
            self.sentiment_analyzer = pipeline(
                "sentiment-analysis", 
                model=self.model_name, 
                device=0 if self.device == "cuda" else -1
            )
            # Lưu ý: Pipeline tiêu chuẩn không hỗ trợ max_memory trực tiếp như AutoModel, 
            # nhưng giới hạn process của gpu_config sẽ bảo vệ VRAM.
            
            print(f"{Fore.GREEN}✅ [LOCAL PERCEPTION]: Engine sẵn sàng.{Style.RESET_ALL}")
        except Exception as e:
            print(f"{Fore.RED}❌ [LOCAL PERCEPTION]: Lỗi khi nạp mô hình: {e}{Style.RESET_ALL}")

    def analyze(self, text: str) -> dict:
        """
        Phân tích văn bản và trả về valence, arousal
        Mapping từ RoBERTa Sentiment:
        - Negative -> Valence thấp (-0.7), Arousal cao (0.8)
        - Neutral  -> Valence trung bình (0.0), Arousal thấp (0.2)
        - Positive -> Valence cao (0.7), Arousal trung bình (0.5)
        """
        if not self.sentiment_analyzer:
            return {"valence": 0.0, "arousal": 0.5, "importance": 0.5}

        try:
            results = self.sentiment_analyzer(text)
            if not results:
                return {"valence": 0.0, "arousal": 0.5, "importance": 0.5}

            res = results[0]
            label = res['label']
            score = res['score']

            # Mapping logic cho mô hình cardiffnlp/twitter-roberta-base-sentiment
            # Labels: 'LABEL_0' (negative), 'LABEL_1' (neutral), 'LABEL_2' (positive)
            if label == 'LABEL_0': # Negative
                valence = -0.7 * score
                arousal = 0.8  # Thường mang tính kích thích cao (giận dữ, buồn bã)
            elif label == 'LABEL_1': # Neutral
                valence = 0.0
                arousal = 0.3
            else: # LABEL_2 - Positive
                valence = 0.7 * score
                arousal = 0.5

            # Tính toán Importance cơ bản dựa trên độ dài và cường độ sentiment
            importance = min(0.9, 0.3 + (score * 0.4) + (min(len(text), 100) / 200))

            return {
                "valence": valence,
                "arousal": arousal,
                "importance": importance,
                "raw_label": label,
                "confidence": score
            }
        except Exception as e:
            print(f"Lỗi Local Perception Analyze: {e}")
            return {"valence": 0.0, "arousal": 0.5, "importance": 0.5}

if __name__ == "__main__":
    # Test script nhanh
    lp = LocalPerception()
    tests = [
        "I love you so much!",
        "You are so annoying and stupid.",
        "What is the weather today?",
        "Hôm nay trời đẹp quá, đi chơi không?"
    ]
    for t in tests:
        res = lp.analyze(t)
        print(f"Text: {t}\nResult: {res}\n")
