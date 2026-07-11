"""Durable tenant-scoped state for asynchronous document ingestion."""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

from turing_agentmemory_mcp.document_jobs_schema import (
    _RUNNING_STATUSES,
    _SHA256_PATTERN,
    DOCUMENT_JOB_SCHEMA_VERSION,
    DocumentIngestJob,
    _instant,
    _job,
    _json,
    _timestamp,
)

BUSY_TIMEOUT_MS = 5000


class DocumentJobStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS document_job_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS document_ingest_jobs (
                    job_id TEXT PRIMARY KEY,
                    user_identifier TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    staged_path TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    total_bytes INTEGER NOT NULL,
                    document_id TEXT NOT NULL,
                    source TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress_current INTEGER NOT NULL,
                    progress_total INTEGER NOT NULL,
                    attempt INTEGER NOT NULL,
                    max_attempts INTEGER NOT NULL,
                    next_attempt_at TEXT NOT NULL,
                    lease_owner TEXT NOT NULL,
                    lease_expires_at TEXT NOT NULL,
                    error_code TEXT NOT NULL,
                    error_message TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS document_ingest_jobs_claim
                ON document_ingest_jobs(status, next_attempt_at, lease_expires_at, created_at);
                """
            )
            version_row = connection.execute(
                "SELECT value FROM document_job_meta WHERE key = 'schema_version'"
            ).fetchone()
            if version_row is not None and int(version_row["value"]) != DOCUMENT_JOB_SCHEMA_VERSION:
                connection.rollback()
                raise RuntimeError(
                    f"document job schema {version_row['value']} does not match "
                    f"{DOCUMENT_JOB_SCHEMA_VERSION}"
                )
            connection.execute(
                "INSERT OR REPLACE INTO document_job_meta(key, value) VALUES('schema_version', ?)",
                (str(DOCUMENT_JOB_SCHEMA_VERSION),),
            )
            connection.commit()

    def enqueue(
        self,
        *,
        user_identifier: str,
        title: str,
        staged_path: str | Path,
        filename: str,
        sha256: str,
        total_bytes: int,
        document_id: str | None = None,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
        idempotency_key: str | None = None,
        max_attempts: int = 3,
        now: datetime | None = None,
    ) -> DocumentIngestJob:
        tenant = user_identifier.strip()
        normalized_title = title.strip()
        safe_filename = Path(filename).name
        digest = sha256.strip().lower()
        if not tenant:
            raise ValueError("user_identifier is required")
        if not normalized_title:
            raise ValueError("title is required")
        if not safe_filename or safe_filename in {".", ".."}:
            raise ValueError("filename is required")
        if not _SHA256_PATTERN.fullmatch(digest):
            raise ValueError("sha256 must be a lowercase hexadecimal SHA-256 digest")
        if total_bytes < 1:
            raise ValueError("total_bytes must be positive")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        normalized_document_id = str(document_id or "").strip()
        key = (idempotency_key or "").strip() or self.idempotency_key(
            user_identifier=tenant,
            document_id=normalized_document_id,
            filename=safe_filename,
            sha256=digest,
        )
        timestamp = _timestamp(now)
        job_id = f"docjob_{uuid.uuid4().hex}"
        tags_json = _json(list(tags or []))
        metadata_json = _json(dict(metadata or {}))
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT OR IGNORE INTO document_ingest_jobs(
                    job_id, user_identifier, idempotency_key, title, staged_path, filename,
                    sha256, total_bytes, document_id, source, tags_json, metadata_json,
                    expires_at, status, stage, progress_current, progress_total, attempt,
                    max_attempts, next_attempt_at, lease_owner, lease_expires_at,
                    error_code, error_message, result_json, created_at, updated_at,
                    started_at, completed_at
                ) VALUES(
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', 'queued', 0, 0, 0,
                    ?, ?, '', '', '', '', '{}', ?, ?, '', ''
                )
                """,
                (
                    job_id,
                    tenant,
                    key,
                    normalized_title,
                    str(staged_path),
                    safe_filename,
                    digest,
                    total_bytes,
                    normalized_document_id,
                    source.strip(),
                    tags_json,
                    metadata_json,
                    str(expires_at or ""),
                    max_attempts,
                    timestamp,
                    timestamp,
                    timestamp,
                ),
            )
            row = connection.execute(
                "SELECT * FROM document_ingest_jobs WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        return _job(row)

    @staticmethod
    def idempotency_key(
        *,
        user_identifier: str,
        document_id: str,
        filename: str,
        sha256: str,
    ) -> str:
        identity = document_id or Path(filename).name
        material = "\0".join((user_identifier, identity, sha256)).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def get(self, job_id: str, *, user_identifier: str) -> DocumentIngestJob | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM document_ingest_jobs WHERE job_id = ? AND user_identifier = ?",
                (job_id, user_identifier.strip()),
            ).fetchone()
        return _job(row) if row is not None else None

    def status_counts(self) -> dict[str, int]:
        counts = {
            "queued": 0,
            "running": 0,
            "cancel_requested": 0,
            "succeeded": 0,
            "failed": 0,
            "canceled": 0,
        }
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM document_ingest_jobs GROUP BY status"
            ).fetchall()
        for row in rows:
            status = str(row["status"])
            if status in counts:
                counts[status] = int(row["count"])
        return counts

    def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> DocumentIngestJob | None:
        owner = worker_id.strip()
        if not owner:
            raise ValueError("worker_id is required")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        instant = _instant(now)
        timestamp = _timestamp(instant)
        lease_expires_at = _timestamp(instant + timedelta(seconds=lease_seconds))
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE document_ingest_jobs
                SET status = 'failed', stage = 'failed', error_code = 'attempts_exhausted',
                    error_message = 'Document ingestion attempts exhausted', updated_at = ?,
                    completed_at = ?, lease_owner = '', lease_expires_at = ''
                WHERE status = 'running' AND lease_expires_at != '' AND lease_expires_at <= ?
                    AND attempt >= max_attempts
                """,
                (timestamp, timestamp, timestamp),
            )
            row = connection.execute(
                """
                SELECT * FROM document_ingest_jobs
                WHERE attempt < max_attempts AND (
                    (status = 'queued' AND next_attempt_at <= ?)
                    OR (status = 'running' AND lease_expires_at != '' AND lease_expires_at <= ?)
                )
                ORDER BY created_at, job_id
                LIMIT 1
                """,
                (timestamp, timestamp),
            ).fetchone()
            if row is None:
                return None
            started_at = row["started_at"] or timestamp
            connection.execute(
                """
                UPDATE document_ingest_jobs
                SET status = 'running', stage = CASE WHEN stage = 'queued' THEN 'starting' ELSE stage END,
                    attempt = attempt + 1, lease_owner = ?, lease_expires_at = ?,
                    started_at = ?, updated_at = ?, error_code = '', error_message = ''
                WHERE job_id = ?
                """,
                (owner, lease_expires_at, started_at, timestamp, row["job_id"]),
            )
            claimed = connection.execute(
                "SELECT * FROM document_ingest_jobs WHERE job_id = ?", (row["job_id"],)
            ).fetchone()
        return _job(claimed)

    def update_progress(
        self,
        job_id: str,
        *,
        worker_id: str,
        stage: str,
        current: int,
        total: int,
        lease_seconds: int = 60,
        now: datetime | None = None,
    ) -> DocumentIngestJob:
        if current < 0 or total < 0 or (total and current > total):
            raise ValueError("progress must satisfy 0 <= current <= total")
        normalized_stage = stage.strip()
        if not normalized_stage:
            raise ValueError("stage is required")
        instant = _instant(now)
        timestamp = _timestamp(instant)
        lease_expires_at = _timestamp(instant + timedelta(seconds=lease_seconds))
        with self._transaction() as connection:
            self._require_lease(connection, job_id, worker_id, timestamp)
            connection.execute(
                """
                UPDATE document_ingest_jobs
                SET stage = ?, progress_current = ?, progress_total = ?, updated_at = ?,
                    lease_expires_at = ?
                WHERE job_id = ?
                """,
                (normalized_stage, current, total, timestamp, lease_expires_at, job_id),
            )
            row = self._row(connection, job_id)
        return _job(row)

    def renew_lease(
        self,
        job_id: str,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> DocumentIngestJob:
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        instant = _instant(now)
        timestamp = _timestamp(instant)
        lease_expires_at = _timestamp(instant + timedelta(seconds=lease_seconds))
        with self._transaction() as connection:
            self._require_owner(connection, job_id, worker_id)
            connection.execute(
                """
                UPDATE document_ingest_jobs
                SET lease_expires_at = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (lease_expires_at, timestamp, job_id),
            )
            row = self._row(connection, job_id)
        return _job(row)

    def cancel(
        self,
        job_id: str,
        *,
        user_identifier: str,
        now: datetime | None = None,
    ) -> DocumentIngestJob:
        timestamp = _timestamp(now)
        with self._transaction() as connection:
            row = self._tenant_row(connection, job_id, user_identifier)
            if row["status"] == "queued":
                connection.execute(
                    """
                    UPDATE document_ingest_jobs
                    SET status = 'canceled', stage = 'canceled', updated_at = ?, completed_at = ?
                    WHERE job_id = ?
                    """,
                    (timestamp, timestamp, job_id),
                )
            elif row["status"] == "running":
                connection.execute(
                    "UPDATE document_ingest_jobs SET status = 'cancel_requested', updated_at = ? "
                    "WHERE job_id = ?",
                    (timestamp, job_id),
                )
            row = self._row(connection, job_id)
        return _job(row)

    def cancel_requested(self, job_id: str, *, worker_id: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT status, lease_owner FROM document_ingest_jobs WHERE job_id = ?",
                (job_id,),
            ).fetchone()
        return bool(
            row is not None
            and row["status"] == "cancel_requested"
            and row["lease_owner"] == worker_id.strip()
        )

    def mark_canceled(
        self,
        job_id: str,
        *,
        worker_id: str,
        now: datetime | None = None,
    ) -> DocumentIngestJob:
        timestamp = _timestamp(now)
        with self._transaction() as connection:
            self._require_owner(connection, job_id, worker_id)
            connection.execute(
                """
                UPDATE document_ingest_jobs
                SET status = 'canceled', stage = 'canceled', updated_at = ?, completed_at = ?,
                    lease_owner = '', lease_expires_at = ''
                WHERE job_id = ?
                """,
                (timestamp, timestamp, job_id),
            )
            row = self._row(connection, job_id)
        return _job(row)

    def fail(
        self,
        job_id: str,
        *,
        worker_id: str,
        error_code: str,
        error_message: str,
        retryable: bool,
        retry_delay_seconds: int = 5,
        now: datetime | None = None,
    ) -> DocumentIngestJob:
        instant = _instant(now)
        timestamp = _timestamp(instant)
        with self._transaction() as connection:
            current = self._require_owner(connection, job_id, worker_id)
            will_retry = retryable and int(current["attempt"]) < int(current["max_attempts"])
            status = "queued" if will_retry else "failed"
            stage = "queued" if will_retry else "failed"
            completed_at = "" if will_retry else timestamp
            next_attempt_at = _timestamp(instant + timedelta(seconds=max(0, retry_delay_seconds)))
            connection.execute(
                """
                UPDATE document_ingest_jobs
                SET status = ?, stage = ?, error_code = ?, error_message = ?,
                    next_attempt_at = ?, updated_at = ?, completed_at = ?,
                    lease_owner = '', lease_expires_at = ''
                WHERE job_id = ?
                """,
                (
                    status,
                    stage,
                    error_code.strip() or "document_ingest_failed",
                    error_message.strip() or "Document ingestion failed",
                    next_attempt_at,
                    timestamp,
                    completed_at,
                    job_id,
                ),
            )
            row = self._row(connection, job_id)
        return _job(row)

    def retry(
        self,
        job_id: str,
        *,
        user_identifier: str,
        now: datetime | None = None,
    ) -> DocumentIngestJob:
        timestamp = _timestamp(now)
        with self._transaction() as connection:
            row = self._tenant_row(connection, job_id, user_identifier)
            if row["status"] != "failed":
                raise ValueError("only failed document ingestion jobs can be retried")
            connection.execute(
                """
                UPDATE document_ingest_jobs
                SET status = 'queued', stage = 'queued', attempt = 0, next_attempt_at = ?,
                    error_code = '', error_message = '', result_json = '{}', updated_at = ?,
                    started_at = '', completed_at = '', lease_owner = '', lease_expires_at = ''
                WHERE job_id = ?
                """,
                (timestamp, timestamp, job_id),
            )
            row = self._row(connection, job_id)
        return _job(row)

    def succeed(
        self,
        job_id: str,
        *,
        worker_id: str,
        result: dict[str, object],
        now: datetime | None = None,
    ) -> DocumentIngestJob:
        timestamp = _timestamp(now)
        with self._transaction() as connection:
            self._require_owner(connection, job_id, worker_id)
            connection.execute(
                """
                UPDATE document_ingest_jobs
                SET status = 'succeeded', stage = 'complete', progress_current = progress_total,
                    result_json = ?, error_code = '', error_message = '', updated_at = ?,
                    completed_at = ?, lease_owner = '', lease_expires_at = ''
                WHERE job_id = ?
                """,
                (_json(result), timestamp, timestamp, job_id),
            )
            row = self._row(connection, job_id)
        return _job(row)

    def _require_lease(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        worker_id: str,
        timestamp: str,
    ) -> sqlite3.Row:
        row = self._require_owner(connection, job_id, worker_id)
        if row["lease_expires_at"] <= timestamp:
            raise ValueError("document ingestion job does not have an active lease")
        return row

    def _require_owner(
        self,
        connection: sqlite3.Connection,
        job_id: str,
        worker_id: str,
    ) -> sqlite3.Row:
        row = self._row(connection, job_id)
        if row["status"] not in _RUNNING_STATUSES or row["lease_owner"] != worker_id.strip():
            raise ValueError("document ingestion job does not have an active lease")
        return row

    @staticmethod
    def _row(connection: sqlite3.Connection, job_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM document_ingest_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            raise ValueError("document ingestion job is unknown")
        return row

    @classmethod
    def _tenant_row(
        cls,
        connection: sqlite3.Connection,
        job_id: str,
        user_identifier: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM document_ingest_jobs WHERE job_id = ? AND user_identifier = ?",
            (job_id, user_identifier.strip()),
        ).fetchone()
        if row is None:
            raise ValueError("document ingestion job is unknown")
        return row

    @contextmanager
    def _transaction(self):
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            connection.commit()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000)
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        try:
            yield connection
        finally:
            connection.close()
