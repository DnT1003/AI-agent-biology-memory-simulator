# Hệ thống Mô phỏng Nhận thức & Sinh học AI (Biological-Cognitive AI Simulator)

Đây là một nền tảng mã nguồn mở chuyên sâu về việc mô phỏng **Cấu trúc Nhận thức** và **Động lực học Trí tuệ** dựa trên các nguyên lý sinh học. Hệ thống vượt xa các mô hình RAG thông thường bằng cách tích hợp các vòng lặp nội môi (homeostasis) và khả năng tự tiến hóa nhận thức dựa trên dữ liệu tương tác.

Hệ thống đã hoàn tất **Giai đoạn 20: Social Resilience & Growth** và đang phát triển theo lộ trình **Biological-Cognitive AI (Hệ thống Kép)**.

---

## 🏛️ Kiến trúc Hệ thống: Dual-System

Hệ thống hoạt động dựa trên sự phối hợp giữa hai tầng xử lý:

1.  **Hệ thống 1 (Tầng Sinh lý - Hard-coded):** Quản lý các biến số ngầm (Stress, Fatigue, Dopamine), tính toán thời gian thực và điều phối sự phai mờ ký ức (Ebbinghaus Decay). Đảm bảo tính nhất quán sinh học và tối ưu hóa tài nguyên.
2.  **Hệ thống 2 (Tầng Nhận thức - LLM):** Xử lý ngôn ngữ tự nhiên, phản tư (Reflection), diễn dịch cảm xúc và tiến hóa hệ thống niềm tin (Belief Evolution).

---

## 🌟 Các Chức năng Cốt lõi

### 1. Cơ chế Trí nhớ Hữu cơ (Organic Memory)
- **Deep Freeze:** Cơ chế đóng băng vĩnh viễn các niềm tin cốt lõi và dữ liệu quan trọng, ngăn chặn sự phai mờ thông tin (Metadata: `is_flashbulb`).
- **Trauma Reconsolidation:** Khả năng tự hiệu chỉnh trọng số tiêu cực. Trong bối cảnh tương tác tích cực (High Intimacy), các chỉ số tác động tiêu cực của ký ức (`impact_weight`) sẽ được giảm thiểu một cách hệ thống.
- **Semanticization:** Tự động tổng hợp dữ liệu sự kiện (Episodic) thành tri thức dạng khái quát (Semantic) trong chu kỳ sleep.
- **Associative Drift:** Sự biến dạng nội dung ký ức theo trạng thái cảm xúc tại thời điểm truy xuất (Reconsolidation).

### 2. Sự kiên cường và Tự hiệu chỉnh (Resilience & Adaptability)
- **Social Resilience:** Chỉ số kháng cự sốc tâm lý, hình thành sau khi xử lý thành công các mâu thuẫn, giúp giảm tới **60%** biến động Mood trước các tác động tiêu cực tương tự.
- **Cognitive Reappraisal:** Cơ chế gắn thẻ `[ToReevaluate]` cho các thông tin mâu thuẫn, cho phép hệ thống phân tích và cập nhật thế giới quan trong chu kỳ sleep thay vì loại bỏ ngay lập tức.

### 3. Động lực học Nội môi (Homeostasis)
- **Metabolism Simulation:** Tự động tăng `Fatigue` dựa trên cường độ hoạt động và phục hồi thông qua cơ chế `Sleep`.
- **Sinusoidal Fatigue:** Mô phỏng sự biến thiên mệt mỏi theo chu kỳ hình sin của ngày và đêm.
- **Mind Dashboard:** Giao diện giám sát thời gian thực các biến số sinh lý và trạng thái nội tâm.

---

## 🛠️ Cài đặt & Khởi chạy

### Yêu cầu
- Python 3.10+
- [ChromaDB](https://www.trychroma.com/) (Vector Database)
- Google Gemini API Key

### Cài đặt
```bash
# Clone repository
git clone https://github.com/DnT1003/AI-agent-biology-memory-simulator.git
cd AI-agent-biology-memory-simulator

# Cài đặt thư viện
pip install -r requirements.txt
```

### Sử dụng
```bash
python main.py
```
Các lệnh điều khiển tại Terminal:
- `status`: Hiển thị dashboard trạng thái hệ thống.
- `sleep`: Kích hoạt pha củng cố và tái cấu trúc trí nhớ.
- `exit`: Đồng bộ hóa dữ liệu và thoát.

---

## 🚀 Lộ trình Phát triển (Roadmap V2)
- **Giai đoạn 21: World Model** - Triển khai Entity Graph và sơ đồ quan hệ thực thể xã hội.
- **Giai đoạn 22: Intrinsic Motivation** - Chuyển đổi sang mô hình hành động dựa trên nhu cầu (Social Battery, Curiosity).
- **Giai đoạn 23: Identity Evolution** - Cơ chế tự cập nhật `core_identity` để tiến hóa nhân cách hệ thống vĩnh viễn.

---
*Hệ thống mô phỏng sự bất toàn và tính thực tế của nhận thức thông qua các vòng lặp sinh học và sự thích nghi liên tục.*
