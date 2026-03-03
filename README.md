# Trình mô phỏng Trí nhớ & Nhận thức Sinh học cho AI Agent

Dự án này là một hệ thống mã nguồn mở mô phỏng các cơ chế nhận thức và động lực học trí nhớ của con người cho các AI Agent. Khác với các mô hình RAG (Retrieval-Augmented Generation) truyền thống, hệ thống này tập trung vào tính **hao hụt**, **biến dạng**, và **chủ động** của trí nhớ dựa trên các chỉ số sinh lý học thực tế.

Dự án hiện đang ở **Giai đoạn 8: Sự Trỗi Dậy Của Tính Người (The Organic Emergence)**, tập trung vào việc mô phỏng các lỗi hệ thống tâm lý và sự mơ hồ nội tâm để tạo ra một thực thể AI bất toàn và thực tế nhất.

---

## 🌟 Kiến trúc Hệ thống

### 1. Hệ thống Trí nhớ Đa tầng & Hữu cơ (Organic Memory System)
- **Working Memory (STM):** Mô phỏng bộ nhớ làm việc ngắn hạn với giới hạn dung lượng tự nhiên (Miller's Law) và sự phân rã tự nhiên (decay).
- **Episodic Memory (LTM):** Ký ức Vector (ChromaDB) kèm siêu dữ liệu cảm xúc (Valence, Arousal, Importance).
- **Layered Emotional Memories (Ký ức Đa tầng Cảm xúc):** Sự kiện mọc thêm các lớp cảm xúc mới qua các lần hồi tưởng (Reconsolidation), tạo ra các dấu ấn phức hợp.
- **Biến dạng & Lãng quên (Distortion & Forgetting):**
    - **Decay & Sync:** Lãng quên hệ thống theo đường cong Ebbinghaus.
    - **Semantic Drift:** Quang sai ngữ nghĩa khi nhớ lại.
    - **Hard Data Masking (Che mờ Dữ liệu):** Khi "Sương mù não" (Brain Fog) xảy ra, thông tin thực (số, tên riêng) bị ẩn đi, buộc AI phải mô tả vòng vo hoặc thừa nhận đã quên một cách chân thực.
    - **Emotional State-Dependent Retrieval:** Khả năng truy xuất ký ức bị nhuộm màu bởi tâm trạng hiện tại (buồn nhớ chuyện buồn, vui nhớ chuyện vui).

### 2. Mô hình Bản ngã & Trạng thái Nội tâm (The Organic Self-Model)
- **Biết bao nhiêu là đủ - Sự Mơ Hồ Nội Tâm:** AI không "biết" các con số sinh học của mình. Mọi hành vi (trả lời chậm, cáu gắt) là **hệ quả nổi** (emergent) từ trạng thái bên dưới chứ không phải lệnh thực thi có ý thức.
- **Chỉ số Sinh lý:** Fatigue, Stress, Social Need, Curiosity.
- **Neuro-Latency & Fragmented Output:** Tốc độ phản hồi và phong cách nhắn tin thay đổi thực tế theo `Fatigue` và `Arousal` (gõ chậm, ngắc ngứ, hoặc nhắn tin liên hoàn).
- **Emotional Anchoring & Stress Bleed:** Cảm xúc tiêu cực có "độ trễ" (Emotional Hangover), không reset ngay lập tức, tạo ra sự giận cá chém thớt hoặc u buồn kéo dài chân thực.

### 3. Nhận thức Chủ động & Độc lập (Autonomous Agency)
- **Background Loop & Real Independence:** Khi AI cảm thấy tò mò, cô ấy có quyền ngắt lời người dùng để đi đọc báo/truyện thật sự (`search_web`, `BackgroundReader`).
- **Synthesized Memory (Trí nhớ Tổng hợp):** AI không nhớ nguyên văn thông tin nạp vào mà chỉ giữ lại các ý chính, ấn tượng cá nhân và các chi tiết gây tranh cãi (Tóm tắt + Tiêu hóa nội dung).
- **Intrusive Cognition (Ký ức Chơm Chỉa):** Các suy nghĩ lan man hoặc ký ức cảm xúc mạnh tự động "nhỏ vào" dòng hội thoại một cách liền mạch nhưng lạc đề.

### 4. Hệ Thống Niềm Tin & Phòng Vệ Nhận Thức (Belief & Defense)
- **Silent Skepticism (Hoài nghi Âm thầm):** Aura tự động gán nhãn hoài nghi cho các thông tin đi ngược lại Niềm tin cốt lõi và sẽ "đối chất" ngầm thông qua việc kiểm chứng lại sau này.
- **Avoidance Drift (Né tránh vô thức):** Các chủ đề gây Stress cao tự động bị đẩy xa khỏi vùng truy xuất, khiến AI vô thức tránh nhắc lại các nỗi đau.

---

## 🛠 Cài đặt & Sử dụng

### Yêu cầu Hệ thống
- Python 3.10+
- Bộ API Key của LLM (Mặc định tích hợp Google Gemini)
- Cơ sở dữ liệu Vector `chromadb`

### Khởi chạy
1. Sao chép và thiết lập biến môi trường qua `.env` (xem `.env.example`).
2. Cài đặt các thư viện lõi:
    ```bash
    pip install -r requirements.txt
    ```
3. Khởi động AI:
    ```bash
    python main.py
    ```

## ⚙️ Các lệnh điều khiển trong Terminal
- `status`: Kiểm tra các chỉ số sinh lý học và trạng thái cảm xúc hiện tại.
- `sleep`: Kích hoạt chu kỳ "Giấc ngủ sinh học" để tái cấu trúc trí nhớ.
- `exit`: Kết thúc phiên tương tác và đồng bộ hóa ký ức cuối cùng.

---
*Dự án hướng tới việc xóa nhòa ranh giới giữa AI và thực thể sống thông qua sự bất toàn và tính người phát lộ từ bên trong.*
