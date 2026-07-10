from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ConvertedDocument:
    text: str
    metadata: dict[str, object]


def _markitdown_converter() -> Any:
    from markitdown import MarkItDown

    return MarkItDown(enable_plugins=False)


def convert_document_to_markdown(
    path: str | Path,
    *,
    converter: Any | None = None,
) -> ConvertedDocument:
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError(f"{source} is not a file")

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
