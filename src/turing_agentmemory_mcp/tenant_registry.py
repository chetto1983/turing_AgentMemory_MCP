"""Durable pseudonymous lifecycle state for tenant ArcadeDB databases."""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

TENANT_REGISTRY_SCHEMA_VERSION = 1
TENANT_STATE_PROVISIONING = "provisioning"
TENANT_STATE_READY = "ready"

_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_REGISTRY_TABLES = {"registry_meta", "tenant_database"}
_META_COLUMNS = (
    "singleton",
    "schema_version",
    "naming_version",
    "key_fingerprint",
    "created_at",
)
_TENANT_COLUMNS = ("database_name", "digest", "state", "created_at", "updated_at")
_TENANT_STATES = {TENANT_STATE_PROVISIONING, TENANT_STATE_READY}


@dataclass(frozen=True, slots=True)
class TenantRegistryRecord:
    database_name: str
    digest: str
    state: str
    created_at: str
    updated_at: str


class TenantRegistry:
    def __init__(
        self,
        path: str | Path,
        *,
        naming_version: int,
        key_fingerprint: str,
        busy_timeout_ms: int = 5000,
    ) -> None:
        if not isinstance(naming_version, int) or isinstance(naming_version, bool):
            raise ValueError("naming_version must be a positive integer")
        if naming_version < 1:
            raise ValueError("naming_version must be a positive integer")
        if not isinstance(key_fingerprint, str) or not _FINGERPRINT_PATTERN.fullmatch(
            key_fingerprint
        ):
            raise ValueError("key_fingerprint must be a lowercase SHA-256 digest")
        if not isinstance(busy_timeout_ms, int) or isinstance(busy_timeout_ms, bool):
            raise ValueError("busy_timeout_ms must be a positive integer")
        if busy_timeout_ms < 1:
            raise ValueError("busy_timeout_ms must be a positive integer")
        self.path = Path(path)
        self.naming_version = naming_version
        self.key_fingerprint = key_fingerprint
        self.busy_timeout_ms = busy_timeout_ms

    def initialize(self) -> None:
        existed_before = self.path.exists()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._transaction(allow_create=True) as connection:
            tables = self._table_names(connection)
            if not tables:
                if existed_before:
                    raise RuntimeError("tenant registry schema is missing")
                self._create_schema(connection)
                self._insert_metadata(connection)
                return
            self._validate_schema_and_metadata(connection)
            self._validate_all_records(connection)

    def get(self, database_name: str) -> TenantRegistryRecord | None:
        self._database_digest(database_name)
        with self._connection() as connection:
            self._validate_schema_and_metadata(connection)
            row = connection.execute(
                "SELECT * FROM tenant_database WHERE database_name = ?",
                (database_name,),
            ).fetchone()
        return self._record(row) if row is not None else None

    def begin_provisioning(
        self,
        database_name: str,
        *,
        digest: str,
        created_at: str,
        updated_at: str,
    ) -> TenantRegistryRecord:
        self._require_matching_identity(database_name, digest)
        self._require_timestamp(created_at)
        self._require_timestamp(updated_at)
        with self._transaction() as connection:
            self._validate_schema_and_metadata(connection)
            row = connection.execute(
                "SELECT * FROM tenant_database WHERE database_name = ? OR digest = ?",
                (database_name, digest),
            ).fetchone()
            if row is not None:
                record = self._record(row)
                if record.database_name != database_name or record.digest != digest:
                    raise RuntimeError("tenant registry opaque tenant identity does not match")
                return record
            connection.execute(
                """
                INSERT INTO tenant_database(
                    database_name, digest, state, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?)
                """,
                (
                    database_name,
                    digest,
                    TENANT_STATE_PROVISIONING,
                    created_at,
                    updated_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM tenant_database WHERE database_name = ?",
                (database_name,),
            ).fetchone()
        return self._record(row)

    def mark_ready(self, database_name: str, *, updated_at: str) -> TenantRegistryRecord:
        self._database_digest(database_name)
        self._require_timestamp(updated_at)
        with self._transaction() as connection:
            self._validate_schema_and_metadata(connection)
            cursor = connection.execute(
                """
                UPDATE tenant_database
                SET state = ?, updated_at = ?
                WHERE database_name = ? AND state = ?
                """,
                (
                    TENANT_STATE_READY,
                    updated_at,
                    database_name,
                    TENANT_STATE_PROVISIONING,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("tenant registry has no matching provisioning tenant database")
            row = connection.execute(
                "SELECT * FROM tenant_database WHERE database_name = ?",
                (database_name,),
            ).fetchone()
        return self._record(row)

    def runtime_status(self) -> dict[str, object]:
        with self._connection() as connection:
            self._validate_schema_and_metadata(connection)
            self._validate_all_records(connection)
        return {
            "ready": True,
            "schema_version": TENANT_REGISTRY_SCHEMA_VERSION,
            "naming_version": self.naming_version,
            "key_fingerprint": self.key_fingerprint,
        }

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE registry_meta (
                singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                schema_version INTEGER NOT NULL,
                naming_version INTEGER NOT NULL,
                key_fingerprint TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            f"""
            CREATE TABLE tenant_database (
                database_name TEXT PRIMARY KEY,
                digest TEXT NOT NULL UNIQUE
                    CHECK(length(digest) = 64 AND digest NOT GLOB '*[^0-9a-f]*'),
                state TEXT NOT NULL
                    CHECK(state IN ('{TENANT_STATE_PROVISIONING}', '{TENANT_STATE_READY}')),
                created_at TEXT NOT NULL CHECK(length(created_at) > 0),
                updated_at TEXT NOT NULL CHECK(length(updated_at) > 0)
            )
            """
        )

    def _insert_metadata(self, connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            INSERT INTO registry_meta(
                singleton, schema_version, naming_version, key_fingerprint, created_at
            ) VALUES(1, ?, ?, ?, ?)
            """,
            (
                TENANT_REGISTRY_SCHEMA_VERSION,
                self.naming_version,
                self.key_fingerprint,
                datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            ),
        )

    def _validate_schema_and_metadata(self, connection: sqlite3.Connection) -> None:
        if self._table_names(connection) != _REGISTRY_TABLES:
            raise RuntimeError("tenant registry schema is missing or incompatible")
        if self._column_names(connection, "registry_meta") != _META_COLUMNS:
            raise RuntimeError("tenant registry schema is missing or incompatible")
        if self._column_names(connection, "tenant_database") != _TENANT_COLUMNS:
            raise RuntimeError("tenant registry schema is missing or incompatible")
        rows = connection.execute("SELECT * FROM registry_meta").fetchall()
        if len(rows) != 1:
            raise RuntimeError("tenant registry metadata is missing or invalid")
        row = rows[0]
        try:
            singleton = int(row["singleton"])
            schema_version = int(row["schema_version"])
            naming_version = int(row["naming_version"])
            key_fingerprint = str(row["key_fingerprint"])
            self._require_timestamp(str(row["created_at"]), error_type=RuntimeError)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("tenant registry metadata is missing or invalid") from exc
        if (
            singleton != 1
            or schema_version != TENANT_REGISTRY_SCHEMA_VERSION
            or naming_version != self.naming_version
            or key_fingerprint != self.key_fingerprint
        ):
            raise RuntimeError("tenant registry metadata does not match configured identity")

    def _validate_all_records(self, connection: sqlite3.Connection) -> None:
        for row in connection.execute("SELECT * FROM tenant_database"):
            self._record(row)

    def _record(self, row: sqlite3.Row | None) -> TenantRegistryRecord:
        if row is None:
            raise RuntimeError("tenant registry row is missing")
        try:
            record = TenantRegistryRecord(
                database_name=str(row["database_name"]),
                digest=str(row["digest"]),
                state=str(row["state"]),
                created_at=str(row["created_at"]),
                updated_at=str(row["updated_at"]),
            )
            self._require_matching_identity(record.database_name, record.digest)
            self._require_timestamp(record.created_at, error_type=RuntimeError)
            self._require_timestamp(record.updated_at, error_type=RuntimeError)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("tenant registry tenant row is invalid") from exc
        if record.state not in _TENANT_STATES:
            raise RuntimeError("tenant registry tenant row is invalid")
        return record

    def _require_matching_identity(self, database_name: str, digest: str) -> None:
        if not isinstance(digest, str) or not _DIGEST_PATTERN.fullmatch(digest):
            raise ValueError("digest must be a lowercase SHA-256 digest")
        if self._database_digest(database_name) != digest:
            raise RuntimeError("tenant registry opaque tenant identity does not match")

    def _database_digest(self, database_name: str) -> str:
        prefix = f"agentmem_t_v{self.naming_version}_"
        if not isinstance(database_name, str) or not database_name.startswith(prefix):
            raise ValueError("database_name must be an opaque tenant database name")
        digest = database_name.removeprefix(prefix)
        if not _DIGEST_PATTERN.fullmatch(digest):
            raise ValueError("database_name must be an opaque tenant database name")
        return digest

    @staticmethod
    def _require_timestamp(
        value: str,
        *,
        error_type: type[Exception] = ValueError,
    ) -> None:
        if not isinstance(value, str) or not value:
            raise error_type("tenant registry timestamp must be timezone-aware ISO-8601")
        normalized = f"{value[:-1]}+00:00" if value.endswith("Z") else value
        try:
            instant = datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise error_type("tenant registry timestamp must be timezone-aware ISO-8601") from exc
        if instant.tzinfo is None:
            raise error_type("tenant registry timestamp must be timezone-aware ISO-8601")

    @staticmethod
    def _table_names(connection: sqlite3.Connection) -> set[str]:
        rows = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            """
        ).fetchall()
        return {str(row["name"]) for row in rows}

    @staticmethod
    def _column_names(connection: sqlite3.Connection, table: str) -> tuple[str, ...]:
        return tuple(str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})"))

    @contextmanager
    def _transaction(
        self,
        *,
        allow_create: bool = False,
    ) -> Iterator[sqlite3.Connection]:
        with self._connection(allow_create=allow_create) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            connection.commit()

    @contextmanager
    def _connection(
        self,
        *,
        allow_create: bool = False,
    ) -> Iterator[sqlite3.Connection]:
        if not allow_create and not self.path.exists():
            raise RuntimeError("tenant registry schema is missing")
        connection: sqlite3.Connection | None = None
        try:
            connection = sqlite3.connect(
                self.path,
                timeout=self.busy_timeout_ms / 1000,
            )
            connection.row_factory = sqlite3.Row
            connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
            mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()
            if mode is None or str(mode[0]).lower() != "wal":
                raise RuntimeError("tenant registry could not enable WAL journaling")
            connection.execute("PRAGMA synchronous = FULL")
            yield connection
        except sqlite3.DatabaseError as exc:
            raise RuntimeError("tenant registry is unreadable") from exc
        finally:
            if connection is not None:
                connection.close()
