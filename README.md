# Trình mô phỏng Trí nhớ Sinh học cho AI Agent

Một trình mô phỏng AI Agent bằng Python, mô phỏng các quá trình nhận thức và trí nhớ sinh học giống con người. Khác với các chatbot LLM thông thường chỉ đơn thuần nối thêm lịch sử hội thoại, hệ thống này sở hữu kiến trúc trí nhớ động, có tính hao hụt và được thúc đẩy bởi cảm xúc.

## Tóm tắt Tính năng

### 1. Hệ thống Trí nhớ Đa tầng
- **Working Memory (Bộ nhớ Ngắn hạn):** Hoạt động như RAM tinh thần. Lưu giữ ngữ cảnh hội thoại gần nhất (có giới hạn cấu hình) trước khi nó từ từ tan biến (decay).
- **Episodic Memory (Ký ức Tính tiết):** Ghi lại các sự kiện cụ thể kèm theo siêu dữ liệu cảm xúc và giác quan (Valence - Mức độ Tích/Tiêu cực, Arousal - Mức độ Kích động, Importance - Độ Quan trọng).
- **Semantic Memory (Ký ức Ngữ nghĩa):** Trích xuất kiến thức chung, sự thật hiển nhiên và niềm tin từ các sự kiện Episodic.

### 2. Động lực học Trí nhớ Sinh học
- **Memory Decay (Lãng quên):** Ký ức mờ dần theo thời gian và qua các chu kỳ giấc ngủ, mô phỏng sự đãng trí của con người.
- **Memory Drift (Biến dạng):** Ký ức có thể hơi méo mó hoặc thay đổi chi tiết theo thời gian tùy thuộc vào trạng thái cảm xúc và những lần hồi tưởng sau đó.
- **Associative Chaining (Liên tưởng dây chuyền):** Khi nhớ lại một ký ức, nó sẽ tụ nhiên kích hoạt các ký ức liên quan trồi lên bề mặt, củng cố các mạng lưới nơ-ron liên kết.
- **Flashbulb Memories (Ký ức Sâu sắc):** Các sự kiện có cảm xúc mãnh liệt hoặc cực kỳ quan trọng (Arousal cao + Importance cao) sẽ được khắc sâu vĩnh viễn vào kho lưu trữ vector và bỏ qua vòng lặp lãng quên.

### 3. Giấc ngủ & Hồi phục (Sleep & Consolidation)
Agent sở hữu một chu kỳ `sleep()` mô phỏng giấc ngủ sâu REM của con người:
- **Consolidation:** Chuyển đổi các dấu vết ngắn hạn quan trọng thành lưu trữ dài hạn.
- **Semanticization:** Phân tích chéo nhiều ký ức Episodic (sử dụng khả năng lập luận của LLM) để tìm ra các mối liên kết ngầm, xác định dòng thời gian và hình thành niềm tin/ngữ nghĩa sắc bén.
- **Garbage Collection (Dọn dẹp rác):** Xóa bỏ các ký ức không còn liên quan hoặc đã phai mờ hoàn toàn để tối ưu hóa hiệu suất.

### 4. Mô hình Tư duy Cảm xúc (Emotional Self-Model)
Agent sở hữu một `Ego` (Bản ngã) phản ứng bất đối xứng với các tác nhân kích thích ngoài:
- **Mood (-1.0 đến 1.0):** Ảnh hưởng đến câu trả lời. Sự chênh lệch cảm xúc quá đà có khả năng tạo ra các hậu quả hành vi (ví dụ: Trầm cảm cực độ khiến agent bơ người dùng; Hưng phấn tạo ra sự liên tưởng quá khích).
- **Stress (0.0 đến 1.0):** Tăng vọt nhanh chóng khi gặp chuyện buồn rầu nhưng phục hồi cực kỳ chậm chạp.
- **Integrity (Tính toàn vẹn):** Theo dõi mức độ ổn định của bản sắc/nhân cách cốt lõi.

## Kiến trúc & Các thành phần chính
- **`CognitiveEngine` (`core/engine.py`):** Bộ não trung tâm kết nối các luồng trích xuất trí nhớ, cập nhật trạng thái bản thân và quy trình nhận thức/phản hồi của LLM.
- **`BiologicalMemory` (`core/memory.py`):** Xử lý dấu vết trí nhớ, sự tự hủy (decay), hồi phục, chắp vá (confabulation) và truy xuất.
- **`SelfModel` (`core/self_model.py`):** Duy trì trạng thái cảm xúc, châm ngôn sống và các bộ điều chỉnh hành vi.
- **`LLMClient` & `Embedder`:** Tích hợp với APIs LLM (ví dụ: Google Gemini) cho phép tạo sinh văn bản và nhúng (Embeds) vector không gian đa chiều.
- **`VectorStore`:** CSDL nội bộ dùng để mô phỏng tìm kiếm vector tương đồng (Cosine Similarity).

## Cài đặt & Khởi chạy
1. Cấu hình file `.env` với các khóa API cần thiết (ví dụ: `GEMINI_API_KEY`).
2. Chạy `python main.py` để bắt đầu trò chuyện với agent trong không gian Terminal.
3. Gõ lệnh `sleep` trên dấu nhắc terminal để bắt tác nhân đi ngủ và bắt đầu phân tích/tiêu hóa trí nhớ.
