from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any

from fastmcp import Client

from turing_agentmemory_mcp.document_job_manager import DocumentIngestManager
from turing_agentmemory_mcp.document_jobs import DocumentJobStore
from turing_agentmemory_mcp.document_processing import ConvertedDocument
from turing_agentmemory_mcp.file_upload import DocumentUploadStore
from turing_agentmemory_mcp.models import IngestedDocument
from turing_agentmemory_mcp.server import create_mcp_app
from turing_agentmemory_mcp.tenant_router import StaticStoreResolver


def payload(result: Any) -> Any:
    if hasattr(result, "structured_content") and result.structured_content is not None:
        value = result.structured_content
        if isinstance(value, dict) and set(value) == {"result"}:
            return value["result"]
        return value
    if hasattr(result, "data") and result.data is not None:
        return result.data
    if hasattr(result, "content"):
        text = "".join(getattr(item, "text", "") for item in result.content)
        return json.loads(text)
    return result


class RecordingDocumentMemory:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def ingest_document_text(
        self,
        *,
        user_identifier: str,
        title: str,
        text: str,
        chunk_chars: int = 360,
        document_id: str | None = None,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> IngestedDocument:
        self.calls.append(
            {
                "user_identifier": user_identifier,
                "title": title,
                "text": text,
                "chunk_chars": chunk_chars,
                "document_id": document_id,
                "source": source,
                "tags": tags,
                "metadata": metadata,
                "expires_at": expires_at,
            }
        )
        return IngestedDocument(
            document_id=document_id or "doc-markitdown",
            title=title,
            chunk_count=2,
            user_identifier=user_identifier,
            source=source,
            tags=tags or [],
            metadata=metadata or {},
            expires_at=expires_at or "",
        )


def test_document_ingest_file_enqueues_then_reports_background_result(
    tmp_path: Path,
) -> None:
    source = tmp_path / "runbook.pdf"
    source.write_bytes(b"%PDF")
    memory = RecordingDocumentMemory()

    def fake_convert(path: str | Path) -> ConvertedDocument:
        assert Path(path).read_bytes() == b"%PDF"
        return ConvertedDocument(
            text="# Runbook\n\nKeep breaker A17 closed.",
            metadata={
                "converter": "markitdown",
                "source_filename": "runbook.pdf",
                "source_path": str(source),
            },
        )

    manager = DocumentIngestManager(
        DocumentJobStore(tmp_path / "jobs.sqlite3"),
        staging_root=tmp_path / "staging",
        store_factory=lambda: memory,
        converter=fake_convert,
    )

    async def enqueue() -> dict[str, object]:
        async with Client(
            create_mcp_app(memory, document_manager=manager)  # type: ignore[arg-type]
        ) as client:
            result = payload(
                await client.call_tool(
                    "document_ingest_file",
                    {
                        "user_identifier": "alice",
                        "title": "Machine Runbook",
                        "path": str(source),
                        "document_id": "doc-runbook",
                        "source": "ops",
                        "tags": ["pdf", "runbook"],
                        "metadata": {"department": "plant"},
                        "expires_at": "2099-01-02T00:00:00Z",
                    },
                )
            )
        return result

    queued = asyncio.run(enqueue())
    assert queued["document_id"] == "doc-runbook"
    assert queued["status"] == "queued"
    assert memory.calls == []

    completed = manager.process_next(worker_id="worker-a")
    assert completed is not None and completed.status == "succeeded"

    async def status() -> dict[str, object]:
        async with Client(
            create_mcp_app(memory, document_manager=manager)  # type: ignore[arg-type]
        ) as client:
            return payload(
                await client.call_tool(
                    "document_ingest_status",
                    {"job_id": queued["job_id"], "user_identifier": "alice"},
                )
            )

    reported = asyncio.run(status())
    assert reported["status"] == "succeeded"
    assert reported["result"]["chunk_count"] == 2

    assert memory.calls == [
        {
            "user_identifier": "alice",
            "title": "Machine Runbook",
            "text": "# Runbook\n\nKeep breaker A17 closed.",
            "chunk_chars": 360,
            "document_id": "doc-runbook",
            "source": "ops",
            "tags": ["pdf", "runbook"],
            "metadata": {
                "department": "plant",
                "document_processing": {
                    "bytes": 4,
                    "converter": "markitdown",
                    "sha256": hashlib.sha256(b"%PDF").hexdigest(),
                    "source_filename": "runbook.pdf",
                    "transport": "server-local-file",
                },
            },
            "expires_at": "2099-01-02T00:00:00Z",
        }
    ]


def test_production_app_gives_document_worker_the_foreground_resolver(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    import turing_agentmemory_mcp.server as server_module

    memory = RecordingDocumentMemory()
    resolver = StaticStoreResolver(memory)  # type: ignore[arg-type]
    legacy_store = RecordingDocumentMemory()
    captured: dict[str, object] = {}

    def manager_from_env(*, store_factory: Any) -> object:
        captured["worker_dependency"] = store_factory()
        return object()

    monkeypatch.setattr(server_module, "tenant_router_from_env", lambda: resolver)
    monkeypatch.setattr(server_module, "store_from_env", lambda: legacy_store)
    monkeypatch.setattr(server_module, "document_ingest_manager_from_env", manager_from_env)
    monkeypatch.setattr(
        server_module,
        "document_upload_store_from_env",
        lambda: DocumentUploadStore(tmp_path / "uploads", max_file_bytes=32, chunk_bytes=4),
    )

    server_module.create_mcp_app(start_document_worker=False)

    assert captured["worker_dependency"] is resolver
