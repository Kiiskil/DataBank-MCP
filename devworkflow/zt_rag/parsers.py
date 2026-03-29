"""EPUB-, PDF- ja Markdown-jäsentimet."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ebooklib
import fitz  # pymupdf
from bs4 import BeautifulSoup
from ebooklib import epub


@dataclass
class ParsedDocument:
    title: str
    sections: list[dict[str, Any]]  # {heading, page, text}


# Hakemistoskannauksessa mukana olevat päätteet (zt_sync_sources)
INGEST_SYNC_SUFFIXES = frozenset({".epub", ".pdf", ".md", ".markdown"})

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def parse_markdown(path: Path) -> ParsedDocument:
    """
    Jakaa Markdown-dokumentin ATX-otsikoilla (# .. ######) osiin.
    Dokumentin otsikko: ensimmäinen tason 1 -otsikko, muuten tiedostonimi.
    """
    raw = path.read_text(encoding="utf-8", errors="replace")
    if raw.startswith("\ufeff"):
        raw = raw[1:]
    lines = raw.splitlines()
    sections: list[dict[str, Any]] = []
    current_heading = ""
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_heading, current_lines
        text = "\n".join(current_lines).strip()
        if text:
            h = current_heading.strip() if current_heading.strip() else "body"
            sections.append({"heading": h, "page": None, "text": text})
        current_lines = []

    doc_title = path.stem
    seen_h1 = False
    for line in lines:
        m = _MD_HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            current_heading = m.group(2).strip()
            if level == 1 and not seen_h1:
                doc_title = current_heading
                seen_h1 = True
        else:
            current_lines.append(line)
    flush()

    return ParsedDocument(title=doc_title, sections=sections)


def _epub_title(book: epub.EpubBook) -> str:
    try:
        md = book.get_metadata("DC", "title")
        if md and md[0] and md[0][0]:
            return str(md[0][0])
    except Exception:
        pass
    return "unknown"


def _epub_sections_from_html_soup(
    soup: BeautifulSoup,
    fallback_heading: str,
) -> list[dict[str, Any]]:
    """
    Jaa HTML-sisältö otsikkotasoihin (h1–h6), jos mahdollista; muuten yksi lohko.
    """
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    body = soup.body or soup
    heads = body.find_all(re.compile(r"^h[1-6]$", re.I))
    sections: list[dict[str, Any]] = []
    if not heads:
        text = body.get_text(separator="\n", strip=True)
        if text.strip():
            sections.append(
                {"heading": fallback_heading, "page": None, "text": text}
            )
        return sections

    for i, h in enumerate(heads):
        sec_title = h.get_text(separator=" ", strip=True) or f"section_{i + 1}"
        parts: list[str] = []
        for sib in h.next_siblings:
            name = getattr(sib, "name", None)
            if isinstance(name, str) and name.lower() in (
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
            ):
                break
            if hasattr(sib, "get_text"):
                t = sib.get_text(separator="\n", strip=True)
                if t:
                    parts.append(t)
        text = "\n\n".join(parts)
        if text.strip():
            sections.append({"heading": sec_title, "page": None, "text": text})
    return sections


def parse_epub(path: Path) -> ParsedDocument:
    book = epub.read_epub(str(path))
    title = _epub_title(book)
    sections: list[dict[str, Any]] = []
    for item in book.get_items():
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        raw = item.get_content()
        try:
            soup = BeautifulSoup(raw, "lxml")
        except Exception:
            soup = BeautifulSoup(raw, "html.parser")
        fallback = item.get_name() or "section"
        sections.extend(_epub_sections_from_html_soup(soup, fallback))
    return ParsedDocument(title=title, sections=sections)


def parse_pdf(path: Path) -> tuple[ParsedDocument, dict[str, Any]]:
    """
    Palauttaa dokumentin ja laatureportin.
    Heuristinen born-digital vs heikko teksti: vähän merkkejä/sivu -> quarantine-ehdotus.
    """
    doc = fitz.open(str(path))
    title = Path(path).stem
    if doc.metadata and doc.metadata.get("title"):
        title = str(doc.metadata["title"]) or title

    sections: list[dict[str, Any]] = []
    total_chars = 0
    page_count = len(doc)
    for i in range(page_count):
        page = doc.load_page(i)
        text = page.get_text() or ""
        total_chars += len(text.strip())
        if text.strip():
            sections.append(
                {
                    "heading": f"Page {i + 1}",
                    "page": i + 1,
                    "text": text,
                }
            )
    doc.close()

    avg = total_chars / max(page_count, 1)
    quality = {
        "page_count": page_count,
        "total_text_chars": total_chars,
        "avg_chars_per_page": avg,
        "suggest_quarantine": avg < 40.0 and page_count > 0,
    }
    return ParsedDocument(title=title, sections=sections), quality


def detect_type(path: Path) -> str:
    suf = path.suffix.lower()
    if suf == ".epub":
        return "epub"
    if suf == ".pdf":
        return "pdf"
    if suf in (".md", ".markdown"):
        return "md"
    return "unknown"
