"""04-08: vector-projection + community-graph rebuild ported from TuringDB to
ArcadeDB (ARC-04/ARC-05/INFRA-03), D-07 versioned atomic-swap.

Every test runs against `_arcadedb_rebuild_fake.FakeArcadeDBClient`, a small
in-memory stand-in for `ArcadeDBClient` (same convention as
`tests/test_store_arcadedb_documents.py`'s fake, extended there with a
SET-clause interpreter that supports both bound-param assignment and
same-record field-to-field copies -- the atomic swap's `UPDATE Type SET
embedding = <staging_property>` shape -- plus `sqlscript()`
(BEGIN/LET/COMMIT) support for `_replace_community_graph`). No live ArcadeDB
container is required.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from _arcadedb_rebuild_fake import (
    FakeArcadeDBClient,
    all_rows,
    make_store,
    row,
    seed_edge,
    seed_vertex,
)
from _batch_memory_shared import CountingBatchEmbedder

from turing_agentmemory_mcp.entity_extraction import NoopEntityProcessor
from turing_agentmemory_mcp.governance import NoopAuditSink, NoopRedactor
from turing_agentmemory_mcp.observability import InMemorySpanRecorder
from turing_agentmemory_mcp.sparse_index import SparseIndex
from turing_agentmemory_mcp.store import TuringAgentMemory

_STORE_REBUILD_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp" / "store_rebuild.py"
)
_STORE_REBUILD_QUERIES_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "turing_agentmemory_mcp"
    / "store_rebuild_queries.py"
)
_STORE_PATH = Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp" / "store.py"


# -- Task 1, Test 1: builds a NEW versioned index, populates, swaps, drops --
# in that order --


def test_rebuild_stages_populates_swaps_then_drops_in_order(tmp_path: Path) -> None:
    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path, CountingBatchEmbedder())
    seed_vertex(
        client,
        "Memory",
        id="m1",
        user_identifier="alice",
        content="original content",
        embedding=[0.0, 0.0, 0.0],
        lexical_tokens=[],
        lexical_weights=[],
    )

    result = store.rebuild_vector_projection(user_identifier="alice")

    assert result["counts"]["memory"] == 1
    ddl_order = [entry for entry in client.schema_ddl if "Memory" in entry]
    create_index_at = next(
        index for index, entry in enumerate(ddl_order) if entry.startswith("CREATE INDEX")
    )
    drop_index_at = next(
        index for index, entry in enumerate(ddl_order) if entry.startswith("DROP INDEX")
    )
    assert create_index_at < drop_index_at, "staging index must be created before it is dropped"
    update_commands = [
        entry[0] for entry in client.commands if entry[0].startswith("UPDATE Memory")
    ]
    populate_index = next(
        i
        for i, s in enumerate(update_commands)
        if "embedding" not in s.split("WHERE")[0] or "_tenant_" in s
    )
    # The swap statement is the ONLY UPDATE that sets the bare `embedding` column.
    swap_index = next(
        i
        for i, s in enumerate(update_commands)
        if s.split("SET", 1)[1].split("WHERE")[0].strip().startswith("embedding =")
    )
    assert swap_index > populate_index, "populate (staging) must precede swap (live fields)"
    memory_row = row(client, "Memory", "m1")
    assert memory_row["embedding"] == CountingBatchEmbedder()._vector("original content")
    assert memory_row["lexical_tokens"], "lexical channel repopulated via shared sparse_encoder"


# -- Task 1: rebuild_vector_projection re-embeds EVERY active canonical kind
# (memory/document/entity/fact/community) from its own text property, each via
# _canonical_vector_records' bound-param ArcadeDB SELECT -- supersedes the
# retired TuringDB-shaped `test_rebuild_vector_projection_reembeds_each_active_
# canonical_kind`/`test_canonical_vector_records_use_active_document_chunk_text`
# (tests/test_batch_memory.py), which asserted `_ensure_vector_index`/
# `_memory_vector_id`/indexed CSV-vector-load overrides and Cypher `"c.id"`/
# `"c.text"` row keys -- all retired by this port (04-EXECUTION-STATE.md
# routing; see 04-08-SUMMARY.md for the deletion justification). --


def test_rebuild_reembeds_every_active_canonical_kind_from_its_own_text_property(
    tmp_path: Path,
) -> None:
    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path, CountingBatchEmbedder())
    seed_vertex(client, "Memory", id="m1", user_identifier="alice", content="episode text")
    seed_vertex(
        client,
        "Chunk",
        id="chunk1",
        document_id="doc1",
        user_identifier="alice",
        text="document text",
    )
    seed_vertex(client, "Entity", id="e1", user_identifier="alice", content="entity text")
    seed_vertex(client, "Fact", id="f1", user_identifier="alice", content="fact text")
    seed_vertex(client, "Community", id="c1", user_identifier="alice", content="community text")

    result = store.rebuild_vector_projection(user_identifier="alice")

    assert result["counts"] == {
        "memory": 1,
        "document": 1,
        "entity": 1,
        "fact": 1,
        "community": 1,
    }
    assert result["total"] == 5
    expected = {
        "Memory": ("m1", "episode text"),
        "Chunk": ("chunk1", "document text"),
        "Entity": ("e1", "entity text"),
        "Fact": ("f1", "fact text"),
        "Community": ("c1", "community text"),
    }
    for type_name, (record_id, text) in expected.items():
        found_row = row(client, type_name, record_id)
        assert found_row["embedding"] == CountingBatchEmbedder()._vector(text)


# -- Task 1, Test 2: a search issued mid-rebuild resolves the OLD version
# until the swap completes --


def test_live_embedding_unchanged_until_swap_completes(tmp_path: Path) -> None:
    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path, CountingBatchEmbedder())
    original_vector = [9.0, 9.0, 9.0]
    seed_vertex(
        client,
        "Memory",
        id="m1",
        user_identifier="alice",
        content="fresh content",
        embedding=original_vector,
        lexical_tokens=[1],
        lexical_weights=[1.0],
    )

    # Drive only the POPULATE phase directly (mirrors what rebuild_vector_projection
    # does before its swap statement runs) and assert the live field is untouched.
    store._ensure_staging_vector_schema("Memory", "scratch_embedding")
    store._write_many(
        [
            (
                "UPDATE Memory SET scratch_embedding = :embedding WHERE id = :id",
                {"id": "m1", "embedding": [1.0, 2.0, 3.0]},
            )
        ]
    )
    row_mid_rebuild = row(client, "Memory", "m1")
    assert row_mid_rebuild["embedding"] == original_vector, (
        "populate phase must never touch the live embedding field"
    )

    store.rebuild_vector_projection(user_identifier="alice")

    row_after_swap = row(client, "Memory", "m1")
    assert row_after_swap["embedding"] != original_vector, "swap must refresh the live field"


# -- Task 1, Test 3: running rebuild twice does not accumulate stale vectors --


def test_rebuild_twice_leaves_no_stale_scratch_schema_or_accumulation(tmp_path: Path) -> None:
    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path, CountingBatchEmbedder())
    seed_vertex(
        client,
        "Memory",
        id="m1",
        user_identifier="alice",
        content="round one",
        embedding=[0.0, 0.0, 0.0],
        lexical_tokens=[],
        lexical_weights=[],
    )

    store.rebuild_vector_projection(user_identifier="alice")
    store.rebuild_vector_projection(user_identifier="alice")

    memory_rows = [item for item in all_rows(client) if item.get("_type") == "Memory"]
    assert len(memory_rows) == 1, "vector count must equal live record count, not 2x"
    create_index_ddl = [
        entry
        for entry in client.schema_ddl
        if entry.startswith("CREATE INDEX") and "Memory" in entry
    ]
    drop_index_ddl = [entry for entry in client.schema_ddl if entry.startswith("DROP INDEX")]
    assert len(create_index_ddl) == len(drop_index_ddl) >= 2, (
        "every staged scratch index created across both rebuilds was also dropped"
    )


# -- Task 1, Test 4: vectors are written inline -- no CSV, no vector_id --


def test_rebuild_writes_no_csv_and_no_vector_id_helper(tmp_path: Path) -> None:
    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path, CountingBatchEmbedder())
    seed_vertex(
        client,
        "Entity",
        id="e1",
        user_identifier="alice",
        content="entity text",
        embedding=[0.0],
        lexical_tokens=[],
        lexical_weights=[],
    )

    store.rebuild_vector_projection(user_identifier="alice")

    for statement, _params, _session in client.commands:
        assert "LOAD VECTOR" not in statement
    entity_row = row(client, "Entity", "e1")
    assert "vector_id" not in entity_row


# -- Task 1, Test 5: rebuild is user_identifier-scoped --


def test_rebuild_is_tenant_scoped(tmp_path: Path) -> None:
    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path, CountingBatchEmbedder())
    alice_vector = [1.0, 1.0, 1.0]
    bob_vector = [2.0, 2.0, 2.0]
    seed_vertex(
        client,
        "Memory",
        id="m-alice",
        user_identifier="alice",
        content="alice content",
        embedding=alice_vector,
        lexical_tokens=[],
        lexical_weights=[],
    )
    seed_vertex(
        client,
        "Memory",
        id="m-bob",
        user_identifier="bob",
        content="bob content",
        embedding=bob_vector,
        lexical_tokens=[],
        lexical_weights=[],
    )

    store.rebuild_vector_projection(user_identifier="alice")

    bob_row = row(client, "Memory", "m-bob")
    assert bob_row["embedding"] == bob_vector, "tenant B's vectors must be untouched"
    alice_row = row(client, "Memory", "m-alice")
    assert alice_row["embedding"] != alice_vector


# -- Task 2, Test 1: _replace_community_graph is one sqlscript transaction --


def test_replace_community_graph_runs_as_one_sqlscript_transaction(tmp_path: Path) -> None:
    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path, CountingBatchEmbedder())
    seed_vertex(client, "Entity", id="a", user_identifier="alice", display_name="Alice")
    seed_vertex(client, "Entity", id="b", user_identifier="alice", display_name="Hiking")
    seed_edge(client, "MENTIONS", "m1", "a")
    seed_edge(client, "MENTIONS", "m1", "b")
    seed_vertex(client, "Memory", id="m1", user_identifier="alice", content="Alice loves hiking")
    seed_vertex(
        client,
        "Fact",
        id="f1",
        user_identifier="alice",
        subject_entity_id="a",
        predicate="prefers",
        object_entity_id="b",
        content="Alice prefers Hiking",
        confidence=0.9,
        observed_at="2026-07-10T10:00:00Z",
        source_memory_id="m1",
    )

    result = store.rebuild_communities(user_identifier="alice")

    assert result["community_count"] >= 1
    assert len(client.sqlscripts) == 1, "the whole community replace is ONE sqlscript call"


# -- Task 2, Test 2: community vectors inline, keyed on stable_id, no vector_id --


def test_community_vectors_inline_keyed_on_stable_id_no_vector_id(tmp_path: Path) -> None:
    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path, CountingBatchEmbedder())
    seed_vertex(client, "Entity", id="a", user_identifier="alice", display_name="Alice")
    seed_vertex(client, "Entity", id="b", user_identifier="alice", display_name="Hiking")
    seed_edge(client, "MENTIONS", "m1", "a")
    seed_edge(client, "MENTIONS", "m1", "b")
    seed_vertex(client, "Memory", id="m1", user_identifier="alice", content="Alice loves hiking")
    seed_vertex(
        client,
        "Fact",
        id="f1",
        user_identifier="alice",
        subject_entity_id="a",
        predicate="prefers",
        object_entity_id="b",
        content="Alice prefers Hiking",
        confidence=0.9,
        observed_at="2026-07-10T10:00:00Z",
        source_memory_id="m1",
    )

    result = store.rebuild_communities(user_identifier="alice")

    community_rows = [item for item in all_rows(client) if item.get("_type") == "Community"]
    assert community_rows
    for community_row in community_rows:
        assert community_row["id"] in result["community_ids"]
        assert isinstance(community_row["embedding"], list) and community_row["embedding"]
        assert community_row["lexical_tokens"], (
            "both lexical channels populated via shared sparse_encoder"
        )
        assert "vector_id" not in community_row


# -- Task 2, Test 3: replace removes prior communities (no orphan
# accumulation) and is user_identifier-scoped --


def test_replace_marks_prior_communities_stale_and_is_tenant_scoped(tmp_path: Path) -> None:
    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path, CountingBatchEmbedder())
    seed_vertex(
        client, "Community", id="stale-community", user_identifier="alice", content="old grouping"
    )
    seed_vertex(
        client,
        "Community",
        id="bob-community",
        user_identifier="bob",
        content="bob's grouping",
    )
    seed_vertex(client, "Entity", id="a", user_identifier="alice", display_name="Alice")
    seed_vertex(client, "Entity", id="b", user_identifier="alice", display_name="Hiking")
    seed_edge(client, "MENTIONS", "m1", "a")
    seed_edge(client, "MENTIONS", "m1", "b")
    seed_vertex(client, "Memory", id="m1", user_identifier="alice", content="Alice loves hiking")
    seed_vertex(
        client,
        "Fact",
        id="f1",
        user_identifier="alice",
        subject_entity_id="a",
        predicate="prefers",
        object_entity_id="b",
        content="Alice prefers Hiking",
        confidence=0.9,
        observed_at="2026-07-10T10:00:00Z",
        source_memory_id="m1",
    )

    store.rebuild_communities(user_identifier="alice")

    stale_row = row(client, "Community", "stale-community")
    assert stale_row["status"] == "stale", "prior community replaced, no orphan accumulation"
    bob_row = row(client, "Community", "bob-community")
    assert bob_row["status"] == "active", "tenant B's community graph is untouched"


# -- source-level acceptance-criteria grep gates --


def test_rebuild_files_contain_no_vector_id_or_load_vector() -> None:
    for path_ in (_STORE_REBUILD_PATH, _STORE_REBUILD_QUERIES_PATH):
        source = path_.read_text(encoding="utf-8")
        for forbidden in (
            "vector_id",
            "_memory_vector_id",
            "_community_vector_id",
            "LOAD VECTOR",
            "_load_vectors",
        ):
            assert forbidden not in source, f"{path_.name} still references {forbidden!r}"


# -- 04-10 gap closure (ARC-06): the write-side legacy SQLite-FTS5 outbox is
# retired from rebuild_communities, and its dedicated rebuild mixin is deleted
# entirely --


def test_community_rebuild_succeeds_with_uninitialized_sparse_index(tmp_path: Path) -> None:
    """T-04-10-01: rebuild_communities must not touch the legacy outbox at
    all -- a SparseIndex present but never `.initialize()`'d (as on a fresh
    deployment volume) has no outbox schema and would raise
    SparseSchemaMismatch on first touch if any prepare/commit/replay/discard
    call remained."""
    client = FakeArcadeDBClient()
    sparse = SparseIndex(tmp_path / "communities.sqlite3")  # deliberately never .initialize()'d
    store = TuringAgentMemory(
        client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=CountingBatchEmbedder(),
        reranker=None,
        entity_processor=NoopEntityProcessor(),
        redactor=NoopRedactor(),
        audit_sink=NoopAuditSink(),
        observer=InMemorySpanRecorder(),
        sparse_index=sparse,
    )
    assert store.fusion_enabled is True
    seed_vertex(client, "Entity", id="a", user_identifier="alice", display_name="Alice")
    seed_vertex(client, "Entity", id="b", user_identifier="alice", display_name="Hiking")
    seed_edge(client, "MENTIONS", "m1", "a")
    seed_edge(client, "MENTIONS", "m1", "b")
    seed_vertex(client, "Memory", id="m1", user_identifier="alice", content="Alice loves hiking")
    seed_vertex(
        client,
        "Fact",
        id="f1",
        user_identifier="alice",
        subject_entity_id="a",
        predicate="prefers",
        object_entity_id="b",
        content="Alice prefers Hiking",
        confidence=0.9,
        observed_at="2026-07-10T10:00:00Z",
        source_memory_id="m1",
    )

    result = store.rebuild_communities(user_identifier="alice")

    assert result["community_count"] >= 1
    community_rows = [item for item in all_rows(client) if item.get("_type") == "Community"]
    assert community_rows
    assert community_rows[0]["lexical_tokens"], (
        "native lexical channel unaffected by outbox removal"
    )


def test_store_rebuild_sparse_module_deleted_and_mixin_removed_from_mro() -> None:
    rebuild_sparse_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "turing_agentmemory_mcp"
        / "store_rebuild_sparse.py"
    )
    assert not rebuild_sparse_path.exists()
    store_source = _STORE_PATH.read_text(encoding="utf-8")
    assert "_RebuildSparseMixin" not in store_source
    assert "store_rebuild_sparse" not in store_source


def test_rebuild_file_contains_no_sparse_outbox_calls() -> None:
    source = _STORE_REBUILD_PATH.read_text(encoding="utf-8")
    for forbidden in (
        "sparse_index.prepare(",
        "sparse_index.commit_batch(",
        "sparse_index.replay(",
        "sparse_index.discard_prepared(",
    ):
        assert forbidden not in source, f"store_rebuild.py still references {forbidden!r}"
