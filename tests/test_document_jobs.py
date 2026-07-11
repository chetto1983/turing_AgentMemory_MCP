from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from turing_agentmemory_mcp.document_jobs import DocumentJobStore

NOW = datetime(2026, 7, 11, 10, 0, tzinfo=UTC)


def enqueue_job(store: DocumentJobStore, **overrides: object):
    arguments: dict[str, object] = {
        "user_identifier": "alice",
        "title": "G220 Operation Instructions",
        "staged_path": "/turing/data/document-ingest/manual.pdf",
        "filename": "manual.pdf",
        "sha256": "a" * 64,
        "total_bytes": 1024,
        "document_id": "g220",
        "source": "field-service",
        "tags": ["manual", "pdf"],
        "metadata": {"department": "service"},
        "expires_at": "2099-01-01T00:00:00Z",
        "now": NOW,
    }
    arguments.update(overrides)
    return store.enqueue(**arguments)  # type: ignore[arg-type]


def test_enqueue_is_idempotent_and_get_is_tenant_scoped(tmp_path: Path) -> None:
    store = DocumentJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()

    first = enqueue_job(store)
    duplicate = enqueue_job(store, staged_path="/different/temporary/path.pdf")
    other_tenant = enqueue_job(store, user_identifier="bob")

    assert duplicate.job_id == first.job_id
    assert duplicate.staged_path == first.staged_path
    assert other_tenant.job_id != first.job_id
    assert store.get(first.job_id, user_identifier="alice") == first
    assert store.get(first.job_id, user_identifier="bob") is None
    assert first.to_dict()["metadata"] == {"department": "service"}


def test_claim_is_exclusive_and_recovers_an_expired_lease(tmp_path: Path) -> None:
    store = DocumentJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    queued = enqueue_job(store)

    first = store.claim(worker_id="worker-a", lease_seconds=30, now=NOW)

    assert first is not None
    assert first.job_id == queued.job_id
    assert first.status == "running"
    assert first.attempt == 1
    assert first.lease_owner == "worker-a"
    assert store.claim(worker_id="worker-b", lease_seconds=30, now=NOW) is None

    recovered = store.claim(
        worker_id="worker-b",
        lease_seconds=30,
        now=NOW + timedelta(seconds=31),
    )

    assert recovered is not None
    assert recovered.job_id == queued.job_id
    assert recovered.attempt == 2
    assert recovered.lease_owner == "worker-b"


def test_progress_requires_the_active_lease_and_cancel_is_cooperative(tmp_path: Path) -> None:
    store = DocumentJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    queued = enqueue_job(store)

    canceled = store.cancel(queued.job_id, user_identifier="alice", now=NOW)
    assert canceled.status == "canceled"
    assert canceled.stage == "canceled"

    running_job = enqueue_job(store, sha256="b" * 64, document_id="g220-rev2")
    running = store.claim(worker_id="worker-a", lease_seconds=60, now=NOW)
    assert running is not None and running.job_id == running_job.job_id

    with pytest.raises(ValueError, match="active lease"):
        store.update_progress(
            running.job_id,
            worker_id="worker-b",
            stage="converting",
            current=1,
            total=830,
            now=NOW,
        )

    progress = store.update_progress(
        running.job_id,
        worker_id="worker-a",
        stage="converting",
        current=10,
        total=830,
        lease_seconds=60,
        now=NOW + timedelta(seconds=5),
    )
    assert progress.progress_current == 10
    assert progress.progress_total == 830

    requested = store.cancel(running.job_id, user_identifier="alice", now=NOW)
    assert requested.status == "cancel_requested"
    assert store.cancel_requested(running.job_id, worker_id="worker-a") is True

    finished = store.mark_canceled(running.job_id, worker_id="worker-a", now=NOW)
    assert finished.status == "canceled"
    assert finished.completed_at


def test_failure_manual_retry_and_success_preserve_safe_result(tmp_path: Path) -> None:
    store = DocumentJobStore(tmp_path / "jobs.sqlite3")
    store.initialize()
    queued = enqueue_job(store, max_attempts=2)
    running = store.claim(worker_id="worker-a", lease_seconds=60, now=NOW)
    assert running is not None

    failed = store.fail(
        queued.job_id,
        worker_id="worker-a",
        error_code="embedding_provider_unavailable",
        error_message="Embedding provider did not respond",
        retryable=False,
        now=NOW,
    )
    assert failed.status == "failed"
    assert failed.error_code == "embedding_provider_unavailable"
    assert failed.lease_owner == ""

    retried = store.retry(queued.job_id, user_identifier="alice", now=NOW)
    assert retried.status == "queued"
    assert retried.attempt == 0
    assert retried.error_message == ""

    claimed = store.claim(worker_id="worker-b", lease_seconds=60, now=NOW)
    assert claimed is not None
    succeeded = store.succeed(
        queued.job_id,
        worker_id="worker-b",
        result={"document_id": "g220", "chunk_count": 841},
        now=NOW,
    )

    assert succeeded.status == "succeeded"
    assert succeeded.stage == "complete"
    assert succeeded.result == {"document_id": "g220", "chunk_count": 841}
    assert succeeded.to_dict()["result"] == {
        "document_id": "g220",
        "chunk_count": 841,
    }
