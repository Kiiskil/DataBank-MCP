"""EPUB-parserin yksikkötestit (spine, nav-skip, otsikkopolku, lang, markdown)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ebooklib import epub

from devworkflow.zt_rag.chunking import ChunkConfig, chunk_text
from devworkflow.zt_rag.parsers import (
    _format_heading_path,
    _html_lang,
    _html_to_markdown,
    parse_epub,
)
from bs4 import BeautifulSoup


def _build_minimal_spine_epub(path: Path) -> None:
    """Spine: ch2, ch1, nav — nav ohitetaan; osiot järjestyksessä ch2 → ch1."""
    book = epub.EpubBook()
    book.set_identifier("test-minimal-spine")
    book.set_title("Test Spine Book")
    book.set_language("en")

    nav = epub.EpubHtml(title="Nav", file_name="nav.xhtml", lang="en")
    nav.content = (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<html xmlns="http://www.w3.org/1999/xhtml" '
        b'xmlns:epub="http://www.idpf.org/2007/ops">'
        b"<head><title>Nav</title></head><body>"
        b'<nav epub:type="toc" id="toc"><ol>'
        b'<li><a href="ch1.xhtml">One</a></li>'
        b'<li><a href="http://example.com">x</a></li>'
        b"</ol></nav></body></html>"
    )
    nav.properties = ["nav"]

    ch1 = epub.EpubHtml(title="Ch1", file_name="ch1.xhtml", lang="en")
    ch1.content = (
        b"<html><body><h1>Chapter One</h1><p>First chapter body.</p></body></html>"
    )

    ch2 = epub.EpubHtml(title="Ch2", file_name="ch2.xhtml", lang="fi")
    ch2.content = (
        b'<html lang="fi"><body><h2>Section B</h2><p>Overview here.</p>'
        b"<h3>dnf install</h3><p>Run <code>dnf install</code> as root.</p></body></html>"
    )

    book.add_item(nav)
    book.add_item(ch1)
    book.add_item(ch2)
    book.spine = [(nav.get_id(), True), (ch2.get_id(), True), (ch1.get_id(), True)]
    book.toc = [(epub.Section("Chapter One"), [ch1]), (epub.Section("Section B"), [ch2])]
    epub.write_epub(str(path), book, {})


class TestEpubParser(unittest.TestCase):
    def test_spine_order_and_nav_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            epub_path = Path(tmp) / "minimal.epub"
            _build_minimal_spine_epub(epub_path)
            doc, quality = parse_epub(epub_path)

        self.assertTrue(quality.get("spine_order"))
        skipped = {s["name"]: s["reason"] for s in quality.get("skipped_items", [])}
        self.assertIn("nav.xhtml", skipped)

        headings = [s["heading"] for s in doc.sections]
        self.assertEqual(headings[:3], ["Section B", "dnf install", "Chapter One"])

    def test_heading_path_and_lang(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            epub_path = Path(tmp) / "minimal.epub"
            _build_minimal_spine_epub(epub_path)
            doc, _ = parse_epub(epub_path)

        self.assertEqual(doc.lang, "en")
        nested = next(s for s in doc.sections if s["heading"] == "dnf install")
        self.assertEqual(nested["heading_path"], ["Section B", "dnf install"])
        self.assertIn("dnf install", nested["text"])

    def test_html_lang_from_tag(self) -> None:
        soup = BeautifulSoup('<html lang="fi"><body></body></html>', "lxml")
        self.assertEqual(_html_lang(soup), "fi")

    def test_format_heading_path_truncation(self) -> None:
        long_path = ["A" * 100, "B" * 100]
        out = _format_heading_path(long_path, max_len=50)
        self.assertLessEqual(len(out), 50)
        self.assertTrue(out.endswith("..."))

    def test_html_to_markdown_code(self) -> None:
        soup = BeautifulSoup(
            "<pre><code>dnf install</code></pre>",
            "html.parser",
        )
        text = _html_to_markdown(soup)
        self.assertIn("dnf install", text)

    def test_ingest_section_blob_breadcrumb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            epub_path = Path(tmp) / "minimal.epub"
            _build_minimal_spine_epub(epub_path)
            doc, _ = parse_epub(epub_path)

        sec = next(s for s in doc.sections if s["heading"] == "dnf install")
        path_str = _format_heading_path(sec["heading_path"])
        breadcrumb = f"{doc.title} > {path_str}"
        blob = f"{breadcrumb}\n\n## {sec['heading']}\n{sec['text']}"
        chunks = chunk_text(blob, ChunkConfig())
        self.assertTrue(chunks)
        self.assertIn("Test Spine Book", chunks[0])
        self.assertIn("dnf install", chunks[0])


if __name__ == "__main__":
    unittest.main()
