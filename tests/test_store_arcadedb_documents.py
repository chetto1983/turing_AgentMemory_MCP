"""04-06: document ingest/chunking/search paths ported from TuringDB to ArcadeDB
(ARC-04/05/06, PERF-01).

Fixtures (`_FakeArcadeDBClient`/`make_document_store`/`committed_by_type`/
`edge_commands`) live in `_documents_arcadedb_shared.py` (HI-01, 600-LOC cap
split, mirrors `_retrieval_arcadedb_shared.py`'s convention) -- no live
ArcadeDB container is required.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from _batch_memory_shared import CountingBatchEmbedder
from _documents_arcadedb_shared import (
    _FakeArcadeDBClient,
    committed_by_type,
    edge_commands,
    make_document_store,
)

from turing_agentmemory_mcp.ids import stable_id
from turing_agentmemory_mcp.store_documents_queries import escape_lucene_query

_STORE_DOCUMENTS_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp" / "store_documents.py"
)
_STORE_CHUNKING_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp" / "store_chunking.py"
)
_STORE_DOCUMENTS_QUERIES_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "turing_agentmemory_mcp"
    / "store_documents_queries.py"
)


# -- Task 1, Test 1: ingest CREATEs one Document + N Chunk vertices + N
# HAS_CHUNK + (N-1) NEXT_CHUNK edges in ONE managed transaction --


def test_ingest_document_creates_document_and_chunks_in_one_managed_transaction(
    tmp_path: Path,
) -> None:
    client = _FakeArcadeDBClient()
    store = make_document_store(client, tmp_path, CountingBatchEmbedder())
    store._ensure_user("alice")  # excluded from the transaction-count assertion below
    client.begin_calls = 0
    client.commit_calls = 0

    document = store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-1",
        title="Runbook",
        text="first chunk body\nsecond chunk body\nthird chunk body",
        chunk_chars=20,
    )

    assert document.chunk_count == 3
    assert client.begin_calls == 1, "the whole document+chunk+edge batch is ONE transaction"
    assert client.commit_calls == 1
    assert len(committed_by_type(client, "Document")) == 1
    assert len(committed_by_type(client, "Chunk")) == 3
    assert len(edge_commands(client, "HAS_DOCUMENT")) == 1
    assert len(edge_commands(client, "HAS_CHUNK")) == 3
    assert len(edge_commands(client, "NEXT_CHUNK")) == 2


# -- Task 1, Test 2: each Chunk id is a stable_id, embedding inline, no
# vector_id property --


def test_chunk_id_is_stable_id_with_inline_embedding_and_no_vector_id(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = make_document_store(client, tmp_path, CountingBatchEmbedder())

    store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-1",
        title="Runbook",
        text="only chunk body",
        chunk_chars=1000,
    )

    chunks = committed_by_type(client, "Chunk")
    assert len(chunks) == 1
    expected_id = stable_id("chunk", "alice", "doc-1", "1")
    assert chunks[0]["id"] == expected_id
    assert isinstance(chunks[0]["embedding"], list) and chunks[0]["embedding"]
    assert "vector_id" not in chunks[0]
    assert chunks[0]["lexical_tokens"], "expected at least one lexical token bucket"


# -- Task 1, Test 3: re-ingesting the same title+text is deduped by hash --


def test_reingesting_same_title_and_text_dedupes_by_hash(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = make_document_store(client, tmp_path, CountingBatchEmbedder())

    first = store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-1",
        title="Runbook",
        text="stable content",
        chunk_chars=1000,
    )
    second = store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-1",
        title="Runbook",
        text="stable content",
        chunk_chars=1000,
    )

    assert first.document_id == second.document_id
    assert first.chunk_count == second.chunk_count
    assert len(committed_by_type(client, "Document")) == 1
    document_creates = [
        entry for entry in client.commands if entry[0].startswith("CREATE VERTEX Document")
    ]
    assert len(document_creates) == 1


# 04-09 regression (Rule 1 bug, found live via the ArcadeDB E2E capture):
# reindex_document_text used to call the soft `delete_document()` (an UPDATE
# setting status='deleted') before recreating a Document/Chunk with the SAME
# id -- but a soft-deleted row still occupies its slot in the UNIQUE `id`
# index, so the recreate raised a live DuplicatedKeyException. Fixed to hard
# DELETE the old Document/Chunk rows (confirmed live: ArcadeDB's
# `DELETE FROM <VertexType>` cascades edge removal too) before recreating.
def test_reindex_document_text_hard_deletes_old_rows_before_recreating_same_id(
    tmp_path: Path,
) -> None:
    client = _FakeArcadeDBClient()
    store = make_document_store(client, tmp_path, CountingBatchEmbedder())
    store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-1",
        title="Runbook v1",
        text="original safety procedure content",
        chunk_chars=1000,
    )

    reindexed = store.reindex_document_text(
        user_identifier="alice",
        document_id="doc-1",
        title="Runbook v2",
        text="reindexed safety procedure content",
        chunk_chars=1000,
    )

    hard_deletes = [entry[0] for entry in client.commands if entry[0].startswith("DELETE FROM")]
    assert any("DELETE FROM Document" in stmt for stmt in hard_deletes)
    assert any("DELETE FROM Chunk" in stmt for stmt in hard_deletes)
    soft_deletes = [
        entry[0]
        for entry in client.commands
        if entry[0].startswith("UPDATE") and "status = 'deleted'" in entry[0]
    ]
    assert not soft_deletes, "reindex must not use the soft delete_document() path"
    assert reindexed.document_id == "doc-1"
    assert len(committed_by_type(client, "Document")) == 1

    fetched = store.get_document(user_identifier="alice", document_id="doc-1")
    assert fetched is not None
    assert fetched.title == "Runbook v2"


# -- Task 1, Test 4: _chunk_context(chunk_id) resolves NEXT_CHUNK neighbors by
# chunk_id traversal --


def test_chunk_context_resolves_next_chunk_neighbor_by_chunk_id(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = make_document_store(client, tmp_path, CountingBatchEmbedder())

    store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-1",
        title="Runbook",
        text="first chunk body\nsecond chunk body",
        chunk_chars=20,
    )
    first_chunk_id = stable_id("chunk", "alice", "doc-1", "1")
    second_chunk_id = stable_id("chunk", "alice", "doc-1", "2")

    context = store._chunk_context(first_chunk_id, user_identifier="alice")

    assert len(context) == 1
    assert context[0]["chunk_id"] == second_chunk_id
    assert context[0]["locator"] == "chunk=2"
    assert context[0]["text"] == "second chunk body"


# HI-01 regression: chunk_context_statement had no user_identifier filter at
# all -- a cross-tenant NEXT_CHUNK edge planted directly (bypassing the
# normal write path) must never surface another tenant's chunk text/locator.
def test_chunk_context_never_crosses_tenant_via_next_chunk_edge(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = make_document_store(client, tmp_path, CountingBatchEmbedder())
    store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-1",
        title="Runbook",
        text="alice only chunk body",
        chunk_chars=1000,
    )
    alice_chunk_id = stable_id("chunk", "alice", "doc-1", "1")
    bob_chunk_id = stable_id("chunk", "bob", "doc-1", "1")
    client._committed.append(
        {
            "_type": "Chunk",
            "id": bob_chunk_id,
            "document_id": "doc-1",
            "user_identifier": "bob",
            "status": "active",
            "locator": "chunk=1",
            "text": "bob private chunk body",
        }
    )
    # Cross-tenant edge planted directly, simulating "the invariant that
    # currently prevents this breaks" (same pattern as CR-01's regression).
    client._edges.append(("NEXT_CHUNK", alice_chunk_id, bob_chunk_id))

    context = store._chunk_context(alice_chunk_id, user_identifier="alice")

    assert context == [], f"cross-tenant chunk leaked through NEXT_CHUNK: {context!r}"


# -- Task 1, Test 5: fail-closed on empty user_identifier; tenant-scoped reads --


def test_ingest_with_empty_user_identifier_raises_value_error(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = make_document_store(client, tmp_path, CountingBatchEmbedder())

    try:
        store.ingest_document_text(user_identifier="", title="T", text="body")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for empty user_identifier")


def test_tenant_scoped_get_document_never_returns_other_tenants_document(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = make_document_store(client, tmp_path, CountingBatchEmbedder())

    store.ingest_document_text(
        user_identifier="alice", document_id="doc-1", title="Secret", text="alice's secret body"
    )

    assert store.get_document(user_identifier="bob", document_id="doc-1") is None


# -- Task 2, Test 1: vector search returns DocumentHit citations ordered by
# native HNSW score, no vector_id join --


def test_document_search_returns_hits_ordered_by_native_vector_score(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = make_document_store(client, tmp_path, CountingBatchEmbedder())
    store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-a",
        title="A",
        text="aaaaaaaaaaaaaaaaaaaa",  # length 20, matches the query's embedding
        chunk_chars=1000,
    )
    store.ingest_document_text(
        user_identifier="alice", document_id="doc-b", title="B", text="bbbbb", chunk_chars=1000
    )

    hits = store.search_documents(user_identifier="alice", query="xxxxxxxxxxxxxxxxxxxx", limit=5)

    assert hits
    assert hits[0].document_id == "doc-a"
    assert hits[0].chunk_id == stable_id("chunk", "alice", "doc-a", "1")
    assert hits[0].text == "aaaaaaaaaaaaaaaaaaaa"
    assert hits[0].score > 0.0


# -- Task 2, Test 2: adaptive over-fetch (D-03) -- the vector channel's k is
# max(limit*4, limit), not the raw limit --


def test_document_search_applies_adaptive_overfetch_multiplier(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = make_document_store(client, tmp_path, CountingBatchEmbedder())
    store.ingest_document_text(
        user_identifier="alice", document_id="doc-a", title="A", text="alpha content chunk"
    )

    store.search_documents(user_identifier="alice", query="alpha", limit=3)

    vector_queries = [
        (stmt, params) for stmt, params in client.queries if "vectorNeighbors" in stmt
    ]
    assert vector_queries
    assert vector_queries[0][1]["k"] == max(3 * 4, 3)


# -- Task 2, Test 3: the full-text channel matches an exact keyword query via
# native Lucene, with the query string escaped first --


def test_document_search_matches_via_native_lucene_full_text(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = make_document_store(client, tmp_path, CountingBatchEmbedder())
    store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-a",
        title="A",
        text="the zephyrion incident report",
    )

    raw_query = "what is zephyrion?"
    hits = store.search_documents(user_identifier="alice", query=raw_query, limit=5)

    assert any(hit.document_id == "doc-a" for hit in hits)
    lucene_queries = [(stmt, params) for stmt, params in client.queries if "SEARCH_INDEX" in stmt]
    assert lucene_queries
    assert lucene_queries[0][1]["q"] == escape_lucene_query(raw_query)
    assert "\\?" in str(lucene_queries[0][1]["q"])


# -- Task 2, Test 4: tenant scoping -- a tenant-A query never returns
# tenant-B chunks --


def test_document_search_tenant_scoped_never_returns_other_tenants_chunks(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = make_document_store(client, tmp_path, CountingBatchEmbedder())
    store.ingest_document_text(
        user_identifier="alice", document_id="doc-a", title="A", text="alice private content"
    )

    hits = store.search_documents(user_identifier="bob", query="alice private content", limit=5)

    assert hits == []


# -- source-level acceptance-criteria grep gates --


def test_document_files_contain_no_vector_id_or_helper_calls() -> None:
    for path in (_STORE_DOCUMENTS_PATH, _STORE_CHUNKING_PATH, _STORE_DOCUMENTS_QUERIES_PATH):
        source = path.read_text(encoding="utf-8")
        for forbidden in ("vector_id", "_document_vector_id"):
            assert forbidden not in source, f"{path.name} still references {forbidden!r}"
