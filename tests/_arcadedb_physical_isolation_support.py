"""Shared live ArcadeDB isolation harness for Phase 5."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.arcadedb_client import ArcadeDBClient
from turing_agentmemory_mcp.embeddings import HashingEmbedder
from turing_agentmemory_mcp.entity_extraction import NoopEntityProcessor
from turing_agentmemory_mcp.governance import NoopAuditSink, NoopRedactor
from turing_agentmemory_mcp.observability import InMemorySpanRecorder
from turing_agentmemory_mcp.rerank import Scored
from turing_agentmemory_mcp.store import TuringAgentMemory
from turing_agentmemory_mcp.tenant_identity import (
    derive_tenant_database_identity,
    tenant_key_fingerprint,
)
from turing_agentmemory_mcp.tenant_provisioning import TenantProvisioner
from turing_agentmemory_mcp.tenant_registry import TenantRegistry
from turing_agentmemory_mcp.tenant_router import TenantRouter

_PINNED_IMAGE = "arcadedata/arcadedb:26.7.1"
_NAMING_KEY = b"0123456789abcdef0123456789abcdef"
_TENANTS = ("Tenant-A", "Tenant-B", "Tenant-C")
_IDENTITY_VARIANTS = (*_TENANTS, "tenant-a", "T\u0435nant-A")
_CANARIES = {"Tenant-A": "amberalpha", "Tenant-B": "bronzeecho", "Tenant-C": "cobaltomega"}
_TENANT_RECORD_TYPES = frozenset({"Memory", "Document", "Chunk", "Entity", "Fact", "Community"})
_REQUIRED_OPERATIONS = frozenset(
    {
        "memory_store",
        "memory_search",
        "memory_list",
        "memory_get",
        "memory_update",
        "memory_delete",
        "document_ingest",
        "document_search",
        "document_reindex",
        "document_delete",
    }
)


class _IdentityReranker:
    model = "phase-05-identity-reranker"

    def rerank(self, query: str, documents: list[str]) -> list[Scored]:
        del query
        return [Scored(index=index, score=1.0 - index / 1000) for index in range(len(documents))]


@dataclass(frozen=True)
class _LiveEnvironment:
    root: Path
    base_client: ArcadeDBClient
    registry_path: Path
    router: TenantRouter


@dataclass(frozen=True)
class _WorkloadResult:
    memory_id: str
    memory_content: str
    document_id: str
    operations: frozenset[str]


@dataclass(frozen=True)
class _PhysicalIsolationProof:
    expected_databases: frozenset[str]
    listed_databases: frozenset[str] = frozenset()
    operations_by_tenant: dict[str, frozenset[str]] = field(default_factory=dict)
    record_tenants_by_database: dict[str, frozenset[str]] = field(default_factory=dict)
    bound_tenants_by_database: dict[str, frozenset[str]] = field(default_factory=dict)
    tenant_types_checked: dict[str, frozenset[str]] = field(default_factory=dict)
    manifest_databases: frozenset[str] = frozenset()
    foreign_attempts_denied: bool = False
    registry_bytes: bytes = b""
    diagnostic_text: str = ""
    invalid_identity_preserved_state: bool = False


def _client(database: str = "fixture-control-not-tenant-data") -> ArcadeDBClient:
    return ArcadeDBClient(
        base_url=os.environ.get("ARCADEDB_URL", "http://127.0.0.1:2480"),
        database=database,
        username=os.environ.get("ARCADEDB_USER", "root"),
        password=os.environ.get("ARCADEDB_PASSWORD", "agentmemory-arcadedb-dev"),
        retry_base_s=0.05,
    )


def _compose(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["docker", "compose", *args], capture_output=True, timeout=120)


def _dependency_reason(base_client: ArcadeDBClient) -> str | None:
    if shutil.which("docker") is None:
        return "docker is not available on PATH"
    try:
        version = _compose("version")
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"docker compose is unavailable: {type(exc).__name__}"
    if version.returncode != 0:
        return "docker compose is unavailable"
    if not base_client.is_ready():
        return f"ArcadeDB is not reachable at {base_client.base_url}"
    return None


def _skip_dependency(reason: str) -> None:
    pytest.skip(f"live ArcadeDB dependency unavailable: {reason}")


def _expected_database_names() -> frozenset[str]:
    return frozenset(
        derive_tenant_database_identity(identity, naming_key=_NAMING_KEY).database_name
        for identity in _IDENTITY_VARIANTS
    )


def _drop_fixture_databases(client: ArcadeDBClient, database_names: frozenset[str]) -> None:
    for database_name in sorted(database_names & client.list_databases()):
        client._server_command(f"drop database {database_name}")


def _registry_bytes(path: Path) -> bytes:
    parts = []
    for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
        if candidate.exists():
            parts.append(candidate.read_bytes())
    return b"".join(parts)


@contextmanager
def live_environment_context(
    tmp_path_factory: pytest.TempPathFactory,
) -> Any:
    base_client = _client()
    reason = _dependency_reason(base_client)
    if reason is not None:
        _skip_dependency(reason)

    ps_result = _compose("ps", "--format", "json", "arcadedb")
    assert ps_result.returncode == 0, ps_result.stderr.decode(errors="replace")
    service = json.loads(ps_result.stdout.decode())
    assert service["Image"] == _PINNED_IMAGE
    assert service["State"] == "running"

    database_names = _expected_database_names()
    _drop_fixture_databases(base_client, database_names)
    root = tmp_path_factory.mktemp("arcadedb-physical-isolation")
    registry_path = root / "tenant-registry.sqlite3"
    registry = TenantRegistry(
        registry_path,
        naming_version=1,
        key_fingerprint=tenant_key_fingerprint(_NAMING_KEY),
    )
    registry.initialize()
    assembly_store = TuringAgentMemory(
        base_client,
        turing_home=root,
        dimensions=32,
        embedder=HashingEmbedder(dimensions=32),
        reranker=_IdentityReranker(),  # type: ignore[arg-type]
        entity_processor=NoopEntityProcessor(),
        redactor=NoopRedactor(),
        audit_sink=NoopAuditSink(),
        observer=InMemorySpanRecorder(),
    )
    shared_dependencies = assembly_store.shared_dependencies()
    provisioner = TenantProvisioner(
        base_client,
        registry,
        naming_key=_NAMING_KEY,
        dimensions=32,
        max_attempts=3,
        retry_base_s=0.05,
        retry_ceiling_s=0.2,
    )
    environment = _LiveEnvironment(
        root=root,
        base_client=base_client,
        registry_path=registry_path,
        router=TenantRouter(
            provisioner,
            shared_dependencies,
            store_factory=TuringAgentMemory,
            capacity=16,
            idle_ttl_s=300,
        ),
    )
    try:
        yield environment
    finally:
        _drop_fixture_databases(base_client, database_names)


def _run_tenant_workload(router: TenantRouter, tenant: str) -> _WorkloadResult:
    memory = router.resolve(tenant).memory
    canary = _CANARIES[tenant]
    operations: set[str] = set()

    memory.store_message(
        user_identifier=tenant,
        session_id="shared-session",
        role="user",
        content="identical collision-prone memory payload",
    )
    active = memory.store_message(
        user_identifier=tenant,
        session_id="shared-session",
        role="user",
        content=f"live isolation canary {canary}",
    )
    deletion_target = memory.store_message(
        user_identifier=tenant,
        session_id="shared-session",
        role="user",
        content=f"delete-only memory {canary}",
    )
    operations.add("memory_store")
    assert any(
        item.id == active.id for item in memory.search_memory(user_identifier=tenant, query=canary)
    )
    operations.add("memory_search")
    assert active.id in {item.id for item in memory.list_memories(user_identifier=tenant, limit=20)}
    operations.add("memory_list")
    assert memory.get_memory(user_identifier=tenant, memory_id=active.id) is not None
    operations.add("memory_get")
    updated = memory.update_memory(
        user_identifier=tenant,
        memory_id=active.id,
        content=f"updated live isolation canary {canary}",
    )
    operations.add("memory_update")
    assert memory.delete_memory(user_identifier=tenant, memory_id=deletion_target.id)["deleted"]
    operations.add("memory_delete")

    memory.ingest_document_text(
        user_identifier=tenant,
        title="Shared collision document",
        text="identical collision-prone document payload",
        document_id="shared-collision-document",
    )
    document_id = f"document-{canary}"
    memory.ingest_document_text(
        user_identifier=tenant,
        title="Live isolation document",
        text=f"document canary {canary} with scoped citation text",
        document_id=document_id,
    )
    deletion_document_id = f"delete-document-{canary}"
    memory.ingest_document_text(
        user_identifier=tenant,
        title="Delete-only document",
        text=f"delete-only document canary {canary}",
        document_id=deletion_document_id,
    )
    operations.add("document_ingest")
    hits = memory.search_documents(
        user_identifier=tenant,
        query=canary,
        document_id=document_id,
    )
    assert hits and all(hit.document_id == document_id for hit in hits)
    operations.add("document_search")
    memory.reindex_document_text(
        user_identifier=tenant,
        document_id=document_id,
        title="Reindexed live isolation document",
        text=f"reindexed document canary {canary} with scoped citation text",
    )
    operations.add("document_reindex")
    assert memory.delete_document(user_identifier=tenant, document_id=deletion_document_id)[
        "deleted"
    ]
    operations.add("document_delete")
    return _WorkloadResult(
        memory_id=updated.id,
        memory_content=updated.content,
        document_id=document_id,
        operations=frozenset(operations),
    )


def _track_bound_tenants(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, set[str]]:
    captured: dict[str, set[str]] = {}
    lock = threading.Lock()
    original_query = ArcadeDBClient.query
    original_command = ArcadeDBClient.command

    def record(client: ArcadeDBClient, params: dict[str, object] | None) -> None:
        values = {
            str(value)
            for key, value in (params or {}).items()
            if key in {"user_identifier", "identifier"}
        }
        if values:
            with lock:
                captured.setdefault(client.database, set()).update(values)

    def query(client: ArcadeDBClient, statement: str, **kwargs: Any) -> list[dict[str, object]]:
        record(client, kwargs.get("params"))
        return original_query(client, statement, **kwargs)

    def command(client: ArcadeDBClient, statement: str, **kwargs: Any) -> list[dict[str, object]]:
        record(client, kwargs.get("params"))
        return original_command(client, statement, **kwargs)

    monkeypatch.setattr(ArcadeDBClient, "query", query)
    monkeypatch.setattr(ArcadeDBClient, "command", command)
    return captured


def _inspect_physical_databases(
    environment: _LiveEnvironment,
) -> tuple[
    dict[str, frozenset[str]],
    dict[str, frozenset[str]],
    frozenset[str],
    list[str],
]:
    record_tenants: dict[str, frozenset[str]] = {}
    types_checked: dict[str, frozenset[str]] = {}
    manifest_databases: set[str] = set()
    safe_manifest_text: list[str] = []
    for tenant in _IDENTITY_VARIANTS:
        identity = derive_tenant_database_identity(tenant, naming_key=_NAMING_KEY)
        client = replace(environment.base_client, database=identity.database_name)
        manifests = client.query("SELECT FROM TenantManifest")
        assert len(manifests) == 1
        assert manifests[0]["database_name"] == identity.database_name
        assert "user_identifier" not in manifests[0]
        manifest_databases.add(str(manifests[0]["database_name"]))
        safe_manifest_text.append(json.dumps(manifests, sort_keys=True, default=str))
        if tenant not in _TENANTS:
            continue

        seen_tenants: set[str] = set()
        checked: set[str] = set()
        for type_name in sorted(_TENANT_RECORD_TYPES):
            rows = client.query(f"SELECT FROM {type_name}")
            checked.add(type_name)
            seen_tenants.update(
                str(row["user_identifier"])
                for row in rows
                if row.get("user_identifier") is not None
            )
            serialized = json.dumps(rows, ensure_ascii=False, default=str)
            for other_tenant, other_canary in _CANARIES.items():
                if other_tenant != tenant:
                    assert other_canary not in serialized
        users = client.query("SELECT identifier FROM User")
        assert {str(row["identifier"]) for row in users} == {tenant}
        record_tenants[identity.database_name] = frozenset(seen_tenants)
        types_checked[identity.database_name] = frozenset(checked)
    return record_tenants, types_checked, frozenset(manifest_databases), safe_manifest_text


def _run_physical_isolation_contract(
    environment: _LiveEnvironment,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> _PhysicalIsolationProof:
    bound_tenants = _track_bound_tenants(monkeypatch)
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = dict(
            zip(
                _TENANTS,
                pool.map(lambda tenant: _run_tenant_workload(environment.router, tenant), _TENANTS),
                strict=True,
            )
        )
    for tenant in _IDENTITY_VARIANTS[3:]:
        environment.router.resolve(tenant)

    foreign_errors: list[str] = []
    tenant_a = environment.router.resolve(_TENANTS[0]).memory
    tenant_b = environment.router.resolve(_TENANTS[1]).memory
    tenant_b_result = results[_TENANTS[1]]
    assert (
        tenant_a.get_memory(user_identifier=_TENANTS[0], memory_id=tenant_b_result.memory_id)
        is None
    )
    with pytest.raises(ValueError) as update_error:
        tenant_a.update_memory(
            user_identifier=_TENANTS[0],
            memory_id=tenant_b_result.memory_id,
            content="foreign mutation must fail",
        )
    foreign_errors.append(str(update_error.value))
    assert (
        tenant_a.delete_memory(user_identifier=_TENANTS[0], memory_id=tenant_b_result.memory_id)[
            "deleted"
        ]
        is False
    )
    assert (
        tenant_a.get_document(user_identifier=_TENANTS[0], document_id=tenant_b_result.document_id)
        is None
    )
    assert (
        tenant_a.search_documents(
            user_identifier=_TENANTS[0],
            query=_CANARIES[_TENANTS[1]],
            document_id=tenant_b_result.document_id,
        )
        == []
    )
    assert (
        tenant_a.delete_document(
            user_identifier=_TENANTS[0], document_id=tenant_b_result.document_id
        )["deleted"]
        is False
    )
    unchanged = tenant_b.get_memory(
        user_identifier=_TENANTS[1], memory_id=tenant_b_result.memory_id
    )
    assert unchanged is not None and unchanged.content == tenant_b_result.memory_content
    assert (
        tenant_b.get_document(user_identifier=_TENANTS[1], document_id=tenant_b_result.document_id)
        is not None
    )

    record_tenants, types_checked, manifest_databases, safe_manifest_text = (
        _inspect_physical_databases(environment)
    )
    listed_before_invalid = environment.base_client.list_databases()
    registry_before_invalid = _registry_bytes(environment.registry_path)
    invalid_errors: list[str] = []
    for invalid in ("", " ", "surrounding ", "control\x00", "\ud800"):
        with pytest.raises(ValueError) as invalid_error:
            environment.router.resolve(invalid)
        invalid_errors.append(str(invalid_error.value))
    invalid_preserved = (
        environment.base_client.list_databases() == listed_before_invalid
        and _registry_bytes(environment.registry_path) == registry_before_invalid
    )

    status_values = [environment.router.runtime_status()]
    status_values.extend(environment.router.tenant_status(tenant) for tenant in _IDENTITY_VARIANTS)
    view_reprs = [repr(environment.router.resolve(tenant)) for tenant in _IDENTITY_VARIANTS]
    diagnostic_text = "\n".join(
        [
            caplog.text,
            *foreign_errors,
            *invalid_errors,
            *view_reprs,
            json.dumps(status_values, sort_keys=True, default=str),
            *safe_manifest_text,
        ]
    )
    return _PhysicalIsolationProof(
        expected_databases=_expected_database_names(),
        listed_databases=environment.base_client.list_databases(),
        operations_by_tenant={tenant: result.operations for tenant, result in results.items()},
        record_tenants_by_database=record_tenants,
        bound_tenants_by_database={
            database_name: frozenset(values) for database_name, values in bound_tenants.items()
        },
        tenant_types_checked=types_checked,
        manifest_databases=manifest_databases,
        foreign_attempts_denied=True,
        registry_bytes=_registry_bytes(environment.registry_path),
        diagnostic_text=diagnostic_text,
        invalid_identity_preserved_state=invalid_preserved,
    )
