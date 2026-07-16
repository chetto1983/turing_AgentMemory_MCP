"""Staging and worker lifecycle for asynchronous document ingestion."""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from turing_agentmemory_mcp.document_jobs import DocumentIngestJob, DocumentJobStore
from turing_agentmemory_mcp.document_processing import (
    ConvertedDocument,
    convert_document_to_markdown,
)
from turing_agentmemory_mcp.tenant_identity import validate_user_identifier
from turing_agentmemory_mcp.tenant_router import StaticStoreResolver, StoreResolver

Converter = Callable[[str | Path], ConvertedDocument]
StoreFactory = Callable[[], Any]


class DocumentIngestManager:
    def __init__(
        self,
        jobs: DocumentJobStore,
        *,
        staging_root: str | Path,
        store_factory: StoreFactory,
        converter: Converter = convert_document_to_markdown,
        lease_seconds: int = 900,
        heartbeat_seconds: float = 15.0,
        poll_seconds: float = 1.0,
        max_attempts: int = 3,
    ) -> None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        if heartbeat_seconds <= 0 or heartbeat_seconds >= lease_seconds:
            raise ValueError("heartbeat_seconds must be positive and shorter than the lease")
        if poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        self.jobs = jobs
        self.staging_root = Path(staging_root).expanduser().resolve()
        store_or_resolver = store_factory()
        self.resolver = (
            store_or_resolver
            if isinstance(store_or_resolver, StoreResolver)
            else StaticStoreResolver(store_or_resolver)
        )
        self.converter = converter
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.poll_seconds = poll_seconds
        self.max_attempts = max_attempts
        self.worker_id = f"document-worker-{uuid.uuid4().hex}"
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.jobs.initialize()
        self.staging_root.mkdir(parents=True, exist_ok=True)

    def enqueue_file(
        self,
        path: str | Path,
        *,
        user_identifier: str,
        title: str,
        document_id: str | None = None,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
        transport: str = "server-local-file",
        expected_sha256: str | None = None,
        expected_bytes: int | None = None,
    ) -> DocumentIngestJob:
        tenant = validate_user_identifier(user_identifier)
        source_path = Path(path).expanduser().resolve(strict=True)
        if not source_path.is_file():
            raise ValueError(f"{source_path} is not a file")
        total_bytes, sha256 = _hash_file(source_path)
        if expected_bytes is not None and expected_bytes != total_bytes:
            raise ValueError("staged document size changed before enqueue")
        if expected_sha256 is not None and expected_sha256.lower() != sha256:
            raise ValueError("staged document SHA-256 changed before enqueue")

        key = self.jobs.idempotency_key(
            user_identifier=tenant,
            document_id=str(document_id or "").strip(),
            filename=source_path.name,
            sha256=sha256,
        )
        target_directory = self.staging_root / key
        target = target_directory / source_path.name
        target_directory.mkdir(parents=True, exist_ok=True)
        if not target.exists() or _hash_file(target) != (total_bytes, sha256):
            temporary = target_directory / f".{source_path.name}.{uuid.uuid4().hex}.part"
            try:
                shutil.copyfile(source_path, temporary)
                copied_bytes, copied_sha256 = _hash_file(temporary)
                if copied_bytes != total_bytes or copied_sha256 != sha256:
                    raise ValueError("staged document copy failed integrity verification")
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)

        enriched_metadata = dict(metadata or {})
        raw_processing = enriched_metadata.get("document_processing")
        processing = dict(raw_processing) if isinstance(raw_processing, dict) else {}
        processing.update(
            {
                "source_filename": source_path.name,
                "transport": transport,
                "sha256": sha256,
                "bytes": total_bytes,
            }
        )
        enriched_metadata["document_processing"] = processing
        try:
            job = self.jobs.enqueue(
                user_identifier=tenant,
                title=title,
                staged_path=target,
                filename=source_path.name,
                sha256=sha256,
                total_bytes=total_bytes,
                document_id=document_id,
                source=source,
                tags=tags,
                metadata=enriched_metadata,
                expires_at=expires_at,
                idempotency_key=key,
                max_attempts=self.max_attempts,
            )
        except BaseException:
            self._discard_staged_path(target)
            raise
        if job.status in {"succeeded", "canceled"}:
            self._discard_staged_path(target)
        self._wake.set()
        return job

    def get(self, job_id: str, *, user_identifier: str) -> DocumentIngestJob | None:
        return self.jobs.get(job_id, user_identifier=user_identifier)

    def runtime_status(self) -> dict[str, object]:
        thread = self._thread
        return {
            "worker_running": bool(thread is not None and thread.is_alive()),
            "counts": self.jobs.status_counts(),
        }

    def cancel(self, job_id: str, *, user_identifier: str) -> DocumentIngestJob:
        job = self.jobs.cancel(job_id, user_identifier=user_identifier)
        if job.status == "canceled":
            self._discard_staged_path(Path(job.staged_path))
        self._wake.set()
        return job

    def retry(self, job_id: str, *, user_identifier: str) -> DocumentIngestJob:
        current = self.jobs.get(job_id, user_identifier=user_identifier)
        if current is None:
            raise ValueError("document ingestion job is unknown")
        if not Path(current.staged_path).is_file():
            raise ValueError("document staging file is no longer available")
        job = self.jobs.retry(job_id, user_identifier=user_identifier)
        self._wake.set()
        return job

    def process_next(
        self,
        *,
        worker_id: str | None = None,
    ) -> DocumentIngestJob | None:
        owner = worker_id or self.worker_id
        job = self.jobs.claim(
            worker_id=owner,
            lease_seconds=self.lease_seconds,
        )
        if job is None:
            return None
        try:
            document_memory = self.resolver.resolve(job.user_identifier).memory
        except Exception:
            return self.jobs.fail(
                job.job_id,
                worker_id=owner,
                error_code="document_indexing_unavailable",
                error_message="Document indexing service is unavailable",
                retryable=True,
            )
        staged_path = Path(job.staged_path)
        if not staged_path.is_file():
            return self.jobs.fail(
                job.job_id,
                worker_id=owner,
                error_code="staged_file_missing",
                error_message="Document staging file is unavailable",
                retryable=False,
            )

        self.jobs.update_progress(
            job.job_id,
            worker_id=owner,
            stage="converting",
            current=0,
            total=0,
            lease_seconds=self.lease_seconds,
        )
        try:
            with self._heartbeat(job.job_id, owner):
                converted = self.converter(staged_path)
        except ValueError:
            return self.jobs.fail(
                job.job_id,
                worker_id=owner,
                error_code="invalid_document",
                error_message="Document conversion failed",
                retryable=False,
            )
        except Exception:
            return self.jobs.fail(
                job.job_id,
                worker_id=owner,
                error_code="document_conversion_unavailable",
                error_message="Document conversion service is unavailable",
                retryable=True,
            )

        if self.jobs.cancel_requested(job.job_id, worker_id=owner):
            canceled = self.jobs.mark_canceled(job.job_id, worker_id=owner)
            self._discard_staged_path(staged_path)
            return canceled

        metadata = dict(job.metadata)
        raw_processing = metadata.get("document_processing")
        processing = dict(raw_processing) if isinstance(raw_processing, dict) else {}
        converted_processing = dict(converted.metadata)
        converted_processing.pop("source_path", None)
        processing.update(converted_processing)
        processing.update(
            {
                "source_filename": job.filename,
                "sha256": job.sha256,
                "bytes": job.total_bytes,
            }
        )
        metadata["document_processing"] = processing
        progress_total = max(1, _positive_int(processing.get("page_count"), default=1))
        self.jobs.update_progress(
            job.job_id,
            worker_id=owner,
            stage="indexing",
            current=0,
            total=progress_total,
            lease_seconds=self.lease_seconds,
        )
        try:
            with self._heartbeat(job.job_id, owner):
                result = document_memory.ingest_document_text(
                    user_identifier=job.user_identifier,
                    title=job.title,
                    text=converted.text,
                    chunk_chars=converted.chunk_chars or 360,
                    document_id=job.document_id or None,
                    source=job.source,
                    tags=list(job.tags),
                    metadata=metadata,
                    expires_at=job.expires_at or None,
                )
        except Exception:
            return self.jobs.fail(
                job.job_id,
                worker_id=owner,
                error_code="document_indexing_unavailable",
                error_message="Document indexing service is unavailable",
                retryable=True,
            )

        payload = result.to_dict() if hasattr(result, "to_dict") else dict(result)
        succeeded = self.jobs.succeed(job.job_id, worker_id=owner, result=payload)
        self._discard_staged_path(staged_path)
        return succeeded

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="agentmemory-document-worker",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 10.0) -> None:
        self._stop.set()
        self._wake.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                processed = self.process_next(worker_id=self.worker_id)
            except Exception:
                processed = None
            if processed is None:
                self._wake.wait(self.poll_seconds)
                self._wake.clear()

    @contextmanager
    def _heartbeat(self, job_id: str, worker_id: str):
        stopped = threading.Event()

        def renew() -> None:
            while not stopped.wait(self.heartbeat_seconds):
                try:
                    self.jobs.renew_lease(
                        job_id,
                        worker_id=worker_id,
                        lease_seconds=self.lease_seconds,
                    )
                except ValueError:
                    return

        thread = threading.Thread(target=renew, name=f"{worker_id}-heartbeat", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stopped.set()
            thread.join(min(self.heartbeat_seconds, 1.0))

    def _discard_staged_path(self, path: Path) -> None:
        try:
            directory = path.resolve().parent
            directory.relative_to(self.staging_root)
        except (OSError, ValueError):
            return
        shutil.rmtree(directory, ignore_errors=True)


def _hash_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    total_bytes = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
            total_bytes += len(chunk)
    return total_bytes, digest.hexdigest()


def _positive_int(value: object, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def document_ingest_manager_from_env(*, store_factory: StoreFactory) -> DocumentIngestManager:
    home = Path(os.environ.get("BERTONI_HOME", "/bertoni"))
    return DocumentIngestManager(
        DocumentJobStore(
            os.environ.get(
                "AGENTMEMORY_DOCUMENT_JOB_PATH",
                str(home / "data" / "agent-memory-document-jobs.sqlite3"),
            )
        ),
        staging_root=os.environ.get(
            "AGENTMEMORY_DOCUMENT_STAGING_ROOT",
            str(home / "data" / "document-ingest"),
        ),
        store_factory=store_factory,
        lease_seconds=int(os.environ.get("AGENTMEMORY_DOCUMENT_JOB_LEASE_SECONDS", "900")),
        heartbeat_seconds=float(os.environ.get("AGENTMEMORY_DOCUMENT_JOB_HEARTBEAT_SECONDS", "15")),
        poll_seconds=float(os.environ.get("AGENTMEMORY_DOCUMENT_JOB_POLL_SECONDS", "1")),
        max_attempts=int(os.environ.get("AGENTMEMORY_DOCUMENT_JOB_MAX_ATTEMPTS", "3")),
    )
