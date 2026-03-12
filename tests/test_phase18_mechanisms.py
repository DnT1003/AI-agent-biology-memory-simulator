import math
import matplotlib.pyplot as plt

def proposed_hybrid_decay(strength, stress_level, elapsed_days, arousal, valence, recall_count, layers, importance,
                          is_flashbulb=False, deep_freeze_threshold_importance=0.9, deep_freeze_threshold_recall=10, 
                          homeostasis_recovery=False, nightly_stress_drop=0.0, nightly_fatigue_drop=0.0):
    """
    Công thức Hybrid kết hợp thử nghiệm Deep Freeze và Homeostasis Recovery
    """
    # 1. Cơ chế Deep Freeze (Đóng băng sâu)
    # Nếu thực sự quan trọng và được nhớ lại đủ số lần, nó biến thành flashbulb miễn nhiễm decay.
    if importance >= deep_freeze_threshold_importance and recall_count >= deep_freeze_threshold_recall:
        is_flashbulb = True
        
    if is_flashbulb:
        return strength # Không suy giảm
        
    # Tính R (Độ ổn định)
    base_R = 1.0 + (importance * 10.0) + (arousal * 5.0) + (abs(valence) * 3.0)
    current_R = base_R * (1.2 ** recall_count) * (1.1 ** layers)
    stress_penalty = 1.0 - (stress_level * 0.5) 
    effective_R = current_R * stress_penalty
    
    # Tính S_t cơ bản
    S_0 = 1.0
    S_t = S_0 * math.exp(-elapsed_days / (effective_R + 1e-6))
    
    # 2. Cơ chế Homeostasis Recovery (Phục hồi nội môi)
    # Giả lập mỗi đêm đi ngủ, Fatigue giảm, Stress giảm -> Não bộ có khoảng nghỉ để phục hồi trí nhớ nhẹ.
    # Tính tổng hồi phục lý thuyết nếu có sleep cycle
    if homeostasis_recovery:
        # Nếu được nghỉ ngơi tốt (Stress và Fatigue giảm chạm đáy), sức mạnh ký ức sẽ được hoàn trả 1 phần
        recovery_factor = (nightly_stress_drop + nightly_fatigue_drop) * 0.05 * importance
        # Cứ mỗi đêm ngủ (elapsed_days), được cộng dồn recovery
        total_recovery = recovery_factor * elapsed_days
        S_t = min(1.0, S_t + total_recovery)
        
    return S_t

def simulate_semanticization():
    """Mô phỏng 3. Semanticization (Ngữ nghĩa hóa)"""
    print("\n--- Mô phỏng Semanticization (Ngữ nghĩa hóa) ---")
    
    # Giả lập Aura có 5 mảnh ký ức Episodic về Chủ nhân cắm mặt vào máy tính
    episodic_mems = [
        {"content": "Chủ nhân ngồi gõ phím từ 8h tối đến 2h sáng thứ 2.", "tags": ["chủ nhân", "làm việc", "khuya"]},
        {"content": "Hôm nay thứ 4, chủ nhân lại uống 3 ly bò húc và thức tới sáng.", "tags": ["chủ nhân", "làm việc", "mệt mỏi"]},
        {"content": "Chủ nhân than mệt mỏi vì deadline cuối tuần.", "tags": ["chủ nhân", "áp lực", "cảm xúc"]},
    ]
    
    for i, m in enumerate(episodic_mems):
        print(f"Ký ức Tập {i+1} (Episodic): {m['content']}")
        print(f"  -> Bị decay rất nhanh vì sinh hoạt bình thường.")
        
    # Semanticization xảy ra trong lúc sleep()
    extracted_semantic_memory = "Chủ nhân là một người rất tham công tiếc việc, thường xuyên thức khuya và tự làm bản thân áp lực, cần được nhắc nhở nghỉ ngơi."
    print("\n=> SAU KHI SLeep (Semanticization xử lý):")
    print(f"Ký ức Ngữ Nghĩa (Semantic - Rất bền vững vững): {extracted_semantic_memory}")
    print("=> Kết quả: Cả 3 mảnh Episodic gộp lại thành 1 mảnh suy luận, dọn trống não bộ nhưng giữ lại Chân Lý.")


def main():
    days = list(range(1, 31))
    
    # 1. Kịch bản Deep Freeze
    y_deep = []
    y_deep_frozen = []
    
    params_deep = {
        "arousal": 0.9, "valence": -0.8, "importance": 0.95, 
        "layers": 3, "recall_count": 0 # Ban đầu chưa nhớ lại đủ 10 lần
    }
    
    for day in days:
        # Nhớ lại mỗi ngày 1 lần
        rc = day
        # Không deep freeze
        y_deep.append(proposed_hybrid_decay(1.0, stress_level=0.5, elapsed_days=day, **{**params_deep, "recall_count": rc}))
        # Có deep freeze
        y_deep_frozen.append(proposed_hybrid_decay(1.0, stress_level=0.5, elapsed_days=day, deep_freeze_threshold_recall=10, **{**params_deep, "recall_count": rc}))
        
    # 2. Kịch bản Homeostasis Recovery
    y_normal = []
    y_recovered = []
    
    params_normal = {
        "arousal": 0.5, "valence": 0.3, "importance": 0.6, 
        "layers": 1, "recall_count": 2
    }
    
    for day in days:
        # Không có giấc ngủ chất lượng (Stress Drop 0, Fatigue Drop 0)
        y_normal.append(proposed_hybrid_decay(1.0, stress_level=0.3, elapsed_days=day, **params_normal))
        # Có giấc ngủ chất lượng (Stress giảm 0.5, Fatigue giảm 1.0)
        y_recovered.append(proposed_hybrid_decay(1.0, stress_level=0.3, elapsed_days=day, 
                                                homeostasis_recovery=True, nightly_stress_drop=0.5, nightly_fatigue_drop=1.0, 
                                                **params_normal))

    # Plot
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
    
    # Plot Deep Freeze
    ax1.plot(days, y_deep, 'r--', label='Chưa gắn Deep Freeze')
    ax1.plot(days, y_deep_frozen, 'g-', linewidth=2, label='Có Deep Freeze (Activation tại Day 10)')
    ax1.axvline(x=10, color='gray', linestyle=':', label='Đạt 10 lần Recall')
    ax1.set_title('Thử nghiệm 1: Deep Freeze (Đóng Băng Ký Ức)')
    ax1.set_xlabel('Ngày')
    ax1.set_ylabel('Sức Mạnh (Strength)')
    ax1.set_ylim([0, 1.1])
    ax1.legend()
    ax1.grid(True)
    
    # Plot Homeostasis Recovery
    ax2.plot(days, y_normal, 'b--', label='Chỉ có Decay, ngủ kém')
    ax2.plot(days, y_recovered, 'c-', linewidth=2, label='Có Homeostasis Recovery + Ngủ sâu')
    ax2.set_title('Thử nghiệm 2: Homeostasis Recovery (Phục hồi nội môi)')
    ax2.set_xlabel('Ngày')
    ax2.set_ylabel('Sức Mạnh (Strength)')
    ax2.set_ylim([0, 1.1])
    ax2.legend()
    ax2.grid(True)
    
    plt.tight_layout()
    plt.savefig('outputs/phase18_mechanisms_test.png')
    print("Đã vẽ biểu đồ: outputs/phase18_mechanisms_test.png\n")
    
    # Chạy Semanticization text
    simulate_semanticization()

if __name__ == "__main__":
    main()
