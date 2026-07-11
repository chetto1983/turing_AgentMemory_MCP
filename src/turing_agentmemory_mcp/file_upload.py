from __future__ import annotations

import base64
import hashlib
import os
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class UploadedFile:
    upload_id: str
    user_identifier: str
    filename: str
    path: Path
    total_bytes: int
    sha256: str
    attributes: dict[str, Any]


@dataclass
class _UploadSession:
    upload_id: str
    user_identifier: str
    filename: str
    path: Path
    total_bytes: int
    sha256: str
    attributes: dict[str, Any] = field(default_factory=dict)
    received_bytes: int = 0
    next_sequence: int = 0


class DocumentUploadStore:
    def __init__(
        self,
        root: str | Path,
        *,
        max_file_bytes: int,
        chunk_bytes: int,
    ) -> None:
        if max_file_bytes < 1:
            raise ValueError("max_file_bytes must be positive")
        if chunk_bytes < 1:
            raise ValueError("chunk_bytes must be positive")
        self.root = Path(root).expanduser().resolve()
        self.max_file_bytes = max_file_bytes
        self.chunk_bytes = chunk_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, _UploadSession] = {}

    def begin(
        self,
        *,
        user_identifier: str,
        filename: str,
        total_bytes: int,
        sha256: str,
        attributes: dict[str, Any] | None = None,
    ) -> dict[str, object]:
        tenant = user_identifier.strip()
        safe_filename = Path(filename).name
        digest = sha256.strip().lower()
        if not tenant:
            raise ValueError("user_identifier is required")
        if not safe_filename or safe_filename in {".", ".."}:
            raise ValueError("filename is required")
        if total_bytes < 1 or total_bytes > self.max_file_bytes:
            raise ValueError(f"total_bytes must be between 1 and {self.max_file_bytes}")
        if not _SHA256_PATTERN.fullmatch(digest):
            raise ValueError("sha256 must be a lowercase hexadecimal SHA-256 digest")

        upload_id = uuid.uuid4().hex
        directory = self.root / upload_id
        directory.mkdir(parents=False)
        path = directory / safe_filename
        path.touch(exist_ok=False)
        self._sessions[upload_id] = _UploadSession(
            upload_id=upload_id,
            user_identifier=tenant,
            filename=safe_filename,
            path=path,
            total_bytes=total_bytes,
            sha256=digest,
            attributes=dict(attributes or {}),
        )
        return {
            "upload_id": upload_id,
            "chunk_bytes": self.chunk_bytes,
            "total_bytes": total_bytes,
        }

    def append(
        self,
        upload_id: str,
        *,
        user_identifier: str,
        sequence: int,
        content: bytes,
    ) -> dict[str, object]:
        session = self._session(upload_id, user_identifier)
        if sequence != session.next_sequence:
            raise ValueError(
                f"invalid sequence: expected {session.next_sequence}, received {sequence}"
            )
        if not content or len(content) > self.chunk_bytes:
            raise ValueError(f"chunk must contain between 1 and {self.chunk_bytes} bytes")
        if session.received_bytes + len(content) > session.total_bytes:
            raise ValueError("chunk exceeds declared total_bytes")

        with session.path.open("ab") as handle:
            handle.write(content)
        session.received_bytes += len(content)
        session.next_sequence += 1
        return {
            "upload_id": upload_id,
            "sequence": sequence,
            "received_bytes": session.received_bytes,
            "complete": session.received_bytes == session.total_bytes,
        }

    def append_base64(
        self,
        upload_id: str,
        *,
        user_identifier: str,
        sequence: int,
        content_base64: str,
    ) -> dict[str, object]:
        try:
            content = base64.b64decode(content_base64, validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("content_base64 must be valid base64") from exc
        return self.append(
            upload_id,
            user_identifier=user_identifier,
            sequence=sequence,
            content=content,
        )

    def complete(self, upload_id: str, *, user_identifier: str) -> UploadedFile:
        session = self._session(upload_id, user_identifier)
        if session.received_bytes != session.total_bytes:
            raise ValueError(
                f"upload is incomplete: received {session.received_bytes} "
                f"of {session.total_bytes} bytes"
            )
        digest_builder = hashlib.sha256()
        with session.path.open("rb") as handle:
            while chunk := handle.read(1 << 20):
                digest_builder.update(chunk)
        digest = digest_builder.hexdigest()
        if digest != session.sha256:
            raise ValueError("uploaded file SHA-256 does not match the declared digest")
        return UploadedFile(
            upload_id=session.upload_id,
            user_identifier=session.user_identifier,
            filename=session.filename,
            path=session.path,
            total_bytes=session.total_bytes,
            sha256=session.sha256,
            attributes=dict(session.attributes),
        )

    def discard(self, upload_id: str, *, user_identifier: str) -> bool:
        session = self._session(upload_id, user_identifier)
        self._sessions.pop(upload_id, None)
        shutil.rmtree(session.path.parent, ignore_errors=True)
        return True

    def _session(self, upload_id: str, user_identifier: str) -> _UploadSession:
        session = self._sessions.get(upload_id)
        if session is None:
            raise ValueError("upload_id is unknown")
        if session.user_identifier != user_identifier.strip():
            raise ValueError("upload tenant does not match user_identifier")
        return session


def document_upload_store_from_env() -> DocumentUploadStore:
    return DocumentUploadStore(
        os.environ.get("AGENTMEMORY_UPLOAD_ROOT", "/tmp/agentmemory-uploads"),
        max_file_bytes=int(os.environ.get("AGENTMEMORY_UPLOAD_MAX_FILE_BYTES", str(128 << 20))),
        chunk_bytes=int(os.environ.get("AGENTMEMORY_UPLOAD_CHUNK_BYTES", str(512 << 10))),
    )
