from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Boilerplate chrome to prune from the chosen content root before MarkItDown runs.
# .mw-editsection/.ambox/.metadata/.noprint are load-bearing: they hold the
# "index.php" / message-box links that survive INSIDE #mw-content-text otherwise.
_HTML_BOILERPLATE_SELECTOR = (
    "nav, header, footer, aside, script, style, "
    ".navbox, .catlinks, #mw-navigation, .mw-jump-link, "
    '[class*="vector-"], '
    "#footer, #siteNotice, .printfooter, .mw-editsection, .ambox, .metadata, .noprint"
)


@dataclass(frozen=True)
class ConvertedDocument:
    text: str
    metadata: dict[str, object]
    chunk_chars: int | None = None


def _markitdown_converter() -> Any:
    from markitdown import MarkItDown

    return MarkItDown(enable_plugins=False)


def _pdfium_document(path: str) -> Any:
    import pypdfium2

    return pypdfium2.PdfDocument(path)


def _convert_pdfium(source: Path) -> ConvertedDocument | None:
    document = _pdfium_document(str(source))
    pages: list[str] = []
    page_count = len(document)
    try:
        for index in range(page_count):
            page = document[index]
            try:
                text_page = page.get_textpage()
                try:
                    text = str(text_page.get_text_bounded() or "")
                finally:
                    text_page.close()
            finally:
                page.close()
            normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
            if normalized:
                pages.append(f"<!-- page {index + 1} -->\n\n{normalized}")
    finally:
        document.close()
    if not pages:
        return None
    return ConvertedDocument(
        text="\n\n".join(pages),
        metadata={
            "converter": "pdfium-text",
            "page_count": page_count,
            "pages_with_text": len(pages),
            "source_filename": source.name,
            "source_path": str(source),
        },
        chunk_chars=4096,
    )


def _extract_html_main_content(html: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - bs4 is a MarkItDown transitive dep
        raise ImportError(
            "bs4 is required for HTML boilerplate stripping and is normally provided "
            "transitively by MarkItDown; it is missing from this environment"
        ) from exc

    soup = BeautifulSoup(html, "html.parser")
    root = soup.select_one("#mw-content-text") or soup.find("main") or soup.find("article") or soup
    # Decompose boilerplate even inside a found landmark: editsection/message-box
    # chrome (.mw-editsection, .ambox, .metadata, .noprint) lives INSIDE
    # #mw-content-text on MediaWiki pages, not just outside it.
    for element in root.select(_HTML_BOILERPLATE_SELECTOR):
        element.decompose()
    return str(root)


def _convert_html_cleaned(source: Path, converter: Any | None) -> ConvertedDocument:
    html = source.read_text(encoding="utf-8", errors="replace")
    cleaned = _extract_html_main_content(html)
    markitdown = converter if converter is not None else _markitdown_converter()

    tmp = tempfile.NamedTemporaryFile("w", suffix=".html", encoding="utf-8", delete=False)
    try:
        tmp.write(cleaned)
        tmp.close()
        result = markitdown.convert_local(tmp.name)
    finally:
        Path(tmp.name).unlink(missing_ok=True)

    text = str(getattr(result, "text_content", "") or getattr(result, "markdown", "") or "")
    if not text.strip():
        raise ValueError(f"MarkItDown produced empty markdown for {source}")

    return ConvertedDocument(
        text=text,
        metadata={
            "converter": "markitdown-html-cleaned",
            "boilerplate_stripped": True,
            "source_filename": source.name,
            "source_path": str(source),
        },
    )


def convert_document_to_markdown(
    path: str | Path,
    *,
    converter: Any | None = None,
) -> ConvertedDocument:
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError(f"{source} is not a file")

    if converter is None and source.suffix.lower() == ".pdf":
        converted = _convert_pdfium(source)
        if converted is not None:
            return converted

    if source.suffix.lower() in (".html", ".htm"):
        return _convert_html_cleaned(source, converter)

    markitdown = converter if converter is not None else _markitdown_converter()
    result = markitdown.convert_local(str(source))
    text = str(getattr(result, "text_content", "") or getattr(result, "markdown", "") or "")
    if not text.strip():
        raise ValueError(f"MarkItDown produced empty markdown for {source}")

    return ConvertedDocument(
        text=text,
        metadata={
            "converter": "markitdown",
            "source_filename": source.name,
            "source_path": str(source),
        },
    )
