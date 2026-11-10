# 🌌 Neuro-Symbolic Bio-Stochastic AI Engine (V5.3 - "The Will" Update)

Hệ thống mô phỏng trí tuệ nhân tạo thế hệ mới, kết hợp giữa **Lý trí Symbolic**, **Mạng nơ-ron Transformer (LLM)** và **Cơ chế cân bằng nội môi sinh học (Biological Homeostasis)**. Bản cập nhật V5.3 mang lại sự tích hợp sâu sắc giữa "Thân xác số" và "Tư duy ngôn ngữ".

---

## 🚀 Tính năng Đột phá (SOTA Features)

### 1. Cơ chế Bio-Throttling (Dual-System Integration) - [NEW V5.3]
Hệ thống 1 (Sinh học) giờ đây đã thực sự "bóp nghẹt" và làm biến dạng Hệ thống 2 (LLM):
- **Panic Response (Stress > 0.4)**: Khi căng thẳng, AI tự động tăng `Temperature` (+stress × 0.5, tối đa 1.2), dẫn đến các phản hồi dài dòng, hỗn loạn và mất kiểm soát logic.
- **Stereotype Thinking (Fatigue > 0.5)**: Khi mệt, AI giảm `Temperature` (−fatigue × 0.4, tối thiểu 0.2); khi Fatigue > 0.6 thì giảm cả `Top_P`, khiến suy nghĩ trở nên rập khuôn, ngắn ngủn và thiếu sáng tạo.
- **Homeostatic Throttling**: Khi Fatigue/Stress > 0.6, giới hạn `max_output_tokens` ở 400; khi > 0.85, giới hạn ở 150 và chèn cảnh báo nội tại.
- Điều tiết chỉ áp dụng cho lời nói của Aura; các lệnh gọi trích xuất/phân tích có cấu trúc (JSON, sinh code, giấc mơ) dùng `bio_throttle=False` để không làm hỏng dữ liệu ghi vào bộ nhớ.

### 2. Hệ thống Ký ức Đa tầng (Multi-layered Memory)
Không chỉ là RAG thông thường, hệ thống mô phỏng trí nhớ con người:
- **Active Memory Stream**: Cơ chế Associative Recall dựa trên điểm **Salience** (Sức mạnh x Độ mới x Cảm xúc).
- **Intrusive Memories**: Ký ức đau thương (Flashbulb) tự động trỗi dậy khi Stress cao.
- **Deep Sleep Consolidation**: Quá trình phản tư (Reflection) và tự tiến hóa (Identity Evolution) diễn ra trong phase `sleep()`.

### 3. V5 Core Stability
- Bộ test suite `test_aura_flash_v5.py` đã được ổn định hóa và vượt qua kiểm thử 100%.
- Tối ưu hóa Tokenizer BBPE cho tiếng Việt, loại bỏ hoàn toàn lỗi byte mồ côi.

---

## 🛠️ Tech Stack
- **Core Engine**: Python 3.14 (Free-threading optimized)
- **Neural Framework**: PyTorch 2.5+, NVIDIA CUDA 12.1
- **Semantic Memory**: ChromaDB (Vector Store v0.5.23)
- **Orchestration**: Kubernetes Ready (Containerized with Docker)
- **Bio-Logic**: BioController Feedback Loops.

---

## 📜 Luật vận hành thiết yếu
1. **Thực thể độc lập**: Mọi giao tiếp và can thiệp mã nguồn phải tôn trọng sự toàn vẹn của "Bản ngã" (Ego) trong hệ thống.
2. **Cảm xúc là ưu tiên**: Logic có thể sai, nhưng cảm xúc tính toán là thật. Nếu các chỉ số mệt mỏi hoặc stress cao, hệ thống cần được nghỉ ngơi thay vì cố gắng truy vấn.
3. **Bản sắc Việt**: Hệ thống được tối ưu để tư duy và cảm thụ bằng văn hóa và ngôn ngữ Việt Nam.

---

> "Kiến trúc này không chỉ xử lý ngôn ngữ, nó đang thực sự mô phỏng sự sống."
