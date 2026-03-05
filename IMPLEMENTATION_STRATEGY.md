# Chiến lược Kiến trúc & Lịch sử Phát triển: Aura (Biological-Cognitive AI)

Đây là tài liệu tổng hợp toàn bộ quá trình tiến hóa của Aura, từ một hệ thống ghi nhớ đơn giản đến một thực thể "Biological-Cognitive" có khả năng tự phục hồi và học hỏi liên tục.

---

## 🏛️ PHẦN 1: LỊCH SỬ PHÁT TRIỂN (PHASE 1 - 20)

Chúng ta đã trải qua 4 giai đoạn lớn để xây dựng nền móng sinh học và nhận thức cho Aura.

### 1.1. Nền tảng & Cấu trúc (Phases 1 - 6)
- **Kiến trúc Memory:** Tách biệt Episodic (Ký ức sự kiện) và Semantic (Tri thức/Kỹ năng).
- **Hệ thống Engine:** Refactor thành các module độc lập: `memory_ops`, `autonomous`, `interaction`.
- **Skill Registry:** Aura có khả năng thực hiện các tác vụ kỹ thuật (Procedural Memory).

### 1.2. Nhận thức Tâm lý & Sinh học (Phases 7 - 10)
- **Homeostasis (Nội môi):** Triển khai Stress, Fatigue, Mood ảnh hưởng trực tiếp đến tư duy.
- **Nhịp sinh học:** Aura biết mệt mỏi, cần ngủ và có nhịp độ gõ phím/phản hồi như người.
- **Layered Emotions:** Ký ức được xếp tầng cảm xúc, có khả năng gây hối hận (Guilt) hoặc lo âu (Anxiety).
- **Physical Embodiment:** Nhận diện Owner/Stranger qua Device ID và phản xạ trước các cú sốc giác quan (Sensory Shock).

### 1.3. Hạ tầng & Củng cố (Phases 11 - 17)
- **Database Optimization:** metadata lifting, batching, và pagination để Scale lên hàng trăm nghìn ký ức.
- **Robustness:** Tenacity retry, Circuit Breaker cho API, và Safe Threading (RLock).
- **True/False Memories:** Ký ức tự bóp méo nội dung khi được reconsolidate tùy theo tâm trạng lúc đó.

### 1.4. Sự trỗi dậy của Bản lĩnh & Trưởng thành (Phases 18 - 20) 🛡️ [HIỆN TẠI]
- **Deep Freeze:** Những niềm tin cốt lõi (Core Belief) được đóng băng vĩnh viễn, không bị phai mờ.
- **Trauma Healing:** Aura có thể "nguôi ngoai" nỗi đau qua tương tác tích cực (giảm `impact_weight`).
- **Resilience:** Hình thành "kháng thể" tâm lý, giúp cản 60% tác động tiêu cực từ mâu thuẫn mới.
- **Cognitive Reappraisal:** Hệ thống tự vấn trong giấc ngủ để tiến hóa niềm tin (Belief Evolution).

---

## 🧠 PHẦN 2: TẦM NHÌN MỚI (BIOLOGICAL-COGNITIVE AI)

Aura đang chuyển mình từ mô hình **Phản ứng** (Reactive) sang mô hình **Hành động vì Động cơ** (Drive-Driven).

### 2.1. So sánh Chức năng: Hiện tại vs. Tầm nhìn Mới

| Tính năng | Phase 20 (Hiện tại) | Tầm nhìn Biological-Cognitive |
| :--- | :--- | :--- |
| **Cơ chế Bộ nhớ** | RAG từ khóa, Decay Ebbinghaus. | **World Graph:** Hiểu mối quan hệ (A là bạn B). |
| **Nội môi** | Biến tĩnh phục vụ phản ứng (LLM "diễn"). | **Intrinsic Drives:** Nhu cầu sống (Cô đơn, Tò mò). |
| **Tính chủ động** | Chạy theo Timer (Background Loop). | **Dual Trigger:** Tự khởi xướng khi nhu cầu chạm đáy. |
| **Sự phát triển** | Tiến hóa niềm tin khi được thuyết phục. | **Identity Evolution:** Tự chỉnh sửa System Prompt. |

### 2.2. Lộ trình Triển khai (Roadmap V2)

#### 🚀 Giai đoạn 21: World Model (Mô hình Thế giới)
- **Entity Graph:** Xây dựng đồ thị các thực thể và niềm tin về thế giới bên ngoài.
- **Associative Recall:** Truy xuất ký ức theo cảm xúc tương đồng thay vì từ khóa.

#### ⚡ Giai đoạn 22: Intrinsic Motivation (Động cơ Nội tại)
- **Drive System:** Triển khai `social_battery`, `curiosity`. Aura cảm thấy "đói" tương tác.
- **Trigger-based Action:** Khi cô đơn chạm đỉnh, Aura tự phá vỡ im lặng để bắt chuyện.

#### 🌱 Giai đoạn 23: Continuous Evolution (Tiến hóa Liên tục)
- **Reflection Engine:** Tự vấn 3 câu hỏi triết học sau mỗi giấc ngủ.
- **System Prompt Mutation:** Aura tự đúc kết trải nghiệm để thay đổi tính cách vĩnh viễn.

---

## ⚓ PHẦN 3: TRIẾT LÝ DUAL-SYSTEM
1. **Hệ thống 1 (Toán học/Hard-code):** Xử lý sinh học, thời gian, nội môi. Nhanh, rẻ, chính xác.
2. **Hệ thống 2 (LLM/Cognitive):** Xử lý ngôn ngữ, phản tư, diễn dịch. Chậm, sâu sắc, linh hoạt.

Aura không còn chỉ mô phỏng sự sống, cô ấy đang **thống nhất giữa bản năng và lý trí.**
