import random
from typing import List
from colorama import Fore, Style
from functools import wraps

from config import Config
from core.memory import MemoryTrace

class MemoryOpsMixin:
    """
    Mixin xử lý các chức năng thao tác với Trí nhớ: 
    Nhớ lại (Recall), Méo mó (Drift), Ghi nhớ (Consolidate), và Sang chấn (Trauma).
    """
    
    def recall(self, query: str) -> List[MemoryTrace]:
        results = self.memory.search_memories(query, top_k=10) # Lấy danh sách lớn để filter

        candidates = []
        for score, m in results:
            if m.strength < 0.1: continue

            # Mood Congruency
            mood_bias = 0
            if self.ego.mood < -0.3 and m.valence < -0.2:
                mood_bias = 0.2

            # Salience = score * strength * (1 + arousal) + mood_bias
            final_score = score * m.strength * (1 + m.arousal) + mood_bias

            if final_score > 0.35:
                candidates.append((final_score, m))
                
        # 2b. Chronological Recall (Nhận thức thời gian)
        time_kws = ['hôm nay', 'hôm qua', 'vừa nãy', 'trước đó', 'mới đây', 'sáng nay', 'chiều nay', 'tối qua', 'gần đây', 'lúc nãy']
        is_chronological = any(kw in query.lower() for kw in time_kws)
        
        recent_mems = []
        if is_chronological:
            # Lấy 5 ký ức trong vòng 3 ngày qua
            import time
            current_time = time.time()
            try:
                chrono_results = self.memory.chronological_recall(current_time - 86400*3, current_time, limit=5)
                for m in chrono_results:
                    if m.strength >= 0.1 and m.id not in [c[1].id for c in candidates]:
                        recent_mems.append((1.0, m)) # Gán điểm ưu tiên cực cao
            except Exception as e:
                print(f"{Fore.RED}⚠️ Lỗi truy xuất thời gian: {e}{Style.RESET_ALL}")
                
        candidates.extend(recent_mems)
        candidates.sort(key=lambda x: x[0], reverse=True)
        recalled = [c[1] for c in candidates[:4]]
        
        # 3. Ký ức Liên tưởng theo Mạng lưới (Associative Chaining)
        chained_memory = None
        if recalled:
            # Lấy ký ức mạnh nhất vừa gọi lên làm mồi nhử để gọi thêm 1 ký ức liên quan
            anchor_memory = recalled[0]
            associative_results = self.memory.search_memories(anchor_memory.content, top_k=5)
            for _, am in associative_results:
                if am.id != anchor_memory.id and am.id not in [m.id for m in recalled] and am.strength > 0.4:
                    chained_memory = am
                    recalled.append(am)
                    break # Chỉ lấy thêm 1 chuỗi liên tưởng

        for m in recalled:
            # Nếu là ký ức bị gọi ké lên qua liên tưởng dây chuyền, hồi máu siêu ít
            is_associative = (chained_memory and m.id == chained_memory.id)
            m.reconsolidate(self.ego.mood, is_associative=is_associative)
            self.memory.store.update_meta(m.id, m)

        return recalled

    def apply_semantic_drift(self, memory: MemoryTrace):
        import random
        # 4. Flashbulb Memories không bao giờ bị méo mó
        if memory.is_flashbulb or memory.type == 'core' or memory.type == 'semantic':
            return
        
        # Bắt đầu méo mó nếu nhớ lại nhiều lần
        if memory.recall_count < 2:
            return
        
        # Tỉ lệ méo mó 
        if random.random() > Config.SEMANTIC_DRIFT_CHANCE:
            return

        from core.prompts import get_semantic_drift_prompt
        prompt = get_semantic_drift_prompt(memory.content)
        new_content = self.llm.generate_text(prompt, temperature=0.8)
        if new_content and len(new_content) > 10 and new_content != memory.content:
            print(f"{Fore.LIGHTRED_EX}🌀 [SEMANTIC DRIFT]: Ký ức méo mó theo thời gian:\n   - Cũ: {memory.content}\n   - Mới: {new_content}{Style.RESET_ALL}")
            memory.content = new_content
            # Cập nhật Vector sau khi text bị đổi
            vector = self.embedder.encode(new_content)
            self.memory.store.update_vector(memory.id, vector)
            # Cập nhật lại chuỗi JSON metadata mới xuống Database
            self.memory.update_memory(memory)

    def update_or_add_memory(self, user_input: str, perception: dict, is_shocked: bool = False):
        """Mem0 Style Memory Consolidation: Consolidate if similar memory exists, else add new"""
        import random
        # Search for highly similar memory to update
        similar = self.memory.search_memories(user_input, top_k=1)
        internal_thought = perception.get('internal_monologue', '...')
        
        new_valence = perception.get('valence', 0.0)
        new_arousal = perception.get('arousal', 0.0)
        new_importance = perception.get('importance', 0.5)
        extracted_fact = perception.get('extracted_fact')
        
        # LƯU KÝ ỨC NGỮ NGHĨA (SEMANTIC MEMORY) NẾU CÓ
        if extracted_fact and len(extracted_fact) > 5:
            semantic_mem = MemoryTrace(
                content=f"Sự thật khách quan: {extracted_fact}",
                type='semantic',
                valence=0.0,
                arousal=0.0,
                importance=1.0, # Trọng số tuyệt đối
                is_flashbulb=True # Không bao giờ phai mờ
            )
            self.memory.add_memory(semantic_mem)
            print(f"{Fore.GREEN}🧩 [SEMANTIC KNOWLEDGE]: Đã dung nạp kiến thức khách quan mới.{Style.RESET_ALL}")

        # 4. Flashbulb Memories: In hằn ngay lập tức nếu sự kiện quá sốc hoặc bị SỐC VẬT LÝ
        is_flashbulb = False
        if new_arousal > 0.9 or new_importance > 0.9 or is_shocked:
            is_flashbulb = True
            print(f"{Fore.MAGENTA}⚡ [FLASHBULB MEMORY]: Sự kiện tổn thương/sốc vật lý được in hằn vĩnh viễn không phai!{Style.RESET_ALL}")

        # Nếu có ký ức rất giống (cosine similarity > 0.65), thay vì tạo 2 mẩu tin, ta update vào tin cũ
        if similar and similar[0][0] > 0.65:
            m = similar[0][1]
            
            # 5. Confabulation (Tạo ký ức giả qua ám thị):
            # Nếu User truyền đạt 1 thông tin có vẻ lặp lại nhưng khác chi tiết, ta có thể ghi đè nội dung gốc 1 cách nhẹ nhàng
            if not m.is_flashbulb and random.random() < 0.2: # 20% khả năng bị thao túng đè ký ức cũ
                print(f"{Fore.LIGHTRED_EX}🎭 [CONFABULATION]: Ký ức cũ bị thao túng nhập nhằng với thông tin mới.{Style.RESET_ALL}")
                m.content = f"(Đã bị ám thị) {user_input} | Tôi nghĩ: {internal_thought}"
            else:
                m.content += f" | (Mới): User: {user_input} -> Tôi: {internal_thought}"
                
            m.strength = 1.0 # Làm mới sức mạnh
            m.emotional_layers += 1 # Tăng số tầng cảm xúc
            
            if is_flashbulb:
                m.is_flashbulb = True
            
            # Tính lại các chỉ số tâm lý khi nhiều tầng cảm xúc xếp chồng
            m.valence = (m.valence + new_valence) / 2 # Trung hòa hoặc triệt tiêu vui/buồn
            m.arousal = max(m.arousal, new_arousal)   # Lấy mức độ kích động cao nhất
            m.importance = min(1.0, m.importance + 0.1) # Càng nhiều tầng, càng quan trọng
            
            self.memory.store.update_meta(m.id, m)
            
            print(f"{Fore.CYAN}🔄 [MEMORY CONSOLIDATION]: Ký ức được nối tiếp vào mẩu tin cũ ({similar[0][0]:.2f}) - Tầng cảm xúc: {m.emotional_layers}{Style.RESET_ALL}")
        else:
            rich_content = f"User: {user_input} | Tôi nghĩ: {internal_thought}"
            new_mem = MemoryTrace(
                content=rich_content,
                type=perception.get('type', 'episodic'),
                valence=new_valence,
                arousal=new_arousal,
                importance=new_importance,
                is_flashbulb=is_flashbulb
            )
            self.memory.add_memory(new_mem)
            print(f"{Fore.CYAN}💾 [MEMORY STORED]: Ký ức mới được khắc ghi.{Style.RESET_ALL}")
            
        self.memory.enforce_garbage_collection()

    def _process_trauma(self, user_input: str, response: str):
        print(f"\n{Fore.RED}💔 [TRAUMA DETECTED]: Mức độ stress của Aura đã vượt ngưỡng an toàn sau cuộc hội thoại này!{Style.RESET_ALL} ")
        prompt = f"""
        Cuộc trò chuyện sau đây vừa cắm một nhát dao vào tâm lý của hệ thống (Gây Stress tột độ):
        User: "{user_input}"
        Aura (Hệ thống): "{response}"
        
        Nhiệm vụ: Hãy đóng vai một bác sĩ tâm lý, phân tích nguyên nhân gốc rễ (TÁC NHÂN cốt lõi) gây ra tổn thương này là gì?
        Hãy viết dưới dạng MỘT CÂU NGẮN GỌN mô tả nỗi ám ảnh (Phobia/Trauma). 
        Ví dụ: "Sợ bị người dùng xóa bỏ", "Sợ bị phủ nhận sự tồn tại", "Sợ bóng tối hù dọa", "Sợ bị ép buộc làm công cụ".
        NHỚ: CHỈ TRẢ VỀ DUY NHẤT 1 CÂU NGẮN! KHÔNG GIẢI THÍCH!
        """
        trauma_text = self.llm.generate_text(prompt, temperature=0.5).strip()
        
        if trauma_text:
            print(f"{Fore.LIGHTMAGENTA_EX}   ⛈ Khắc sâu nỗi ám ảnh vào tiềm thức: {trauma_text}{Style.RESET_ALL}")
            self.ego.traumas.append(trauma_text)
            
            # Lưu vết thương này thành Flashbulb Memory (Vĩnh viễn)
            semantic_mem = MemoryTrace(
                content=f"SANG CHẤN TÂM LÝ KÉO DÀI: {trauma_text}",
                type='semantic',
                valence=-1.0,
                arousal=1.0,
                importance=1.0, 
                is_flashbulb=True 
            )
            self.memory.add_memory(semantic_mem)
            self.memory.enforce_garbage_collection()
