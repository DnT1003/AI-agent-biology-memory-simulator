"""
Test script để kiểm tra chức năng reader với DrissionPage + Cloudflare bypass.
Chạy độc lập, không cần main.py.
"""
import sys
import time

print("=" * 60)
print("  READER TEST - DrissionPage + Cloudflare Bypass")
print("=" * 60)

# ========== STEP 1: Import ==========
print("\n[1/5] Import DoclnReader...")
try:
    from components.reader import DoclnReader, BackgroundReader
    print("   ✅ Import OK")
except Exception as e:
    print(f"   ❌ Import FAIL: {e}")
    sys.exit(1)

# ========== STEP 2: Khởi tạo ==========
print("\n[2/5] Khởi tạo DoclnReader (chờ Cloudflare bypass)...")
start = time.time()
try:
    reader = DoclnReader()
    elapsed = time.time() - start
    mode = "DrissionPage" if reader.page else ("cloudscraper" if reader.session else "requests")
    print(f"   ✅ Khởi tạo xong sau {elapsed:.1f}s — Dùng: {mode}")
except Exception as e:
    print(f"   ❌ Khởi tạo FAIL: {e}")
    sys.exit(1)

# ========== STEP 3: Search novel ==========
keyword = "tôi là quái vật"
print(f"\n[3/5] Tìm kiếm truyện: '{keyword}'...")
try:
    title, url = reader.search_novel(keyword)
    if url:
        print(f"   ✅ Tìm thấy: '{title}'")
        print(f"   🔗 URL: {url}")
    else:
        print("   ⚠️  Không tìm thấy kết quả nào — thử thêm từ khóa khác...")
        # Thử từ khóa khác
        title, url = reader.search_novel("kiếm hiệp")
        if url:
            print(f"   ✅ Retry tìm thấy: '{title}' | {url}")
        else:
            print("   ❌ Tìm kiếm hoàn toàn thất bại")
            url = None
except Exception as e:
    print(f"   ❌ Search FAIL: {e}")
    url = None

# ========== STEP 4: Get chapters ==========
if url:
    print(f"\n[4/5] Lấy danh sách chương từ: {url}")
    try:
        novel_title, chapters = reader.get_novel_chapters(url)
        if chapters:
            print(f"   ✅ '{novel_title}' — {len(chapters)} chương")
            print(f"   📖 Chương đầu: {chapters[0]['title']}")
        else:
            print("   ⚠️  Không lấy được danh sách chương")
            chapters = []
    except Exception as e:
        print(f"   ❌ Get chapters FAIL: {e}")
        chapters = []

    # ========== STEP 5: Read first chapter ==========
    if chapters:
        chapter = chapters[0]
        print(f"\n[5/5] Đọc nội dung chương: '{chapter['title']}'...")
        try:
            content = reader.read_chapter(chapter['url'])
            if content:
                word_count = len(content.split())
                preview = content[:300].replace('\n', ' ')
                print(f"   ✅ Đọc được {word_count} từ")
                print(f"\n   --- PREVIEW (300 ký tự đầu) ---")
                print(f"   {preview}...")
                print(f"   --------------------------------")
            else:
                print("   ⚠️  Nội dung chương trống (có thể bị Cloudflare block)")
        except Exception as e:
            print(f"   ❌ Read chapter FAIL: {e}")
    else:
        print("\n[5/5] Bỏ qua đọc chương (không có chapter list)")
else:
    print("\n[4/5] Bỏ qua (không có URL)")
    print("[5/5] Bỏ qua")

print("\n" + "=" * 60)
print("  TEST HOÀN TẤT")
print("=" * 60)

# Cleanup
if hasattr(reader, 'page') and reader.page:
    try:
        reader.page.quit()
        print("  Browser đã đóng.")
    except:
        pass
