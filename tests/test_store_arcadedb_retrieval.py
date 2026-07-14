"""04-07: fused memory search + entity/fact/community evidence traversal
ported from TuringDB to ArcadeDB (ARC-04/ARC-05/ARC-06).

Fixtures (`_FakeArcadeDBClient`/`_ScriptedExtractor`/`make_retrieval_store`)
live in `_retrieval_arcadedb_shared.py` (600-LOC cap split, mirrors
`_batch_memory_shared.py`'s convention) -- no live ArcadeDB container is
required.
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path
from typing import Any

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from _batch_memory_shared import CountingBatchEmbedder
from _retrieval_arcadedb_shared import (
    _FakeArcadeDBClient,
    _ScriptedExtractor,
    make_retrieval_store,
)

import turing_agentmemory_mcp.store_search as store_search_module
from turing_agentmemory_mcp.entity_extraction import NoopEntityProcessor
from turing_agentmemory_mcp.governance import NoopAuditSink, NoopRedactor
from turing_agentmemory_mcp.ids import stable_id
from turing_agentmemory_mcp.models import RetrievalCandidate
from turing_agentmemory_mcp.observability import InMemorySpanRecorder
from turing_agentmemory_mcp.sparse_index import SparseIndex
from turing_agentmemory_mcp.store import TuringAgentMemory

_STORE_SEARCH_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp" / "store_search.py"
)
_STORE_EVIDENCE_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp" / "store_evidence.py"
)
_STORE_RETRIEVAL_QUERIES_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "turing_agentmemory_mcp"
    / "store_retrieval_queries.py"
)


# ============================================================================
# Task 1: fused-search seed channels (native HNSW dense + BOTH-channels
# lexical), unchanged RRF, FTS5 retired
# ============================================================================


def test_fused_search_feeds_per_channel_candidates_to_unchanged_rrf(
    tmp_path: Path, monkeypatch: Any
) -> None:
    calls: list[dict[str, list[RetrievalCandidate]]] = []
    original_fuse = store_search_module.fuse_rankings

    def capture(rankings, **kwargs):  # type: ignore[no-untyped-def]
        calls.append(dict(rankings))
        return original_fuse(rankings, **kwargs)

    monkeypatch.setattr(store_search_module, "fuse_rankings", capture)
    client = _FakeArcadeDBClient()
    store = make_retrieval_store(client, tmp_path)
    store.store_message(
        user_identifier="alice", session_id="s1", role="user", content="the router is stable"
    )
    store.store_message(
        user_identifier="alice", session_id="s1", role="user", content="the router needs a reboot"
    )

    hits = store.search_memory(user_identifier="alice", query="router", limit=5, explain=True)

    assert hits
    assert calls, "fuse_rankings was never invoked"
    rankings = calls[0]
    assert "episode_dense" in rankings
    assert "bm25" in rankings
    for candidates in rankings.values():
        assert all(isinstance(candidate, RetrievalCandidate) for candidate in candidates)


def test_dense_channel_orders_by_native_hnsw_score_with_no_vector_id_join(
    tmp_path: Path,
) -> None:
    client = _FakeArcadeDBClient()
    store = make_retrieval_store(client, tmp_path)
    near = store.store_message(user_identifier="alice", session_id="s1", role="user", content="a")
    store.store_message(user_identifier="alice", session_id="s1", role="user", content="aaaaaaaaaa")

    evidence = store._episode_dense_evidence(
        "alice", store._embed_text("a", operation="memory.search"), 10
    )

    assert evidence
    assert evidence[0].source_memory_id == near.id
    dense_queries = [stmt for stmt, _ in client.queries if "vectorNeighbors" in stmt]
    assert dense_queries
    assert "vector_id" not in dense_queries[0]


# 04-09 regression (found via the D-10 chaos-restart test against a live
# ArcadeDB container, Rule 1 bug fix): the non-fused `search_memory` path
# (the actual production default -- fusion is opt-in via
# AGENTMEMORY_FUSION_ENABLED) fed `dense_search_statement`'s bare `id`/
# `distance` rows straight into `_memory_from_row` with no `extra_fields`,
# so every hit came back with empty content/kind/session_id/etc. whenever
# the memory was found via the dense channel -- virtually always.
def test_non_fused_search_memory_returns_full_content_not_just_id_and_distance(
    tmp_path: Path,
) -> None:
    client = _FakeArcadeDBClient()
    store = TuringAgentMemory(
        client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=CountingBatchEmbedder(),
        reranker=None,
        entity_processor=NoopEntityProcessor(),
        redactor=NoopRedactor(),
        audit_sink=NoopAuditSink(),
        observer=InMemorySpanRecorder(),
        fusion_enabled=False,
    )
    written = store.store_message(
        user_identifier="alice",
        session_id="s1",
        role="user",
        content="the router is stable after the reset",
    )

    hits = store.search_memory(user_identifier="alice", query="router reset", limit=5)

    assert hits
    assert hits[0].id == written.id
    assert hits[0].content == written.content
    assert hits[0].kind == written.kind
    assert hits[0].user_identifier == "alice"


def test_bm25_channel_reads_native_arcadedb_lexical_not_sqlite_sparse_index(
    tmp_path: Path,
) -> None:
    client = _FakeArcadeDBClient()
    store = make_retrieval_store(client, tmp_path)
    assert store.sparse_index is None
    store.store_message(
        user_identifier="alice", session_id="s1", role="user", content="zephyrion incident report"
    )

    channels, degraded = store._collect_retrieval_evidence(
        user_identifier="alice", query="zephyrion", candidate_limit=20
    )

    assert "bm25" in channels
    assert "bm25" not in degraded


def test_write_then_search_round_trips_lexical_hit_with_uninitialized_sparse_index(
    tmp_path: Path,
) -> None:
    """04-10 (ARC-06 gap closure), T-04-10-02: end-to-end proof that lexical
    retrieval is unaffected by retiring the write-side SQLite-FTS5 outbox.
    A SparseIndex is present (so `fusion_enabled` is True) but deliberately
    never `.initialize()`'d, mirroring a fresh deployment volume -- the real
    write path (store_memory_write.py, 04-10) must not touch it, and the real
    read path (store_search.py/store_evidence.py, already-correct since 04-07)
    must still find the memory via the native sparse-vector + Lucene channels
    alone.
    """
    client = _FakeArcadeDBClient()
    sparse = SparseIndex(tmp_path / "fts.sqlite3")  # deliberately never .initialize()'d
    store = make_retrieval_store(client, tmp_path, sparse_index=sparse)

    written = store.store_message(
        user_identifier="alice",
        session_id="s1",
        role="user",
        content="zephyrion incident report filed by the router team",
    )

    hits = store.search_memory(user_identifier="alice", query="zephyrion", limit=5)

    assert hits
    assert any(hit.id == written.id for hit in hits)


def test_fused_search_applies_adaptive_overfetch_multiplier_to_dense_channel(
    tmp_path: Path,
) -> None:
    client = _FakeArcadeDBClient()
    store = make_retrieval_store(client, tmp_path)
    store.store_message(user_identifier="alice", session_id="s1", role="user", content="alpha")

    store.search_memory(user_identifier="alice", query="alpha", limit=3, explain=True)

    dense_queries = [
        params
        for stmt, params in client.queries
        if "vectorNeighbors" in stmt and "Memory[embedding]" in stmt
    ]
    assert dense_queries
    candidate_limit = min(max(3 * 8, 40), 200)
    assert dense_queries[0]["k"] == candidate_limit


def test_fused_search_tenant_a_never_sees_tenant_b_candidates(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = make_retrieval_store(client, tmp_path)
    store.store_message(
        user_identifier="alice", session_id="s1", role="user", content="alice private router notes"
    )
    store.store_message(
        user_identifier="bob", session_id="s1", role="user", content="bob private router notes"
    )

    hits = store.search_memory(user_identifier="alice", query="router notes", limit=5)

    assert hits
    assert all(hit.user_identifier == "alice" for hit in hits)
    channels, _degraded = store._collect_retrieval_evidence(
        user_identifier="alice", query="router notes", candidate_limit=20
    )
    rows = store._memory_rows_for_ids(
        "alice",
        [evidence.source_memory_id for values in channels.values() for evidence in values],
    )
    assert all(row.get("user_identifier") == "alice" for row in rows.values())


# ============================================================================
# Task 2: entity/fact/community evidence traversal (D-05 surface, bound IN
# arrays, no vector_id)
# ============================================================================


def test_expand_entity_evidence_runs_two_hop_traversal_on_match_surface(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    script = {
        "Alice enjoys hiking": ("Alice", "person", "enjoys", "hiking", "activity"),
        "Bob mentions hiking": ("Bob", "person", "mentions", "hiking", "activity"),
    }
    store = make_retrieval_store(client, tmp_path, memory_extractor=_ScriptedExtractor(script))
    mem_alice = store.store_message(
        user_identifier="alice", session_id="s1", role="user", content="Alice enjoys hiking"
    )
    mem_bob = store.store_message(
        user_identifier="alice", session_id="s1", role="user", content="Bob mentions hiking"
    )
    bob_id = stable_id("ent", "alice", "person", "bob")

    evidence = store._expand_entity_evidence("alice", {bob_id: 1.0}, limit=10)

    by_memory: dict[str, list[int]] = {}
    for item in evidence:
        by_memory.setdefault(item.source_memory_id, []).append(item.hop)
    assert mem_bob.id in by_memory, "hop=1 direct SUBJECT_OF from Bob must be found"
    assert 1 in by_memory[mem_bob.id]
    assert mem_alice.id in by_memory, "hop=2 via the shared 'hiking' entity must be found"
    assert 2 in by_memory[mem_alice.id]
    assert all(item.evidence_kind == "fact" for item in evidence)
    assert all(item.metadata.get("entity_id") == bob_id for item in evidence)


def test_fact_sources_by_ids_binds_array_param_single_quote_safe(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = make_retrieval_store(client, tmp_path)
    tricky_id = "fact_o'brien"
    client._committed.append(
        {
            "_type": "Fact",
            "id": tricky_id,
            "user_identifier": "alice",
            "source_memory_id": "mem-1",
            "confidence": 0.8,
            "status": "active",
        }
    )

    sources = store._fact_sources_by_ids("alice", [tricky_id])

    assert sources == {tricky_id: "mem-1"}
    fact_queries = [
        (stmt, params) for stmt, params in client.queries if "FROM Fact" in stmt and "IN" in stmt
    ]
    assert fact_queries
    assert tricky_id not in fact_queries[0][0], "value must be bound, not interpolated"
    assert fact_queries[0][1]["fact_ids"] == [tricky_id]


def test_expand_entity_evidence_never_crosses_tenant_via_intermediate_hops(
    tmp_path: Path,
) -> None:
    """CR-01 regression: a cross-tenant `SUBJECT_OF`/`SUPPORTED_BY` edge
    planted directly (bypassing the normal write path -- simulating "the
    invariant that currently prevents this breaks") must never surface
    tenant B's fact/memory through tenant A's seed entity, at hop=1 OR
    hop=2 (the `.both()` intermediate-entity step)."""
    client = _FakeArcadeDBClient()
    store = make_retrieval_store(client, tmp_path)
    alice_entity = stable_id("ent", "alice", "person", "alice")
    bob_bridge_entity = stable_id("ent", "bob", "person", "bridge")
    client._committed.extend(
        [
            {
                "_type": "Entity",
                "id": alice_entity,
                "user_identifier": "alice",
                "status": "active",
            },
            # Cross-tenant intermediate entity (hop=2 `.both()` step) --
            # belongs to bob, not alice.
            {
                "_type": "Entity",
                "id": bob_bridge_entity,
                "user_identifier": "bob",
                "status": "active",
            },
            # Cross-tenant Fact/Memory -- belong to bob, reached only via
            # edges planted directly below (never through alice's own write
            # batch).
            {
                "_type": "Fact",
                "id": "fact-bob-direct",
                "user_identifier": "bob",
                "confidence": 1.0,
                "status": "active",
            },
            {
                "_type": "Memory",
                "id": "mem-bob-direct",
                "user_identifier": "bob",
                "status": "active",
            },
            {
                "_type": "Fact",
                "id": "fact-bob-two-hop",
                "user_identifier": "bob",
                "confidence": 1.0,
                "status": "active",
            },
            {
                "_type": "Memory",
                "id": "mem-bob-two-hop",
                "user_identifier": "bob",
                "status": "active",
            },
        ]
    )
    client._edges.extend(
        [
            # hop=1: alice's own entity directly SUBJECT_OF a bob-owned fact.
            ("SUBJECT_OF", alice_entity, "fact-bob-direct"),
            ("SUPPORTED_BY", "fact-bob-direct", "mem-bob-direct"),
            # hop=2: alice's entity bridges through a bob-owned intermediate
            # entity to reach another bob-owned fact/memory.
            ("MENTIONS", alice_entity, bob_bridge_entity),
            ("SUBJECT_OF", bob_bridge_entity, "fact-bob-two-hop"),
            ("SUPPORTED_BY", "fact-bob-two-hop", "mem-bob-two-hop"),
        ]
    )

    evidence = store._expand_entity_evidence("alice", {alice_entity: 1.0}, limit=10)

    assert evidence == [], (
        f"cross-tenant fact/memory leaked through an unscoped intermediate hop: {evidence!r}"
    )

    hits = store.search_memory(user_identifier="alice", query="anything", limit=5)
    assert all(hit.user_identifier == "alice" for hit in hits)


def test_dense_evidence_channels_order_by_native_score_with_no_vector_id_join(
    tmp_path: Path,
) -> None:
    client = _FakeArcadeDBClient()
    store = make_retrieval_store(client, tmp_path)
    client._committed.extend(
        [
            {
                "_type": "Fact",
                "id": "fact-near",
                "user_identifier": "alice",
                "source_memory_id": "mem-near",
                "status": "active",
                "embedding": [0.0, 0.0, 0.0],
            },
            {
                "_type": "Fact",
                "id": "fact-far",
                "user_identifier": "alice",
                "source_memory_id": "mem-far",
                "status": "active",
                "embedding": [10.0, 10.0, 10.0],
            },
        ]
    )

    evidence = store._fact_dense_evidence("alice", [0.0, 0.0, 0.0], limit=10)

    assert [item.source_memory_id for item in evidence] == ["mem-near", "mem-far"]
    fact_dense_queries = [stmt for stmt, _ in client.queries if "Fact[embedding]" in stmt]
    assert fact_dense_queries
    assert "vector_id" not in fact_dense_queries[0]


def test_evidence_traversal_and_lookups_are_tenant_scoped(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = make_retrieval_store(client, tmp_path)
    alice_entity = stable_id("ent", "alice", "person", "alice")
    bob_entity = stable_id("ent", "bob", "person", "bob")
    client._committed.extend(
        [
            {
                "_type": "Entity",
                "id": alice_entity,
                "user_identifier": "alice",
                "status": "active",
            },
            {"_type": "Entity", "id": bob_entity, "user_identifier": "bob", "status": "active"},
            {
                "_type": "Fact",
                "id": "fact-alice",
                "user_identifier": "alice",
                "confidence": 1.0,
                "status": "active",
            },
            {
                "_type": "Memory",
                "id": "mem-alice",
                "user_identifier": "alice",
                "status": "active",
            },
        ]
    )
    client._edges.extend(
        [
            ("SUBJECT_OF", alice_entity, "fact-alice"),
            ("SUPPORTED_BY", "fact-alice", "mem-alice"),
        ]
    )

    evidence = store._expand_entity_evidence(
        "alice", {alice_entity: 1.0, bob_entity: 1.0}, limit=10
    )

    assert {item.source_memory_id for item in evidence} == {"mem-alice"}
    assert all(item.metadata.get("entity_id") == alice_entity for item in evidence)


# ============================================================================
# Source-level acceptance-criteria grep gates
# ============================================================================


def test_store_search_and_evidence_contain_no_vector_id_or_helper_calls() -> None:
    for path in (_STORE_SEARCH_PATH, _STORE_EVIDENCE_PATH, _STORE_RETRIEVAL_QUERIES_PATH):
        source = path.read_text(encoding="utf-8")
        for forbidden in ("vector_id", "VECTOR SEARCH IN"):
            assert forbidden not in source, f"{path.name} still references {forbidden!r}"


def test_store_search_does_not_read_sqlite_sparse_index() -> None:
    source = _STORE_SEARCH_PATH.read_text(encoding="utf-8")
    assert "sparse_index" not in source


def test_store_evidence_has_no_string_built_or_list() -> None:
    source = _STORE_EVIDENCE_PATH.read_text(encoding="utf-8")
    assert not re.search(r'OR .*= "', source)


def test_store_search_and_evidence_under_loc_cap() -> None:
    for path in (_STORE_SEARCH_PATH, _STORE_EVIDENCE_PATH):
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        assert line_count < 600, f"{path.name} is {line_count} lines, over the 600-LOC cap"
