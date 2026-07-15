from __future__ import annotations

import inspect
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, asdict, fields
from pathlib import Path

import pytest

from turing_agentmemory_mcp.tenant_identity import derive_tenant_database_identity
from turing_agentmemory_mcp.tenant_registry import (
    TENANT_REGISTRY_SCHEMA_VERSION,
    TENANT_STATE_PROVISIONING,
    TENANT_STATE_READY,
    TenantRegistry,
    TenantRegistryRecord,
)

NAMING_VERSION = 1
KEY_FINGERPRINT = "f" * 64
OTHER_KEY_FINGERPRINT = "e" * 64
CREATED_AT = "2026-07-15T10:00:00Z"
UPDATED_AT = "2026-07-15T10:01:00Z"
READY_AT = "2026-07-15T10:02:00Z"


def _database_identity(seed: int) -> tuple[str, str]:
    digest = f"{seed:064x}"
    return f"agentmem_t_v1_{digest}", digest


def _registry(path: Path, **overrides: object) -> TenantRegistry:
    arguments: dict[str, object] = {
        "naming_version": NAMING_VERSION,
        "key_fingerprint": KEY_FINGERPRINT,
        "busy_timeout_ms": 5000,
    }
    arguments.update(overrides)
    return TenantRegistry(path, **arguments)  # type: ignore[arg-type]


def _begin(registry: TenantRegistry, seed: int = 1) -> TenantRegistryRecord:
    database_name, digest = _database_identity(seed)
    return registry.begin_provisioning(
        database_name,
        digest=digest,
        created_at=CREATED_AT,
        updated_at=UPDATED_AT,
    )


def _scan_registry_bytes(path: Path) -> bytes:
    return b"".join(
        candidate.read_bytes()
        for candidate in path.parent.glob(f"{path.name}*")
        if candidate.is_file()
    )


def test_registry_record_is_frozen_and_contains_only_opaque_fields() -> None:
    assert [field.name for field in fields(TenantRegistryRecord)] == [
        "database_name",
        "digest",
        "state",
        "created_at",
        "updated_at",
    ]
    database_name, digest = _database_identity(1)
    record = TenantRegistryRecord(
        database_name=database_name,
        digest=digest,
        state=TENANT_STATE_PROVISIONING,
        created_at=CREATED_AT,
        updated_at=UPDATED_AT,
    )

    with pytest.raises(FrozenInstanceError):
        record.state = TENANT_STATE_READY  # type: ignore[misc]


def test_initialize_reopen_preserves_versioned_registry_records(tmp_path: Path) -> None:
    path = tmp_path / "tenant-registry.sqlite3"
    registry = _registry(path)
    registry.initialize()
    record = _begin(registry)

    reopened = _registry(path)
    reopened.initialize()

    assert reopened.get(record.database_name) == record
    assert reopened.get(_database_identity(999)[0]) is None
    assert reopened.runtime_status() == {
        "ready": True,
        "schema_version": TENANT_REGISTRY_SCHEMA_VERSION,
        "naming_version": NAMING_VERSION,
        "key_fingerprint": KEY_FINGERPRINT,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"naming_version": 2},
        {"key_fingerprint": OTHER_KEY_FINGERPRINT},
    ],
    ids=["naming-version", "key-fingerprint"],
)
def test_reopen_rejects_immutable_metadata_drift_before_writes(
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    path = tmp_path / "tenant-registry.sqlite3"
    original = _registry(path)
    original.initialize()

    with pytest.raises(RuntimeError, match="tenant registry metadata"):
        _registry(path, **overrides).initialize()

    assert original.get(_database_identity(1)[0]) is None


def test_begin_provisioning_is_idempotent_and_never_demotes_ready(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "tenant-registry.sqlite3")
    registry.initialize()
    first = _begin(registry)

    duplicate = registry.begin_provisioning(
        first.database_name,
        digest=first.digest,
        created_at="2099-01-01T00:00:00Z",
        updated_at="2099-01-01T00:00:01Z",
    )
    ready = registry.mark_ready(first.database_name, updated_at=READY_AT)
    replayed = registry.begin_provisioning(
        first.database_name,
        digest=first.digest,
        created_at="2099-01-01T00:00:00Z",
        updated_at="2099-01-01T00:00:01Z",
    )

    assert first.state == TENANT_STATE_PROVISIONING
    assert duplicate == first
    assert ready.state == TENANT_STATE_READY
    assert replayed == ready


def test_begin_provisioning_rejects_database_name_digest_mismatches(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "tenant-registry.sqlite3")
    registry.initialize()
    first = _begin(registry)
    other_name, other_digest = _database_identity(2)

    with pytest.raises(RuntimeError, match="opaque tenant identity"):
        registry.begin_provisioning(
            first.database_name,
            digest=other_digest,
            created_at=CREATED_AT,
            updated_at=UPDATED_AT,
        )
    with pytest.raises(RuntimeError, match="opaque tenant identity"):
        registry.begin_provisioning(
            other_name,
            digest=first.digest,
            created_at=CREATED_AT,
            updated_at=UPDATED_AT,
        )

    assert registry.get(first.database_name) == first
    assert registry.get(other_name) is None


def test_mark_ready_is_an_atomic_provisioning_only_transition(tmp_path: Path) -> None:
    registry = _registry(tmp_path / "tenant-registry.sqlite3")
    registry.initialize()
    database_name, _digest = _database_identity(1)

    with pytest.raises(RuntimeError, match="provisioning tenant database"):
        registry.mark_ready(database_name, updated_at=READY_AT)

    provisioning = _begin(registry)
    ready = registry.mark_ready(provisioning.database_name, updated_at=READY_AT)

    assert ready == TenantRegistryRecord(
        database_name=provisioning.database_name,
        digest=provisioning.digest,
        state=TENANT_STATE_READY,
        created_at=CREATED_AT,
        updated_at=READY_AT,
    )
    with pytest.raises(RuntimeError, match="provisioning tenant database"):
        registry.mark_ready(provisioning.database_name, updated_at=READY_AT)


def test_concurrent_writers_preserve_complete_ready_rows(tmp_path: Path) -> None:
    path = tmp_path / "tenant-registry.sqlite3"
    registry = _registry(path, busy_timeout_ms=10_000)
    registry.initialize()

    def provision(seed: int) -> TenantRegistryRecord:
        worker_registry = _registry(path, busy_timeout_ms=10_000)
        record = _begin(worker_registry, seed)
        assert worker_registry.get(record.database_name) == record
        return worker_registry.mark_ready(record.database_name, updated_at=READY_AT)

    with ThreadPoolExecutor(max_workers=8) as pool:
        records = list(pool.map(provision, range(1, 25)))

    assert len({record.database_name for record in records}) == 24
    assert all(record.state == TENANT_STATE_READY for record in records)
    assert all(registry.get(record.database_name) == record for record in records)


def test_registry_never_persists_raw_user_identifier(tmp_path: Path) -> None:
    path = tmp_path / "tenant-registry.sqlite3"
    raw_identifier = "private-tenant-identity@example.test"
    identity = derive_tenant_database_identity(raw_identifier, naming_key=bytes(range(32)))
    registry = TenantRegistry(
        path,
        naming_version=identity.naming_version,
        key_fingerprint=identity.key_fingerprint,
    )
    registry.initialize()
    record = registry.begin_provisioning(
        identity.database_name,
        digest=identity.digest,
        created_at=CREATED_AT,
        updated_at=UPDATED_AT,
    )

    serialized = json.dumps(asdict(record), sort_keys=True).encode()
    assert raw_identifier.encode() not in serialized
    assert raw_identifier.encode() not in _scan_registry_bytes(path)
    assert raw_identifier not in repr(record)


def test_registry_public_api_cannot_accept_raw_user_identifier() -> None:
    for method_name in ["__init__", "get", "begin_provisioning", "mark_ready"]:
        parameters = inspect.signature(getattr(TenantRegistry, method_name)).parameters
        assert "user_identifier" not in parameters


def test_existing_empty_sqlite_file_fails_closed_without_schema_creation(tmp_path: Path) -> None:
    path = tmp_path / "tenant-registry.sqlite3"
    sqlite3.connect(path).close()

    with pytest.raises(RuntimeError, match="tenant registry schema"):
        _registry(path).initialize()

    with sqlite3.connect(path) as connection:
        tables = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        ).fetchall()
    assert tables == []


@pytest.mark.parametrize("damage", ["tenant-table", "metadata-row"])
def test_missing_schema_or_metadata_fails_closed_without_repair(
    tmp_path: Path,
    damage: str,
) -> None:
    path = tmp_path / "tenant-registry.sqlite3"
    registry = _registry(path)
    registry.initialize()
    with sqlite3.connect(path) as connection:
        if damage == "tenant-table":
            connection.execute("DROP TABLE tenant_database")
        else:
            connection.execute("DELETE FROM registry_meta")

    with pytest.raises(RuntimeError, match="tenant registry (schema|metadata)"):
        _registry(path).initialize()

    with sqlite3.connect(path) as connection:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        meta_count = (
            connection.execute("SELECT COUNT(*) FROM registry_meta").fetchone()[0]
            if "registry_meta" in tables
            else 0
        )
    if damage == "tenant-table":
        assert "tenant_database" not in tables
    else:
        assert meta_count == 0


@pytest.mark.parametrize("damage", ["metadata", "state", "identity"])
def test_corrupt_metadata_or_tenant_rows_fail_closed(tmp_path: Path, damage: str) -> None:
    path = tmp_path / "tenant-registry.sqlite3"
    registry = _registry(path)
    registry.initialize()
    record = _begin(registry)
    with sqlite3.connect(path) as connection:
        if damage == "metadata":
            connection.execute("UPDATE registry_meta SET schema_version = 999")
        elif damage == "state":
            connection.execute("PRAGMA ignore_check_constraints = ON")
            connection.execute(
                "UPDATE tenant_database SET state = 'unknown' WHERE database_name = ?",
                (record.database_name,),
            )
        else:
            connection.execute(
                "UPDATE tenant_database SET digest = ? WHERE database_name = ?",
                ("a" * 64, record.database_name),
            )

    with pytest.raises(RuntimeError, match="tenant registry"):
        _registry(path).initialize()


def test_non_sqlite_registry_bytes_fail_closed_without_replacement(tmp_path: Path) -> None:
    path = tmp_path / "tenant-registry.sqlite3"
    corrupt_bytes = b"not-a-sqlite-database\x00private-evidence"
    path.write_bytes(corrupt_bytes)

    with pytest.raises(RuntimeError, match="tenant registry"):
        _registry(path).initialize()

    assert path.read_bytes() == corrupt_bytes
