"""ARC-07 gap closure: read/write/update/delete/document/background
adversarial binding matrix (05-10 Task 2).

Reuses the `_StoreCore` seam fixture established in 05-09
(`tests/_store_arcadedb_core_shared.py`) -- `FakeArcadeDBClient` records
every `query`/`command` call, which is exactly what proves "zero client
activity" on rejection. The store itself is constructed directly (not via
that module's `make_full_store`) because the bound-identifier "succeeds"
matrix needs a working `.embed()`/`.embed_many()` embedder and a real
`NoopEntityProcessor`, neither of which that helper's fixed stub provides.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from _store_arcadedb_core_shared import FakeArcadeDBClient

from turing_agentmemory_mcp.entity_extraction import NoopEntityProcessor
from turing_agentmemory_mcp.observability import InMemorySpanRecorder
from turing_agentmemory_mcp.store import TuringAgentMemory
from turing_agentmemory_mcp.tenant_binding import TenantBinding, TenantBindingError
from turing_agentmemory_mcp.tenant_identity import derive_tenant_database_identity
from turing_agentmemory_mcp.tenant_router import StaticStoreResolver

_NAMING_KEY = bytes(range(32))
_TENANT_A = "Tenant-A"
_TENANT_B = "Tenant-B"


class _WorkingEmbedder:
    """A `.embed()`/`.embed_many()`-capable stand-in -- unlike
    `_store_arcadedb_core_shared.StubEmbedder` (dimensions-only, no callable
    methods), the bound-identifier "succeeds" path here actually reaches
    embedding for the six search/ingest methods."""

    dimensions = 3

    def embed(self, text: str) -> list[float]:
        return [float(len(text)), 1.0, 0.0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class RecordingAuditSink:
    """Mirrors tests/test_governance.py::RecordingAuditSink."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, event: dict[str, object]) -> None:
        self.events.append(event)


@dataclass(frozen=True)
class MethodCase:
    name: str
    kwargs: dict[str, object]
    spans: bool  # opens its own `with self._span(...)` block
    # Seeds state (via the SAME bound tenant) so the "bound identifier
    # succeeds" test exercises a real success path rather than an
    # incidental "not found" -- e.g. update_memory requires an existing row.
    setup: Callable[[TuringAgentMemory], None] | None = field(default=None)


def _seed_memory(store: TuringAgentMemory) -> None:
    store.store_message(
        user_identifier=_TENANT_A,
        session_id="s1",
        role="user",
        content="seed",
        memory_id="mem-1",
    )


# Explicit literal table (not derived from introspection) so a newly added
# public method does not silently fall out of coverage -- it must be added
# here by name for the parametrized adversarial tests to see it.
_METHOD_CASES: tuple[MethodCase, ...] = (
    MethodCase("store_message", {"session_id": "s1", "role": "user", "content": "hello"}, True),
    MethodCase(
        "store_messages",
        {"messages": [{"session_id": "s1", "role": "user", "content": "hello"}]},
        True,
    ),
    MethodCase("add_entity", {"name": "Alice", "entity_type": "person"}, False),
    MethodCase("add_preference", {"category": "diet", "preference": "vegan"}, False),
    MethodCase(
        "add_fact", {"subject": "Alice", "predicate": "knows", "object_value": "Bob"}, False
    ),
    MethodCase("get_memory", {"memory_id": "mem-1"}, False),
    MethodCase("list_memories", {}, False),
    MethodCase(
        "update_memory", {"memory_id": "mem-1", "content": "updated"}, False, setup=_seed_memory
    ),
    MethodCase("delete_memory", {"memory_id": "mem-1"}, False),
    MethodCase("get_context", {"query": "hello"}, False),
    MethodCase("ingest_document_text", {"title": "doc", "text": "document text"}, True),
    MethodCase("get_document", {"document_id": "doc-1"}, False),
    MethodCase(
        "reindex_document_text",
        {"document_id": "doc-1", "title": "doc", "text": "document text"},
        True,
    ),
    MethodCase("delete_document", {"document_id": "doc-1"}, False),
    MethodCase("search_documents", {"query": "hello"}, True),
    MethodCase("search_memory", {"query": "hello"}, True),
    MethodCase("rebuild_vector_projection", {}, False),
    MethodCase("rebuild_communities", {}, False),
)

assert len(_METHOD_CASES) == 18, "table must cover all 18 public store methods (see 05-10-PLAN.md)"


def _binding(user_identifier: str) -> TenantBinding:
    identity = derive_tenant_database_identity(user_identifier, naming_key=_NAMING_KEY)
    return TenantBinding(identity=identity, naming_key=_NAMING_KEY)


def _bound_store(
    tmp_path: Path,
    *,
    observer: InMemorySpanRecorder | None = None,
    audit_sink: RecordingAuditSink | None = None,
) -> tuple[TuringAgentMemory, FakeArcadeDBClient]:
    client = FakeArcadeDBClient()
    kwargs: dict[str, object] = {}
    if observer is not None:
        kwargs["observer"] = observer
    if audit_sink is not None:
        kwargs["audit_sink"] = audit_sink
    store = TuringAgentMemory(
        client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=_WorkingEmbedder(),  # type: ignore[arg-type]
        reranker=object(),  # type: ignore[arg-type]
        entity_processor=NoopEntityProcessor(),
        tenant_binding=_binding(_TENANT_A),
        **kwargs,
    )
    return store, client


@pytest.mark.parametrize("case", _METHOD_CASES, ids=lambda case: case.name)
def test_foreign_identifier_rejected_on_every_public_path(tmp_path: Path, case: MethodCase) -> None:
    store, client = _bound_store(tmp_path)
    method = getattr(store, case.name)

    with pytest.raises(TenantBindingError):
        method(user_identifier=_TENANT_B, **case.kwargs)

    assert client.queries == [], case.name
    assert client.commands == [], case.name


@pytest.mark.parametrize(
    "case", [case for case in _METHOD_CASES if case.spans], ids=lambda case: case.name
)
def test_foreign_identifier_rejected_before_span_or_audit(tmp_path: Path, case: MethodCase) -> None:
    observer = InMemorySpanRecorder()
    audit = RecordingAuditSink()
    store, client = _bound_store(tmp_path, observer=observer, audit_sink=audit)
    method = getattr(store, case.name)

    with pytest.raises(TenantBindingError):
        method(user_identifier=_TENANT_B, **case.kwargs)

    assert observer.events == [], case.name
    assert audit.events == [], case.name
    assert client.queries == [], case.name
    assert client.commands == [], case.name


@pytest.mark.parametrize("case", _METHOD_CASES, ids=lambda case: case.name)
def test_bound_identifier_succeeds_on_every_public_path(tmp_path: Path, case: MethodCase) -> None:
    store, _client = _bound_store(tmp_path)
    if case.setup is not None:
        case.setup(store)
    method = getattr(store, case.name)

    method(user_identifier=_TENANT_A, **case.kwargs)  # must not raise


def test_background_job_identifier_rejected_by_foreign_view(tmp_path: Path) -> None:
    # Mirrors DocumentIngestManager.process_next's
    # `self.resolver.resolve(job.user_identifier).memory` shape
    # (document_job_manager.py) without re-architecting the worker: a claimed
    # job whose stored user_identifier is foreign to the resolved tenant-A
    # view must fail closed before any client activity.
    store, client = _bound_store(tmp_path)
    resolver = StaticStoreResolver(store)

    document_memory = resolver.resolve(_TENANT_B).memory

    with pytest.raises(TenantBindingError):
        document_memory.ingest_document_text(
            user_identifier=_TENANT_B, title="doc", text="document text"
        )

    assert client.queries == []
    assert client.commands == []
