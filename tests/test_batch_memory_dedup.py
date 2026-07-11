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
    assert len(store.write_queries) == 1
    query = store.write_queries[0]
    assert ":Memory" in query
    assert query.count(":Entity {") == 2
    assert query.count(":Fact {") == 1
    assert ":MENTIONS" in query
    assert ":SUBJECT_OF" in query
    assert ":OBJECT_OF" in query
    assert ":SUPPORTED_BY" in query
    assert ":PREFERS" in query
    assert 'source_memory_id: "episode-1"' in query
    assert 'session_id: "session-1"' in query
    assert 'speaker: "user"' in query
    assert 'source: "locomo"' in query
    assert 'schema_version: "memory-v1"' in query
    assert 'model: "test-gliner2"' in query
    assert embedder.embed_many_calls == [
        ["Alice likes hiking.", "Alice (person)", "hiking (activity)", "Alice prefers hiking"]
    ]
    assert [name for name, _ in store.indexed_vector_loads] == [
        store._tenant_vector_index(store.memory_index, "alice"),
        store._tenant_vector_index(store.entity_index, "alice"),
        store._tenant_vector_index(store.fact_index, "alice"),
    ]


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

    query = store.write_queries[0]
    assert query.count(":Entity {") == 2
    assert query.count(":Fact {") == 2
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
    assert len(store.write_queries) == 1
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
    assert len(store.write_queries) == 1
    assert ":Fact {" in store.write_queries[0]
    assert ":PREFERS" in store.write_queries[0]


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
    assert len(store.write_queries) == 1


def test_temporal_graph_write_failure_publishes_no_vectors(tmp_path: Path) -> None:
    class FailingWriteStore(RecordingMemoryStore):
        def _write(self, query: str) -> None:
            self.write_queries.append(query)
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

    assert len(store.write_queries) == 1
    assert store.vector_loads == []


def test_temporal_store_projects_episode_entities_and_fact_to_sparse_index(
    tmp_path: Path,
) -> None:
    sparse = SparseIndex(tmp_path / "fts.sqlite3")
    sparse.initialize()
    store = RecordingMemoryStore(
        tmp_path,
        CountingBatchEmbedder(),
        RecordingMemoryExtractor(),
        sparse,
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

    hits = sparse.search(user_identifier="alice", query="Alice hiking", limit=20)
    assert {hit.kind for hit in hits} == {"episode", "entity", "fact"}
    assert {hit.source_id for hit in hits} >= {"e1"}
    assert sparse.status()["document_count"] == 4
    assert sparse.status()["pending_count"] == 0


def test_graph_failure_discards_prepared_sparse_projection(tmp_path: Path) -> None:
    class FailingWriteStore(RecordingMemoryStore):
        def _write(self, query: str) -> None:
            raise RuntimeError("graph commit failed")

    sparse = SparseIndex(tmp_path / "fts.sqlite3")
    sparse.initialize()
    store = FailingWriteStore(
        tmp_path,
        CountingBatchEmbedder(),
        RecordingMemoryExtractor(),
        sparse,
    )

    with pytest.raises(RuntimeError, match="graph commit failed"):
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

    assert sparse.status()["document_count"] == 0
    assert sparse.status()["pending_count"] == 0


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

    assert len(store.write_queries) == 1


def test_delete_removes_episode_and_supported_facts_from_sparse_projection(
    tmp_path: Path,
) -> None:
    sparse = SparseIndex(tmp_path / "fts.sqlite3")
    sparse.initialize()
    store = RecordingMemoryStore(
        tmp_path,
        CountingBatchEmbedder(),
        RecordingMemoryExtractor(),
        sparse,
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
    fact_ids = [
        hit.source_id
        for hit in sparse.search(
            user_identifier="alice",
            query="hiking",
            kinds=["fact"],
            limit=10,
        )
    ]
    store._fact_ids_for_memory = types.MethodType(  # type: ignore[method-assign]
        lambda self, user_identifier, memory_id: fact_ids,
        store,
    )

    result = store.delete_memory(user_identifier="alice", memory_id="e1")

    assert result["deleted"] is True
    assert (
        sparse.search(
            user_identifier="alice",
            query="hiking",
            kinds=["episode", "fact"],
            limit=10,
        )
        == []
    )
    assert (
        len(sparse.search(user_identifier="alice", query="hiking", kinds=["entity"], limit=10)) == 1
    )
    assert sparse.status()["pending_count"] == 0
