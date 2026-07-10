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
