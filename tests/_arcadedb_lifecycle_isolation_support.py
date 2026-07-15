"""Live tenant lifecycle and document-worker proof for Phase 5."""

from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from threading import Barrier, Lock
from typing import Any

from _arcadedb_physical_isolation_support import (
    _LIFECYCLE_TENANTS,
    _NAMING_KEY,
    _compose,
    _drop_fixture_databases,
    _LiveEnvironment,
)
from fastmcp import Client

from turing_agentmemory_mcp.document_job_manager import DocumentIngestManager
from turing_agentmemory_mcp.document_jobs import DocumentJobStore
from turing_agentmemory_mcp.file_upload import DocumentUploadStore
from turing_agentmemory_mcp.server import create_mcp_app
from turing_agentmemory_mcp.store import TuringAgentMemory
from turing_agentmemory_mcp.tenant_identity import derive_tenant_database_identity
from turing_agentmemory_mcp.tenant_provisioning import (
    ProvisionedTenantDatabase,
    TenantProvisioner,
    TenantProvisioningError,
)
from turing_agentmemory_mcp.tenant_router import TenantRouter

(
    _SAME_TENANT,
    _DIFFERENT_TENANT_A,
    _DIFFERENT_TENANT_B,
    _CACHE_TENANT_A,
    _CACHE_TENANT_B,
    _MISSING_TENANT,
    _RESTART_TENANT,
    _FILE_TENANT,
    _FILE_FOREIGN_TENANT,
) = _LIFECYCLE_TENANTS


@dataclass(frozen=True)
class _LifecycleChaosProof:
    same_tenant_single_ready: bool = False
    different_tenant_databases: frozenset[str] = frozenset()
    eviction_reused_durable_data: bool = False
    active_reference_survived: bool = False
    missing_ready_failed_closed: bool = False
    missing_ready_database_absent: bool = False
    restart_observed_degraded: bool = False
    restart_recovered_existing_data: bool = False
    real_file_job_succeeded: bool = False
    cited_search_scoped: bool = False
    staged_bytes_removed: bool = False
    foreign_file_absent: bool = False


class _CountingProvisioner:
    def __init__(self, delegate: TenantProvisioner) -> None:
        self.delegate = delegate
        self.naming_key = delegate.naming_key
        self.base_client = delegate.base_client
        self.registry = delegate.registry
        self.calls = 0
        self._lock = Lock()

    def provision(self, user_identifier: str) -> ProvisionedTenantDatabase:
        with self._lock:
            self.calls += 1
        return self.delegate.provision(user_identifier)


class _BarrierProvisioner(_CountingProvisioner):
    def __init__(self, delegate: TenantProvisioner) -> None:
        super().__init__(delegate)
        self.barrier = Barrier(2)
        self.active = 0
        self.max_active = 0

    def provision(self, user_identifier: str) -> ProvisionedTenantDatabase:
        with self._lock:
            self.calls += 1
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            self.barrier.wait(timeout=30)
            return self.delegate.provision(user_identifier)
        finally:
            with self._lock:
                self.active -= 1


class _ManualClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _router(
    environment: _LiveEnvironment,
    *,
    provisioner: Any | None = None,
    capacity: int = 16,
    idle_ttl_s: float = 300,
    clock: Any = time.monotonic,
) -> TenantRouter:
    return TenantRouter(
        provisioner or environment.provisioner,
        environment.shared_dependencies,
        store_factory=TuringAgentMemory,
        capacity=capacity,
        idle_ttl_s=idle_ttl_s,
        clock=clock,
    )


def _same_tenant_first_use(environment: _LiveEnvironment) -> bool:
    provisioner = _CountingProvisioner(environment.provisioner)
    router = _router(environment, provisioner=provisioner)
    with ThreadPoolExecutor(max_workers=8) as pool:
        views = list(pool.map(router.resolve, [_SAME_TENANT] * 8))

    database_name = derive_tenant_database_identity(
        _SAME_TENANT, naming_key=_NAMING_KEY
    ).database_name
    client = replace(environment.base_client, database=database_name)
    manifests = client.query("SELECT FROM TenantManifest")
    record = environment.provisioner.registry.get(database_name)
    return (
        provisioner.calls == 1
        and all(view is views[0] for view in views)
        and database_name in environment.base_client.list_databases()
        and len(manifests) == 1
        and manifests[0].get("database_name") == database_name
        and getattr(record, "state", "") == "ready"
    )


def _different_tenant_first_use(environment: _LiveEnvironment) -> frozenset[str]:
    provisioner = _BarrierProvisioner(environment.provisioner)
    router = _router(environment, provisioner=provisioner)
    with ThreadPoolExecutor(max_workers=2) as pool:
        views = list(pool.map(router.resolve, (_DIFFERENT_TENANT_A, _DIFFERENT_TENANT_B)))
    database_names = frozenset(
        view.identity.database_name for view in views if view.identity is not None
    )
    if provisioner.max_active != 2 or provisioner.calls != 2:
        return frozenset()
    if not database_names <= environment.base_client.list_databases():
        return frozenset()
    return database_names


def _cache_lifecycle(environment: _LiveEnvironment) -> tuple[bool, bool]:
    clock = _ManualClock()
    router = _router(environment, capacity=1, idle_ttl_s=1, clock=clock)
    active_view = router.resolve(_CACHE_TENANT_A)
    stored = active_view.memory.store_message(
        user_identifier=_CACHE_TENANT_A,
        session_id="cache-lifecycle",
        role="user",
        content="durable cache lifecycle canary",
    )

    router.resolve(_CACHE_TENANT_B)
    capacity_reused_view = router.resolve(_CACHE_TENANT_A)
    capacity_item = capacity_reused_view.memory.get_memory(
        user_identifier=_CACHE_TENANT_A,
        memory_id=stored.id,
    )
    active_item = active_view.memory.get_memory(
        user_identifier=_CACHE_TENANT_A,
        memory_id=stored.id,
    )

    clock.advance(2)
    ttl_reused_view = router.resolve(_CACHE_TENANT_A)
    ttl_item = ttl_reused_view.memory.get_memory(
        user_identifier=_CACHE_TENANT_A,
        memory_id=stored.id,
    )
    durable_reuse = (
        capacity_reused_view is not active_view
        and ttl_reused_view is not capacity_reused_view
        and capacity_reused_view.identity == active_view.identity == ttl_reused_view.identity
        and capacity_item is not None
        and ttl_item is not None
        and capacity_item.content == stored.content == ttl_item.content
    )
    return durable_reuse, active_item is not None and active_item.content == stored.content


def _missing_ready_lifecycle(environment: _LiveEnvironment) -> tuple[bool, bool]:
    router = _router(environment)
    view = router.resolve(_MISSING_TENANT)
    assert view.identity is not None
    database_name = view.identity.database_name
    record = environment.provisioner.registry.get(database_name)
    assert getattr(record, "state", "") == "ready"
    _drop_fixture_databases(environment.base_client, frozenset({database_name}))

    failed_closed = False
    try:
        _router(environment).resolve(_MISSING_TENANT)
    except TenantProvisioningError as exc:
        failed_closed = "is missing" in str(exc) and database_name in str(exc)
    database_absent = database_name not in environment.base_client.list_databases()
    return failed_closed, database_absent


def _wait_for_arcadedb(environment: _LiveEnvironment, *, timeout_s: float = 90) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if environment.base_client.is_ready():
            return
        time.sleep(0.25)
    raise AssertionError("ArcadeDB did not become ready after the scoped service restart")


def _restart_lifecycle(environment: _LiveEnvironment) -> tuple[bool, bool]:
    router = _router(environment)
    view = router.resolve(_RESTART_TENANT)
    stored = view.memory.store_message(
        user_identifier=_RESTART_TENANT,
        session_id="restart-lifecycle",
        role="user",
        content="durable restart lifecycle canary",
    )

    stopped = _compose("stop", "arcadedb")
    assert stopped.returncode == 0, stopped.stderr.decode(errors="replace")
    observed_degraded = False
    try:
        health_degraded = router.runtime_status().get("ready") is False
        operation_degraded = False
        try:
            view.memory.get_memory(user_identifier=_RESTART_TENANT, memory_id=stored.id)
        except Exception:
            operation_degraded = True
        observed_degraded = health_degraded and operation_degraded
    finally:
        started = _compose("start", "arcadedb")
        assert started.returncode == 0, started.stderr.decode(errors="replace")
        _wait_for_arcadedb(environment)

    recovery_router = _router(environment)
    deadline = time.monotonic() + 30
    recovered_item = None
    while recovered_item is None and time.monotonic() < deadline:
        try:
            recovered_view = recovery_router.resolve(_RESTART_TENANT)
            recovered_item = recovered_view.memory.get_memory(
                user_identifier=_RESTART_TENANT,
                memory_id=stored.id,
            )
        except Exception:
            time.sleep(0.25)
    recovered = recovered_item is not None and recovered_item.content == stored.content
    return observed_degraded, recovered


def _payload(result: Any) -> Any:
    if hasattr(result, "structured_content") and result.structured_content is not None:
        value = result.structured_content
        if isinstance(value, dict) and set(value) == {"result"}:
            return value["result"]
        return value
    if hasattr(result, "data") and result.data is not None:
        return result.data
    if hasattr(result, "content"):
        text = "".join(getattr(item, "text", "") for item in result.content)
        return json.loads(text)
    return result


async def _enqueue_and_poll(app: Any, *, source: Path) -> dict[str, object]:
    async with Client(app) as client:
        queued = _payload(
            await client.call_tool(
                "document_ingest_file",
                {
                    "user_identifier": _FILE_TENANT,
                    "title": "Lifecycle isolation manual",
                    "path": str(source),
                    "document_id": "lifecycle-isolation-document",
                    "source": "phase-05-live-fixture",
                    "tags": ["live", "isolation"],
                },
            )
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            status = _payload(
                await client.call_tool(
                    "document_ingest_status",
                    {
                        "job_id": queued["job_id"],
                        "user_identifier": _FILE_TENANT,
                    },
                )
            )
            if status["status"] in {"succeeded", "failed", "canceled"}:
                return status
            await asyncio.sleep(0.1)
    raise AssertionError("document ingestion job did not reach a terminal state")


def _real_file_lifecycle(environment: _LiveEnvironment) -> tuple[bool, bool, bool, bool]:
    source = environment.root / "lifecycle-isolation.md"
    canary = "zephyrcitationcanary"
    source.write_text(
        "# Lifecycle isolation\n\nThe zephyrcitationcanary survives the asynchronous path.\n",
        encoding="utf-8",
    )
    manager = DocumentIngestManager(
        DocumentJobStore(environment.root / "lifecycle-document-jobs.sqlite3"),
        staging_root=environment.root / "lifecycle-document-staging",
        store_factory=lambda: environment.router,
    )
    app = create_mcp_app(
        resolver=environment.router,
        upload_store=DocumentUploadStore(
            environment.root / "lifecycle-document-uploads",
            max_file_bytes=1024 * 1024,
            chunk_bytes=64 * 1024,
        ),
        document_manager=manager,
        start_document_worker=True,
    )
    try:
        terminal = asyncio.run(_enqueue_and_poll(app, source=source))
    finally:
        manager.stop()

    job = manager.get(str(terminal["job_id"]), user_identifier=_FILE_TENANT)
    job_succeeded = (
        terminal["status"] == "succeeded"
        and job is not None
        and job.status == "succeeded"
        and job.result.get("document_id") == "lifecycle-isolation-document"
    )
    staged_removed = job is not None and not Path(job.staged_path).exists()

    tenant_view = environment.router.resolve(_FILE_TENANT)
    hits = tenant_view.memory.search_documents(
        user_identifier=_FILE_TENANT,
        query=canary,
        document_id="lifecycle-isolation-document",
    )
    assert tenant_view.identity is not None
    tenant_client = replace(environment.base_client, database=tenant_view.identity.database_name)
    chunks = tenant_client.query(
        "SELECT FROM Chunk WHERE user_identifier = :user_identifier AND document_id = :document_id",
        params={
            "user_identifier": _FILE_TENANT,
            "document_id": "lifecycle-isolation-document",
        },
    )
    cited_scoped = (
        bool(chunks)
        and bool(hits)
        and all(hit.document_id == "lifecycle-isolation-document" for hit in hits)
        and all(bool(hit.locator) for hit in hits)
    )

    foreign_view = environment.router.resolve(_FILE_FOREIGN_TENANT)
    foreign_hits = foreign_view.memory.search_documents(
        user_identifier=_FILE_FOREIGN_TENANT,
        query=canary,
    )
    assert foreign_view.identity is not None
    foreign_client = replace(environment.base_client, database=foreign_view.identity.database_name)
    foreign_chunks = foreign_client.query(
        "SELECT FROM Chunk WHERE user_identifier = :user_identifier",
        params={"user_identifier": _FILE_FOREIGN_TENANT},
    )
    return job_succeeded, cited_scoped, staged_removed, not foreign_hits and not foreign_chunks


def _run_lifecycle_chaos_contract(
    environment: _LiveEnvironment,
) -> _LifecycleChaosProof:
    same_tenant_single_ready = _same_tenant_first_use(environment)
    different_tenant_databases = _different_tenant_first_use(environment)
    eviction_reused_durable_data, active_reference_survived = _cache_lifecycle(environment)
    missing_ready_failed_closed, missing_ready_database_absent = _missing_ready_lifecycle(
        environment
    )
    restart_observed_degraded, restart_recovered_existing_data = _restart_lifecycle(environment)
    real_file_job_succeeded, cited_search_scoped, staged_bytes_removed, foreign_file_absent = (
        _real_file_lifecycle(environment)
    )
    return _LifecycleChaosProof(
        same_tenant_single_ready=same_tenant_single_ready,
        different_tenant_databases=different_tenant_databases,
        eviction_reused_durable_data=eviction_reused_durable_data,
        active_reference_survived=active_reference_survived,
        missing_ready_failed_closed=missing_ready_failed_closed,
        missing_ready_database_absent=missing_ready_database_absent,
        restart_observed_degraded=restart_observed_degraded,
        restart_recovered_existing_data=restart_recovered_existing_data,
        real_file_job_succeeded=real_file_job_succeeded,
        cited_search_scoped=cited_search_scoped,
        staged_bytes_removed=staged_bytes_removed,
        foreign_file_absent=foreign_file_absent,
    )
