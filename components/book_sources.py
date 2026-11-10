"""Real-book sources for BackgroundReader.

Aura only reads text that exists: a local library folder, public-domain works
on Vietnamese Wikisource, and Project Gutenberg (via the Gutendex catalogue).
docln.net is available only when explicitly enabled, because it relies on
Cloudflare bypassing and hosts fan translations of copyrighted novels.

Every source exposes the same small surface:
``search(keyword)``, ``random_book()``, ``chapters(book)``,
``fetch_chapter(book, chapter)`` and ``book_from_url(url)``.
Network errors never raise to the caller; they return empty results.
"""

import os
import random
import re
import zipfile
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup

from core.logger import get_logger

logger = get_logger("book_sources")

HTTP_TIMEOUT = 20
USER_AGENT = "AuraReader/1.0 (personal reading companion; public-domain books)"


@dataclass(frozen=True)
class BookRef:
    source: str
    book_id: str
    title: str


@dataclass(frozen=True)
class Chapter:
    title: str
    locator: str


def _http_get(url: str, **params):
    try:
        response = requests.get(
            url,
            params=params or None,
            timeout=HTTP_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        return response
    except Exception as exc:
        logger.warning("[BookSource] GET failed cause_type=%s", type(exc).__name__)
        return None


def _html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "sup", "table", "nav"]):
        tag.decompose()
    # <p>/<dd> blocks; "\n" keeps verse lines split by <br> (Wikisource poems).
    paragraphs = [p.get_text("\n", strip=True) for p in soup.find_all(["p", "dd"])]
    text = "\n\n".join(p for p in paragraphs if p)
    return text or soup.get_text("\n", strip=True)


# ---------------------------------------------------------------- local files
class LocalLibrarySource:
    """Free ebooks the owner drops into a folder (.txt or .epub)."""

    name = "local"
    _EXTENSIONS = (".txt", ".epub")

    def __init__(self, directory: str):
        self.directory = directory

    def _books(self) -> list[BookRef]:
        try:
            names = sorted(os.listdir(self.directory))
        except OSError:
            return []
        return [
            BookRef(self.name, name, os.path.splitext(name)[0])
            for name in names
            if name.lower().endswith(self._EXTENSIONS)
            and os.path.isfile(os.path.join(self.directory, name))
        ]

    def search(self, keyword: str, limit: int = 5) -> list[BookRef]:
        needle = keyword.strip().lower()
        return [b for b in self._books() if needle and needle in b.title.lower()][:limit]

    def random_book(self, exclude=frozenset()) -> BookRef | None:
        books = [b for b in self._books() if b.book_id not in exclude]
        return random.choice(books) if books else None

    def _path(self, book: BookRef) -> str | None:
        # book_id is a bare filename from our own listing; refuse anything else.
        if os.path.basename(book.book_id) != book.book_id:
            return None
        return os.path.join(self.directory, book.book_id)

    def chapters(self, book: BookRef) -> list[Chapter]:
        path = self._path(book)
        if path is None or not os.path.isfile(path):
            return []  # deleted or renamed since it was listed
        if path.lower().endswith(".epub"):
            return [Chapter(f"{book.title} ({i + 1})", item) for i, item in enumerate(self._epub_items(path))]
        return [Chapter(book.title, "")]

    def fetch_chapter(self, book: BookRef, chapter: Chapter) -> str | None:
        path = self._path(book)
        if path is None:
            return None
        try:
            if path.lower().endswith(".epub"):
                with zipfile.ZipFile(path) as archive:
                    return _html_to_text(archive.read(chapter.locator).decode("utf-8", "replace")) or None
            with open(path, "rb") as handle:
                raw = handle.read()
            for encoding in ("utf-8-sig", "utf-16", "cp1258", "latin-1"):
                try:
                    return raw.decode(encoding)
                except UnicodeDecodeError:
                    continue
        except (OSError, zipfile.BadZipFile, KeyError):
            logger.warning("[BookSource] local read failed")
        return None

    @staticmethod
    def _epub_items(path: str) -> list[str]:
        """Content documents in spine order (falls back to archive order)."""
        try:
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
                opf_name = next((n for n in names if n.endswith(".opf")), None)
                if opf_name:
                    opf = BeautifulSoup(archive.read(opf_name), "html.parser")
                    base = os.path.dirname(opf_name)
                    manifest = {
                        item.get("id"): item.get("href")
                        for item in opf.find_all("item")
                    }
                    ordered = []
                    for ref in opf.find_all("itemref"):
                        href = manifest.get(ref.get("idref"))
                        if href:
                            full = os.path.normpath(os.path.join(base, unquote(href))).replace("\\", "/")
                            if full in names:
                                ordered.append(full)
                    if ordered:
                        return ordered
                return [n for n in names if n.lower().endswith((".xhtml", ".html", ".htm"))]
        except (OSError, zipfile.BadZipFile):
            return []

    def book_from_url(self, url: str) -> BookRef | None:
        return None


# ---------------------------------------------------------------- Wikisource
class WikisourceSource:
    """Public-domain literature on Wikisource (Vietnamese by default)."""

    name = "wikisource"
    # Seeds for random picks: well-known Vietnamese works in the public domain.
    SEED_QUERIES = (
        "Truyện Kiều", "Lục Vân Tiên", "Số đỏ", "Giông tố", "Chí Phèo",
        "Tắt đèn", "Hồ Biểu Chánh", "Chinh phụ ngâm", "Cung oán ngâm khúc",
    )

    def __init__(self, lang: str = "vi"):
        self.lang = lang
        self.api = f"https://{lang}.wikisource.org/w/api.php"

    def search(self, keyword: str, limit: int = 5) -> list[BookRef]:
        response = _http_get(
            self.api, action="query", list="search", srsearch=keyword,
            srnamespace=0, srlimit=limit, format="json", formatversion=2,
        )
        if response is None:
            return []
        try:
            hits = response.json()["query"]["search"]
        except (ValueError, KeyError, TypeError):
            return []
        return [BookRef(self.name, hit["title"], hit["title"]) for hit in hits if hit.get("title")]

    def random_book(self, exclude=frozenset()) -> BookRef | None:
        for query in random.sample(self.SEED_QUERIES, len(self.SEED_QUERIES)):
            candidates = [b for b in self.search(query, limit=5) if b.book_id not in exclude]
            if candidates:
                return candidates[0]
        return None

    def chapters(self, book: BookRef) -> list[Chapter]:
        """Subpages ("Title/Hồi 1", ...) when the work is split, else the page."""
        response = _http_get(
            self.api, action="query", list="allpages", apprefix=f"{book.book_id}/",
            apnamespace=0, aplimit=500, format="json", formatversion=2,
        )
        subpages = []
        if response is not None:
            try:
                subpages = [p["title"] for p in response.json()["query"]["allpages"]]
            except (ValueError, KeyError, TypeError):
                subpages = []
        if subpages:
            return [Chapter(title.split("/", 1)[-1], title) for title in subpages]
        return [Chapter(book.title, book.book_id)]

    def fetch_chapter(self, book: BookRef, chapter: Chapter) -> str | None:
        response = _http_get(
            self.api, action="parse", page=chapter.locator, prop="text",
            format="json", formatversion=2, disablelimitreport=1,
        )
        if response is None:
            return None
        try:
            html = response.json()["parse"]["text"]
        except (ValueError, KeyError, TypeError):
            return None
        return _html_to_text(html) or None

    def book_from_url(self, url: str) -> BookRef | None:
        parsed = urlparse(url)
        if parsed.netloc != f"{self.lang}.wikisource.org" or not parsed.path.startswith("/wiki/"):
            return None
        title = unquote(parsed.path[len("/wiki/"):]).replace("_", " ")
        return BookRef(self.name, title, title) if title else None


# ------------------------------------------------------------ Project Gutenberg
class GutenbergSource:
    """Project Gutenberg books located through the Gutendex catalogue."""

    name = "gutenberg"
    CATALOGUE = "https://gutendex.com/books/"
    _START = re.compile(r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG.*?\*\*\*", re.I | re.S)
    _END = re.compile(r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG", re.I)

    def __init__(self, languages: str = "vi,en"):
        self.languages = languages

    def _query(self, **params) -> list[dict]:
        response = _http_get(self.CATALOGUE, languages=self.languages, **params)
        if response is None:
            return []
        try:
            return list(response.json().get("results", []))
        except (ValueError, AttributeError):
            return []

    @staticmethod
    def _text_url(book: dict) -> str | None:
        formats = book.get("formats") or {}
        for mime, url in formats.items():
            if mime.startswith("text/plain") and not url.endswith(".zip"):
                return url
        return None

    def _ref(self, book: dict) -> BookRef | None:
        if not self._text_url(book) or not book.get("id"):
            return None
        return BookRef(self.name, str(book["id"]), str(book.get("title") or book["id"]))

    def search(self, keyword: str, limit: int = 5) -> list[BookRef]:
        refs = [self._ref(b) for b in self._query(search=keyword)]
        return [r for r in refs if r][:limit]

    def random_book(self, exclude=frozenset()) -> BookRef | None:
        refs = [self._ref(b) for b in self._query(sort="popular", page=random.randint(1, 10))]
        refs = [r for r in refs if r and r.book_id not in exclude]
        return random.choice(refs) if refs else None

    def chapters(self, book: BookRef) -> list[Chapter]:
        return [Chapter(book.title, book.book_id)]

    def fetch_chapter(self, book: BookRef, chapter: Chapter) -> str | None:
        results = self._query(ids=book.book_id)
        url = self._text_url(results[0]) if results else None
        response = _http_get(url) if url else None
        if response is None:
            return None
        response.encoding = response.encoding or "utf-8"
        text = response.text
        start = self._START.search(text)
        end = self._END.search(text)
        if start:
            text = text[start.end():end.start() if end and end.start() > start.end() else None]
        return text.strip() or None

    def book_from_url(self, url: str) -> BookRef | None:
        match = re.search(r"gutenberg\.org/(?:ebooks|cache/epub)/(\d+)", url)
        if not match:
            return None
        results = self._query(ids=match.group(1))
        return self._ref(results[0]) if results else None


# ------------------------------------------------------- docln.net (opt-in)
class DoclnSource:
    """docln.net light novels. Opt-in only (AURA_READER_ENABLE_DOCLN=true)."""

    name = "docln"

    def __init__(self):
        self._reader = None

    def _docln(self):
        if self._reader is None:
            from components.reader import DoclnReader

            self._reader = DoclnReader()
        return self._reader

    def close(self):
        if self._reader is not None:
            self._reader.close()

    def search(self, keyword: str, limit: int = 5) -> list[BookRef]:
        return [BookRef(self.name, url, title) for title, url in self._docln().search_novel(keyword)[:limit]]

    def random_book(self, exclude=frozenset()) -> BookRef | None:
        url = self._docln().get_random_novel_url()
        return BookRef(self.name, url, url) if url and url not in exclude else None

    def chapters(self, book: BookRef) -> list[Chapter]:
        _title, chapters = self._docln().get_novel_chapters(book.book_id)
        return [Chapter(c["title"], c["url"]) for c in chapters]

    def fetch_chapter(self, book: BookRef, chapter: Chapter) -> str | None:
        return self._docln().read_chapter(chapter.locator)

    def book_from_url(self, url: str) -> BookRef | None:
        if not re.match(r"https?://docln\.net/", url):
            return None
        return BookRef(self.name, url, url)


def build_sources(config) -> list:
    """Enabled sources in preference order (Config.READER_SOURCES)."""
    factories = {
        "local": lambda: LocalLibrarySource(config.READER_LIBRARY_DIR),
        "wikisource": lambda: WikisourceSource("vi"),
        "gutenberg": lambda: GutenbergSource("vi,en"),
        "docln": DoclnSource,
    }
    sources = []
    for name in config.READER_SOURCES:
        if name == "docln" and not config.READER_ENABLE_DOCLN:
            continue
        factory = factories.get(name)
        if factory is not None:
            sources.append(factory())
    if config.READER_ENABLE_DOCLN and "docln" not in config.READER_SOURCES:
        sources.append(DoclnSource())
    return sources
