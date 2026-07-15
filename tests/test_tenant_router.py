"""Immutable tenant views, per-key single flight, and bounded cache contracts."""

from __future__ import annotations

import threading
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import FrozenInstanceError, dataclass, field
from types import SimpleNamespace

import pytest

import turing_agentmemory_mcp.tenant_router as tenant_router_module
from turing_agentmemory_mcp.tenant_binding import TenantBinding, TenantBindingError
from turing_agentmemory_mcp.tenant_identity import (
    TenantDatabaseIdentity,
    derive_tenant_database_identity,
    validate_user_identifier,
)
from turing_agentmemory_mcp.tenant_provisioning import (
    ProvisionedTenantDatabase,
    TenantManifest,
)
from turing_agentmemory_mcp.tenant_router import (
    StaticStoreResolver,
    StoreResolver,
    TenantRouter,
    TenantStoreView,
)

_NAMING_KEY = bytes(range(32))
_INVALID_IDENTIFIERS = ("", "   ", " alice", "alice ", "ali\x00ce", "\ud800")


@dataclass
class _FakeClient:
    database: str
    lifecycle_calls: list[str]
    queries: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)

    def close(self) -> None:
        self.lifecycle_calls.append("close")

    def drop_database(self) -> None:
        self.lifecycle_calls.append("drop")


class _FakeMemory:
    def __init__(
        self,
        client: _FakeClient,
        shared_dependencies: object,
        *,
        tenant_binding: TenantBinding | None = None,
    ) -> None:
        self.client = client
        self.shared_dependencies = shared_dependencies
        self.tenant_binding = tenant_binding

    def ping(self) -> str:
        return self.client.database

    def _require_user(self, user_identifier: str) -> None:
        # Mirrors production _StoreCore._require_user (Task 2): delegates to the
        # binding so this assertion exercises the real guard, not a test double.
        if self.tenant_binding is None:
            validate_user_identifier(user_identifier)
            return
        self.tenant_binding.verify(user_identifier)


class _RecordingStoreFactory:
    def __init__(self) -> None:
        self.calls: list[tuple[_FakeClient, object, TenantBinding | None]] = []

    def __call__(
        self,
        client: _FakeClient,
        *,
        shared_dependencies: object,
        tenant_binding: TenantBinding | None = None,
    ) -> _FakeMemory:
        self.calls.append((client, shared_dependencies, tenant_binding))
        return _FakeMemory(client, shared_dependencies, tenant_binding=tenant_binding)


class _FakeRegistry:
    def __init__(self) -> None:
        self.records: dict[str, SimpleNamespace] = {}
        self.damaged: set[str] = set()

    def get(self, database_name: str) -> SimpleNamespace | None:
        if database_name in self.damaged:
            raise RuntimeError(f"tenant database {database_name} is damaged")
        return self.records.get(database_name)

    def runtime_status(self) -> dict[str, object]:
        return {
            "ready": True,
            "schema_version": 1,
            "naming_version": 1,
            "key_fingerprint": "f" * 64,
        }


class _BaseClient:
    def __init__(self) -> None:
        self.ready = True

    def is_ready(self) -> bool:
        return self.ready


class _RecordingProvisioner:
    def __init__(self) -> None:
        self.naming_key = _NAMING_KEY
        self.registry = _FakeRegistry()
        self.base_client = _BaseClient()
        self.calls: list[str] = []
        self.attempts: Counter[str] = Counter()
        self.clients: list[_FakeClient] = []
        self.overlap_barrier: threading.Barrier | None = None
        self.started = threading.Event()
        self.release = threading.Event()
        self.block = False
        self.failure: BaseException | None = None

    def identity(self, user_identifier: str) -> TenantDatabaseIdentity:
        return derive_tenant_database_identity(user_identifier, naming_key=self.naming_key)

    def provision(self, user_identifier: str) -> ProvisionedTenantDatabase:
        identity = self.identity(user_identifier)
        self.calls.append(user_identifier)
        self.attempts[identity.database_name] += 1
        if self.overlap_barrier is not None:
            self.overlap_barrier.wait(timeout=2)
        self.started.set()
        if self.block:
            assert self.release.wait(timeout=2)
        if self.failure is not None:
            raise self.failure
        lifecycle_calls: list[str] = []
        client = _FakeClient(identity.database_name, lifecycle_calls)
        self.clients.append(client)
        manifest = TenantManifest(
            singleton_id="tenant-manifest-v1",
            database_name=identity.database_name,
            digest=identity.digest,
            naming_version=identity.naming_version,
            key_fingerprint=identity.key_fingerprint,
            schema_version=1,
            created_at="2026-07-15T00:00:00Z",
        )
        self.registry.records[identity.database_name] = SimpleNamespace(state="ready")
        return ProvisionedTenantDatabase(identity=identity, client=client, manifest=manifest)  # type: ignore[arg-type]


class _ManualClock:
    def __init__(self) -> None:
        self.value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class _ObservedFuture(Future[TenantStoreView]):
    def __init__(self) -> None:
        super().__init__()
        self.waiter_entered = threading.Event()

    def result(self, timeout: float | None = None) -> TenantStoreView:
        self.waiter_entered.set()
        return super().result(timeout)


def _router(
    provisioner: _RecordingProvisioner | None = None,
    *,
    capacity: int = 128,
    idle_ttl_s: float = 900.0,
    clock: _ManualClock | None = None,
) -> tuple[TenantRouter, _RecordingProvisioner, _RecordingStoreFactory, object]:
    selected_provisioner = provisioner or _RecordingProvisioner()
    factory = _RecordingStoreFactory()
    shared_dependencies = object()
    router = TenantRouter(
        selected_provisioner,
        shared_dependencies,
        store_factory=factory,  # type: ignore[arg-type]
        capacity=capacity,
        idle_ttl_s=idle_ttl_s,
        clock=clock or _ManualClock(),
    )
    return router, selected_provisioner, factory, shared_dependencies


def _resolve_error(router: TenantRouter, user_identifier: str) -> BaseException:
    try:
        router.resolve(user_identifier)
    except BaseException as exc:  # noqa: BLE001 - exact cross-thread outcome is asserted
        return exc
    raise AssertionError("resolve unexpectedly succeeded")


def test_same_tenant_callers_share_one_attempt_and_one_immutable_view() -> None:
    router, provisioner, factory, shared = _router()

    with ThreadPoolExecutor(max_workers=8) as pool:
        views = list(pool.map(router.resolve, ["tenant-alpha"] * 8))

    assert len({id(view) for view in views}) == 1
    assert provisioner.attempts[provisioner.identity("tenant-alpha").database_name] == 1
    assert len(factory.calls) == 1
    assert factory.calls[0][1] is shared
    with pytest.raises(FrozenInstanceError):
        views[0].memory = object()  # type: ignore[misc]
    assert not hasattr(views[0], "user_identifier")
    assert "tenant-alpha" not in repr(views[0])


def test_different_tenants_provision_concurrently() -> None:
    provisioner = _RecordingProvisioner()
    provisioner.overlap_barrier = threading.Barrier(2)
    router, _, _, _ = _router(provisioner)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(router.resolve, "tenant-alpha")
        second = pool.submit(router.resolve, "tenant-beta")
        views = (first.result(timeout=3), second.result(timeout=3))

    assert views[0].identity != views[1].identity
    assert len(provisioner.calls) == 2


def test_leader_exception_fans_out_and_clears_exact_inflight_for_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provisioner = _RecordingProvisioner()
    provisioner.block = True
    failure = RuntimeError("opaque provisioning failure")
    provisioner.failure = failure
    created_futures: list[_ObservedFuture] = []

    def future_factory() -> _ObservedFuture:
        future = _ObservedFuture()
        created_futures.append(future)
        return future

    monkeypatch.setattr(tenant_router_module, "Future", future_factory)
    router, _, _, _ = _router(provisioner)

    with ThreadPoolExecutor(max_workers=2) as pool:
        leader = pool.submit(_resolve_error, router, "tenant-alpha")
        assert provisioner.started.wait(timeout=2)
        waiter = pool.submit(_resolve_error, router, "tenant-alpha")
        assert created_futures[0].waiter_entered.wait(timeout=2)
        provisioner.release.set()
        errors = (leader.result(timeout=2), waiter.result(timeout=2))

    assert errors[0] is failure
    assert errors[1] is failure
    provisioner.failure = None
    provisioner.block = False
    retried = router.resolve("tenant-alpha")
    assert retried.memory.ping() == provisioner.identity("tenant-alpha").database_name  # type: ignore[union-attr]
    assert provisioner.attempts[provisioner.identity("tenant-alpha").database_name] == 2


def test_capacity_lru_eviction_only_removes_cache_reference() -> None:
    clock = _ManualClock()
    router, provisioner, _, _ = _router(capacity=2, clock=clock)
    alpha = router.resolve("tenant-alpha")
    clock.advance(1)
    beta = router.resolve("tenant-beta")
    clock.advance(1)
    assert router.resolve("tenant-alpha") is alpha
    clock.advance(1)
    router.resolve("tenant-gamma")

    assert router.tenant_status("tenant-beta")["cached"] is False
    assert beta.memory.ping() == provisioner.identity("tenant-beta").database_name  # type: ignore[union-attr]
    recreated = router.resolve("tenant-beta")
    assert recreated is not beta
    assert provisioner.attempts[provisioner.identity("tenant-beta").database_name] == 2
    assert all(client.lifecycle_calls == [] for client in provisioner.clients)


def test_idle_ttl_uses_injected_monotonic_clock_and_recreates_expired_view() -> None:
    clock = _ManualClock()
    router, provisioner, _, _ = _router(capacity=4, idle_ttl_s=10.0, clock=clock)
    original = router.resolve("tenant-alpha")
    clock.advance(9)
    assert router.resolve("tenant-alpha") is original
    clock.advance(10)
    replacement = router.resolve("tenant-alpha")

    assert replacement is not original
    assert original.memory.ping() == provisioner.identity("tenant-alpha").database_name  # type: ignore[union-attr]
    assert all(client.lifecycle_calls == [] for client in provisioner.clients)


@pytest.mark.parametrize(
    ("capacity", "idle_ttl_s"),
    [(0, 1.0), (-1, 1.0), (True, 1.0), (1, 0.0), (1, -1.0), (1, float("inf"))],
)
def test_router_rejects_unbounded_or_non_positive_cache_configuration(
    capacity: int, idle_ttl_s: float
) -> None:
    with pytest.raises(ValueError):
        _router(capacity=capacity, idle_ttl_s=idle_ttl_s)


def test_diagnostics_are_pseudonymous_non_provisioning_and_tenant_local() -> None:
    router, provisioner, _, _ = _router()
    status = router.tenant_status("tenant-alpha")
    database_name = provisioner.identity("tenant-alpha").database_name

    assert provisioner.calls == []
    assert status["database_name"] == database_name
    assert status["cached"] is False
    assert "tenant-alpha" not in repr(status)
    assert router.runtime_status()["ready"] is True

    provisioner.registry.damaged.add(database_name)
    with pytest.raises(RuntimeError, match=database_name):
        router.tenant_status("tenant-alpha")
    assert router.runtime_status()["ready"] is True
    assert provisioner.calls == []


def test_static_resolver_returns_injected_view_without_store_activity() -> None:
    provisioner = _RecordingProvisioner()
    provisioned = provisioner.provision("tenant-alpha")
    memory = _FakeMemory(provisioned.client, object())  # type: ignore[arg-type]
    view = TenantStoreView(provisioned.identity, provisioned.manifest, memory)  # type: ignore[arg-type]
    resolver = StaticStoreResolver(view)

    assert isinstance(resolver, StoreResolver)
    assert resolver.resolve("opaque-\u03a9") is view


@pytest.mark.parametrize("invalid_identifier", _INVALID_IDENTIFIERS)
def test_resolvers_reject_invalid_identity_before_provision_build_or_store_activity(
    invalid_identifier: str,
) -> None:
    router, provisioner, factory, _ = _router()
    memory = SimpleNamespace(activity=[])
    static = StaticStoreResolver(memory)  # type: ignore[arg-type]

    with pytest.raises(ValueError):
        router.resolve(invalid_identifier)
    with pytest.raises(ValueError):
        static.resolve(invalid_identifier)

    assert provisioner.calls == []
    assert factory.calls == []
    assert memory.activity == []


def test_valid_opaque_unicode_passes_unchanged_through_router_and_static_resolver() -> None:
    exact_identifier = "Tenant-\u212b-\u03c2"
    router, provisioner, _, _ = _router()
    view = router.resolve(exact_identifier)
    static = StaticStoreResolver(view)

    assert provisioner.calls == [exact_identifier]
    assert static.resolve(exact_identifier) is view
    assert view.identity == provisioner.identity(exact_identifier)


def test_resolve_binds_logical_tenant_into_store() -> None:
    router, provisioner, factory, _ = _router()

    view = router.resolve("Tenant-A")

    expected_identity = provisioner.identity("Tenant-A")
    binding = view.memory.tenant_binding  # type: ignore[union-attr]
    assert binding is not None
    assert binding.identity.database_name == expected_identity.database_name
    assert binding.naming_key == provisioner.naming_key
    assert factory.calls[0][2] is binding


def test_foreign_identifier_rejected_before_client_call() -> None:
    router, _, _, _ = _router()
    tenant_a_view = router.resolve("Tenant-A")

    with pytest.raises(TenantBindingError):
        tenant_a_view.memory._require_user("Tenant-B")  # type: ignore[union-attr]

    client = tenant_a_view.memory.client  # type: ignore[union-attr]
    assert client.queries == []
    assert client.commands == []


def test_unbound_store_factory_fails_closed() -> None:
    def dropping_factory(
        client: _FakeClient,
        *,
        shared_dependencies: object,
        tenant_binding: TenantBinding | None = None,
    ) -> _FakeMemory:
        return _FakeMemory(client, shared_dependencies, tenant_binding=None)

    provisioner = _RecordingProvisioner()
    router = TenantRouter(
        provisioner,
        object(),
        store_factory=dropping_factory,  # type: ignore[arg-type]
    )
    database_name = provisioner.identity("Tenant-A").database_name

    with pytest.raises(RuntimeError, match=database_name):
        router.resolve("Tenant-A")
