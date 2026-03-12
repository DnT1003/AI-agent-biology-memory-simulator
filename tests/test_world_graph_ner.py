import os
import sys

# Đảm bảo PATH trỏ đúng vào dự án
sys.path.append(os.getcwd())

from core.world_graph import WorldGraph
from colorama import Fore, Style

class FakeLLM:
    def generate_json(self, prompt, temperature=0.1):
        # print(f"DEBUG PROMPT: {prompt}")
        if "John" in prompt and "brother" in prompt:
            return [{"source": "User", "relation": "has brother", "target": "John"}]
        return []

def test_world_graph_ner():
    print(f"{Fore.CYAN}--- BẮT ĐẦU KIỂM TRA WORLD GRAPH NER (SPACY) ---{Style.RESET_ALL}")
    
    # 1. Khởi tạo WorldGraph
    wg = WorldGraph(filepath="outputs/test_world_graph.json")
    
    if wg.nlp is None:
        print(f"{Fore.RED}Lỗi: Không load được model spaCy. Kết thúc test.{Style.RESET_ALL}")
        return

    # 2. Test trích xuất thực thể (English)
    text = "My brother is John and he works at Microsoft in New York."
    print(f"\nPhân tích câu: '{text}'")
    entities = wg.extract_entities(text)
    print("Thực thể tìm thấy bởi spaCy NER:")
    for ent in entities:
        print(f" - {ent['text']} [{ent['label']}]")
    
    found_names = [e['text'] for e in entities]
    if "John" in found_names:
        print(f"{Fore.GREEN}✅ Nhận diện tên John chính xác.{Style.RESET_ALL}")
    if "Microsoft" in found_names:
        print(f"{Fore.GREEN}✅ Nhận diện Microsoft chính xác.{Style.RESET_ALL}")

    # 3. Test cập nhật đồ thị
    print(f"\nThử nghiệm cập nhật đồ thị quan hệ...")
    fake_llm = FakeLLM()
    wg.update_from_text(text, fake_llm)
    
    relations = wg.query("John")
    print(f"Kết quả query 'John': {relations}")
    if any("User" in r and "John" in r for r in relations):
        print(f"{Fore.GREEN}✅ Cập nhật quan hệ thành công.{Style.RESET_ALL}")
    else:
        print(f"{Fore.RED}❌ Cập nhật quan hệ thất bại.{Style.RESET_ALL}")


if __name__ == "__main__":
    test_world_graph_ner()
