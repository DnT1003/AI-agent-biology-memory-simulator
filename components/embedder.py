from google import genai
from config import Config
from colorama import Fore, Style
import numpy as np
from typing import List, Union

EMBEDDING_DIM = 3072  # MRL: gemini-embedding-001 hỗ trợ outputDimensionality tới 3072

class Embedder:
    def __init__(self):
        print(f"{Fore.CYAN}⏳ Đang kết nối lên Gemini Embedding ({Config.EMBEDDING_MODEL}, {EMBEDDING_DIM}D MRL)...{Style.RESET_ALL}")
        self.client = genai.Client(api_key=Config.API_KEY)
        self._cache = {} # Bộ đệm Vector

    def encode(self, text: Union[str, List[str]]) -> np.ndarray:
        try:
            # Nếu gọi mảng, lấy item đầu tiên để check cache
            input_text = text if isinstance(text, str) else text[0]
            
            if input_text in self._cache:
                return self._cache[input_text]
                
            if isinstance(text, str):
                text_list = [text]
            else:
                text_list = text
                
            response = self.client.models.embed_content(
                model=Config.EMBEDDING_MODEL,
                contents=text_list,
                config={"output_dimensionality": EMBEDDING_DIM}  # MRL: 3072 chiều
            )
            
            embedding_values = response.embeddings[0].values
            vec = np.array(embedding_values)
            self._cache[input_text] = vec
            return vec
        except Exception as e:
            print(f"{Fore.RED}⚠️ Lỗi Gemini Embedding: {e}{Style.RESET_ALL}")
            # Fallback: trả về zero vector đúng 3072 chiều để tránh crash
            return np.zeros(EMBEDDING_DIM)
