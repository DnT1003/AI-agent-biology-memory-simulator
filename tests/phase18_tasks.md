## Giai đoạn 18: Sự Củng Cố Ký Ức Lõi (Phase 18: Core Memory Consolidation)
- [ ] Xóa bỏ hàm `decay` tĩnh cũ trong `core/memory.py` và thay thế bằng Mô hình `proposed_hybrid_decay` (Hybrid Ebbinghaus x Stress Penalty).
- [ ] Tích hợp tính năng **Deep Freeze** (`MemoryTrace.decay()`): Tự động set `is_flashbulb = True` khi `importance > 0.9` và `recall_count > 10`.
- [ ] Tích hợp tính năng **Homeostasis Recovery** vào `core/engine/memory_ops.py` (tính delta drop của Stress và Fatigue sau khi `sleep()`, truyền vào lúc gọi vòng lặp decay).
- [ ] Tích hợp **Semanticization** vào `dream_consolidation_phase()` (`memory_ops.py`): Query lấy các Episodic yếu (< 0.2 strength) -> Gộp thành 1 Semantic bằng LLM -> Xóa các mảnh rác yếu khỏi DB.
- [ ] Sửa lại hệ thống hàm sinh prompt trong `core/prompts.py` để ra lệnh rõ ràng cho LLM tổng hợp Ký ức Ngữ nghĩa từ các mẩu ký ức rác.
