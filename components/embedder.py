from google import genai
from config import Config
from colorama import Fore, Style
import numpy as np
from typing import List, Union, Any, cast
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

EMBEDDING_DIM = 1024  # MRL: Giảm chiều Vector xuống 1024 (Phase 17B)

class Embedder:
    requires_network = True

    def __init__(self):
        from core.settings_manager import settings_manager
        self.settings = settings_manager
        print(f"{Fore.CYAN}[WAIT] Connecting to Gemini Embedding ({Config.EMBEDDING_MODEL}, {EMBEDDING_DIM}D MRL)...{Style.RESET_ALL}")
        self.client = None
        self._cache = {} # Bộ đệm Vector

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        retry=retry_if_exception_type(Exception),
        reraise=True
    )
    def _call_embedding_api(self, text_list: List[str]) -> List[np.ndarray]:
        api_key = self.settings.get("gemini_api_key", Config.API_KEY)
        if not getattr(self, "client", None) or getattr(self, "_current_api_key", "") != api_key:
            self.client = genai.Client(api_key=api_key)
            self._current_api_key = api_key
            
        response = self.client.models.embed_content(
            model=Config.EMBEDDING_MODEL,
            contents=cast(Any, text_list),
            config={"output_dimensionality": EMBEDDING_DIM}
        )
        embeddings = response.embeddings or []
        return [np.array(e.values) for e in embeddings]

    def encode(self, text: Union[str, List[str]]) -> Union[np.ndarray, List[np.ndarray]]:
        is_single = isinstance(text, str)
        text_list = [text] if is_single else list(text)

        results = []
        texts_to_embed = []
        indices_to_embed = []

        # 1. Quét Cache
        for i, t in enumerate(text_list):
            if t in self._cache:
                results.append(self._cache[t])
            else:
                results.append(None)
                texts_to_embed.append(t)
                indices_to_embed.append(i)

        # 2. Gọi API cho những text chưa encode
        if texts_to_embed:
            try:
                embedded_vecs = self._call_embedding_api(texts_to_embed)
                for i, vec in zip(indices_to_embed, embedded_vecs):
                    results[i] = vec
                    # 3. Cache với giới hạn (Evict oldest if > 1000)
                    if len(self._cache) >= 1000:
                        # Simple random eviction or FIFO if ordered
                        first_key = next(iter(self._cache))
                        del self._cache[first_key]
                    self._cache[text_list[i]] = vec
            except Exception as e:
                print(f"{Fore.RED}⚠️ Lỗi Gemini Embedding (retry failed): {e}{Style.RESET_ALL}")
                raise RuntimeError(f"Embedding API failed: {e}")

        return results[0] if is_single else results
