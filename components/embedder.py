from google import genai
from config import Config
from colorama import Fore, Style
import numpy as np
from typing import List, Union

class Embedder:
    def __init__(self):
        print(f"{Fore.CYAN}⏳ Đang kết nối lên Gemini Embedding ({Config.EMBEDDING_MODEL})...{Style.RESET_ALL}")
        self.client = genai.Client(api_key=Config.API_KEY)
        self._cache = {} # Bộ đớ đệm Vector

    def encode(self, text: Union[str, List[str]]) -> np.ndarray:
        try:
            # Nếu gọi mảng, lấy item đầu tiên để check cache
            input_text = text if isinstance(text, str) else text[0]
            
            if input_text in self._cache:
                return self._cache[input_text]
                
            # Nếu truyền vào là string lẻ, Google GenAI cũng chấp nhận. 
            # Nhưng để cho chắc chắn mapping sang numpy, ta bọc nó lại thành mảng.
            if isinstance(text, str):
                text_list = [text]
            else:
                text_list = text
                
            response = self.client.models.embed_content(
                model=Config.EMBEDDING_MODEL,
                contents=text_list
            )
            
            # response.embeddings là 1 mảng các object. Mỗi object có .values là list float 768 chiều.
            # Ta lấy mảng đầu tiên nếu input là string đơn (như cách hệ thống đang dùng cho 1 session suy nghĩ).
            embedding_values = response.embeddings[0].values
            
            vec = np.array(embedding_values)
            self._cache[input_text] = vec
            return vec
        except Exception as e:
            print(f"{Fore.RED}⚠️ Lỗi Gemini Embedding: {e}{Style.RESET_ALL}")
            # Trả về zero vector 768 chiều để tránh crash hệ thống (fallback)
            return np.zeros(768)
