# Trình mô phỏng Trí nhớ & Nhận thức Sinh học cho AI Agent

Dự án này là một hệ thống mã nguồn mở mô phỏng các cơ chế nhận thức và động lực học trí nhớ của con người cho các AI Agent. Khác với các mô hình RAG (Retrieval-Augmented Generation) truyền thống, hệ thống này tập trung vào tính **hao hụt**, **biến dạng**, và **chủ động** của trí nhớ dựa trên các chỉ số sinh lý học thực tế.

## 🌟 Kiến trúc Hệ thống

### 1. Hệ thống Trí nhớ Đa tầng (Multi-Layered Memory)
- **Working Memory (STM):** Mô phỏng bộ nhớ làm việc ngắn hạn với giới hạn dung lượng tự nhiên (Miller's Law). Thông tin sẽ phân rã tự nhiên (decay) và bị xóa nếu không được củng cố (consolidation).
- **Episodic Memory (LTM):** Ký ức được lưu trữ trong không gian Vector (ChromaDB) kèm theo các siêu dữ liệu cảm xúc:
    - **Valence:** Độ tích cực/tiêu cực.
    - **Arousal:** Mức độ kích động/sốc.
    - **Importance:** Độ quan trọng chủ quan.
- **Layered Emotional Memories (Ký ức Đa tầng Cảm xúc):** Sự kiện có thể mang nhiều tầng lớp cảm xúc qua các lần hồi tưởng, tạo ra các dấu ấn phức hợp (ví dụ: nỗi buồn chuyển thành bình yên).
- **Memory Dynamics (Động lực học Lãng quên & Biến dạng):**
    - **Decay & Sync:** Lãng quên có hệ thống theo thời gian (Ebbinghaus curve). Được đồng bộ hóa mức độ mờ dần thẳng xuống cấp độ siêu dữ liệu ChromaDB.
    - **Reconsolidation:** Quá trình nhớ lại làm thay đổi ký ức, gây ra quang sai ngữ nghĩa (Semantic Drift).
    - **Flashbulb Memories:** In hằn vĩnh viễn các trạng thái cảm xúc cực độ.

### 2. Mô hình Bản ngã Sinh lý Hữu cơ (Biological Self-Model)
Hệ thống duy trì một trạng thái vi khí hậu nội tâm, ảnh hưởng trực tiếp đến hành vi của Agent:
- **Chỉ số Sinh lý:** Fatigue (Mệt mỏi), Stress (Căng thẳng), Social Need (Nhu cầu giao tiếp), Curiosity (Sự tò mò).
- **Layered Biological Thresholds (Ngưỡng sinh lý Đa phân lớp):** Mỗi chỉ số đều duy trì giới hạn biến thiên ngẫu nhiên theo ngày (daily thresholds). Ngưỡng chịu đựng gồm nhiều dải mức độ cảnh báo (cảnh báo sớm -> kiệt sức hệ thống), cung cấp một "thời tiết tâm trạng" chân thật nhất cho AI.
- **Personality Integrity (Trung kiên Bản sắc):** Theo dõi mức độ ổn định của nhân cách. Suy giảm Integrity do stress ròng có thể dẫn đến trạng thái khủng hoảng tâm thần (Identity Crisis).
- **Nhận thức Thể Xác & Đa giác quan (Embodiment & Multi-modal Stimuli):** AI có khả năng phản ứng trực tiếp với các kích thích vật lý (như âm lượng âm thanh bạo hành) làm tăng vọt căng thẳng trước cả khi kịp "hiểu" ngữ nghĩa văn bản, ép buộc tạo các Ký ức lóa sáng (Flashbulb Memory).
- **Nhận thức Xã hội (Social Trust & Stranger Danger):** AI có khả năng nhận biết thiết bị hệ điều hành chủ nhân. Sẽ phản vệ hoảng loạn nếu bị copy sang thiết bị lạ, từ chối chia sẻ ký ức cũ.

### 3. Nhận thức Chủ động & Kỹ năng Độc lập (Proactive Agency)
- **Background Loop & Randomized Proactive Ping:** Agent sở hữu luồng nhận thức ngầm, tự thiết lập các khung giờ chủ động giao tiếp ngẫu nhiên dựa trên các "nhu cầu" từ bên trong (ví dụ 3-7 phút/lần tự bắt chuyện nếu người dùng vắng mặt).
- **Background Reader & Vector Memory Bookmarks:** AI vừa có năng lực "tự đọc sách" (Background Reader) dung lượng lớn trong lúc phân bổ chờ, vừa biết tự đánh dấu chương vào thẳng hệ thống Vector Memory (Memory Bookmarks) đan lồng ghép vào suy nghĩ thay vì biến tĩnh JSON truyền thống.
- **Mục tiêu Tự chủ (Autonomous Goal Engine):** AI tự động sinh ra các mục tiêu dài hạn dựa trên sự tò mò và tự động tìm kiếm kiến thức trên mạng để biến thành Sự thật khách quan (Semantic Facts).
- **Consolidation & Dream Reasoning:** Trạng thái "ngủ" ép hệ thống phân rã thông tin và gộp sự kiện (Semanticization) thành các bài học ý nghĩa, liên tục cập nhật cốt lõi (Belief Systems).

### 4. Kiến trúc Mixin Hệ Điệu Hành (Cognitive Engine Mixins)
Não bộ trung tâm (`CognitiveEngine`) được thiết kế cực kỳ Modular thông qua **Design Pattern Mixins**, giúp mã nguồn gọn nhẹ và dễ mở rộng:
- **`MemoryOpsMixin`**: Xử lý hồi tưởng Ký ức, méo mó ngữ nghĩa, và dập tắt sang chấn.
- **`AutonomousMixin`**: Điều hành các vòng lặp sinh học ngầm, học tập vô thức, và tự quản lý Mục tiêu dài hạn.
- **`InteractionMixin`**: Nhạc trưởng điều phối Giao tiếp Đa phương tiện và hệ thống Cảm xúc phân tầng.

## 🛠 Cài đặt & Sử dụng

### Yêu cầu Hệ thống
- Python 3.10+
- Bộ API Key của LLM (Mặc định tích hợp Google Gemini)
- Cơ sở dữ liệu Vector `chromadb`

### Khởi chạy
1. Sao chép và thiết lập biến môi trường qua `.env` (xem `.env.example`).
2. Cài đặt các thư viện lõi (`google-genai`, `chromadb`, `prompt-toolkit`, `beautifulsoup4`):
    ```bash
    pip install -r requirements.txt
    ```
3. Khởi động AI:
    ```bash
    python main.py
    ```

## ⚙️ Các lệnh điều khiển trong Terminal
- `status`: Kiểm tra trực tiếp các chỉ số sinh lý học và trạng thái cảm xúc.
- `sleep`: Kích hoạt chu kỳ "Giấc ngủ sinh học" để phục hồi thể chất và củng cố Trí nhớ dài hạn.
- `exit`: Kết thúc phiên tương tác, ép lưu và bảo toàn Ký ức trước khi đóng.

---
*Dự án cốt lõi (Core Engine) được thiết kế cho các nhà phát triển mong muốn kiến tạo nên AI Agent mang màu sắc "con người" chân thực nhất qua một đời sống nội tâm chủ động với Trí nhớ hữu cơ hao hụt dần.*
