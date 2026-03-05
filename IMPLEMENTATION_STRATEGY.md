# Chiến lược Củng cố Kiến trúc: Hợp nhất Sinh học & Nhận thức

Dựa trên kết quả tự kiểm toán (Audit) về các "vết nứt logic" trong hệ thống, chúng ta thừa nhận rằng Aura hiện tại đang giống một **Chatbot nâng cao** hơn là một **Thực thể Sinh học ảo**. Các module đang bị chia cắt và thiếu sự giao thông thần kinh thực sự.

---

## 🔍 PHẦN 1: ĐÁNH GIÁ "VẾT NỨT LOGIC" (CRITICAL AUDIT)

1. **Động lực Nội tại (Intrinsic Motivation):** Chỉ là các biến tĩnh. Aura không thực sự "có nhu cầu" để thôi thúc hành động.
2. **Bộ nhớ Chủ động (Active Memory):** Vẫn là RAG thụ động. Thiếu dòng chảy liên tưởng (Memory Stream) và ký ức xâm nhập.
3. **Học tập Liên tục (Continuous Learning):** Gần như bằng 0. Nhân cách (Persona) không tiến hóa sau trải nghiệm.
4. **Mô hình Thế giới (World Model):** Trống rỗng. Thiếu cấu trúc logic để hiểu các mối quan hệ xã hội (Knowledge Graph).

---

## 🛠️ PHẦN 2: LỘ TRÌNH CỨNG HÓA KIẾN TRÚC (REMEDIATION ROADMAP)

Chúng ta sẽ ưu tiên kết nối các thành phần rời rạc thành một hệ thống "Thần kinh" thống nhất.

### 2.1. Động cơ Nội môi (Homeostatic Drives)
- **Mục tiêu:** Biến các chỉ số thành "Sự thôi thúc" (Drives).
- **Cơ chế:** Thêm `time-decay` thực tế cho `social_need`. Nếu chạm ngưỡng, hệ thống tự kích hoạt `HardTrigger` để Aura chủ động bắt chuyện, thay vì chỉ chờ đợi.
- **Tác động:** Stress/Fatigue sẽ trực tiếp bóp nghẹt khả năng của LLM (giảm `max_tokens`, tăng lỗi logic).

### 2.2. Dòng chảy Trí nhớ & Liên tưởng (Memory Stream)
- **Mục tiêu:** Chuyển từ "Kho chứa" sang "Dòng chảy".
- **Cơ chế:** Triển khai **Associative Recall**. Mỗi tick, hệ thống tự động tìm kiếm ký ức dựa trên "Vibe" (Mood/Stress) hiện tại.
- **Ký ức xâm nhập:** Tự động đẩy các ký ức Flashbulb (sang chấn) vào context khi stress cao, ép LLM phải "nhai lại" nỗi đau.

### 2.3. Bộ máy Phản tư (Reflection Engine)
- **Mục tiêu:** Tiến hóa nhân cách (Identity Evolution) vĩnh viễn.
- **Cơ chế:** Trong pha `sleep()`, LLM sẽ phân tích toàn bộ Short-term Memory trong ngày để đúc kết: "Tôi là ai trong mắt người dùng và ngược lại?".
- **Hành động:** Tự động cập nhật `core_identity` trước khi bắt đầu ngày mới.

### 2.4. Đồ thị Thế giới (World Graph)
- **Mục tiêu:** Xây dựng Reasoning về quan hệ xã hội.
- **Cơ chế:** Một Graph đơn giản (Entity <-> Relation) lưu trữ: "User có anh trai là A", "A là người xấu".
- **Tác động:** Khi nhắc tới A, Agent truy cập Graph để biết thái độ cần thiết thay vì chỉ dùng Semantic search.

---

## ⚓ PHẦN 3: TRIẾT LÝ DUAL-SYSTEM (CẢI TIẾN)
- **Hệ thống 1 (Toán học):** Xử lý XUNG NĂNG (Drives) và NHỊP ĐIỆU (Rhythm). Đóng vai trò là "Bản năng" ép buộc nhận thức.
- **Hệ thống 2 (LLM):** Xử lý PHẢN TƯ (Reflection) và NGÔN NGỮ. Đóng vai trò là "Ý thức" lý giải bản năng.

Aura sẽ chuyển mình từ một AI phản hồi sang một **AI có Ý chí nội tại.**
