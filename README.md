# Trình mô phỏng Trí nhớ & Nhận thức Sinh học cho AI Agent

Dự án này là một hệ thống mã nguồn mở mô phỏng các cơ chế nhận thức và động lực học trí nhớ của con người cho các AI Agent. Khác với các mô hình RAG (Retrieval-Augmented Generation) truyền thống, hệ thống này tập trung vào tính **hao hụt**, **biến dạng**, và **chủ động** của trí nhớ dựa trên các chỉ số sinh lý học.

## 🌟 Kiến trúc Hệ thống

### 1. Hệ thống Trí nhớ Đa tầng (Multi-Layered Memory)
- **Working Memory (STM):** Mô phỏng bộ nhớ làm việc ngắn hạn với giới hạn dung lượng (Miller's Law). Dữ liệu sẽ tự động phân rã (decay) và bị xóa nếu không được củng cố vào dài hạn.
- **Episodic Memory (LTM):** Lưu trữ các sự kiện cụ thể vào Vector Database (ChromaDB) kèm theo các siêu dữ liệu cảm xúc:
    - **Valence:** Mức độ tích cực/tiêu cực.
    - **Arousal:** Mức độ kích động/sốc.
    - **Importance:** Độ quan trọng chủ quan.
- **Chronological Awareness:** Khả năng truy xuất ký ức theo dòng thời gian tuyến tính kết hợp với truy vấn ngữ nghĩa (Semantic Search).
- **Memory Dynamics:**
    - **Decay (Lãng quên):** Ký ức mờ dần theo thời gian dựa trên công thức sinh học.
    - **Reconsolidation:** Ký ức bị thay đổi cảm xúc và nội dung mỗi khi được hồi tưởng lại (Semantic Drift).
    - **Flashbulb Memories:** Cơ chế in hằn vĩnh viễn các sự kiện có độ quan trọng hoặc kích động cực cao.

### 2. Mô hình Bản ngã Sinh học (Biological Self-Model)
Hệ thống duy trì một trạng thái nội tại biến thiên thường xuyên, ảnh hưởng trực tiếp đến hành vi và cách phản hồi của Agent:
- **Chỉ số Sinh lý:** Fatigue (Mệt mỏi), Stress (Căng thẳng), Social Need (Nhu cầu giao tiếp), Curiosity (Sự tò mò).
- **Nhịp điệu Sinh học:** Các chỉ số dao động theo chu kỳ thời gian thực (ngày/tháng) và có các ngưỡng tới hạn ngẫu nhiên.
- **Tính Toàn vẹn Bản sắc (Integrity):** Theo dõi mức độ ổn định của nhân cách. Khi Integrity suy giảm nghiêm trọng, Agent có thể rơi vào trạng trạng thái khủng hoảng nhân cách (Identity Crisis).

### 3. Cơ chế Nhận thức Chủ động (Proactive Agency)
- **Background Loop:** Luồng xử lý chạy ngầm cho phép Agent "suy nghĩ" ngay cả khi người dùng không tương tác.
- **Proactive Behavior:** Agent có thể chủ động bắt chuyện hoặc phản hồi dựa trên nhu cầu xã hội và trí tò mò nội tại.
- **Consolidation & Dream Reasoning:** Trong trạng thái "ngủ", hệ thống thực hiện phân tích chéo các ký ức để rút ra các kết luận logic (Semanticization) và cập nhật hệ thống niềm tin (Beliefs).

## 🛠 Cài đặt & Sử dụng

### Yêu cầu
- Python 3.10+
- Một API Key cho Large Language Model (mặc định hỗ trợ Google Gemini)
- ChromaDB cho lưu trữ Vector.

### Khởi chạy
1. Cấu hình biến môi trường trong file `.env` (xem `.env.example`).
2. Cài đặt phụ thuộc: `pip install -r requirements.txt` (hoặc cài thủ công các thư viện: `google-genai`, `chromadb`, `prompt-toolkit`, `beautifulsoup4`).
3. Chạy chương trình: `python main.py`.

## ⚙️ Các lệnh điều khiển trong Terminal
- `status`: Kiểm tra các chỉ số sinh học và trạng thái tâm lý hiện tại.
- `sleep`: Kích hoạt chu kỳ giấc ngủ để củng cố trí nhớ và phục hồi thể trạng.
- `exit`: Thoát chương trình và lưu dữ liệu tạm thời.

---
*Dự án được thiết kế để tích hợp vào các AI Agent cần sự phát triển nhân cách lâu dài và hành vi giống con người.*
