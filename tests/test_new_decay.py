import math
import matplotlib.pyplot as plt

def old_decay(strength, stress_level, importance, layers, arousal, valence, dt_days=1):
    """Mô phỏng hàm decay cũ của Aura"""
    vulnerability = max(0.01, 1.0 - importance - (layers * 0.05))
    decay_factor = 0.05 * (1 + stress_level * 0.5) * (vulnerability * 5.0)
    emotional_glue = 0.1 + (arousal * 3.0) + (abs(valence) * 2.0) + (layers * 0.5)
    
    # Do hàm cũ gọi trong .sleep() tức là 1 lần/ngày
    return strength * math.exp(-decay_factor / emotional_glue)

def proposed_ebbinghaus_decay(strength, elapsed_days, arousal, valence, recall_count, layers, importance):
    """
    Công thức: S_t = S_0 * exp(-t / R)
    R: Retrievability (Độ ổn định)
    """
    # Tính R (Độ ổn định) phụ thuộc vào tầm quan trọng và cảm xúc
    base_R = 1.0 + (importance * 10.0) + (arousal * 5.0) + (abs(valence) * 3.0)
    
    # Recall và layers làm tăng R theo cấp số nhân (spacing effect)
    current_R = base_R * (1.2 ** recall_count) * (1.1 ** layers)
    
    # S_0 luôn là 1.0 ở thời điểm ban đầu
    S_0 = 1.0
    return S_0 * math.exp(-elapsed_days / current_R)

def proposed_hybrid_decay(strength, stress_level, elapsed_days, arousal, valence, recall_count, layers, importance):
    """
    Công thức Hybrid: Kết hợp độ dốc của hàm Ebbinghaus với tác động của Stress hiện tại.
    Khi Stress cao, não trạng căng thẳng, khả năng giữ trí nhớ hoặc gợi nhớ giảm đi.
    """
    # Tính R (Độ ổn định) phụ thuộc vào tầm quan trọng và cảm xúc
    base_R = 1.0 + (importance * 10.0) + (arousal * 5.0) + (abs(valence) * 3.0)
    
    # Recall và layers làm tăng R theo cấp số nhân (spacing effect)
    current_R = base_R * (1.2 ** recall_count) * (1.1 ** layers)
    
    # Ở hàm Hybrid, R bị suy giảm nếu Stress cao (não bị ức chế, quên nhanh hơn)
    # Stress 0.0 -> R giữ nguyên
    # Stress 1.0 -> R giảm một nửa
    stress_penalty = 1.0 - (stress_level * 0.5) 
    effective_R = current_R * stress_penalty
    
    S_0 = 1.0
    return S_0 * math.exp(-elapsed_days / (effective_R + 1e-6))

def main():
    days = list(range(1, 31))
    
    # Kịch bản 1: Ký ức nhạt nhẽo (Ăn sáng bánh mì)
    s_old_boring = 1.0
    y_old_boring = []
    y_new_boring = []
    y_hybrid_boring = []
    
    params_boring = {
        "arousal": 0.1, "valence": 0.1, "importance": 0.1, 
        "layers": 1, "recall_count": 0
    }
    
    for day in days:
        s_old_boring = old_decay(s_old_boring, stress_level=0.8, **{k:v for k,v in params_boring.items() if k in ['importance', 'layers', 'arousal', 'valence']})
        y_old_boring.append(s_old_boring)
        y_new_boring.append(proposed_ebbinghaus_decay(1.0, day, **params_boring))
        y_hybrid_boring.append(proposed_hybrid_decay(1.0, stress_level=0.8, elapsed_days=day, **params_boring)) # Stress cao làm quên nhanh
        
    # Kịch bản 2: Ký ức đậm sâu (Bị chia tay)
    s_old_deep = 1.0
    y_old_deep = []
    y_new_deep = []
    y_hybrid_deep = []
    
    params_deep = {
        "arousal": 0.9, "valence": -0.8, "importance": 0.9, 
        "layers": 3, "recall_count": 5
    }
    
    for day in days:
        s_old_deep = old_decay(s_old_deep, stress_level=0.5, **{k:v for k,v in params_deep.items() if k in ['importance', 'layers', 'arousal', 'valence']})
        y_old_deep.append(s_old_deep)
        y_new_deep.append(proposed_ebbinghaus_decay(1.0, day, **params_deep))
        y_hybrid_deep.append(proposed_hybrid_decay(1.0, stress_level=0.2, elapsed_days=day, **params_deep))
        

    plt.figure(figsize=(12, 6))
    
    plt.plot(days, y_old_boring, 'b--', label='Cũ: Ký ức nhạt')
    plt.plot(days, y_new_boring, 'b-', label='Ebbinghaus: Ký ức nhạt')
    plt.plot(days, y_hybrid_boring, 'c-', linewidth=2, label='Hybrid (Stress=0.8): Ký ức nhạt')
    
    plt.plot(days, y_old_deep, 'r--', label='Cũ: Ký ức sâu đậm')
    plt.plot(days, y_new_deep, 'r-', label='Ebbinghaus: Ký ức sâu đậm')
    plt.plot(days, y_hybrid_deep, 'm-', linewidth=2, label='Hybrid (Stress=0.2): Ký ức sâu đậm')
    
    plt.axhline(y=0.1, color='gray', linestyle=':', label='Ngưỡng quên lãng (Threshold)')
    
    plt.title('So sánh Công thức Lãng quên: Hybrid vs Ebbinghaus vs Cũ')
    plt.xlabel('Ngày (Days)')
    plt.ylabel('Sức mạnh Ký ức (Strength)')
    plt.legend()
    plt.grid(True)
    
    # Save text report
    print("--- So sánh 30 Ngày (Ký ức NHẠT) ---")
    print(f"Hàm cũ ngày 10: {y_old_boring[9]:.3f} | Ebbinghaus: {y_new_boring[9]:.3f} | Hybrid: {y_hybrid_boring[9]:.3f}")
    print(f"Hàm cũ ngày 30: {y_old_boring[29]:.3f} | Ebbinghaus: {y_new_boring[29]:.3f} | Hybrid: {y_hybrid_boring[29]:.3f}")
    
    print("\n--- So sánh 30 Ngày (Ký ức SÂU ĐẬM) ---")
    print(f"Hàm cũ ngày 10: {y_old_deep[9]:.3f} | Ebbinghaus: {y_new_deep[9]:.3f} | Hybrid: {y_hybrid_deep[9]:.3f}")
    print(f"Hàm cũ ngày 30: {y_old_deep[29]:.3f} | Ebbinghaus: {y_new_deep[29]:.3f} | Hybrid: {y_hybrid_deep[29]:.3f}")
    
    plt.savefig('outputs/decay_comparison.png')
    print("\nĐã vẽ biểu đồ so sánh: outputs/decay_comparison.png")

if __name__ == "__main__":
    main()
