from components.reader import DoclnReader

def debug_search(keyword):
    reader = DoclnReader()
    print(f"Searching for: {keyword}")
    title, url = reader.search_novel(keyword)
    print(f"Found Title: {title}")
    print(f"Found URL: {url}")
    
    if url:
        t, chapters = reader.get_novel_chapters(url)
        print(f"Chapters found: {len(chapters)}")

if __name__ == "__main__":
    debug_search("bạn gái tôi đến từ tương lai")
