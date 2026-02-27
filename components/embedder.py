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

    def encode(self, text: Union[str, List[str]]) -> Union[np.ndarray, List[np.ndarray]]:
        try:
            if isinstance(text, str):
                if text in self._cache:
                    return self._cache[text]
                
                response = self.client.models.embed_content(
                    model=Config.EMBEDDING_MODEL,
                    contents=text
                )
                vec = np.array(response.embeddings[0].values)
                self._cache[text] = vec
                return vec
            else:
                # Handle list of strings
                results = [None] * len(text)
                uncached_texts = []
                uncached_indices = []
                
                for i, t in enumerate(text):
                    if t in self._cache:
                        results[i] = self._cache[t]
                    else:
                        uncached_texts.append(t)
                        uncached_indices.append(i)
                        
                if uncached_texts:
                    response = self.client.models.embed_content(
                        model=Config.EMBEDDING_MODEL,
                        contents=uncached_texts
                    )
                    for idx, emb in zip(uncached_indices, response.embeddings):
                        vec = np.array(emb.values)
                        self._cache[uncached_texts[uncached_indices.index(idx)]] = vec
                        results[idx] = vec
                        
                return np.array(results)
        except Exception as e:
            print(f"{Fore.RED}⚠️ Lỗi Gemini Embedding: {e}{Style.RESET_ALL}")
            # Trả về zero vector 768 chiều để tránh crash hệ thống (fallback)
            if isinstance(text, str):
                return np.zeros(768)
            else:
                return np.zeros((len(text), 768))
