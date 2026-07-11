from __future__ import annotations

import threading
from pathlib import Path

from turing_agentmemory_mcp.document_job_manager import DocumentIngestManager
from turing_agentmemory_mcp.document_jobs import DocumentJobStore
from turing_agentmemory_mcp.document_processing import ConvertedDocument
from turing_agentmemory_mcp.models import IngestedDocument


class RecordingMemory:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def ingest_document_text(self, **kwargs: object) -> IngestedDocument:
        self.calls.append(dict(kwargs))
        return IngestedDocument(
            document_id=str(kwargs.get("document_id") or "generated-document"),
            title=str(kwargs["title"]),
            chunk_count=841,
            user_identifier=str(kwargs["user_identifier"]),
            source=str(kwargs.get("source") or ""),
            tags=list(kwargs.get("tags") or []),
            metadata=dict(kwargs.get("metadata") or {}),
            expires_at=str(kwargs.get("expires_at") or ""),
        )


def test_enqueue_stages_file_and_processes_it_after_source_is_removed(tmp_path: Path) -> None:
    source = tmp_path / "source" / "manual.pdf"
    source.parent.mkdir()
    source.write_bytes(b"%PDF-real-manual")
    memory = RecordingMemory()
    converted_paths: list[Path] = []

    def convert(path: str | Path) -> ConvertedDocument:
        staged = Path(path)
        converted_paths.append(staged)
        assert staged.read_bytes() == b"%PDF-real-manual"
        return ConvertedDocument(
            text="<!-- page 1 -->\n\nG220 operation instructions",
            metadata={"converter": "pdfium-text", "page_count": 830},
            chunk_chars=4096,
        )

    jobs = DocumentJobStore(tmp_path / "data" / "jobs.sqlite3")
    manager = DocumentIngestManager(
        jobs,
        staging_root=tmp_path / "data" / "staging",
        store_factory=lambda: memory,
        converter=convert,
    )

    queued = manager.enqueue_file(
        source,
        user_identifier="alice",
        title="G220 Operation Instructions",
        document_id="g220",
        source="field-service",
        tags=["manual"],
        metadata={"department": "service"},
        transport="mcp-chunk-upload",
    )
    staged_path = Path(queued.staged_path)
    source.unlink()

    assert queued.status == "queued"
    assert staged_path.is_file()
    processed = manager.process_next(worker_id="worker-a")

    assert processed is not None
    assert processed.status == "succeeded"
    assert processed.result["document_id"] == "g220"
    assert converted_paths == [staged_path]
    assert not staged_path.exists()
    assert memory.calls[0]["chunk_chars"] == 4096
    processing = memory.calls[0]["metadata"]["document_processing"]  # type: ignore[index]
    assert processing == {
        "bytes": len(b"%PDF-real-manual"),
        "converter": "pdfium-text",
        "page_count": 830,
        "sha256": queued.sha256,
        "source_filename": "manual.pdf",
        "transport": "mcp-chunk-upload",
    }


def test_duplicate_enqueue_reuses_job_and_staged_file(tmp_path: Path) -> None:
    source = tmp_path / "manual.pdf"
    source.write_bytes(b"same-document")
    memory = RecordingMemory()
    manager = DocumentIngestManager(
        DocumentJobStore(tmp_path / "jobs.sqlite3"),
        staging_root=tmp_path / "staging",
        store_factory=lambda: memory,
    )

    first = manager.enqueue_file(source, user_identifier="alice", title="Manual")
    duplicate = manager.enqueue_file(source, user_identifier="alice", title="Manual")

    assert duplicate.job_id == first.job_id
    assert duplicate.staged_path == first.staged_path
    assert list((tmp_path / "staging").rglob("manual.pdf")) == [Path(first.staged_path)]


def test_canceling_a_queued_job_removes_the_staged_file(tmp_path: Path) -> None:
    source = tmp_path / "manual.pdf"
    source.write_bytes(b"cancel-me")
    memory = RecordingMemory()
    manager = DocumentIngestManager(
        DocumentJobStore(tmp_path / "jobs.sqlite3"),
        staging_root=tmp_path / "staging",
        store_factory=lambda: memory,
    )
    queued = manager.enqueue_file(source, user_identifier="alice", title="Manual")

    canceled = manager.cancel(queued.job_id, user_identifier="alice")

    assert canceled.status == "canceled"
    assert not Path(queued.staged_path).exists()
    assert manager.process_next(worker_id="worker-a") is None
    assert memory.calls == []


def test_processing_failure_is_recorded_without_exposing_exception_text(tmp_path: Path) -> None:
    source = tmp_path / "manual.pdf"
    source.write_bytes(b"broken")

    def fail_conversion(_path: str | Path) -> ConvertedDocument:
        raise ValueError("secret path and provider token must not escape")

    manager = DocumentIngestManager(
        DocumentJobStore(tmp_path / "jobs.sqlite3"),
        staging_root=tmp_path / "staging",
        store_factory=RecordingMemory,
        converter=fail_conversion,
    )
    queued = manager.enqueue_file(source, user_identifier="alice", title="Manual")

    failed = manager.process_next(worker_id="worker-a")

    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_code == "invalid_document"
    assert failed.error_message == "Document conversion failed"
    assert "secret" not in failed.error_message
    assert Path(queued.staged_path).exists()


def test_background_worker_wakes_and_completes_an_enqueued_job(tmp_path: Path) -> None:
    source = tmp_path / "manual.txt"
    source.write_text("industrial async ingestion", encoding="utf-8")
    completed = threading.Event()

    class SignalingMemory(RecordingMemory):
        def ingest_document_text(self, **kwargs: object) -> IngestedDocument:
            result = super().ingest_document_text(**kwargs)
            completed.set()
            return result

    memory = SignalingMemory()
    manager = DocumentIngestManager(
        DocumentJobStore(tmp_path / "jobs.sqlite3"),
        staging_root=tmp_path / "staging",
        store_factory=lambda: memory,
        converter=lambda _path: ConvertedDocument(
            text="industrial async ingestion",
            metadata={"converter": "test"},
        ),
        poll_seconds=0.05,
    )
    manager.start()
    try:
        queued = manager.enqueue_file(source, user_identifier="alice", title="Manual")
        assert completed.wait(2.0)
    finally:
        manager.stop()

    status = manager.get(queued.job_id, user_identifier="alice")
    assert status is not None
    assert status.status == "succeeded"
    assert manager.runtime_status()["worker_running"] is False
