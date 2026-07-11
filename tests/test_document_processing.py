from types import SimpleNamespace

import pytest

from turing_agentmemory_mcp.document_processing import convert_document_to_markdown


class FakeMarkItDown:
    def __init__(self, text: str) -> None:
        self.text = text
        self.paths: list[str] = []

    def convert_local(self, path: str) -> object:
        self.paths.append(path)
        return SimpleNamespace(text_content=self.text)


def test_convert_document_to_markdown_uses_markitdown_convert_local(tmp_path):
    source = tmp_path / "release-notes.docx"
    source.write_bytes(b"fake docx")
    converter = FakeMarkItDown("# Release Notes\n\n- Alpha")

    result = convert_document_to_markdown(source, converter=converter)

    assert converter.paths == [str(source)]
    assert result.text == "# Release Notes\n\n- Alpha"
    assert result.metadata == {
        "converter": "markitdown",
        "source_filename": "release-notes.docx",
        "source_path": str(source),
    }


def test_convert_document_to_markdown_rejects_missing_files(tmp_path):
    with pytest.raises(FileNotFoundError):
        convert_document_to_markdown(tmp_path / "missing.pdf", converter=FakeMarkItDown("ignored"))


def test_convert_document_to_markdown_rejects_empty_output(tmp_path):
    source = tmp_path / "empty.pdf"
    source.write_bytes(b"%PDF")

    with pytest.raises(ValueError, match="empty markdown"):
        convert_document_to_markdown(source, converter=FakeMarkItDown("  \n"))


def test_convert_pdf_uses_pagewise_pdfium_fast_path(monkeypatch, tmp_path):
    source = tmp_path / "machine-manual.pdf"
    source.write_bytes(b"%PDF fake")
    closed: list[str] = []

    class FakeTextPage:
        def __init__(self, text: str) -> None:
            self.text = text

        def get_text_bounded(self) -> str:
            return self.text

        def close(self) -> None:
            closed.append("text")

    class FakePage:
        def __init__(self, text: str) -> None:
            self.text = text

        def get_textpage(self) -> FakeTextPage:
            return FakeTextPage(self.text)

        def close(self) -> None:
            closed.append("page")

    class FakePdf:
        pages = ["Safety instructions\r\nDisconnect power.", "Commissioning\nSet P0010."]

        def __len__(self) -> int:
            return len(self.pages)

        def __getitem__(self, index: int) -> FakePage:
            return FakePage(self.pages[index])

        def close(self) -> None:
            closed.append("pdf")

    monkeypatch.setattr(
        "turing_agentmemory_mcp.document_processing._pdfium_document",
        lambda path: FakePdf(),
    )

    result = convert_document_to_markdown(source)

    assert result.text == (
        "<!-- page 1 -->\n\nSafety instructions\nDisconnect power.\n\n"
        "<!-- page 2 -->\n\nCommissioning\nSet P0010."
    )
    assert result.metadata == {
        "converter": "pdfium-text",
        "page_count": 2,
        "pages_with_text": 2,
        "source_filename": "machine-manual.pdf",
        "source_path": str(source),
    }
    assert closed == ["text", "page", "text", "page", "pdf"]
