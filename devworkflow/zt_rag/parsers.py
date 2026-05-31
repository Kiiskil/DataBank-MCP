"""EPUB-, PDF- ja Markdown-jäsentimet."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import ebooklib
import fitz  # pymupdf
from bs4 import BeautifulSoup, Tag
from ebooklib import epub


@dataclass
class ParsedDocument:
    title: str
    sections: list[dict[str, Any]]  # heading, heading_path, page, text, lang
    lang: str = ""


# Hakemistoskannauksessa mukana olevat päätteet (zt_sync_sources)
INGEST_SYNC_SUFFIXES = frozenset({".epub", ".pdf", ".md", ".markdown"})

_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_NAV_SKIP_RE = re.compile(r"(^|/)(nav|toc|cover|ncx)(\.|/|$)", re.I)
_HEADING_PATH_MAX_LEN = 200


def _env_include_nonlinear() -> bool:
    return os.environ.get("ZT_EPUB_INCLUDE_NONLINEAR", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _format_heading_path(path: list[str], max_len: int = _HEADING_PATH_MAX_LEN) -> str:
    s = " > ".join(p.strip() for p in path if p and p.strip())
    if len(s) > max_len:
        return s[: max_len - 3] + "..."
    return s


def _epub_language(book: epub.EpubBook) -> str:
    try:
        md = book.get_metadata("DC", "language")
        if md and md[0] and md[0][0]:
            return str(md[0][0]).strip()
    except Exception:
        pass
    return ""


def _html_lang(soup: BeautifulSoup) -> str:
    root = soup.find("html")
    if root is None:
        root = getattr(soup, "html", None)
    if root is not None and root.get("lang"):
        return str(root.get("lang", "")).strip()
    return ""


def _html_to_markdown(element: Tag | BeautifulSoup) -> str:
    try:
        from markdownify import markdownify as md_convert

        html = str(element)
        out = md_convert(
            html,
            heading_style="ATX",
            strip=["script", "style", "noscript"],
        ).strip()
        if out:
            return out
    except Exception:
        pass
    if hasattr(element, "get_text"):
        return element.get_text(separator="\n", strip=True)
    return ""


def _sibling_content_text(sib: Any) -> str:
    if isinstance(sib, Tag):
        return _html_to_markdown(sib)
    if hasattr(sib, "get_text"):
        return sib.get_text(separator="\n", strip=True)
    return str(sib).strip() if sib else ""


def _body_is_link_heavy(soup: BeautifulSoup) -> bool:
    body = soup.body or soup
    text = body.get_text(separator="\n", strip=True)
    if len(text) >= 80:
        return False
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return True
    linkish = 0
    for ln in lines:
        if re.fullmatch(r"https?://\S+", ln):
            linkish += 1
        elif "http" in ln and len(ln) < 60:
            linkish += 1
    return linkish / len(lines) > 0.6


def _epub_item_has_nav_property(item: Any) -> bool:
    props = getattr(item, "properties", None) or []
    return "nav" in props


def _epub_skip_reason(item: Any, soup: BeautifulSoup) -> str | None:
    name = item.get_name() or ""
    if _epub_item_has_nav_property(item):
        return "manifest_nav"
    if _NAV_SKIP_RE.search(name.replace("\\", "/")):
        return "filename_pattern"
    if _body_is_link_heavy(soup):
        return "link_heavy_short"
    return None


def _epub_spine_document_items(book: epub.EpubBook) -> tuple[list[Any], bool]:
    """
    Palauttaa (ITEM_DOCUMENT -itemit järjestyksessä, käytettiinkö spineä).
    """
    spine = getattr(book, "spine", None) or []
    if spine:
        ordered: list[Any] = []
        for entry in spine:
            if isinstance(entry, (list, tuple)) and len(entry) >= 1:
                idref, linear = entry[0], entry[1] if len(entry) > 1 else "yes"
            else:
                idref, linear = str(entry), "yes"
            linear_s = str(linear).lower() if linear is not None else "yes"
            if linear_s == "no" and not _env_include_nonlinear():
                continue
            item = book.get_item_with_id(idref)
            if item is None:
                continue
            if item.get_type() != ebooklib.ITEM_DOCUMENT:
                continue
            ordered.append(item)
        if ordered:
            return ordered, True

    fallback = [
        item
        for item in book.get_items()
        if item.get_type() == ebooklib.ITEM_DOCUMENT
    ]
    return fallback, False


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
            sections.append(
                {
                    "heading": h,
                    "heading_path": [h] if h != "body" else [],
                    "page": None,
                    "text": text,
                    "lang": "",
                }
            )
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
    heading_stack: list[str],
    section_lang: str,
) -> tuple[list[dict[str, Any]], list[str]]:
    """
    Jaa HTML-sisältö otsikkotasoihin (h1–h6); päivittää heading_stack spine-yli.
    """
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    body = soup.body or soup
    heads = body.find_all(re.compile(r"^h[1-6]$", re.I))
    sections: list[dict[str, Any]] = []
    stack = list(heading_stack)

    if not heads:
        text = _html_to_markdown(body)
        if text.strip():
            path = list(stack) if stack else [fallback_heading]
            sections.append(
                {
                    "heading": fallback_heading,
                    "heading_path": path,
                    "page": None,
                    "text": text,
                    "lang": section_lang,
                }
            )
        return sections, stack

    for i, h in enumerate(heads):
        if not isinstance(h, Tag):
            continue
        level = int(h.name[1]) if h.name and len(h.name) == 2 and h.name[0].lower() == "h" else 1
        sec_title = h.get_text(separator=" ", strip=True) or f"section_{i + 1}"
        stack = stack[: level - 1]
        stack.append(sec_title)
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
            t = _sibling_content_text(sib)
            if t:
                parts.append(t)
        text = "\n\n".join(parts)
        if text.strip():
            sections.append(
                {
                    "heading": sec_title,
                    "heading_path": list(stack),
                    "page": None,
                    "text": text,
                    "lang": section_lang,
                }
            )
    return sections, stack


def parse_epub(path: Path) -> tuple[ParsedDocument, dict[str, Any]]:
    book = epub.read_epub(str(path))
    title = _epub_title(book)
    doc_lang = _epub_language(book)
    sections: list[dict[str, Any]] = []
    skipped_items: list[dict[str, str]] = []
    heading_stack: list[str] = []

    items, used_spine = _epub_spine_document_items(book)
    for item in items:
        raw = item.get_content()
        try:
            soup = BeautifulSoup(raw, "lxml")
        except Exception:
            soup = BeautifulSoup(raw, "html.parser")

        skip = _epub_skip_reason(item, soup)
        if skip:
            skipped_items.append(
                {"name": item.get_name() or item.get_id() or "?", "reason": skip}
            )
            continue

        item_lang = (
            _html_lang(soup)
            or str(getattr(item, "language", "") or "").strip()
            or doc_lang
        )
        fallback = item.get_name() or "section"
        new_sections, heading_stack = _epub_sections_from_html_soup(
            soup,
            fallback,
            heading_stack,
            item_lang,
        )
        sections.extend(new_sections)

    quality: dict[str, Any] = {
        "spine_order": used_spine,
        "skipped_items": skipped_items,
    }
    return ParsedDocument(title=title, sections=sections, lang=doc_lang), quality


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
                    "heading_path": [f"Page {i + 1}"],
                    "page": i + 1,
                    "text": text,
                    "lang": "",
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
