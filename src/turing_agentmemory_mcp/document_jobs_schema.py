"""Dataclass schema and row-serialization helpers for document ingestion jobs."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime

DOCUMENT_JOB_SCHEMA_VERSION = 1
_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_RUNNING_STATUSES = {"running", "cancel_requested"}


@dataclass(frozen=True, slots=True)
class DocumentIngestJob:
    job_id: str
    user_identifier: str
    idempotency_key: str
    title: str
    staged_path: str
    filename: str
    sha256: str
    total_bytes: int
    document_id: str
    source: str
    tags: list[str]
    metadata: dict[str, object]
    expires_at: str
    status: str
    stage: str
    progress_current: int
    progress_total: int
    attempt: int
    max_attempts: int
    next_attempt_at: str
    lease_owner: str
    lease_expires_at: str
    error_code: str
    error_message: str
    result: dict[str, object]
    created_at: str
    updated_at: str
    started_at: str
    completed_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "user_identifier": self.user_identifier,
            "title": self.title,
            "filename": self.filename,
            "sha256": self.sha256,
            "total_bytes": self.total_bytes,
            "document_id": self.document_id,
            "source": self.source,
            "tags": list(self.tags),
            "metadata": dict(self.metadata),
            "expires_at": self.expires_at,
            "status": self.status,
            "stage": self.stage,
            "progress_current": self.progress_current,
            "progress_total": self.progress_total,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "next_attempt_at": self.next_attempt_at,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "result": dict(self.result),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


def _instant(value: datetime | None) -> datetime:
    instant = value or datetime.now(UTC)
    if instant.tzinfo is None:
        raise ValueError("job timestamps must be timezone-aware")
    return instant.astimezone(UTC)


def _timestamp(value: datetime | None) -> str:
    return _instant(value).isoformat().replace("+00:00", "Z")


def _json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _job(row: sqlite3.Row) -> DocumentIngestJob:
    return DocumentIngestJob(
        job_id=str(row["job_id"]),
        user_identifier=str(row["user_identifier"]),
        idempotency_key=str(row["idempotency_key"]),
        title=str(row["title"]),
        staged_path=str(row["staged_path"]),
        filename=str(row["filename"]),
        sha256=str(row["sha256"]),
        total_bytes=int(row["total_bytes"]),
        document_id=str(row["document_id"]),
        source=str(row["source"]),
        tags=list(json.loads(row["tags_json"])),
        metadata=dict(json.loads(row["metadata_json"])),
        expires_at=str(row["expires_at"]),
        status=str(row["status"]),
        stage=str(row["stage"]),
        progress_current=int(row["progress_current"]),
        progress_total=int(row["progress_total"]),
        attempt=int(row["attempt"]),
        max_attempts=int(row["max_attempts"]),
        next_attempt_at=str(row["next_attempt_at"]),
        lease_owner=str(row["lease_owner"]),
        lease_expires_at=str(row["lease_expires_at"]),
        error_code=str(row["error_code"]),
        error_message=str(row["error_message"]),
        result=dict(json.loads(row["result_json"])),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        started_at=str(row["started_at"]),
        completed_at=str(row["completed_at"]),
    )
