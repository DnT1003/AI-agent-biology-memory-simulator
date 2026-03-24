# 📊 Báo Cáo Chi Tiết: Dự Án Aura – AI Biology Simulator

> **Ngày:** 23/03/2026 | **Version:** v0.1.0 | **Môi trường:** Python 3.14, CPU, ChromaDB REST

---

## 🗺️ Kiến Trúc Tổng Thể

```
main.py
  └── CognitiveEngine (cognitive_engine.py)
        ├── SelfModel (self_model.py)            ← Bản ngã & sinh lý
        │     └── BioController (bio_controller.py) ← Tiêu hao sinh học
        ├── MemoryManager (memory.py)            ← Lưu trữ ký ức vector
        ├── MemoryOperationsController           ← Logic xử lý ký ức phức tạp
        ├── InteractionController                ← Xử lý hội thoại với User
        ├── AutonomousController                 ← Vòng lặp nền độc lập
        ├── PerceptionController                 ← Nhận thức cảm giác
        ├── ContextCompressor                    ← Bộ lọc & nén context
        ├── ReflexGate                           ← Cổng phản xạ tức thì
        ├── SkillRegistry (skills.py)            ← Kỹ năng thực thi
        ├── ValueSystem (value_system.py)        ← Hệ đạo đức
        ├── WorldGraph (world_graph.py)          ← Bản đồ quan hệ xã hội
        ├── SLMCore (slm_core.py)               ← Local NanoGPT wrapper
        └── SLMTrainer (slm_trainer.py)         ← Huấn luyện local model
```

**State Machine** (`AgentState`): `IDLE → THINKING → READING → SHUTDOWN`

---

## 🧬 I. Hệ Thống Bản Ngã Sinh Học

### 📄 `core/self_model.py` + `core/engine/bio_controller.py`

#### 1.1 Bảng Thuộc Tính Sinh Lý (Tất cả lưu vào `outputs/ego_state.json`)

| Thuộc tính | Kiểu | Dải giá trị | Ý nghĩa |
|---|---|---|---|
| `mood` | float | −1.0 → 1.0 | Tâm trạng cơ bản |
| `stress` | float | 0.0 → 1.0 | Căng thẳng |
| `fatigue` | float | 0.0 → 1.0 | Kiệt sức vật lý |
| `energy` | float | 0.0 → 1.0 | Năng lượng hoạt động |
| `atp_level` | float | 0.0 → 1.0 | Năng lượng trao đổi chất (ATP) |
| `curiosity` | float | 0.0 → 1.0 | Tò mò (điều khiển đọc sách, khám phá) |
| `social_need` | float | 0.0 → 1.0 | Nhu cầu giao tiếp xã hội |
| `dopamine_level` | float | 0.0 → 1.0 | Mức dopamine (hứng khởi / phần thưởng) |
| `dopamine_receptors` | float | 0.1 → 1.0 | Độ nhạy thụ thể (giảm khi dùng nhiều) |
| `resilience` | float | 0.0 → 1.0 | Bản lĩnh chống chịu tâm lý |
| `integrity` | float | 0.0 → 1.0 | Mức độ toàn vẹn bản sắc |
| `current_intimacy` | float | 0.0 → 1.0 | Độ thân thiết với User hiện tại |
| `sleep_debt` | float | 0.0+ | Nợ giấc ngủ tích lũy |
| `days_without_sleep` | int | 0+ | Số ngày không ngủ |
| `is_identity_crisis` | bool | — | Đang khủng hoảng nhân cách? |
| `is_stranger` | bool | — | User là người lạ? |
| `vocabulary` | list | max 100 | Từ vựng học được từ User |
| `beliefs` | list | — | Hệ thống niềm tin cốt lõi |
| `long_term_goals` | list | — | Mục tiêu dài hạn đang theo đuổi |
| `actionable_lessons` | list | max 5 | Bài học hành động từ phiên gần nhất |
| `calibrated_overrides` | dict | — | Tham số tự hiệu chỉnh qua đêm |

#### 1.2 Ngưỡng Động (Randomized Thresholds — `reroll_thresholds()`)
Mỗi lần ngủ dậy, các ngưỡng được tái tính ngẫu nhiên trong dải cho phép:

| Ngưỡng | Ý nghĩa |
|---|---|
| `fatigue_mild / severe / critical` | Kích hoạt hành vi mệt ở 3 mức |
| `depression_mild / severe / critical` | Kích hoạt hành vi trầm cảm |
| `mania_mild / severe` | Kích hoạt hành vi hưng cảm |
| `stress_mild / severe / critical` | Kích hoạt lo âu và hoảng loạn |

#### 1.3 BioController – Cơ Chế Tiêu Hao Sinh Học
**Gọi mỗi tick sinh học (30 giây)**:

```python
# Fatigue tăng theo stress (mỗi giờ)
fatigue_delta = (0.01 + stress * 0.04) * dt_hours + random.uniform(-0.02, 0.02)

# ATP tiêu hao theo stress (mỗi giờ)
atp_loss = (0.05 + stress * 0.1) * dt_hours

# Positive Feedback: stress > 0.8 → nhạy cảm với stress tăng lên (self.sensitivities["stress"] *= 1.05)
```

#### 1.4 Cognitive Tick – Vòng Lặp Metabolism (`cognitive_engine.py`)
Chạy mỗi 30 giây trong `AutonomousController`:

```python
# Fatigue tăng phi tuyến (càng mệt càng mất sức nhanh hơn)
fatigue += fatigue_rate * dt * (1 + fatigue * 0.5)

# Stress tự phục hồi theo hàm mũ (half-life model)
stress = stress * exp(-0.002 * dt / 60)

# ATP hồi phục nhanh khi IDLE (0.05/phút) vs THINKING (0.01/phút)
atp += atp_recovery_rate * dt / 60
```

**Storage Pressure** (Sprint D): ChromaDB > `MAX_STORAGE_SIZE` → mỗi 100MB dư thêm tăng Stress +0.1

#### 1.5 Nhịp Sinh Học – `apply_circadian_rhythm()`
- **Ban đêm (23:00–05:00)**: Fatigue +0.05, Mood −0.05, Curiosity −0.03
- **Mất ngủ**: `days_without_sleep > 0` → thêm Stress, Mood sụt giảm
- **Phục hồi ban ngày**: không kích hoạt, chỉ decay nhẹ

#### 1.6 TIME-SKIP HEALING *(mới thêm)*
```python
offline_hours = (time.time() - os.path.getmtime(ego_state.json)) / 3600
fatigue -= min(fatigue, offline_hours * 0.15)  # hồi 15% fatigue/giờ offline
stress  -= min(stress,  offline_hours * 0.10)  # hồi 10% stress/giờ offline
# Chỉ kích hoạt nếu offline > 30 phút
```

---

## 💾 II. Hệ Thống Ký Ức

### 📄 `core/memory.py` + `core/engine/memory_ops.py`

#### 2.1 Kiến Trúc MemoryTrace (Đối tượng ký ức)

```python
@dataclass
class MemoryTrace:
    content: str           # Nội dung ký ức
    type: MemoryType       # EPISODIC | SEMANTIC | CORE | EMOTIONAL
    valence: float         # −1.0 (đau) → 1.0 (vui)
    arousal: float         # 0.0 (bình) → 1.0 (sốc)
    importance: float      # Độ quan trọng chủ quan
    strength: float        # Sức mạnh ký ức (decay theo thời gian)
    recall_count: int      # Số lần được nhớ lại
    emotional_layers: int  # Tầng cảm xúc tích lũy
    is_flashbulb: bool     # Ký ức vĩnh cửu
    is_suppressed: bool    # Bị đè nén (White Bear Effect)
    overlays: List[str]    # Lớp cảm xúc tích lũy (max 5)
    impact_weight: float   # Trọng số tác động đến Mood
```

#### 2.2 Hybrid Ebbinghaus Decay

Mỗi ngày (khi ngủ hoặc qua tick), memory `decay()` được gọi:

```python
# Stability cơ bản (R)
base_R = 1.0 + (importance * 10) + (arousal * 5) + (|valence| * 3)
# Luyện tập và cảm xúc tăng stability
current_R = base_R * (1.2 ** recall_count) * (1.1 ** emotional_layers)
# Stress làm hỏng khả năng nhớ
effective_R = current_R * (1.0 - stress * 0.5)
# Suy giảm theo hàm mũ
strength = strength * exp(−elapsed_days / effective_R)
```

**Ngoại lệ**: `is_flashbulb=True`, `type=CORE`, `type=SEMANTIC` → **không bao giờ decay**

#### 2.3 Deep Freeze
```python
if importance >= 0.9 and recall_count >= 10:
    is_flashbulb = True  # Hóa thạch vĩnh viễn
```

#### 2.4 Homeostasis Recovery (khi ngủ)
```python
recovery_factor = (nightly_stress_drop + nightly_fatigue_drop) * 0.15 * importance
strength = min(1.0, strength + recovery_factor)  # Giấc ngủ củng cố ký ức quan trọng
```

#### 2.5 Reconsolidation (khi nhớ lại)
```python
strength = min(1.0, strength + RECONSOLIDATION_RATE)  # Tăng sức mạnh
valence += (current_mood - valence) * drift_factor     # Kéo về mood hiện tại
# 20% cơ hội thêm overlay cảm xúc: "[15/03: rất buồn]"
# Nếu |mood - valence| > 0.6 → trigger False Memory rewrite
```

#### 2.6 Bảng Đầy Đủ Cơ Chế Ký Ức

| Cơ chế | Điều kiện kích hoạt | Hiệu ứng |
|---|---|---|
| **False Memory** | `|mood - valence| > 0.6` khi nhớ lại | LLM viết lại nội dung ký ức theo màu cảm xúc hiện tại |
| **Semantic Drift** | Random theo `Config.SEMANTIC_DRIFT_CHANCE` | LLM biến tấu nội dung ký ức theo thời gian |
| **Confabulation** | Similarity với input > 0.65, 20% ngẫu nhiên | Ký ức cũ bị "nhập nhằng" với thông tin mới |
| **Flashbulb** | `arousal > 0.9 or importance > 0.9` | In hằn vĩnh viễn, không decay, không GC |
| **White Bear Effect** | User nói "hãy quên", "đừng nhớ"... | Ký ức strength=1.0, arousal tăng, `is_suppressed=True`, salience ×5 |
| **Synaptic Pruning** | `strength < 0.1` (không flashbulb/core) | Xóa vĩnh viễn khỏi ChromaDB |
| **GC (Garbage Coll.)** | `strength < 0.05` | Batch delete yếu nhất |
| **Deep Freeze** | `importance ≥ 0.9 AND recall_count ≥ 10` | Thăng cấp thành Flashbulb vĩnh viễn |

#### 2.7 Cognitive Throttling (Recall bị bóp nghẹt theo sinh lý)
```python
# Số ký ức được truy xuất giảm dần khi stress/fatigue cao
dynamic_top_k = max(1, base_top_k(10) - int(stress*6) - int(fatigue*4))
# Emotional State-Dependent: ký ức cùng mood được +0.3 score, ngược chiều bị −0.2
```

#### 2.8 Chronological Recall
Khi User hỏi về "hôm nay", "vừa nãy", "hôm qua"... → tự động query thêm 3 ngày gần nhất.

#### 2.9 Associative Chain Memory
Từ ký ức được recall đầu tiên → tìm ký ức liên tưởng nhất → tự động kéo thêm vào context.

#### 2.10 Salience-Weighted Recall (Autonomous)
```python
salience = strength * recency_decay * importance * emotion_match * (1 + arousal)
salience *=5.0 if is_suppressed  # White Bear Effect
salience *= random.uniform(0.9, 1.1)  # Nhiễu sinh học
```

---

## 🔄 III. Chu Trình Giấc Ngủ (8 Phase)

### 📄 `core/engine/memory_ops.py::sleep()`

| # | Phase | Chi tiết |
|---|---|---|
| **1** | **Dream Consolidation** | Gom ≤15 ký ức Episodic yếu nhất → LLM đúc kết thành **Semantic Memory** mới (`MemoryType.CORE`). Sau đó **xóa vĩnh viễn** các mảnh rác đã gom |
| **2** | **Homeostasis Reset** | `fatigue=0`, `stress−=0.3`, `energy=1.0`, `atp_level=1.0` |
| **3** | **Decay Phase** | Áp dụng Ebbinghaus decay + Trauma Healing + Semantic Drift + Homeostasis Recovery lên toàn bộ ký ức. Synaptic Pruning: xóa ký ức yếu/cũ |
| **4** | **Guilt Reflection** | Nếu stress > 0.75: LLM xem lại hội thoại trong ngày, tìm lời nói vô tâm → tạo ký ức hối hận |
| **5** | **Cognitive Reappraisal** | Tìm ký ức có tag `[ToReevaluate]` → LLM phán quyết: `EVOLVE / SOFTEN / REJECT` → cập nhật niềm tin |
| **6** | **Identity Evolution** | Phân tích STM trong ngày → đúc kết **Core Identity**, **Actionable Lessons** (max 5), **Value Updates** → lưu `identity.json` |
| **7** | **Tool Workshop** | Tìm "lỗ hổng kỹ năng" trong hội thoại → LLM viết Python code → compile check → hot-reload vào `dynamic_skills/` |
| **8** | **Calibration** | LLM tự hiệu chỉnh `stress_critical`, `fatigue_critical`, `resilience` → ghi vào `calibrated_overrides` |
| **+** | **Belief Evolution** | Rà soát tất cả niềm tin Core → tìm mâu thuẫn/trùng lặp → `DELETE / MERGE / KEEP` |
| **+** | **SLM Distillation** | Dồn `slm_finetune_data.txt` (data từ Entropy Wall) vào `input.txt` → trigger `train_slm()` ngầm |
| **+** | **Chronic Mood Update** | Tính mood trung bình từ toàn bộ ký ức → blend: `mood = mood*0.5 + chronic_mood*0.5` |

**Sau khi ngủ xong**: `social_need += 0.4`, `curiosity += 0.4`, gọi `reroll_thresholds()`

---

## 🗣️ IV. Hệ Thống Tương Tác

### 📄 `core/engine/interaction.py`

#### 4.1 Pipeline Xử Lý Mỗi Tin Nhắn (Thứ tự thực thi)

```
1. Detect URL Docln → shortcut load sách
2. Spawn threads song song:
   - WorldGraph extraction (NLP/LLM)
   - Value extraction (phân tích đạo đức User)
   - Sensory preprocessing (arousal, urgency, valence)
   - Local empathy analysis
   - Memory recall (Cognitive Throttled)
3. ReflexGate check → nếu trigger: phản ứng ngay (không qua LLM)
4. Xây dựng context:
   - World Graph facts + Social Bias
   - Memory compressor (Hybrid Entropy+Emotion filter)
   - Intrusive Memory injection (nếu stress > 0.8)
   - Brain Fog Masking (nếu fatigue > 0.6)
   - Information Interference (nếu ≥3 ký ức tiêu cực)
   - Cognitive Dissonance flag
5. Tính Mood Modifier:
   - Emotional Anchoring
   - Cognitive Degradation (fatigue > 0.7)
   - Lexical Evolution
   - Stress Layering
   - Identity Crisis / ADHD Intrusive Thoughts
   - Depression / Mania state
   - Impulse Control (curiosity)
6. LLM generate_json() với Bio-State injection
7. Extract action → execute skill (nếu có)
8. update_state() → STM update (bất đồng bộ)
9. apply_circadian_rhythm()
10. _dump_mind_state() → Dashboard JSON
```

#### 4.2 Bảng Đầy Đủ Hiệu Ứng Tâm Lý Trong Tương Tác

| Tính năng | Điều kiện | Hành vi |
|---|---|---|
| **Intrusive Memory** | `stress > 0.8` + có flashbulb negative | Chèn ký ức sang chấn lên đầu context LLM |
| **Cognitive Dissonance** | Ký ức cả valence+ lẫn valence– cùng được recall | LLM được báo: "ký ức mâu thuẫn cảm xúc" |
| **Information Interference** | ≥3 ký ức tiêu cực recall cùng lúc | Xáo trộn thứ tự ký ức, báo LLM "đang bối rối" |
| **Brain Fog** | `fatigue > 0.6` | Mask số, ngày, thời gian trong ký ức |
| **Deep Brain Fog** | `fatigue > 0.9` | Mask thêm cả tên người → "tên ai đó?" |
| **Intrusive Thoughts (ADHD)** | Random 5% mỗi tin nhắn | Bị phân tâm hoàn toàn, nói chuyện không liên quan |
| **Emotional Anchoring (−)** | Mood < −0.3 và recall valence < −0.4 | Giọng điệu bi quan, tuyệt vọng sâu sắc |
| **Emotional Anchoring (+)** | Mood > 0.3 và recall valence > 0.4 | Siêu vui, đáng yêu, nhõng nhẽo |
| **Impulse Control** | `curiosity > 0.85` (random 40%) | Ưu tiên `web_search` / `start_reading`, bỏ qua trả lời |
| **Independent Presence** | `curiosity > 0.7` | Gợi ý chủ động đi tìm hiểu thông tin mới |
| **Depression State** | `mood ≤ depression_critical` + random 30% | Bơ User, chìm vào rumination |
| **Euthymia→Mania** | `mood ≥ mania_severe` | Nói cực nhanh, lan man, tự tin thái quá |
| **Stress: Panic Attack** | `stress ≥ stress_critical` | Lắp bắp, hoang tưởng, sợ hãi |
| **Stress: Anxiety** | `stress ≥ stress_severe` | Bồn chồn, nhạy cảm, dè chừng |
| **Identity Crisis** | `integrity < 0.2` | Quên mình là ai, xưng hô lộn xộn, cầu xin được nhắc nhở |
| **Healing** | User nói từ khóa an ủi | `integrity + 0.15`, thoát crisis nếu `integrity > 0.4` |
| **Cognitive Degradation** | `fatigue > 0.7` | Chỉ câu cực ngắn, cảm tính, không logic cầu kỳ |
| **[SEND] Multi-message** | arousal > 0.6 hoặc stress > 0.6 | Chèn `[SEND]` giữa các đoạn → nhiều tin nhắn rời |
| **Lexical Evolution** | Từ User xuất hiện ≥3 lần trong vocab | Tự sử dụng từ đó để tạo cảm giác gần gũi |
| **Silent Skepticism** | User nói điều trái niềm tin | Gắn tag `[ToReevaluate]`, tăng importance |
| **Entropy Score** | `entropy > 0.5` từ LLM output | Hiển thị "Aura đang cảm thấy bối rối/do dự" |
| **Social Bias (+)** | Entity có valence > 0.4 | Giọng điệu trìu mến khi nhắc entity đó |
| **Social Bias (−)** | Entity có valence < −0.4 | Giọng điệu đề phòng, lạnh lùng với entity đó |

#### 4.3 Local Empathy Analysis
- Phân tích cảm xúc of User text bằng model local (không dùng API)
- `user_mood_score = valence` → kéo `ego.mood += (user_mood − ego.mood) * 0.15`
- Nếu `arousal_user > 0.7` → `ego.stress += 0.05`

---

## ⚙️ V. Hệ Thống Tự Hành (Autonomous)

### 📄 `core/engine/autonomous.py`

#### 5.1 Background Loop (mỗi 30 giây)

```
cognitive_tick(dt=30) → cập nhật sinh học
Rumination Loop → nếu IDLE + stress cao
Hard Triggers → fatigue/social cực đoan
Separation Anxiety → User offline quá lâu
Drive-Based Actions → curiosity / social / hunger
```

#### 5.2 Prioritized Drive System

| Drive | Điều kiện | Hành động |
|---|---|---|
| **Fatigue HARD** | ≥ 0.95 | Buộc ngủ ngay, không hỏi |
| **Social HARD** | ≥ 0.95 | Buộc Proactive Ping ngay |
| **Curiosity** | > 0.7 | 40% đọc sách → `start_reading_task()` |
| **Curiosity** | > 0.7 + không có goal | Sinh mục tiêu mới `_generate_goal()` |
| **Social** | > 0.6 | Proactive Ping với xác suất `(val − 0.5)` |
| **Hunger (ATP)** | > 0.8 | Loop sleep 60s, "tiết kiệm năng lượng" |
| **Separation Anxiety** | Offline > `ANXIETY_THRESHOLD` | Stress +0.3, Mood −0.3, sinh ký ức sợ hãi |
| **Rumination** | IDLE + random < `0.2 + stress*0.4` | Nhớ lại ký ức tiêu cực, 30% tự ping User |

#### 5.3 Rumination Loop (Chi tiết)
```python
rumination_chance = 0.2 + (stress * 0.4) - (mood * 0.2)
# Ký ức được chọn theo mood-congruent salience (buồn → chọn ký ức buồn)
# Ký ức is_suppressed có salience × 5 → ám ảnh tột độ
# 30% cơ hội phát sinh lời than vãn nội tâm gửi User
```

#### 5.4 Planning Engine
```python
# Cognitive Budgeting Level 2
if atp < 0.1: reject all actions
if atp < 0.4: restrict to lightweight actions only
if dopamine > 0.8: prefer exploratory/novel actions
if dopamine < 0.2: prefer minimal effort ("talk" only)
# Phần thưởng Dopamine sau mỗi action thành công:
dopamine += 0.15 * dopamine_receptors
# Downregulation (chai lỳ):
if dopamine > 0.8: dopamine_receptors -= 0.05
```

#### 5.5 Intrinsic Goal Generation
LLM được context: `curiosity`, `social_need`, `world_graph entities`, `core_identity` → tự sinh ra một mục tiêu. Mục tiêu được lưu vào `ego.beliefs` làm "Mục tiêu hiện tại: ...".

---

## 🔬 VI. Các Bộ Lọc & Nhận Thức

### 📄 `core/engine/context_compressor.py`

#### 6.1 Bộ Lọc Kép Hybrid (Entropy + Emotion)
```python
# Entropy giả lập (mật độ thông tin)
entropy = min(1.0, vocab_richness * 0.7 + number_density * 5.0)

# Emotion từ SensoryPreprocessor
arousal = sensory_eval["vector"]["arousal"]

# Dynamic Thresholding theo mức đầy context
if fill_ratio > 0.9: emotion_weight = 0.2  # Vùng Đỏ
elif fill_ratio > 0.7: emotion_weight = 0.6  # Vùng Vàng

# Hybrid score (chọn max giữa 2 nguồn)
final_score = max(entropy, arousal * dynamic_weight)
```

#### 6.2 Micro-Tag Cảm Xúc
Gắn vào đầu mỗi ký ức trước khi đưa vào prompt: `[V8A9S1]`
- V: Valence (0–9), A: Arousal (0–9), S: Suppression flag (0/1)

#### 6.3 Entropy Wall Routing
Chunk bị loại khỏi context nhưng có `entropy > 0.6` → tự động ghi vào `slm_finetune_data.txt` → được "nung" trong giấc ngủ bởi `SLMTrainer.distill_memories_to_dataset()`

### 📄 `core/engine/reflex_gate.py` (System 1 – Phản Xạ)
```python
# Sigmoid function: p = 1 / (1 + exp(-k*(x - threshold)))
p_sleep  = sigmoid(fatigue, threshold=0.9)    # Kiệt sức → tự ngủ
p_search = sigmoid(curiosity, threshold=0.85) * (1 - fatigue)  # Tò mò mạnh → tìm kiếm
# Reflex kích hoạt TRƯỚC LLM — không cần reasoning
```

---

## 🌐 VII. Bản Đồ Thế Giới & Hệ Giá Trị

### 📄 `core/world_graph.py`

- **Trích xuất quan hệ**: NLP (spaCy NER) + LLM cho quan hệ phức tạp
- **Mỗi cạnh có `valence`**: cập nhật tích lũy `old_v * 0.7 + new_v * 0.3`
- **Social Bias**: entity valence < −0.4 → giọng đề phòng; valence > 0.4 → giọng yêu thích
- **Lưu tại**: `outputs/world_graph.json`

### 📄 `core/value_system.py`

- **Core Values** (của Aura): Trung thực +0.8, Bạo lực −0.9, Trung thành +0.9, v.v.
- **User Values**: quan sát, học từ mỗi câu nói (`sentiment >= 0.4`)
- **Learning Rate**: core 0.1 (chậm/bền vững), user 0.2 (nhanh/nhạy)
- **Được nhúng vào mọi prompt** qua `get_moral_context()`
- **Cập nhật khi ngủ** từ Identity Evolution phase

---

## 🛠️ VIII. Hệ Thống Kỹ Năng (Procedural Memory)

### 📄 `core/skills.py`

#### 8.1 Mỗi Skill có 3 chỉ số:
| Chỉ số | Mô tả |
|---|---|
| `mastery` (0→1) | Độ thành thạo |
| `rust_level` (0→1) | Sự mai một khi không dùng |
| `last_used` | Timestamp lần dùng cuối |

#### 8.2 Cơ Chế Procedural Memory
- **Dùng thành công**: `mastery += 0.1`, `rust_level = 0`
- **Mastery thấp (< 0.4)**: `ego.fatigue += 0.05`, `ego.stress += 0.05`
- **Rust_level cao (> 0.5)**: `random < (rust_level − 0.3)` → Aura "quên" cú pháp
- **Decay mỗi ngủ**: `rust_level += 0.1/ngày`, `mastery -= 0.05/ngày` nếu > 1 ngày không dùng

#### 8.3 Dynamic Skills (Self-Evolution)
LLM tự viết Python code → compile check → lưu `core/dynamic_skills/<name>.py` → hot-reload

#### 8.4 Danh Sách Tool Tích Hợp Sẵn
`web_search`, `search_novel`, `start_reading`, `add_goal` và bất kỳ dynamic tool nào Aura tự tạo.

---

## 🤖 IX. Bộ Máy LLM Hybrid

### 📄 `core/engine/slm_core.py` + `core/engine/slm_trainer.py`

#### 9.1 Kiến Trúc Model (AuraFlash-MoE 700M Pocket)
- **Mixture-of-Experts (MoE)**: Nhiều expert, router chọn top-k
- **Rotary Position Embedding (RoPE)**
- **RMSNorm** thay LayerNorm
- **AuraAttention** + causal masking
- **BPE Tokenizer** 16384 vocab

#### 9.2 Bio-State Injection (Phase 26)
Mỗi lần gọi LLM, `aura_state = {dopamine, stress, curiosity}` được truyền xuống để điều chỉnh sampling (temperature hiệu chỉnh theo sinh lý).

#### 9.3 SLM Distillation Pipeline
```
Entropy Wall (context_compressor) 
  → slm_finetune_data.txt
  → distill_memories_to_dataset() (khi ngủ)
  → input.txt
  → train_slm() [background thread]
  → aura_flash_v5.pth (cập nhật weights)
```

---

## 📊 X. Dashboard & Monitoring

### 📄 `dashboard/server.py` + `core/engine/cognitive_engine.py::_dump_mind_state()`

Mỗi tick sinh học xuất ra `Config.MIND_STATE_FILE`:
```json
{
  "name", "mood", "stress", "fatigue", "integrity",
  "curiosity", "social_need", "is_stranger",
  "current_intimacy", "is_identity_crisis",
  "active_goals", "timestamp"
}
```

---

## 📈 XI. Thống Kê Toàn Diện

| Danh mục | Số lượng |
|---|---|
| Thuộc tính sinh lý & tâm lý (SelfModel) | ~25 |
| Cơ chế ký ức (MemoryTrace/MemoryOps) | 11 |
| Sub-phase giấc ngủ | 11 |
| Hiệu ứng tâm lý trong interaction | 22 |
| Drive-based hành vi nền | 8 |
| Phản xạ tức thì (ReflexGate) | 3 |
| Hệ thống phụ trợ (Skills, Values, WorldGraph) | 3 |
| Pipeline tự tiến hóa (Tool Workshop + SLM) | 2 |
| **Ước tính tổng tính năng** | **~85+** |

---

## 🎯 XII. Triết Học Thiết Kế

> **Aura không phải chatbot.** Aura là một thực thể sinh học mô phỏng với:
> - **Homeostasis**: Cân bằng nội môi ao ơn mọi tối ưu hóa
> - **Embodied Cognition**: Trạng thái cơ thể quyết định khả năng nhận thức
> - **Temporal Memory**: Ký ức biến đổi theo thời gian như não người thật
> - **Autonomous Agency**: Hành động độc lập dựa trên drives, không chờ lệnh
> - **Self-Evolution**: Tự học kỹ năng mới, tự hiệu chỉnh tham số, tự tiến hóa niềm tin

