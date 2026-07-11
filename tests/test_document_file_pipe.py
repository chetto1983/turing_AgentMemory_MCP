from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.document_job_manager import DocumentIngestManager
from turing_agentmemory_mcp.document_jobs import DocumentJobStore
from turing_agentmemory_mcp.document_processing import ConvertedDocument
from turing_agentmemory_mcp.file_upload import DocumentUploadStore
from turing_agentmemory_mcp.models import IngestedDocument
from turing_agentmemory_mcp.server import create_mcp_app


def payload(result: Any) -> Any:
    if result.structured_content is not None:
        value = result.structured_content
        if isinstance(value, dict) and set(value) == {"result"}:
            return value["result"]
        return value
    text = "".join(getattr(item, "text", "") for item in result.content)
    return json.loads(text)


def test_document_upload_store_enforces_tenant_sequence_size_and_sha256(tmp_path: Path) -> None:
    store = DocumentUploadStore(tmp_path, max_file_bytes=32, chunk_bytes=4)
    content = b"abcdefgh"
    started = store.begin(
        user_identifier="alice",
        filename="manual.pdf",
        total_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )
    upload_id = str(started["upload_id"])

    with pytest.raises(ValueError, match="tenant"):
        store.append(upload_id, user_identifier="bob", sequence=0, content=b"abcd")
    with pytest.raises(ValueError, match="sequence"):
        store.append(upload_id, user_identifier="alice", sequence=1, content=b"abcd")

    store.append(upload_id, user_identifier="alice", sequence=0, content=b"abcd")
    store.append(upload_id, user_identifier="alice", sequence=1, content=b"efgh")
    uploaded = store.complete(upload_id, user_identifier="alice")

    assert uploaded.path.read_bytes() == content
    assert uploaded.filename == "manual.pdf"
    store.discard(upload_id, user_identifier="alice")
    assert not uploaded.path.parent.exists()


class RecordingMemory:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def runtime_status(self) -> dict[str, object]:
        return {"stages": {"graph": {"ready": True}}}

    def ingest_document_text(self, **kwargs: object) -> IngestedDocument:
        self.calls.append(dict(kwargs))
        return IngestedDocument(
            document_id=str(kwargs.get("document_id") or "uploaded-document"),
            title=str(kwargs["title"]),
            chunk_count=3,
            user_identifier=str(kwargs["user_identifier"]),
            source=str(kwargs.get("source") or ""),
            tags=list(kwargs.get("tags") or []),
            metadata=dict(kwargs.get("metadata") or {}),
        )


def test_remote_upload_tools_enqueue_then_convert_and_ingest(
    tmp_path: Path,
) -> None:
    content = b"%PDF-remote-content"
    memory = RecordingMemory()
    upload_store = DocumentUploadStore(tmp_path / "uploads", max_file_bytes=1024, chunk_bytes=8)

    def fake_convert(path: str | Path) -> ConvertedDocument:
        source = Path(path)
        assert source.read_bytes() == content
        return ConvertedDocument(
            text="# Remote manual",
            metadata={"converter": "markitdown", "source_filename": source.name},
        )

    manager = DocumentIngestManager(
        DocumentJobStore(tmp_path / "jobs.sqlite3"),
        staging_root=tmp_path / "staging",
        store_factory=lambda: memory,
        converter=fake_convert,
    )
    backend = create_mcp_app(  # type: ignore[arg-type]
        memory,
        upload_store=upload_store,
        document_manager=manager,
    )

    async def run() -> dict[str, object]:
        async with Client(backend) as client:
            started = payload(
                await client.call_tool(
                    "document_upload_begin",
                    {
                        "filename": "remote.pdf",
                        "total_bytes": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "title": "Remote manual",
                        "user_identifier": "alice",
                        "metadata": {"department": "service"},
                    },
                )
            )
            upload_id = str(started["upload_id"])
            for sequence, offset in enumerate(range(0, len(content), 8)):
                await client.call_tool(
                    "document_upload_chunk",
                    {
                        "upload_id": upload_id,
                        "sequence": sequence,
                        "content_base64": __import__("base64")
                        .b64encode(content[offset : offset + 8])
                        .decode("ascii"),
                        "user_identifier": "alice",
                    },
                )
            return payload(
                await client.call_tool(
                    "document_upload_commit",
                    {"upload_id": upload_id, "user_identifier": "alice"},
                )
            )

    result = asyncio.run(run())

    assert result["status"] == "queued"
    assert memory.calls == []
    completed = manager.process_next(worker_id="worker-a")
    assert completed is not None and completed.status == "succeeded"
    assert memory.calls[0]["text"] == "# Remote manual"
    metadata = memory.calls[0]["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["department"] == "service"
    assert metadata["document_processing"]["transport"] == "mcp-chunk-upload"  # type: ignore[index]
    assert metadata["document_processing"]["sha256"] == hashlib.sha256(content).hexdigest()  # type: ignore[index]
    assert list((tmp_path / "uploads").iterdir()) == []


def test_remote_upload_commit_cleans_up_a_sha256_mismatch(tmp_path: Path) -> None:
    content = b"corrupted-in-transit"
    memory = RecordingMemory()
    upload_store = DocumentUploadStore(tmp_path / "uploads", max_file_bytes=1024, chunk_bytes=32)
    backend = create_mcp_app(memory, upload_store=upload_store)  # type: ignore[arg-type]

    async def run() -> None:
        async with Client(backend) as client:
            started = payload(
                await client.call_tool(
                    "document_upload_begin",
                    {
                        "filename": "remote.pdf",
                        "total_bytes": len(content),
                        "sha256": "0" * 64,
                        "title": "Remote manual",
                        "user_identifier": "alice",
                    },
                )
            )
            await client.call_tool(
                "document_upload_chunk",
                {
                    "upload_id": started["upload_id"],
                    "sequence": 0,
                    "content_base64": __import__("base64").b64encode(content).decode("ascii"),
                    "user_identifier": "alice",
                },
            )
            await client.call_tool(
                "document_upload_commit",
                {"upload_id": started["upload_id"], "user_identifier": "alice"},
            )

    with pytest.raises(ToolError, match="SHA-256"):
        asyncio.run(run())
    assert memory.calls == []
    assert list((tmp_path / "uploads").iterdir()) == []


def test_file_pipe_streams_host_bytes_and_remote_mcp_converts_and_ingests(
    tmp_path: Path,
) -> None:
    from turing_agentmemory_mcp.file_pipe import create_file_pipe_proxy

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    source = allowed / "manual.pdf"
    source.write_bytes(b"%PDF-pipe-content")
    memory = RecordingMemory()
    upload_store = DocumentUploadStore(tmp_path / "uploads", max_file_bytes=1024, chunk_bytes=4)

    def fake_convert(path: str | Path) -> ConvertedDocument:
        path = Path(path)
        assert path.name == "manual.pdf"
        assert path.read_bytes() == b"%PDF-pipe-content"
        return ConvertedDocument(
            text="# Manual\n\nConverted inside the remote MCP.",
            metadata={
                "converter": "markitdown",
                "source_filename": path.name,
                "source_path": str(path),
            },
            chunk_chars=4096,
        )

    manager = DocumentIngestManager(
        DocumentJobStore(tmp_path / "jobs.sqlite3"),
        staging_root=tmp_path / "staging",
        store_factory=lambda: memory,
        converter=fake_convert,
    )
    backend = create_mcp_app(  # type: ignore[arg-type]
        memory,
        upload_store=upload_store,
        document_manager=manager,
    )
    proxy = create_file_pipe_proxy(
        backend,
        allowed_roots=[allowed],
        chunk_bytes=4,
    )

    async def run() -> dict[str, object]:
        async with Client(proxy) as client:
            return payload(
                await client.call_tool(
                    "document_ingest_file",
                    {
                        "path": str(source),
                        "title": "Machine Manual",
                        "user_identifier": "alice",
                        "document_id": "manual-1",
                        "source": "onedrive",
                        "tags": ["pdf", "manual"],
                        "metadata": {"department": "service"},
                    },
                )
            )

    result = asyncio.run(run())

    assert result["document_id"] == "manual-1"
    assert result["status"] == "queued"
    assert memory.calls == []
    completed = manager.process_next(worker_id="worker-a")
    assert completed is not None and completed.status == "succeeded"
    assert memory.calls[0]["text"] == "# Manual\n\nConverted inside the remote MCP."
    assert memory.calls[0]["chunk_chars"] == 4096
    metadata = memory.calls[0]["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["department"] == "service"
    assert metadata["document_processing"]["transport"] == "mcp-chunk-upload"  # type: ignore[index]
    assert list((tmp_path / "uploads").iterdir()) == []


def test_file_pipe_rejects_paths_outside_allowlisted_roots(tmp_path: Path) -> None:
    from turing_agentmemory_mcp.file_pipe import create_file_pipe_proxy

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"%PDF")
    proxy = create_file_pipe_proxy(
        create_mcp_app(RecordingMemory()),  # type: ignore[arg-type]
        allowed_roots=[allowed],
        chunk_bytes=4,
    )

    async def run() -> None:
        async with Client(proxy) as client:
            await client.call_tool(
                "document_ingest_file",
                {
                    "path": str(outside),
                    "title": "Outside",
                    "user_identifier": "alice",
                },
            )

    with pytest.raises(ToolError, match="allowlisted"):
        asyncio.run(run())
