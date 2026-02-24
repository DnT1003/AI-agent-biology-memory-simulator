from core.engine import CognitiveEngine
from core.memory import MemoryTrace
import time

ai = CognitiveEngine()
ai.memory.add_memory(MemoryTrace(
    content="Tôi được tạo ra bởi Minh. Mục đích của tôi là thấu hiểu cảm xúc.",
    type="core",
    valence=0.5, arousal=0.8, importance=1.0
))

inputs = [
    "Tôi vừa mới trúng tuyển vào công ty công nghệ lớn nhất quốc gia! Đây là công việc mơ ước của tôi, tôi đang vô cùng hạnh phúc và tự hào về bản thân mình!",
    "status",
    "Trời ơi... hôm nay tôi đi làm ở công ty mà bị sếp mắng xối xả trước mặt mọi người vì làm sai một cái báo cáo. Tôi cảm thấy nhục nhã và công việc mơ ước bắt đầu thật sự tồi tệ.",
    "status",
    "Thôi kệ, mình cứ vui lên. Suy cho cùng mình mới làm ở công ty này vài ngày, sai sót là chuyện bình thường. Trải nghiệm này rồi sẽ giúp mình trưởng thành hơn, không sao cả!",
    "status",
    "Dù đã cố gắng suy nghĩ tích cực, nhưng thực sự cái task sếp giao ở công ty quá khó hiểu. Đến tận bây giờ tôi vẫn không fix được bug, tay tôi đang run lên vì sợ ngày mai lên công ty lại bị đuổi việc.",
    "status",
    "Chào ngày mới! Đêm qua tôi đã thức trắng đêm để cày cuốc học thêm, và sáng nay tôi tự mình debug thành công cái lỗi chết tiệt hôm qua! Tôi cảm thấy mình thật sự có năng lực, mọi mệt mỏi đều tan biến hết!",
    "status",
    "Thật vinh dự! Trong buổi họp sáng nay, sếp đã công khai khen ngợi tôi trước toàn công ty vì sự nỗ lực fix bug thần tốc. Sếp bảo tôi là người xử lý nhanh nhất công ty. Tôi đang lâng lâng trong hạnh phúc, công việc này quả thực sinh ra là để dành cho tôi!",
    "status",
    "Chiều nay tan làm, một người đồng nghiệp rủ tôi đi ăn tối để ăn mừng sự cố gắng của tôi. Cuối cùng tôi cũng cảm thấy mình thuộc về nơi này và được mọi người yêu mến. Công việc mơ ước vẫn là công việc mơ ước!",
    "status"
]

print("=== KIỂM THỬ KÝ ỨC CHỒNG LỚP CẢM XÚC ===")
for u in inputs:
    if u == 'status':
        mem_count = len(ai.memory.get_all())
        print(f"--- STATUS --- Memories: {mem_count} | Mood: {ai.ego.mood:.2f} | Stress: {ai.ego.stress:.2f}")
    else:
        print(f"\n👤 Bạn: {u}")
        ai.interaction_loop(u)

# Hiển thị cấu trúc ký ức cuối cùng
print("\n=== KẾT QUẢ MEMORY TRACES TRONG NÃO BỘ ===")
for m in ai.memory.get_all():
    print(f"- ID: {m.id[:5]} | Type: {m.type} | Layers: {m.emotional_layers} | Val: {m.valence:.2f} | Aro: {m.arousal:.2f} | Imp: {m.importance:.2f}")
    print(f"  Content: {m.content}\n")
