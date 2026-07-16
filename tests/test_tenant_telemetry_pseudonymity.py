"""ARC-07 gap closure (05-11): span/audit choke-point pseudonymity.

Proves `_StoreCore._span`/`_audit` are the central sanitizing choke points
(Task 1) and, driving the full public store surface, that no store operation
leaks a raw tenant identifier to either process-wide sink (Task 2). Reuses
the `_StoreCore`/`FakeArcadeDBClient` seam fixtures established in
05-09/05-10 (`tests/_store_arcadedb_core_shared.py`).
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from _store_arcadedb_core_shared import FakeArcadeDBClient, StubEmbedder

from turing_agentmemory_mcp.entity_extraction import NoopEntityProcessor
from turing_agentmemory_mcp.observability import InMemorySpanRecorder
from turing_agentmemory_mcp.store import TuringAgentMemory
from turing_agentmemory_mcp.store_core import _StoreCore
from turing_agentmemory_mcp.tenant_binding import (
    TENANT_CORRELATION_KEY,
    TenantBinding,
    sanitize_tenant_attributes,
)
from turing_agentmemory_mcp.tenant_identity import derive_tenant_database_identity

_NAMING_KEY = bytes(range(32))
_TENANT_A = "Tenant-A-telemetry-canary"


class RecordingAuditSink:
    """Mirrors tests/test_governance.py::RecordingAuditSink."""

    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, event: dict[str, object]) -> None:
        self.events.append(event)


class _WorkingEmbedder:
    """A `.embed()`/`.embed_many()`-capable stand-in, mirroring
    tests/test_tenant_binding_enforcement.py's helper -- the full-surface
    drive test needs real embedding, unlike `StubEmbedder` (dimensions-only)."""

    dimensions = 3

    def embed(self, text: str) -> list[float]:
        return [float(len(text)), 1.0, 0.0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def _binding(user_identifier: str) -> TenantBinding:
    identity = derive_tenant_database_identity(user_identifier, naming_key=_NAMING_KEY)
    return TenantBinding(identity=identity, naming_key=_NAMING_KEY)


def _core(
    tmp_path: Path,
    *,
    tenant_binding: TenantBinding | None = None,
    observer: InMemorySpanRecorder | None = None,
    audit_sink: RecordingAuditSink | None = None,
) -> _StoreCore:
    return _StoreCore(
        FakeArcadeDBClient(),  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=StubEmbedder(),  # type: ignore[arg-type]
        reranker=object(),  # type: ignore[arg-type]
        entity_processor=object(),  # type: ignore[arg-type]
        tenant_binding=tenant_binding,
        observer=observer,
        audit_sink=audit_sink,
    )


def test_bound_store_emits_opaque_tenant_correlation(tmp_path: Path) -> None:
    observer = InMemorySpanRecorder()
    audit = RecordingAuditSink()
    binding = _binding(_TENANT_A)
    store = _core(tmp_path, tenant_binding=binding, observer=observer, audit_sink=audit)

    with store._span("probe", {"user_identifier": _TENANT_A, "source": "cli"}):
        pass
    store._audit(
        operation="probe.op",
        user_identifier=_TENANT_A,
        resource_type="probe",
        resource_id="probe-1",
    )

    span_attributes = observer.events[-1]["attributes"]
    assert "user_identifier" not in span_attributes
    assert span_attributes["source"] == "cli"
    assert span_attributes[TENANT_CORRELATION_KEY] == binding.identity.database_name

    audit_event = audit.events[-1]
    assert "user_identifier" not in audit_event
    assert audit_event[TENANT_CORRELATION_KEY] == binding.identity.database_name
    assert audit_event["operation"] == "probe.op"
    assert audit_event["resource_type"] == "probe"
    assert audit_event["resource_id"] == "probe-1"
    assert audit_event["success"] is True


def test_unbound_store_omits_tenant_identity(tmp_path: Path) -> None:
    observer = InMemorySpanRecorder()
    audit = RecordingAuditSink()
    store = _core(tmp_path, observer=observer, audit_sink=audit)

    with store._span("probe", {"user_identifier": _TENANT_A}):
        pass
    store._audit(
        operation="probe.op",
        user_identifier=_TENANT_A,
        resource_type="probe",
        resource_id="probe-1",
    )

    span_attributes = observer.events[-1]["attributes"]
    assert "user_identifier" not in span_attributes
    assert TENANT_CORRELATION_KEY not in span_attributes

    audit_event = audit.events[-1]
    assert "user_identifier" not in audit_event
    assert TENANT_CORRELATION_KEY not in audit_event


def test_sanitizer_strips_identity_keys_from_nested_attributes() -> None:
    binding = _binding(_TENANT_A)

    clean = sanitize_tenant_attributes(
        {"details": {"user_identifier": _TENANT_A, "count": 3}, "source": "cli"},
        binding,
    )

    assert clean["details"] == {"count": 3}
    assert clean["source"] == "cli"
    assert clean[TENANT_CORRELATION_KEY] == binding.identity.database_name
    assert sanitize_tenant_attributes({"user_identifier": _TENANT_A}, None) == {}
    assert sanitize_tenant_attributes(None, binding) == {
        TENANT_CORRELATION_KEY: binding.identity.database_name
    }


def test_audit_retains_operation_and_resource_fields(tmp_path: Path) -> None:
    audit = RecordingAuditSink()
    binding = _binding(_TENANT_A)
    store = _core(tmp_path, tenant_binding=binding, audit_sink=audit)

    store._audit(
        operation="probe.op",
        user_identifier=_TENANT_A,
        resource_type="probe",
        resource_id="probe-1",
        success=False,
        details={"count": 2},
    )

    event = audit.events[-1]
    assert event["operation"] == "probe.op"
    assert event["resource_type"] == "probe"
    assert event["resource_id"] == "probe-1"
    assert event["success"] is False
    assert event["details"] == {"count": 2}
    assert "user_identifier" not in event


def test_no_store_operation_emits_raw_identifier_to_spans_or_audits(tmp_path: Path) -> None:
    observer = InMemorySpanRecorder()
    audit = RecordingAuditSink()
    binding = _binding(_TENANT_A)
    client = FakeArcadeDBClient()
    store = TuringAgentMemory(
        client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=_WorkingEmbedder(),  # type: ignore[arg-type]
        reranker=object(),  # type: ignore[arg-type]
        entity_processor=NoopEntityProcessor(),
        tenant_binding=binding,
        observer=observer,
        audit_sink=audit,
    )

    memory = store.store_message(
        user_identifier=_TENANT_A, session_id="s1", role="user", content="hello"
    )
    store.store_messages(
        user_identifier=_TENANT_A,
        messages=[{"session_id": "s1", "role": "user", "content": "batch hello"}],
    )
    store.add_entity(user_identifier=_TENANT_A, name="Alice", entity_type="person")
    store.add_preference(user_identifier=_TENANT_A, category="diet", preference="vegan")
    store.add_fact(
        user_identifier=_TENANT_A, subject="Alice", predicate="knows", object_value="Bob"
    )
    store.get_memory(user_identifier=_TENANT_A, memory_id=memory.id)
    store.list_memories(user_identifier=_TENANT_A)
    store.update_memory(user_identifier=_TENANT_A, memory_id=memory.id, content="updated")
    store.get_context(user_identifier=_TENANT_A, query="hello")
    document = store.ingest_document_text(
        user_identifier=_TENANT_A, title="doc", text="document text"
    )
    store.get_document(user_identifier=_TENANT_A, document_id=document.document_id)
    store.reindex_document_text(
        user_identifier=_TENANT_A,
        document_id=document.document_id,
        title="doc",
        text="document text v2",
    )
    store.search_documents(user_identifier=_TENANT_A, query="document")
    store.search_memory(user_identifier=_TENANT_A, query="hello")
    store.rebuild_vector_projection(user_identifier=_TENANT_A)
    store.rebuild_communities(user_identifier=_TENANT_A)
    store.delete_memory(user_identifier=_TENANT_A, memory_id=memory.id)
    store.delete_document(user_identifier=_TENANT_A, document_id=document.document_id)

    assert observer.events, "no span events recorded -- test would be vacuously green"
    assert audit.events, "no audit events recorded -- test would be vacuously green"

    serialized = json.dumps(
        {"spans": observer.events, "audits": audit.events}, ensure_ascii=False, default=str
    )
    assert _TENANT_A not in serialized
    assert any(
        event.get("attributes", {}).get(TENANT_CORRELATION_KEY) == binding.identity.database_name
        for event in observer.events
    )
