import re
import math
from typing import List, Dict

try:
    from core.engine.sensory_preprocessor import SensoryPreprocessor
except ImportError:
    SensoryPreprocessor = None

class ContextCompressor:
    """
    Trạm Tiền Trạm Nhận Thức (Hybrid Cognitive Compressor).
    Ứng dụng cơ chế Bộ lọc Kép (Entropy + Cảm xúc) và Hàng Rào Động (Dynamic Budgeting)
    để nén ngữ cảnh dài xuống dung lượng cho phép của LLM.
    """
    def __init__(self):
        self.sensory = SensoryPreprocessor() if SensoryPreprocessor else None
        
    def calculate_pseudo_entropy(self, text: str) -> float:
        """
        Tính toán tham số Entropy giả lập (Pseudo-Entropy).
        Trong tương lai, AuraTiny sẽ chạy forward pass để lấy Loss thực tế.
        Hiện tại: Văn bản chứa nhiều từ vựng độc nhất, con số, danh từ sẽ có Entropy cao.
        """
        words = re.findall(r'\b\w+\b', text.lower())
        if not words:
             return 0.0
        
        # Tỷ lệ từ vựng độc nhất (Unique vocabulary ratio)
        unique_words = set(words)
        vocab_richness = len(unique_words) / len(words)
        
        # Đếm số lượng con số (Numbers carry high information density / entropy)
        numbers = re.findall(r'\b\d+\b', text)
        number_density = len(numbers) / len(words)
        
        # Công thức entropy giả lập cơ bản
        entropy = min(1.0, vocab_richness * 0.7 + number_density * 5.0)
        return round(entropy, 3)

    def evaluate_hybrid_saliency(self, text: str, context_fill_ratio: float = 0.0) -> Dict:
        """
        Đánh giá điểm quan trọng của mẩu tin bằng Bộ lọc Kép (Kiến thức + Linh hồn).
        """
        # 1. Đo lường thông tin thuần túy
        entropy = self.calculate_pseudo_entropy(text)
        
        # 2. Đo lường cảm xúc
        arousal = 0.0
        valence = 0.0
        suppression_flag = False
        
        if self.sensory:
            sensory_eval = self.sensory.evaluate_input(text)
            vec = sensory_eval.get("vector", {})
            arousal = vec.get("arousal", 0.0)
            valence = vec.get("valence", 0.0)
            
            # White Bear Effect (Hiệu ứng Gấu Trắng)
            if re.search(r'\b(quên|đừng nhớ|xóa|đừng nhắc|xấu hổ)\b', text.lower()):
                arousal = min(1.0, arousal * 2.0)
                suppression_flag = True
                
        # 3. Dynamic Thresholding (Hàng Rào Động)
        # Giảm trọng số cảm xúc nếu ngữ cảnh đang quá đầy
        dynamic_weight = 1.0
        if context_fill_ratio > 0.9: # Vùng Đỏ
             dynamic_weight = 0.2
        elif context_fill_ratio > 0.7: # Vùng Vàng
             dynamic_weight = 0.6
             
        # Hybrid Score: Chọn điểm cao nhất giữa Thông tin và Cảm xúc (có scale)
        final_score = max(entropy, arousal * dynamic_weight)
        
        return {
            "text": text,
            "entropy": entropy,
            "arousal": arousal,
            "valence": valence,
            "suppression_flag": suppression_flag,
            "final_score": round(final_score, 3),
            "micro_tag": self._generate_micro_tag(valence, arousal, suppression_flag, context_fill_ratio)
        }

    def _generate_micro_tag(self, valence: float, arousal: float, suppression_flag: bool, context_fill_ratio: float) -> str:
        """
        Nén Metadata cảm xúc thành Micro-Tag cực ngắn để nhét vào System Prompt.
        Ví dụ: [V8A9S1]
        """
        # Nếu não sắp nổ (Vùng đỏ), tối giản hoàn toàn tag nếu không quá đặc biệt
        if context_fill_ratio > 0.9 and arousal < 0.8:
            return ""
            
        # Nếu nhạt nhẽo (Arousal thấp) thì không cần tag
        if arousal < 0.4:
            return ""
            
        # Thang điểm 0-9
        v_tag = int((valence + 1.0) / 2.0 * 9.0) # Map -1..1 to 0..9
        a_tag = int(arousal * 9.0)
        s_tag = 1 if suppression_flag else 0
        
        return f"[V{v_tag}A{a_tag}S{s_tag}]"

    def compress(self, chunks: List[str], max_tokens: int = 2000, current_tokens: int = 0) -> List[Dict]:
        """
        Nhận vào một mảng các đoạn văn (chunks), trả lại danh sách các chunk vượt qua vòng duyệt.
        """
        evaluated_chunks = []
        
        # Ước lượng độ đầy ngữ cảnh (giả định cực kỳ thô 1 token ~ 4 chars)
        total_estimated_tokens = sum(len(c) // 4 for c in chunks) + current_tokens
        fill_ratio = min(1.0, total_estimated_tokens / max(1, max_tokens))
        
        for chunk in chunks:
            eval_data = self.evaluate_hybrid_saliency(chunk, context_fill_ratio=fill_ratio)
            evaluated_chunks.append(eval_data)
            
        # Sắp xếp theo thứ tự ưu tiên (điểm cao xuống thấp)
        evaluated_chunks.sort(key=lambda x: x['final_score'], reverse=True)
        
        # Chọn lọc cho đến khi đầy Budget
        selected_chunks = []
        budget_used = current_tokens
        
        for item in evaluated_chunks:
            chunk_tokens = len(item['text']) // 4
            # Nếu dư dả hoặc mẩu tin này CỰC KỲ quan trọng (score > 0.8) thì cố nhét
            if budget_used + chunk_tokens <= max_tokens or item['final_score'] > 0.8:
                 selected_chunks.append(item)
                 budget_used += chunk_tokens
                 
        # Phục hồi lại đúng thứ tự thời gian gốc
        final_list = []
        for chunk in chunks:
            for selected in selected_chunks:
                 if selected['text'] == chunk:
                      final_list.append(selected)
                      break
                      
        # Kích hoạt Phase 3: Routing (Tiêu hóa kiến thức phân tầng)
        # Các đoạn text cực kỳ dày đặc (Entropy > 0.6) nhưng bị trượt rớt khỏi danh sách chọn
        # Sẽ được đưa xuống file Training chờ "nung" ngủ
        rejected_high_entropy = []
        for item in evaluated_chunks:
            if item not in selected_chunks and item['entropy'] > 0.6:
                rejected_high_entropy.append(item['text'])
                
        if rejected_high_entropy:
            self._route_to_background_training(rejected_high_entropy)
                      
        return final_list
        
    def _route_to_background_training(self, chunks: List[str]):
        """
        Đẩy văn bản quá cứng rớt lưới lọc vào hàng đợi (Training Queue).
        """
        import os
        try:
            from config import Config
            queue_path = os.path.join(Config.BASE_DIR, "outputs", "slm_finetune_data.txt")
            os.makedirs(os.path.dirname(queue_path), exist_ok=True)
            with open(queue_path, "a", encoding="utf-8") as f:
                for chunk in chunks:
                    f.write(chunk.strip() + "\n\n")
            # print(f"[\u26a0\ufe0f ENTROPY WALL]: Đã định tuyến {len(chunks)} đoạn text quá dày đặc vào hàng chờ Training.")
        except Exception:
            pass
