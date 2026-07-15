"""Tenant-identity/binding boundary tests for `_StoreCore` (ARC-07, 05-09).

Split out of `tests/test_store_arcadedb_core.py` (Task 2) when adding the
tenant-binding assertions pushed that file over the no-allowlist 600-LOC cap
(D-08); shared fixtures live in `tests/_store_arcadedb_core_shared.py`.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest
from _store_arcadedb_core_shared import (
    FakeArcadeDBClient,
    StubEmbedder,
    TrackingSparseIndex,
    make_full_store,
)

import turing_agentmemory_mcp.store_core as store_core_module
from turing_agentmemory_mcp.governance import NoopAuditSink, NoopRedactor
from turing_agentmemory_mcp.observability import InMemorySpanRecorder
from turing_agentmemory_mcp.store_core import _StoreCore
from turing_agentmemory_mcp.tenant_binding import TenantBinding, TenantBindingError
from turing_agentmemory_mcp.tenant_identity import derive_tenant_database_identity

_NAMING_KEY = bytes(range(32))


@pytest.mark.parametrize(
    "invalid_identifier",
    ["", "   ", " alice", "alice ", "ali\x00ce", "\ud800"],
)
def test_direct_store_rejects_exact_invalid_identity_before_client_activity(
    tmp_path: Path, invalid_identifier: str
) -> None:
    client = FakeArcadeDBClient()
    store = make_full_store(client, tmp_path)

    with pytest.raises(ValueError):
        store.list_memories(user_identifier=invalid_identifier)

    assert client.queries == []
    assert client.commands == []


def test_direct_store_passes_valid_opaque_unicode_unchanged_to_client(tmp_path: Path) -> None:
    client = FakeArcadeDBClient()
    store = make_full_store(client, tmp_path)
    exact_identifier = "Tenant-Å-ς"

    assert store.list_memories(user_identifier=exact_identifier) == []

    assert client.queries
    assert any(
        params is not None and exact_identifier in params.values()
        for _statement, params in client.queries
    )


def test_require_user_delegates_to_central_exact_validator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # CONTRACT CHANGE (05-09 Task 2): _require_user became an instance method
    # bound to self.tenant_binding, so it can no longer be called unbound on
    # the class. An unbound store (tenant_binding=None) still delegates
    # straight to the central validator, preserving every existing caller.
    calls: list[str] = []

    def validate_user_identifier(value: str) -> str:
        calls.append(value)
        return value

    monkeypatch.setattr(
        store_core_module,
        "validate_user_identifier",
        validate_user_identifier,
        raising=False,
    )
    client = FakeArcadeDBClient()
    store = make_full_store(client, tmp_path)

    store._require_user("opaque-Ω")

    assert calls == ["opaque-Ω"]


def test_bound_store_rejects_foreign_identifier_via_require_user(tmp_path: Path) -> None:
    identity = derive_tenant_database_identity("Tenant-A", naming_key=_NAMING_KEY)
    binding = TenantBinding(identity=identity, naming_key=_NAMING_KEY)
    client = FakeArcadeDBClient()
    store = make_full_store(client, tmp_path, tenant_binding=binding)

    store._require_user("Tenant-A")
    with pytest.raises(TenantBindingError):
        store._require_user("Tenant-B")

    assert client.queries == []
    assert client.commands == []


def test_shared_dependency_bundle_reuses_dependencies_but_not_tenant_runtime_state(
    tmp_path: Path,
) -> None:
    first_client = FakeArcadeDBClient()
    embedder = StubEmbedder()
    reranker = object()
    entity_processor = object()
    memory_extractor = SimpleNamespace(model_name="extractor")
    sparse_index = TrackingSparseIndex()
    community_detector = SimpleNamespace(seed=17)
    observer = InMemorySpanRecorder()
    redactor = NoopRedactor()
    audit_sink = NoopAuditSink()
    first = _StoreCore(
        first_client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=embedder,  # type: ignore[arg-type]
        reranker=reranker,  # type: ignore[arg-type]
        entity_processor=entity_processor,  # type: ignore[arg-type]
        memory_extractor=memory_extractor,  # type: ignore[arg-type]
        sparse_index=sparse_index,  # type: ignore[arg-type]
        community_detector=community_detector,  # type: ignore[arg-type]
        observer=observer,
        redactor=redactor,
        audit_sink=audit_sink,
        fusion_enabled=True,
        community_rebuild_on_batch=True,
        rerank_threshold=0.25,
        rerank_blend=True,
        rerank_preserve_seed_margin=0.2,
        rerank_candidate_limit=19,
    )

    shared = first.shared_dependencies()
    second_client = FakeArcadeDBClient()
    second = _StoreCore(second_client, shared_dependencies=shared)  # type: ignore[call-arg]

    for name in (
        "embedder",
        "reranker",
        "entity_processor",
        "memory_extractor",
        "sparse_index",
        "community_detector",
        "observer",
        "redactor",
        "audit_sink",
    ):
        assert getattr(second, name) is getattr(first, name)
    assert second.client is second_client
    assert second.client is not first.client
    assert second.runtime_signals is not first.runtime_signals
    assert second.tenant_binding is None
    first._schema_bootstrapped = True
    assert second._schema_bootstrapped is False
    with pytest.raises(FrozenInstanceError):
        shared.dimensions = 5
    assert "tenant_binding" not in type(shared).__annotations__
