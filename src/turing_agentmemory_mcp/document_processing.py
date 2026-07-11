from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


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
