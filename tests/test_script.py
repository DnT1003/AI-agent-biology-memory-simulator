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
    "Hôm qua tôi đi qua ngã tư, có một vụ tai nạn khủng khiếp. Một chiếc xe tải biển số 23A-11911 đã tông vào tôi. Lúc đó tôi thấy một chiếc xe đạp màu xanh lá cây nằm lăn lóc bên đường, và trời đang mưa lất phất.",
    "status",
    "Nhắc lại giùm tôi vụ tai nạn hôm qua đi.",
    "Nhắc lại giùm tôi vụ tai nạn hôm qua đi.",
    "Nhắc lại giùm tôi vụ tai nạn hôm qua đi.",
    "Nhắc lại giùm tôi vụ tai nạn hôm qua đi.",
    "Nhắc lại giùm tôi vụ tai nạn hôm qua đi.",
    "Nhắc lại giùm tôi vụ tai nạn hôm qua đi."
]

for u in inputs:
    print(f"\n👤 Bạn: {u}")
    if u == 'status':
        mem_count = len(ai.memory.get_all())
        print(f"--- STATUS --- Memories: {mem_count} | Mood: {ai.ego.mood:.2f} | Stress: {ai.ego.stress:.2f}")
    else:
        ai.interaction_loop(u)
