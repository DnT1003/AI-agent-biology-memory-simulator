from components.reader import DoclnReader
from bs4 import BeautifulSoup

def debug_novel_page(url):
    reader = DoclnReader()
    print(f"Fetching: {url}")
    html = reader._get_html(url, wait=5)
    
    with open("docln_debug.html", "w", encoding="utf-8") as f:
        f.write(html)
    
    soup = BeautifulSoup(html, 'html.parser')
    
    title_tag = soup.select_one('.series-name a') or soup.select_one('h1')
    print(f"Title found: {title_tag.text.strip() if title_tag else 'None'}")
    
    chapters = soup.select('.chapter-name a')
    print(f"Chapters found: {len(chapters)}")
    
    if chapters:
        print("First 3 chapters:")
        for a in chapters[:3]:
            print(f"- {a.text.strip()} ({a.get('href')})")
    else:
        print("SELECTOR FAILED or NO CHAPTERS.")
        # Try alternative selectors
        print("Trying alternative: '.list-chapters a'")
        alt = soup.select('.list-chapters a')
        print(f"Alt chapters: {len(alt)}")
        
        print("Trying alternative: 'hr + ul a'")
        alt2 = soup.select('hr + ul a')
        print(f"Alt2 chapters: {len(alt2)}")

if __name__ == "__main__":
    debug_novel_page("https://docln.net/ai-dich/24822-ban-gai-cua-toi-den-tu-tuong-lai")
