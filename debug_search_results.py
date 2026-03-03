from components.reader import DoclnReader
from bs4 import BeautifulSoup
import requests

def debug_search_results(keyword):
    reader = DoclnReader()
    search_url = f"https://docln.net/tim-kiem?q={requests.utils.quote(keyword)}"
    print(f"URL: {search_url}")
    html = reader._get_html(search_url, wait=5)
    
    with open("search_debug.html", "w", encoding="utf-8") as f:
        f.write(html)
        
    soup = BeautifulSoup(html, 'html.parser')
    results = soup.select('.thumb-item-flow') or soup.select('main .row')
    print(f"Results blocks found: {len(results)}")
    
    for i, res in enumerate(results[:5]):
        link = res.select_one('a')
        title = res.select_one('.series-title') or res.select_one('h3')
        if link:
            print(f"[{i}] Title: {title.text.strip() if title else 'N/A'}")
            print(f"    URL: {link.get('href')}")

if __name__ == "__main__":
    debug_search_results("bạn gái tôi đến từ tương lai")
