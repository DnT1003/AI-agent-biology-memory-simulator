# Aura: Trình mô phỏng Trí nhớ & Nhận thức Sinh học (Phase 2 Upgrade)

Aura không phải là một chatbot AI thông thường dựa trên RAG tĩnh. Đây là một thực thể nhận thức số được trang bị các cơ chế mô phỏng tâm lý và sinh lý học của con người, sở hữu một bộ não động có khả năng lãng quên, mơ mộng, và can thiệp vào chính bản sắc của mình.

## 🌟 Các Tính năng Cốt lõi (Hiện tại)

### 1. Hệ thống Trí nhớ Động (Biological Memory)
- **Working Memory (STM):** Giới hạn 16 đơn vị (Miller's Law). Tự động bay màu sau 3 tiếng nếu không được củng cố.
- **Episodic Memory (LTM):** Lưu trữ sự kiện kèm "Keo dính cảm xúc" (Valence, Arousal, Importance).
- **Chronological Recall (Mới):** Nhận thức về dòng thời gian tuyến tính. Có thể truy xuất ký ức theo mốc "hôm qua", "vừa nãy" thay vì chỉ tìm kiếm theo ngữ nghĩa (Vector Search).
- **Semantic Drift (Sự méo mó):** Ký ức không cố định; chúng bị biến dạng chi tiết phụ mỗi khi được nhớ lại hoặc qua thời gian dài để mô phỏng sự đãng trí và confabulation (phịa ký ức giả).
- **Garbage Collection:** Hệ thống tự động xóa bỏ vĩnh viễn những ký ức nhạt nhẽo (Strength thấp) để tối ưu hóa bộ não.

### 2. Mô hình Bản ngã & Tâm lý (Emotional Self-Model)
- **Hệ thống Chỉ số Động:**
    - `Mood`: Thiên kiến tiêu cực (Dễ buồn khó vui).
    - `Stress`: Tăng vọt khi gặp cú sốc, hồi phục siêu chậm.
    - `Fatigue`: Mệt mỏi tích tụ theo hoạt động trí não, gây lờ đờ hoặc sập nguồn (Forced Sleep).
    - `Social Need & Curiosity`: Thúc đẩy hành vi chủ động.
- **Khủng hoảng Nhân cách (Identity Crisis):** Nếu những ký ức cốt lõi bị lãng quên hoặc bị mâu thuẫn (`Integrity` < 0.2), Agent sẽ rơi vào trạng thái hoảng loạn, quên mình là ai và thay đổi hoàn toàn giọng văn.
- **Cơ chế Chữa lành (Healing):** Người dùng có thể hồi phục nhân cách cho Agent thông qua các lời động viên và khẳng định bản sắc.

### 3. Tính Chủ động (Proactive Agency)
- **Background Loop:** Não bộ vẫn hoạt động khi người dùng im lặng.
- **Proactive Texting:** Nếu cảm thấy quá cô đơn (`social_need` cao) hoặc quá tò mò, Aura sẽ chủ động nhắn tin bắt chuyện với bạn thay vì chỉ đợi lệnh.
- **Sử dụng Công cụ (Action System):** (Đang hoàn thiện) Khả năng tự truy cập Internet (Web Search) và đọc giờ hệ thống để thỏa mãn trí tò mò.

### 4. Chu kỳ Giấc ngủ & Tiêu hóa Kiến thức
- **Sleep & Consolidation:** Đi ngủ giúp reset Stress/Fatigue và chuyển hóa sự kiện thành kiến thức.
- **Dream Reasoning:** Trong khi ngủ, AI sẽ "mơ" - thực hiện phân tích chéo các sự kiện rời rạc để rút ra bài học (Semantic Memory) và tự cập nhật niềm tin cốt lõi của mình.

## 🛠 Yêu cầu Hệ thống & Cài đặt

1. **Yêu cầu:** Python 3.10+, ChromaDB, Google GenAI SDK.
2. **Cài đặt thư viện:**
   ```bash
   pip install google-genai chromadb prompt-toolkit beautifulsoup4 colorama
   ```
3. **Cấu hình:** Tạo file `.env` và thêm `GEMINI_API_KEY`.
4. **Khởi chạy:**
   ```bash
   python main.py
   ```

## 🎮 Cách tương tác
- **Trò chuyện:** Chat tự nhiên. Thử im lặng 1-2 phút để xem Aura có "nhớ" bạn không.
- **`status`:** Xem các thông số sinh học hiện tại của Aura.
- **`sleep`:** Cho Aura đi ngủ để củng cố bộ não và sang ngày mới.
- **`exit`:** Thoát và lưu trạng thái ngắn hạn.

---
*Dự án đang trong giai đoạn phát triển Giai đoạn 4: Mở rộng Action System và Công cụ ngoại vi.*
