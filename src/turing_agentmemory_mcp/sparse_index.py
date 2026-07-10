"""Recoverable tenant-scoped SQLite FTS5 projection for memory retrieval."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

SPARSE_SCHEMA_VERSION = 1
MAX_SPARSE_RESULTS = 200
BUSY_TIMEOUT_MS = 5000
_TOKEN_RE = re.compile(r"[^\W_]+(?:[-./:@_][^\W_]+)*", re.UNICODE)
_PHRASE_RE = re.compile(r'"([^"\r\n]+)"')


class SparseIndexUnavailable(RuntimeError):
    pass


class SparseSchemaMismatch(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SparseDocument:
    doc_key: str
    user_identifier: str
    source_id: str
    kind: str
    content: str
    source: str = ""
    session_id: str = ""
    created_at: str = ""
    expires_at: str = ""
    projection_version: int = SPARSE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in ("doc_key", "user_identifier", "source_id", "kind", "content"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"sparse document {name} must be non-empty")
        if isinstance(self.projection_version, bool) or not isinstance(
            self.projection_version, int
        ):
            raise ValueError("projection version must be an integer")
        if self.created_at:
            object.__setattr__(self, "created_at", _normalize_timestamp(self.created_at))
        if self.expires_at:
            object.__setattr__(self, "expires_at", _normalize_timestamp(self.expires_at))


@dataclass(frozen=True, slots=True)
class SparseHit:
    doc_key: str
    user_identifier: str
    source_id: str
    kind: str
    content: str
    source: str
    session_id: str
    created_at: str
    expires_at: str
    projection_version: int
    rank: float
    score: float


@dataclass(frozen=True, slots=True)
class SparseMutation:
    operation: str
    doc_key: str
    document: SparseDocument | None = None

    def __post_init__(self) -> None:
        if self.operation not in {"upsert", "delete"}:
            raise ValueError("sparse mutation operation must be upsert or delete")
        if not isinstance(self.doc_key, str) or not self.doc_key.strip():
            raise ValueError("sparse mutation doc_key must be non-empty")
        if self.operation == "upsert":
            if self.document is None or self.document.doc_key != self.doc_key:
                raise ValueError("upsert mutation must contain the matching document")
        elif self.document is not None:
            raise ValueError("delete mutation cannot contain a document")

    @classmethod
    def upsert(cls, document: SparseDocument) -> SparseMutation:
        return cls("upsert", document.doc_key, document)

    @classmethod
    def delete(cls, doc_key: str) -> SparseMutation:
        return cls("delete", doc_key)


class SparseIndex:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as connection:
                self._configure(connection)
                connection.execute("BEGIN IMMEDIATE")
                self._create_tables(connection)
                version = self._schema_version(connection)
                if version is not None and version != SPARSE_SCHEMA_VERSION:
                    connection.rollback()
                    raise SparseSchemaMismatch(
                        f"sparse schema {version} does not match {SPARSE_SCHEMA_VERSION}"
                    )
                connection.execute(
                    "INSERT OR REPLACE INTO sparse_meta(key, value) VALUES('schema_version', ?)",
                    (str(SPARSE_SCHEMA_VERSION),),
                )
                connection.commit()
        except SparseSchemaMismatch:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise SparseIndexUnavailable(f"sparse index unavailable at {self.path}") from exc

    def upsert_many(self, documents: Sequence[SparseDocument]) -> None:
        if not documents:
            return
        self._mutate([SparseMutation.upsert(document) for document in documents])

    def delete_many(self, doc_keys: Sequence[str]) -> None:
        if not doc_keys:
            return
        self._mutate([SparseMutation.delete(doc_key) for doc_key in doc_keys])

    def prepare(
        self,
        mutations: Sequence[SparseMutation],
        *,
        batch_id: str | None = None,
    ) -> str:
        if not mutations:
            raise ValueError("sparse outbox batch must not be empty")
        batch_id = batch_id or f"sparse_{uuid.uuid4().hex}"
        if not isinstance(batch_id, str) or not batch_id.strip():
            raise ValueError("sparse outbox batch_id must be non-empty")
        now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        try:
            with self._ready_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                for sequence, mutation in enumerate(mutations):
                    payload = (
                        json.dumps(
                            asdict(mutation.document),
                            ensure_ascii=True,
                            allow_nan=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        )
                        if mutation.document is not None
                        else ""
                    )
                    connection.execute(
                        "INSERT OR IGNORE INTO sparse_outbox("
                        "batch_id, sequence, state, operation, doc_key, payload_json, created_at"
                        ") VALUES(?, ?, 'prepared', ?, ?, ?, ?)",
                        (
                            batch_id,
                            sequence,
                            mutation.operation,
                            mutation.doc_key,
                            payload,
                            now,
                        ),
                    )
                connection.commit()
            return batch_id
        except (OSError, sqlite3.Error) as exc:
            raise SparseIndexUnavailable(f"cannot prepare sparse outbox at {self.path}") from exc

    def commit_batch(self, batch_id: str) -> None:
        if not isinstance(batch_id, str) or not batch_id.strip():
            raise ValueError("sparse outbox batch_id must be non-empty")
        try:
            with self._ready_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT COUNT(*) FROM sparse_outbox WHERE batch_id = ?",
                    (batch_id,),
                ).fetchone()[0]
                if not existing:
                    connection.rollback()
                    raise ValueError(f"sparse outbox batch not found: {batch_id}")
                connection.execute(
                    "UPDATE sparse_outbox SET state = 'committed' "
                    "WHERE batch_id = ? AND state = 'prepared'",
                    (batch_id,),
                )
                connection.commit()
        except ValueError:
            raise
        except (OSError, sqlite3.Error) as exc:
            raise SparseIndexUnavailable(f"cannot commit sparse outbox at {self.path}") from exc

    def discard_prepared(self, batch_id: str) -> int:
        try:
            with self._ready_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                cursor = connection.execute(
                    "DELETE FROM sparse_outbox WHERE batch_id = ? AND state = 'prepared'",
                    (batch_id,),
                )
                connection.commit()
                return max(0, cursor.rowcount)
        except (OSError, sqlite3.Error) as exc:
            raise SparseIndexUnavailable(f"cannot discard sparse outbox at {self.path}") from exc

    def replay(self, *, batch_id: str | None = None) -> int:
        try:
            with self._ready_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                sql = (
                    "SELECT id, operation, doc_key, payload_json FROM sparse_outbox "
                    "WHERE state = 'committed'"
                )
                parameters: tuple[object, ...] = ()
                if batch_id is not None:
                    sql += " AND batch_id = ?"
                    parameters = (batch_id,)
                sql += " ORDER BY id"
                rows = connection.execute(sql, parameters).fetchall()
                for row in rows:
                    mutation = _mutation_from_outbox(row[1], row[2], row[3])
                    self._apply_mutation(connection, mutation)
                    connection.execute("DELETE FROM sparse_outbox WHERE id = ?", (row[0],))
                connection.commit()
                return len(rows)
        except (ValueError, json.JSONDecodeError) as exc:
            raise SparseIndexUnavailable(f"sparse outbox is corrupt at {self.path}") from exc
        except (OSError, sqlite3.Error) as exc:
            raise SparseIndexUnavailable(f"cannot replay sparse outbox at {self.path}") from exc

    def search(
        self,
        *,
        user_identifier: str,
        query: str,
        limit: int,
        kinds: Sequence[str] | None = None,
        now: str | None = None,
    ) -> list[SparseHit]:
        if not isinstance(user_identifier, str) or not user_identifier.strip():
            raise ValueError("user_identifier must be non-empty")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("sparse query must be non-empty")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_SPARSE_RESULTS:
            raise ValueError(f"sparse limit must be between 1 and {MAX_SPARSE_RESULTS}")
        clean_kinds = tuple(dict.fromkeys(kinds or ()))
        if any(not isinstance(kind, str) or not kind.strip() for kind in clean_kinds):
            raise ValueError("sparse kinds must be non-empty strings")
        compiled = compile_fts_query(query)
        if not compiled:
            return []
        now_value = _normalize_timestamp(now) if now else datetime.now(UTC).isoformat().replace("+00:00", "Z")
        sql = (
            "SELECT doc_key, user_identifier, source_id, kind, content, source, session_id, "
            "created_at, expires_at, projection_version, "
            "bm25(sparse_fts, 0.0, 1.0, 5.0) AS bm25_rank "
            "FROM sparse_fts WHERE sparse_fts MATCH ? AND user_identifier = ? "
            "AND (expires_at = '' OR expires_at > ?)"
        )
        parameters: list[object] = [compiled, user_identifier, now_value]
        if clean_kinds:
            sql += " AND kind IN (" + ",".join("?" for _ in clean_kinds) + ")"
            parameters.extend(clean_kinds)
        sql += " ORDER BY bm25_rank ASC, source_id ASC, doc_key ASC LIMIT ?"
        parameters.append(limit)
        try:
            with self._ready_connection() as connection:
                rows = connection.execute(sql, parameters).fetchall()
        except (OSError, sqlite3.Error) as exc:
            raise SparseIndexUnavailable(f"cannot search sparse index at {self.path}") from exc
        return [
            SparseHit(
                doc_key=str(row[0]),
                user_identifier=str(row[1]),
                source_id=str(row[2]),
                kind=str(row[3]),
                content=str(row[4]),
                source=str(row[5]),
                session_id=str(row[6]),
                created_at=str(row[7]),
                expires_at=str(row[8]),
                projection_version=int(row[9]),
                rank=float(row[10]),
                score=max(0.0, -float(row[10])),
            )
            for row in rows
        ]

    def status(self) -> dict[str, object]:
        try:
            with self._ready_connection() as connection:
                counts = dict(
                    connection.execute(
                        "SELECT state, COUNT(*) FROM sparse_outbox GROUP BY state"
                    ).fetchall()
                )
                oldest = connection.execute(
                    "SELECT MIN(created_at) FROM sparse_outbox"
                ).fetchone()[0]
                document_count = connection.execute(
                    "SELECT COUNT(*) FROM sparse_fts"
                ).fetchone()[0]
        except (OSError, sqlite3.Error) as exc:
            raise SparseIndexUnavailable(f"cannot inspect sparse index at {self.path}") from exc
        prepared = int(counts.get("prepared", 0))
        committed = int(counts.get("committed", 0))
        return {
            "status": "ready",
            "path": str(self.path),
            "schema_version": SPARSE_SCHEMA_VERSION,
            "document_count": int(document_count),
            "pending_count": prepared + committed,
            "prepared_count": prepared,
            "committed_count": committed,
            "oldest_pending_at": str(oldest or ""),
            "repair_required": prepared > 0,
        }

    def rebuild(self, documents: Sequence[SparseDocument]) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._connection() as connection:
                self._configure(connection)
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("DROP TABLE IF EXISTS sparse_fts")
                connection.execute("DROP TABLE IF EXISTS sparse_outbox")
                connection.execute("DROP TABLE IF EXISTS sparse_meta")
                self._create_tables(connection)
                connection.execute(
                    "INSERT INTO sparse_meta(key, value) VALUES('schema_version', ?)",
                    (str(SPARSE_SCHEMA_VERSION),),
                )
                for document in documents:
                    self._apply_mutation(connection, SparseMutation.upsert(document))
                connection.commit()
        except (OSError, sqlite3.Error) as exc:
            raise SparseIndexUnavailable(f"cannot rebuild sparse index at {self.path}") from exc

    def _mutate(self, mutations: Sequence[SparseMutation]) -> None:
        try:
            with self._ready_connection() as connection:
                connection.execute("BEGIN IMMEDIATE")
                for mutation in mutations:
                    self._apply_mutation(connection, mutation)
                connection.commit()
        except (OSError, sqlite3.Error) as exc:
            raise SparseIndexUnavailable(f"cannot mutate sparse index at {self.path}") from exc

    @staticmethod
    def _apply_mutation(connection: sqlite3.Connection, mutation: SparseMutation) -> None:
        connection.execute("DELETE FROM sparse_fts WHERE doc_key = ?", (mutation.doc_key,))
        if mutation.operation == "delete":
            return
        document = mutation.document
        if document is None:
            raise ValueError("upsert mutation is missing its document")
        connection.execute(
            "INSERT INTO sparse_fts("
            "doc_key, content, source_id, user_identifier, kind, source, session_id, "
            "created_at, expires_at, projection_version"
            ") VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                document.doc_key,
                document.content,
                document.source_id,
                document.user_identifier,
                document.kind,
                document.source,
                document.session_id,
                document.created_at,
                document.expires_at,
                document.projection_version,
            ),
        )

    @contextmanager
    def _ready_connection(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            self._configure(connection)
            version = self._schema_version(connection)
            if version != SPARSE_SCHEMA_VERSION:
                raise SparseSchemaMismatch(
                    f"sparse schema {version} does not match {SPARSE_SCHEMA_VERSION}"
                )
            yield connection

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=BUSY_TIMEOUT_MS / 1000)
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _configure(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")

    @staticmethod
    def _create_tables(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS sparse_meta("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS sparse_fts USING fts5("
            "doc_key UNINDEXED, content, source_id, user_identifier UNINDEXED, kind UNINDEXED, "
            "source UNINDEXED, session_id UNINDEXED, created_at UNINDEXED, expires_at UNINDEXED, "
            "projection_version UNINDEXED, tokenize='unicode61 remove_diacritics 2')"
        )
        connection.execute(
            "CREATE TABLE IF NOT EXISTS sparse_outbox("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, batch_id TEXT NOT NULL, sequence INTEGER NOT NULL, "
            "state TEXT NOT NULL CHECK(state IN ('prepared', 'committed')), "
            "operation TEXT NOT NULL CHECK(operation IN ('upsert', 'delete')), "
            "doc_key TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL, "
            "UNIQUE(batch_id, sequence))"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS sparse_outbox_state_id "
            "ON sparse_outbox(state, id)"
        )

    @staticmethod
    def _schema_version(connection: sqlite3.Connection) -> int | None:
        try:
            row = connection.execute(
                "SELECT value FROM sparse_meta WHERE key = 'schema_version'"
            ).fetchone()
        except sqlite3.OperationalError:
            return None
        if row is None:
            return None
        try:
            return int(row[0])
        except (TypeError, ValueError) as exc:
            raise SparseSchemaMismatch("sparse schema version is invalid") from exc


def compile_fts_query(query: str) -> str:
    if not isinstance(query, str):
        raise ValueError("sparse query must be a string")
    values: list[str] = []
    occupied: list[tuple[int, int]] = []
    for match in _PHRASE_RE.finditer(query):
        phrase = " ".join(match.group(1).split())
        if phrase:
            values.append(phrase)
            occupied.append(match.span())
    remainder = list(query)
    for start, end in occupied:
        remainder[start:end] = " " * (end - start)
    values.extend(match.group(0) for match in _TOKEN_RE.finditer("".join(remainder)))
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(value)
    return " OR ".join(
        f'(content : "{_fts_quote(value)}" OR source_id : "{_fts_quote(value)}")'
        for value in unique
    )


def _fts_quote(value: str) -> str:
    return value.replace('"', '""')


def _mutation_from_outbox(operation: str, doc_key: str, payload: str) -> SparseMutation:
    if operation == "delete":
        return SparseMutation.delete(doc_key)
    if operation != "upsert":
        raise ValueError("unknown sparse outbox operation")
    decoded = json.loads(payload)
    if not isinstance(decoded, dict):
        raise ValueError("sparse outbox payload must be an object")
    document = SparseDocument(**decoded)
    return SparseMutation.upsert(document)


def _normalize_timestamp(value: str | None) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
