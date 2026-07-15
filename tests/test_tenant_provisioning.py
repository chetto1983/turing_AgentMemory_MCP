"""Ready-last tenant database provisioning and recovery contract."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError, dataclass, replace
from pathlib import Path
from urllib.error import URLError

import pytest

from turing_agentmemory_mcp.arcadedb_schema import SchemaBootstrapConfig
from turing_agentmemory_mcp.tenant_identity import derive_tenant_database_identity
from turing_agentmemory_mcp.tenant_provisioning import (
    TENANT_MANIFEST_SINGLETON_ID,
    ProvisionedTenantDatabase,
    TenantManifest,
    TenantProvisioner,
    TenantProvisioningError,
)
from turing_agentmemory_mcp.tenant_registry import (
    TENANT_STATE_PROVISIONING,
    TENANT_STATE_READY,
    TenantRegistry,
)

_KEY = b"ready-last-tenant-provisioning-test-key"
_TENANT = "tenant-exact-Å"
_CREATED = "2026-07-15T12:00:00Z"
_UPDATED = "2026-07-15T12:01:00Z"
_SCHEMA_PHASES = ("types", "properties", "indexes")


class _DeterministicFault(TenantProvisioningError):
    pass


class _TransientFault(RuntimeError):
    pass


def _transient_fault() -> _TransientFault:
    error = _TransientFault("opaque transient server failure")
    error.__cause__ = URLError("temporary network failure")
    return error


@dataclass
class _FakeServer:
    databases: set[str]
    manifests: dict[str, TenantManifest]
    calls: list[str]
    fail_after: str | None = None
    transient_failures: int = 0
    returned: int = 0
    hidden_list_results: int = 0
    list_barrier: threading.Barrier | None = None

    def boundary(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_after == name:
            self.fail_after = None
            raise _DeterministicFault(f"fault after {name}")


@dataclass(frozen=True)
class _FakeClient:
    state: _FakeServer
    database: str = "control-plane"

    def list_databases(self) -> frozenset[str]:
        if self.state.transient_failures:
            self.state.transient_failures -= 1
            self.state.calls.append("list")
            raise _transient_fault()
        hidden = self.state.hidden_list_results > 0
        if hidden:
            self.state.hidden_list_results -= 1
            result = frozenset()
        else:
            result = frozenset(self.state.databases)
        self.state.boundary("list")
        if hidden and self.state.list_barrier is not None:
            self.state.list_barrier.wait(timeout=5)
        return result

    def create_database(self) -> None:
        duplicate = self.database in self.state.databases
        self.state.databases.add(self.database)
        self.state.boundary("create")
        if duplicate:
            raise RuntimeError("database already exists")

    def query(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        assert "TenantManifest" in statement
        manifest = self.state.manifests.get(self.database)
        self.state.boundary("manifest-read")
        if manifest is None:
            return []
        return [{field: getattr(manifest, field) for field in manifest.__dataclass_fields__}]

    def command(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        assert "TenantManifest" in statement
        assert params is not None
        if self.database in self.state.manifests:
            raise RuntimeError("record already exists")
        self.state.manifests[self.database] = TenantManifest(**params)
        self.state.boundary("manifest-write")
        return []


class _RecordingRegistry:
    def __init__(self, registry: TenantRegistry, state: _FakeServer):
        self.registry = registry
        self.state = state

    def get(self, database_name: str):
        return self.registry.get(database_name)

    def begin_provisioning(self, *args: object, **kwargs: object):
        record = self.registry.begin_provisioning(*args, **kwargs)
        self.state.boundary("registry-begin")
        return record

    def mark_ready(self, *args: object, **kwargs: object):
        record = self.registry.mark_ready(*args, **kwargs)
        self.state.boundary("registry-ready")
        return record


def _identity(user_identifier: str = _TENANT):
    return derive_tenant_database_identity(user_identifier, naming_key=_KEY)


def _manifest(*, created_at: str = _CREATED, **changes: object) -> TenantManifest:
    identity = _identity()
    values: dict[str, object] = {
        "singleton_id": TENANT_MANIFEST_SINGLETON_ID,
        "database_name": identity.database_name,
        "digest": identity.digest,
        "naming_version": identity.naming_version,
        "key_fingerprint": identity.key_fingerprint,
        "schema_version": 1,
        "created_at": created_at,
    }
    values.update(changes)
    return TenantManifest(**values)


def _registry(tmp_path: Path) -> TenantRegistry:
    identity = _identity()
    registry = TenantRegistry(
        tmp_path / "tenant-registry.sqlite3",
        naming_version=identity.naming_version,
        key_fingerprint=identity.key_fingerprint,
    )
    registry.initialize()
    return registry


def _clock(*values: str):
    remaining = list(values)
    return lambda: remaining.pop(0) if remaining else values[-1]


def _build(
    tmp_path: Path,
    *,
    state: _FakeServer | None = None,
    registry: TenantRegistry | None = None,
    clock=None,
    sleeps: list[float] | None = None,
    max_attempts: int = 3,
) -> tuple[TenantProvisioner, _FakeServer, TenantRegistry]:
    server = state or _FakeServer(set(), {}, [])
    durable_registry = registry or _registry(tmp_path)

    def bootstrap_schema(
        client: _FakeClient, *, dimensions: int, version: int = 1
    ) -> SchemaBootstrapConfig:
        for phase in _SCHEMA_PHASES:
            server.boundary(f"bootstrap-{phase}")
        return SchemaBootstrapConfig(dimensions=dimensions, version=version)

    provisioner = TenantProvisioner(
        _FakeClient(server),
        _RecordingRegistry(durable_registry, server),
        naming_key=_KEY,
        dimensions=8,
        max_attempts=max_attempts,
        retry_base_s=0.5,
        retry_ceiling_s=1.0,
        clock=clock or _clock(_CREATED, _UPDATED),
        sleep=(sleeps if sleeps is not None else []).append,
        jitter=lambda: 0.5,
        bootstrap_schema=bootstrap_schema,
    )
    return provisioner, server, durable_registry


def _register(
    registry: TenantRegistry,
    *,
    state: str = TENANT_STATE_PROVISIONING,
    created_at: str = _CREATED,
) -> None:
    identity = _identity()
    registry.begin_provisioning(
        identity.database_name,
        digest=identity.digest,
        created_at=created_at,
        updated_at=created_at,
    )
    if state == TENANT_STATE_READY:
        registry.mark_ready(identity.database_name, updated_at=_UPDATED)


def test_contract_objects_are_frozen_and_pseudonymous() -> None:
    manifest = _manifest()
    result = ProvisionedTenantDatabase(
        _identity(), _FakeClient(_FakeServer(set(), {}, [])), manifest
    )

    with pytest.raises(FrozenInstanceError):
        manifest.created_at = "changed"  # type: ignore[misc]
    assert not hasattr(manifest, "user_identifier")
    assert _TENANT not in repr(manifest)
    assert _TENANT not in repr(result)


def test_ready_manifest_is_written_last(tmp_path: Path) -> None:
    provisioner, state, registry = _build(tmp_path)

    result = provisioner.provision(_TENANT)

    assert state.calls == [
        "registry-begin",
        "list",
        "create",
        "bootstrap-types",
        "bootstrap-properties",
        "bootstrap-indexes",
        "manifest-write",
        "manifest-read",
        "registry-ready",
    ]
    assert result.client.database == _identity().database_name
    assert registry.get(_identity().database_name).state == TENANT_STATE_READY


def test_provisioning_with_matching_manifest_verifies_then_promotes(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _register(registry)
    identity = _identity()
    state = _FakeServer({identity.database_name}, {identity.database_name: _manifest()}, [])
    provisioner, _, _ = _build(tmp_path, state=state, registry=registry)

    result = provisioner.provision(_TENANT)

    assert result.manifest == _manifest()
    assert state.calls == ["registry-begin", "list", "manifest-read", "registry-ready"]


def test_provisioning_without_manifest_reboots_schema_ready_last(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _register(registry)
    identity = _identity()
    state = _FakeServer({identity.database_name}, {}, [])
    provisioner, _, _ = _build(tmp_path, state=state, registry=registry)

    provisioner.provision(_TENANT)

    assert state.calls == [
        "registry-begin",
        "list",
        "manifest-read",
        "bootstrap-types",
        "bootstrap-properties",
        "bootstrap-indexes",
        "manifest-write",
        "manifest-read",
        "registry-ready",
    ]


def test_ready_missing_database_fails_closed_without_create_or_drop(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _register(registry, state=TENANT_STATE_READY)
    provisioner, state, _ = _build(tmp_path, registry=registry)

    with pytest.raises(TenantProvisioningError, match=_identity().database_name):
        provisioner.provision(_TENANT)

    assert state.calls == ["registry-begin", "list"]
    assert "create" not in state.calls
    assert not any("drop" in call for call in state.calls)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("singleton_id", "other"),
        ("database_name", "agentmem_t_v1_" + "0" * 64),
        ("digest", "0" * 64),
        ("naming_version", 2),
        ("key_fingerprint", "0" * 64),
        ("schema_version", 2),
        ("created_at", "2026-07-15T00:00:00Z"),
    ],
)
def test_ready_manifest_mismatch_fails_once_without_mutation(
    tmp_path: Path, field: str, value: object
) -> None:
    registry = _registry(tmp_path)
    _register(registry, state=TENANT_STATE_READY)
    identity = _identity()
    bad = replace(_manifest(), **{field: value})
    state = _FakeServer({identity.database_name}, {identity.database_name: bad}, [])
    provisioner, _, _ = _build(tmp_path, state=state, registry=registry)

    with pytest.raises(TenantProvisioningError):
        provisioner.provision(_TENANT)

    assert state.calls == ["registry-begin", "list", "manifest-read"]
    assert "create" not in state.calls
    assert "manifest-write" not in state.calls


def test_duplicate_create_is_only_a_reconciliation_candidate(tmp_path: Path) -> None:
    identity = _identity()
    state = _FakeServer({identity.database_name}, {}, [], hidden_list_results=1)
    provisioner, _, registry = _build(tmp_path, state=state)

    result = provisioner.provision(_TENANT)

    assert result.manifest == _manifest()
    assert state.calls[:4] == ["registry-begin", "list", "create", "list"]
    assert "bootstrap-indexes" in state.calls
    assert max(
        i for i, call in enumerate(state.calls) if call == "manifest-read"
    ) > state.calls.index("manifest-write")
    assert registry.get(identity.database_name).state == TENANT_STATE_READY


def test_contenders_use_winning_registry_created_at(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    identity = _identity()
    state = _FakeServer(
        {identity.database_name},
        {},
        [],
        hidden_list_results=2,
        list_barrier=threading.Barrier(2),
    )
    first, _, _ = _build(
        tmp_path,
        state=state,
        registry=registry,
        clock=_clock(_CREATED, _UPDATED),
    )
    second, _, _ = _build(
        tmp_path,
        state=state,
        registry=registry,
        clock=_clock("2030-01-01T00:00:00Z", "2030-01-01T00:01:00Z"),
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(first.provision, _TENANT)
        second_future = pool.submit(second.provision, _TENANT)
        first_result = first_future.result(timeout=10)
        second_result = second_future.result(timeout=10)

    winner_created_at = registry.get(identity.database_name).created_at
    assert winner_created_at in {_CREATED, "2030-01-01T00:00:00Z"}
    assert first_result.manifest.created_at == winner_created_at
    assert second_result.manifest.created_at == winner_created_at
    assert state.calls.count("create") == 2


@pytest.mark.parametrize(
    "boundary",
    [
        "registry-begin",
        "list",
        "create",
        "bootstrap-types",
        "bootstrap-properties",
        "bootstrap-indexes",
        "manifest-write",
        "manifest-read",
        "registry-ready",
    ],
)
def test_fault_after_each_boundary_never_serves_and_later_resumes(
    tmp_path: Path, boundary: str
) -> None:
    state = _FakeServer(set(), {}, [], fail_after=boundary)
    provisioner, _, registry = _build(tmp_path, state=state)

    with pytest.raises(_DeterministicFault):
        provisioner.provision(_TENANT)
    assert state.returned == 0
    assert not any("drop" in call for call in state.calls)

    result = provisioner.provision(_TENANT)

    record = registry.get(_identity().database_name)
    assert result.manifest == _manifest(created_at=record.created_at)
    assert record.state == TENANT_STATE_READY


def test_transient_failures_retry_with_bounded_backoff_and_jitter(tmp_path: Path) -> None:
    state = _FakeServer(set(), {}, [], transient_failures=2)
    sleeps: list[float] = []
    provisioner, _, _ = _build(tmp_path, state=state, sleeps=sleeps, max_attempts=3)

    provisioner.provision(_TENANT)

    assert sleeps == [0.75, 1.0]
    assert state.calls.count("list") == 3


def test_transient_retry_exhaustion_is_finite(tmp_path: Path) -> None:
    state = _FakeServer(set(), {}, [], transient_failures=4)
    sleeps: list[float] = []
    provisioner, _, _ = _build(tmp_path, state=state, sleeps=sleeps, max_attempts=3)

    with pytest.raises(TenantProvisioningError):
        provisioner.provision(_TENANT)

    assert state.calls == [
        "registry-begin",
        "list",
        "registry-begin",
        "list",
        "registry-begin",
        "list",
    ]
    assert sleeps == [0.75, 1.0]


def test_deterministic_failure_is_not_retried_or_leaked(tmp_path: Path) -> None:
    raw = "secret-tenant-user@example.test"
    state = _FakeServer(set(), {}, [], fail_after="list")
    identity = derive_tenant_database_identity(raw, naming_key=_KEY)
    registry = TenantRegistry(
        tmp_path / "registry.sqlite3",
        naming_version=identity.naming_version,
        key_fingerprint=identity.key_fingerprint,
    )
    registry.initialize()
    provisioner, _, _ = _build(tmp_path, state=state, registry=registry)

    with pytest.raises(_DeterministicFault) as caught:
        provisioner.provision(raw)

    assert state.calls == ["registry-begin", "list"]
    assert raw not in str(caught.value)
    assert raw not in repr(provisioner)
