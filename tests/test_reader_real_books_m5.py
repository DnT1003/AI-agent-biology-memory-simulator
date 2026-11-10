import os
import tempfile
import unittest
import zipfile
from types import SimpleNamespace
from unittest.mock import Mock, patch

from components.book_sources import (
    BookRef,
    Chapter,
    GutenbergSource,
    LocalLibrarySource,
    WikisourceSource,
    build_sources,
)
from components.reader import BackgroundReader


class _FakeSource:
    name = "fake"

    def __init__(self, books=None, fail_fetch=False):
        # {book_id: [chapter texts]}
        self.books = books if books is not None else {
            "b1": ["A" * 50 + "\n\n" + "B" * 50, "C" * 30],
        }
        self.fail_fetch = fail_fetch
        self.fetches = []

    def search(self, keyword, limit=5):
        return [BookRef(self.name, b, f"Book {b}") for b in self.books if keyword in b][:limit]

    def random_book(self, exclude=frozenset()):
        for book_id in self.books:
            if book_id not in exclude:
                return BookRef(self.name, book_id, f"Book {book_id}")
        return None

    def chapters(self, book):
        return [Chapter(f"Chương {i + 1}", str(i)) for i in range(len(self.books[book.book_id]))]

    def fetch_chapter(self, book, chapter):
        self.fetches.append((book.book_id, chapter.locator))
        if self.fail_fetch:
            return None
        return self.books[book.book_id][int(chapter.locator)]

    def book_from_url(self, url):
        return None


def _reader(tmp, source, segment_chars=500):
    return BackgroundReader(
        Mock(),
        sources=[source],
        progress_path=os.path.join(tmp, "progress.json"),
        segment_chars=segment_chars,
    )


class BackgroundReaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_reads_sequentially_and_never_asks_llm(self):
        llm = Mock()
        reader = BackgroundReader(
            llm, sources=[_FakeSource()],
            progress_path=os.path.join(self.tmp.name, "p.json"), segment_chars=500,
        )
        first = reader.get_next_reading_material()
        self.assertTrue(reader.last_material_new_book)
        second = reader.get_next_reading_material()
        self.assertFalse(reader.last_material_new_book)
        self.assertIn("Chương 1", first[0])
        self.assertIn("Chương 2", second[0])
        self.assertEqual(second[1], "C" * 30)
        self.assertEqual(llm.mock_calls, [])

    def test_long_chapter_is_split_into_segments(self):
        source = _FakeSource({"b1": ["\n\n".join(["x" * 400] * 3)]})
        reader = _reader(self.tmp.name, source, segment_chars=500)
        tags = [reader.get_next_reading_material()[0] for _ in range(3)]
        self.assertEqual([("(đoạn 1/3)" in tags[0]), ("(đoạn 3/3)" in tags[2])], [True, True])

    def test_no_real_book_means_no_material(self):
        reader = _reader(self.tmp.name, _FakeSource({}))
        self.assertEqual(reader.get_next_reading_material(), (None, None))

    def test_network_failure_keeps_the_place(self):
        source = _FakeSource(fail_fetch=True)
        reader = _reader(self.tmp.name, source)
        self.assertEqual(reader.get_next_reading_material(), (None, None))
        source.fail_fetch = False
        tag, _text = reader.get_next_reading_material()
        self.assertIn("Chương 1", tag)

    def test_finished_book_is_not_reread(self):
        source = _FakeSource({"b1": ["one"], "b2": ["two"]})
        reader = _reader(self.tmp.name, source)
        self.assertEqual(reader.get_next_reading_material()[1], "one")
        self.assertEqual(reader.get_next_reading_material()[1], "two")
        self.assertTrue(reader.last_material_new_book)
        self.assertEqual(reader.get_next_reading_material(), (None, None))

    def test_progress_survives_restart(self):
        source = _FakeSource()
        reader = _reader(self.tmp.name, source)
        reader.get_next_reading_material()
        restarted = _reader(self.tmp.name, _FakeSource())
        tag, text = restarted.get_next_reading_material()
        self.assertIn("Chương 2", tag)
        self.assertFalse(restarted.last_material_new_book)

    def test_search_and_url_loading(self):
        reader = _reader(self.tmp.name, _FakeSource())
        self.assertIn("Book b1", reader.search_and_set_novel("b1"))
        self.assertIn("Không tìm thấy", reader.search_and_set_novel("zzz"))
        self.assertFalse(reader.set_novel_by_url("https://example.com/x"))


class LocalLibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_txt_book(self):
        with open(os.path.join(self.tmp.name, "Truyện Kiều.txt"), "w", encoding="utf-8") as f:
            f.write("Trăm năm trong cõi người ta")
        source = LocalLibrarySource(self.tmp.name)
        book = source.search("kiều")[0]
        chapter = source.chapters(book)[0]
        self.assertEqual(source.fetch_chapter(book, chapter), "Trăm năm trong cõi người ta")

    def test_epub_chapters_follow_spine(self):
        path = os.path.join(self.tmp.name, "book.epub")
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("OEBPS/content.opf", (
                '<package><manifest>'
                '<item id="c2" href="c2.xhtml"/><item id="c1" href="c1.xhtml"/>'
                '</manifest><spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>'
            ))
            z.writestr("OEBPS/c1.xhtml", "<html><body><p>Mở đầu</p></body></html>")
            z.writestr("OEBPS/c2.xhtml", "<html><body><p>Kết thúc</p></body></html>")
        source = LocalLibrarySource(self.tmp.name)
        book = source.random_book()
        texts = [source.fetch_chapter(book, c) for c in source.chapters(book)]
        self.assertEqual(texts, ["Mở đầu", "Kết thúc"])

    def test_path_traversal_is_refused(self):
        source = LocalLibrarySource(self.tmp.name)
        evil = BookRef("local", "../secret.txt", "x")
        self.assertEqual(source.chapters(evil), [])
        self.assertIsNone(source.fetch_chapter(evil, Chapter("x", "")))


def _response(json_data=None, text=None):
    return SimpleNamespace(json=lambda: json_data, text=text, encoding="utf-8",
                           raise_for_status=lambda: None)


class OnlineSourceTests(unittest.TestCase):
    def test_gutenberg_strips_license_header_and_footer(self):
        catalogue = {"results": [{"id": 1, "title": "T", "formats": {
            "text/plain; charset=utf-8": "https://www.gutenberg.org/x.txt"}}]}
        body = "header\n*** START OF THE PROJECT GUTENBERG EBOOK T ***\nStory text\n*** END OF THE PROJECT GUTENBERG EBOOK T ***\nlicense"

        def fake_get(url, **kwargs):
            return _response(catalogue) if "gutendex" in url else _response(text=body)

        with patch("components.book_sources.requests.get", side_effect=fake_get):
            source = GutenbergSource()
            book = source.search("T")[0]
            text = source.fetch_chapter(book, source.chapters(book)[0])
        self.assertEqual(text, "Story text")

    def test_wikisource_parses_page_text_and_urls(self):
        def fake_get(url, params=None, **kwargs):
            if params.get("list") == "allpages":
                return _response({"query": {"allpages": []}})
            return _response({"parse": {"text": "<div class='poem'><p>Trăm năm<br/>trong cõi</p></div>"}})

        source = WikisourceSource("vi")
        book = source.book_from_url("https://vi.wikisource.org/wiki/Truy%E1%BB%87n_Ki%E1%BB%81u")
        self.assertEqual(book.title, "Truyện Kiều")
        with patch("components.book_sources.requests.get", side_effect=fake_get):
            text = source.fetch_chapter(book, source.chapters(book)[0])
        self.assertEqual(text, "Trăm năm\ntrong cõi")

    def test_network_errors_return_empty_results(self):
        with patch("components.book_sources.requests.get", side_effect=OSError("proxy 407")):
            self.assertEqual(WikisourceSource().search("Kiều"), [])
            self.assertIsNone(GutenbergSource().random_book())


class SourceConfigTests(unittest.TestCase):
    def _config(self, **overrides):
        cfg = SimpleNamespace(
            READER_SOURCES=("local", "wikisource", "gutenberg", "docln"),
            READER_ENABLE_DOCLN=False,
            READER_LIBRARY_DIR="lib",
        )
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return cfg

    def test_docln_is_off_by_default(self):
        self.assertEqual([s.name for s in build_sources(self._config())],
                         ["local", "wikisource", "gutenberg"])

    def test_docln_can_be_enabled_explicitly(self):
        names = [s.name for s in build_sources(self._config(READER_ENABLE_DOCLN=True))]
        self.assertIn("docln", names)

    def test_default_config_disables_docln(self):
        from config import Config

        self.assertFalse(Config.READER_ENABLE_DOCLN)


if __name__ == "__main__":
    unittest.main()
