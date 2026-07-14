from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from _batch_memory_shared import (
    CountingBatchEmbedder,
    RecordingMemoryExtractor,
    RecordingMemoryStore,
)

from turing_agentmemory_mcp.sparse_index import SparseIndex


def test_store_messages_projects_temporal_graph_atomically_before_vector_publication(
    tmp_path: Path,
) -> None:
    embedder = CountingBatchEmbedder()
    extractor = RecordingMemoryExtractor()
    store = RecordingMemoryStore(tmp_path, embedder, extractor)

    items = store.store_messages(
        user_identifier="alice",
        messages=[
            {
                "memory_id": "episode-1",
                "session_id": "session-1",
                "role": "user",
                "content": "Alice likes hiking.",
                "source": "locomo",
                "tags": ["benchmark"],
                "metadata": {"conversation_id": "conv-1"},
                "expires_at": "2027-01-01T00:00:00Z",
            }
        ],
    )

    assert [item.id for item in items] == ["episode-1"]
    assert extractor.calls == [["Alice likes hiking."]]
    # ArcadeDB (04-05): one bound-param statement per vertex/edge instead of a
    # single combined Cypher literal -- 1 Memory + 1 HAS_MEMORY edge + 2 Entity
    # + 1 Fact + (2 MENTIONS + SUBJECT_OF + OBJECT_OF + SUPPORTED_BY + a
    # dynamic PREFERS edge type-declare + the PREFERS edge itself) = 12.
    assert len(store.write_queries) == 12
    creates_by_type = {
        record_type: [
            params
            for query, params in zip(store.write_queries, store.write_params, strict=True)
            if query.startswith(f"CREATE VERTEX {record_type}") and params is not None
        ]
        for record_type in ("Memory", "Entity", "Fact")
    }
    assert len(creates_by_type["Memory"]) == 1
    assert len(creates_by_type["Entity"]) == 2
    assert len(creates_by_type["Fact"]) == 1
    edge_queries = [query for query in store.write_queries if query.startswith("CREATE EDGE ")]
    assert sum(query.startswith("CREATE EDGE MENTIONS ") for query in edge_queries) == 2
    assert any(query.startswith("CREATE EDGE SUBJECT_OF ") for query in edge_queries)
    assert any(query.startswith("CREATE EDGE OBJECT_OF ") for query in edge_queries)
    assert any(query.startswith("CREATE EDGE SUPPORTED_BY ") for query in edge_queries)
    assert any(query.startswith("CREATE EDGE PREFERS ") for query in edge_queries)
    assert "CREATE EDGE TYPE PREFERS IF NOT EXISTS" in store.write_queries
    fact_params = creates_by_type["Fact"][0]
    assert fact_params["source_memory_id"] == "episode-1"
    assert fact_params["session_id"] == "session-1"
    assert fact_params["speaker"] == "user"
    assert fact_params["source"] == "locomo"
    assert fact_params["schema_version"] == "memory-v1"
    assert fact_params["model"] == "test-gliner2"
    assert embedder.embed_many_calls == [
        ["Alice likes hiking.", "Alice (person)", "hiking (activity)", "Alice prefers hiking"]
    ]
    # ARC-05: no separate vector-load step remains -- the dense embedding is
    # an inline property on each vertex's own CREATE statement.
    assert store.vector_loads == []
    assert all("embedding" in params for params in creates_by_type["Memory"])
    assert all("embedding" in params for params in creates_by_type["Entity"])
    assert all("embedding" in params for params in creates_by_type["Fact"])


def test_store_messages_deduplicates_entities_across_episode_batch(tmp_path: Path) -> None:
    embedder = CountingBatchEmbedder()
    extractor = RecordingMemoryExtractor()
    store = RecordingMemoryStore(tmp_path, embedder, extractor)

    store.store_messages(
        user_identifier="alice",
        messages=[
            {
                "memory_id": "e1",
                "session_id": "s1",
                "role": "user",
                "content": "Alice likes hiking.",
            },
            {
                "memory_id": "e2",
                "session_id": "s1",
                "role": "user",
                "content": "Alice enjoys hiking.",
            },
        ],
    )

    entity_creates = [q for q in store.write_queries if q.startswith("CREATE VERTEX Entity")]
    fact_creates = [q for q in store.write_queries if q.startswith("CREATE VERTEX Fact")]
    assert len(entity_creates) == 2  # deduplicated across the whole episode batch
    assert len(fact_creates) == 2  # one fact per episode (not deduplicated)
    assert embedder.embed_many_calls[0].count("Alice (person)") == 1
    assert embedder.embed_many_calls[0].count("hiking (activity)") == 1


def test_store_messages_memory_extraction_failure_prevents_every_write_and_embedding(
    tmp_path: Path,
) -> None:
    embedder = CountingBatchEmbedder()
    extractor = RecordingMemoryExtractor(fail=True)
    store = RecordingMemoryStore(tmp_path, embedder, extractor)

    try:
        store.store_messages(
            user_identifier="alice",
            messages=[
                {
                    "memory_id": "e1",
                    "session_id": "s1",
                    "role": "user",
                    "content": "Alice likes hiking.",
                }
            ],
        )
    except RuntimeError as exc:
        assert "memory extraction unavailable" in str(exc)
    else:
        raise AssertionError("expected mandatory extraction failure")

    assert store.write_queries == []
    assert store.vector_loads == []
    assert embedder.embed_many_calls == []


def test_store_messages_replay_skips_temporal_extraction_and_vectors(tmp_path: Path) -> None:
    embedder = CountingBatchEmbedder()
    extractor = RecordingMemoryExtractor()
    store = RecordingMemoryStore(tmp_path, embedder, extractor)
    messages = [
        {"memory_id": "e1", "session_id": "s1", "role": "user", "content": "Alice likes hiking."}
    ]

    first = store.store_messages(user_identifier="alice", messages=messages)
    second = store.store_messages(user_identifier="alice", messages=messages)

    assert second == first
    assert extractor.calls == [["Alice likes hiking."]]
    assert len(store.write_queries) == 12  # 1 Memory+edge + 2 Entity + 1 Fact + 6 edges + 1 declare
    assert len(embedder.embed_many_calls) == 1


def test_store_message_uses_same_temporal_transaction_as_batch(tmp_path: Path) -> None:
    embedder = CountingBatchEmbedder()
    extractor = RecordingMemoryExtractor()
    store = RecordingMemoryStore(tmp_path, embedder, extractor)

    item = store.store_message(
        user_identifier="alice",
        memory_id="single-episode",
        session_id="s1",
        role="user",
        content="Alice likes hiking.",
    )

    assert item.id == "single-episode"
    assert extractor.calls == [["Alice likes hiking."]]
    assert len(store.write_queries) == 12
    assert any(q.startswith("CREATE VERTEX Fact") for q in store.write_queries)
    assert any(q.startswith("CREATE EDGE PREFERS ") for q in store.write_queries)


def test_temporal_episode_id_cannot_be_reused_for_different_content(tmp_path: Path) -> None:
    embedder = CountingBatchEmbedder()
    extractor = RecordingMemoryExtractor()
    store = RecordingMemoryStore(tmp_path, embedder, extractor)
    store.store_messages(
        user_identifier="alice",
        messages=[
            {
                "memory_id": "e1",
                "session_id": "s1",
                "role": "user",
                "content": "Alice likes hiking.",
            }
        ],
    )

    try:
        store.store_messages(
            user_identifier="alice",
            messages=[
                {
                    "memory_id": "e1",
                    "session_id": "s1",
                    "role": "user",
                    "content": "Alice avoids hiking.",
                }
            ],
        )
    except ValueError as exc:
        assert "immutable temporal episode" in str(exc)
    else:
        raise AssertionError("expected immutable episode rejection")

    assert extractor.calls == [["Alice likes hiking."]]
    # Rejected before `_create_memories_batch` ever runs -- no new statements
    # are added beyond the first (successful) store_messages call's 12.
    assert len(store.write_queries) == 12


def test_temporal_graph_write_failure_publishes_no_vectors(tmp_path: Path) -> None:
    class FailingWriteStore(RecordingMemoryStore):
        def _write_many(self, statements: list[object]) -> None:
            raise RuntimeError("graph commit failed")

    embedder = CountingBatchEmbedder()
    store = FailingWriteStore(tmp_path, embedder, RecordingMemoryExtractor())

    try:
        store.store_messages(
            user_identifier="alice",
            messages=[
                {
                    "memory_id": "e1",
                    "session_id": "s1",
                    "role": "user",
                    "content": "Alice likes hiking.",
                }
            ],
        )
    except RuntimeError as exc:
        assert "graph commit failed" in str(exc)
    else:
        raise AssertionError("expected graph write failure")

    # The whole memory+entity+fact+edge batch is ONE managed transaction
    # (D-08) -- a failure there publishes nothing at all, not a partial write.
    assert store.write_queries == []
    assert store.vector_loads == []


# ARC-06 (gap closure, 04-10): store_messages/update_memory/delete_memory must
# never touch the legacy SQLite-FTS5 sparse-index outbox
# (prepare/commit_batch/replay/discard_prepared) -- the native
# lexical_tokens/lexical_weights channel already carries lexical retrieval
# unconditionally (04-05), and store_evidence.py's bm25 channel (04-07)
# reads only ArcadeDB's native sparse-vector + Lucene channels, never
# sparse_index. On a fresh deployment volume (store_core.py's bootstrap no
# longer calls `sparse_index.initialize()`, 04-04) the outbox file has no
# schema, so any surviving outbox touch raises SparseSchemaMismatch --
# these tests construct a SparseIndex that is deliberately never
# `.initialize()`'d to prove no such touch remains (T-04-10-01).


def test_store_messages_succeeds_with_uninitialized_sparse_index_and_populates_lexical_channels(
    tmp_path: Path,
) -> None:
    sparse = SparseIndex(tmp_path / "fts.sqlite3")  # deliberately never .initialize()'d
    store = RecordingMemoryStore(
        tmp_path,
        CountingBatchEmbedder(),
        RecordingMemoryExtractor(),
        sparse,
    )
    assert store.fusion_enabled is True

    items = store.store_messages(
        user_identifier="alice",
        messages=[
            {
                "memory_id": "e1",
                "session_id": "s1",
                "role": "user",
                "content": "Alice likes hiking.",
            }
        ],
    )

    assert [item.id for item in items] == ["e1"]
    memory_params = [
        params
        for query, params in zip(store.write_queries, store.write_params, strict=True)
        if query.startswith("CREATE VERTEX Memory") and params is not None
    ]
    assert len(memory_params) == 1
    assert memory_params[0]["lexical_tokens"], "native lexical channel unaffected by outbox removal"
    assert memory_params[0]["lexical_weights"]


def test_update_and_delete_memory_succeed_with_uninitialized_sparse_index(
    tmp_path: Path,
) -> None:
    sparse = SparseIndex(tmp_path / "fts.sqlite3")  # deliberately never .initialize()'d
    store = RecordingMemoryStore(
        tmp_path,
        CountingBatchEmbedder(),
        None,
        sparse,
    )
    item = store.add_preference(user_identifier="alice", category="hobby", preference="hiking")
    store._fact_ids_for_memory = types.MethodType(  # type: ignore[method-assign]
        lambda self, user_identifier, memory_id: [],
        store,
    )

    updated = store.update_memory(
        user_identifier="alice", memory_id=item.id, content="hobby: trail running."
    )
    assert updated.content == "hobby: trail running."

    result = store.delete_memory(user_identifier="alice", memory_id=item.id)
    assert result["deleted"] is True


def test_temporal_update_rejects_raw_episode_mutation(tmp_path: Path) -> None:
    store = RecordingMemoryStore(
        tmp_path,
        CountingBatchEmbedder(),
        RecordingMemoryExtractor(),
    )
    store.store_messages(
        user_identifier="alice",
        messages=[
            {
                "memory_id": "e1",
                "session_id": "s1",
                "role": "user",
                "content": "Alice likes hiking.",
            }
        ],
    )

    with pytest.raises(ValueError, match="immutable temporal episode"):
        store.update_memory(
            user_identifier="alice",
            memory_id="e1",
            content="Alice avoids hiking.",
        )

    # Rejected before any UPDATE statement is built -- no new write beyond
    # the initial store_messages call's 12 statements.
    assert len(store.write_queries) == 12


# `test_delete_removes_episode_and_supported_facts_from_sparse_projection` was
# deleted here (04-10, ARC-06 gap closure): it asserted `delete_memory`
# staged/committed/replayed a legacy SQLite-FTS5 outbox mutation -- exactly
# the behavior retired by this plan. Superseded by
# `test_update_and_delete_memory_succeed_with_uninitialized_sparse_index`
# above, which proves `delete_memory` succeeds with no outbox touch at all.
