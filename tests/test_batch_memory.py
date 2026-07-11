from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.memory_extraction import (
    Classification,
    EntityMention,
    MemoryExtraction,
    RelationMention,
)
from turing_agentmemory_mcp.models import IngestedDocument, MemoryItem
from turing_agentmemory_mcp.sparse_index import SparseDocument, SparseIndex
from turing_agentmemory_mcp.store import TuringAgentMemory


class CountingBatchEmbedder:
    dimensions = 3

    def __init__(self) -> None:
        self.embed_calls: list[str] = []
        self.embed_many_calls: list[list[str]] = []

    def embed(self, text: str) -> list[float]:
        self.embed_calls.append(text)
        return self._vector(text)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        self.embed_many_calls.append(list(texts))
        return [self._vector(text) for text in texts]

    def _vector(self, text: str) -> list[float]:
        return [float(len(text)), 1.0, 0.0]


class RecordingMemoryStore(TuringAgentMemory):
    def __init__(
        self,
        tmp_path: Path,
        embedder: CountingBatchEmbedder,
        memory_extractor: object | None = None,
        sparse_index: SparseIndex | None = None,
    ) -> None:
        super().__init__(
            client=object(),  # type: ignore[arg-type]
            turing_home=tmp_path,
            embedder=embedder,
            reranker=None,
            memory_extractor=memory_extractor,  # type: ignore[arg-type]
            sparse_index=sparse_index,
        )
        self.memories: dict[tuple[str, str], MemoryItem] = {}
        self.vector_loads: list[list[tuple[int, list[float]]]] = []
        self.indexed_vector_loads: list[tuple[str, list[tuple[int, list[float]]]]] = []
        self.write_queries: list[str] = []

    def _ensure_user(self, user_identifier: str) -> None:
        return

    def get_memory(self, *, user_identifier: str, memory_id: str) -> MemoryItem | None:
        return self.memories.get((user_identifier, memory_id))

    def _existing_entity_ids(self, user_identifier: str, entity_ids: list[str]) -> set[str]:
        return set()

    def _write(self, query: str) -> None:
        self.write_queries.append(query)

    def _load_vectors(self, index_name: str, rows: list[tuple[int, list[float]]], stem: str) -> None:
        self.vector_loads.append(rows)
        self.indexed_vector_loads.append((index_name, rows))

    def _write_memory(self, **kwargs: Any) -> MemoryItem:
        item = super()._write_memory(**kwargs)
        self.memories[(item.user_identifier, item.id)] = item
        return item

    def _create_memories_batch(self, **kwargs: Any) -> list[MemoryItem]:
        items = super()._create_memories_batch(**kwargs)
        for item in items:
            self.memories[(item.user_identifier, item.id)] = item
        return items


class RecordingDocumentStore(RecordingMemoryStore):
    def __init__(self, tmp_path: Path, embedder: CountingBatchEmbedder) -> None:
        super().__init__(tmp_path, embedder)
        self.documents: dict[tuple[str, str], IngestedDocument] = {}

    def get_document(self, *, user_identifier: str, document_id: str) -> IngestedDocument | None:
        return self.documents.get((user_identifier, document_id))

    def _create_document(self, **kwargs: Any) -> IngestedDocument:
        document = super()._create_document(**kwargs)
        self.documents[(document.user_identifier, document.document_id)] = document
        return document


def test_store_messages_batches_embeddings_and_vector_loads(tmp_path: Path) -> None:
    embedder = CountingBatchEmbedder()
    store = RecordingMemoryStore(tmp_path, embedder)

    items = store.store_messages(
        user_identifier="alice",
        messages=[
            {"session_id": "s1", "role": "user", "content": "batch memory one"},
            {"session_id": "s1", "role": "assistant", "content": "batch memory two"},
        ],
        source="chat",
        tags=["batch"],
        metadata={"request_id": "r1"},
    )

    assert [item.content for item in items] == ["batch memory one", "batch memory two"]
    assert [item.source for item in items] == ["chat", "chat"]
    assert [item.tags for item in items] == [["batch"], ["batch"]]
    assert [item.metadata for item in items] == [{"request_id": "r1"}, {"request_id": "r1"}]
    assert embedder.embed_many_calls == [["batch memory one", "batch memory two"]]
    assert embedder.embed_calls == []
    assert len(store.write_queries) == 1
    assert len(store.vector_loads) == 1
    assert len(store.vector_loads[0]) == 2


def test_store_messages_replay_is_duplicate_safe_without_reembedding(tmp_path: Path) -> None:
    embedder = CountingBatchEmbedder()
    store = RecordingMemoryStore(tmp_path, embedder)
    messages = [
        {"session_id": "s1", "role": "user", "content": "retry-safe memory"},
        {"memory_id": "manual-id", "session_id": "s1", "role": "assistant", "content": "manual id memory"},
    ]

    first = store.store_messages(user_identifier="alice", messages=messages)
    second = store.store_messages(user_identifier="alice", messages=messages)

    assert [item.id for item in second] == [item.id for item in first]
    assert [item.content for item in second] == [item.content for item in first]
    assert len(store.memories) == 2
    assert embedder.embed_many_calls == [["retry-safe memory", "manual id memory"]]
    assert embedder.embed_calls == []
    assert len(store.vector_loads) == 1


def test_store_messages_rejects_conflicting_duplicate_ids(tmp_path: Path) -> None:
    embedder = CountingBatchEmbedder()
    store = RecordingMemoryStore(tmp_path, embedder)

    try:
        store.store_messages(
            user_identifier="alice",
            messages=[
                {"memory_id": "same-id", "session_id": "s1", "role": "user", "content": "first"},
                {"memory_id": "same-id", "session_id": "s1", "role": "user", "content": "second"},
            ],
        )
    except ValueError as exc:
        assert "conflicting duplicate memory_id" in str(exc)
    else:
        raise AssertionError("expected conflicting duplicate memory_id")


class RecordingMemoryExtractor:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    def extract_many(self, texts: list[str]) -> tuple[MemoryExtraction, ...]:
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("memory extraction unavailable")
        results: list[MemoryExtraction] = []
        for text in texts:
            alice_start = text.index("Alice")
            hiking_start = text.index("hiking")
            alice = EntityMention("Alice", "person", 0.98, alice_start, alice_start + 5)
            hiking = EntityMention("hiking", "activity", 0.91, hiking_start, hiking_start + 6)
            results.append(
                MemoryExtraction(
                    entities=(alice, hiking),
                    relations=(RelationMention("prefers", alice, hiking, 0.89),),
                    memory_kind=Classification("preference", 0.94),
                    model="test-gliner2",
                    device="cpu",
                    schema_version="memory-v1",
                )
            )
        return tuple(results)


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
        store.memory_index,
        store.entity_index,
        store.fact_index,
    ]


def test_store_messages_deduplicates_entities_across_episode_batch(tmp_path: Path) -> None:
    embedder = CountingBatchEmbedder()
    extractor = RecordingMemoryExtractor()
    store = RecordingMemoryStore(tmp_path, embedder, extractor)

    store.store_messages(
        user_identifier="alice",
        messages=[
            {"memory_id": "e1", "session_id": "s1", "role": "user", "content": "Alice likes hiking."},
            {"memory_id": "e2", "session_id": "s1", "role": "user", "content": "Alice enjoys hiking."},
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
                {"memory_id": "e1", "session_id": "s1", "role": "user", "content": "Alice likes hiking."}
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
            {"memory_id": "e1", "session_id": "s1", "role": "user", "content": "Alice likes hiking."}
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
                {"memory_id": "e1", "session_id": "s1", "role": "user", "content": "Alice likes hiking."}
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
            {"memory_id": "e1", "session_id": "s1", "role": "user", "content": "Alice likes hiking."}
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
                {"memory_id": "e1", "session_id": "s1", "role": "user", "content": "Alice likes hiking."}
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
            {"memory_id": "e1", "session_id": "s1", "role": "user", "content": "Alice likes hiking."}
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
            {"memory_id": "e1", "session_id": "s1", "role": "user", "content": "Alice likes hiking."}
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
    assert sparse.search(
        user_identifier="alice",
        query="hiking",
        kinds=["episode", "fact"],
        limit=10,
    ) == []
    assert len(
        sparse.search(user_identifier="alice", query="hiking", kinds=["entity"], limit=10)
    ) == 1
    assert sparse.status()["pending_count"] == 0


def test_rebuild_sparse_projection_replaces_index_from_canonical_graph_documents(
    tmp_path: Path,
) -> None:
    class RebuildStore(RecordingMemoryStore):
        def _canonical_sparse_documents(self) -> list[SparseDocument]:
            return [
                SparseDocument(
                    "alice:episode:canonical",
                    "alice",
                    "canonical",
                    "episode",
                    "canonical graph memory",
                )
            ]

    sparse = SparseIndex(tmp_path / "fts.sqlite3")
    sparse.initialize()
    sparse.upsert_many(
        [
            SparseDocument(
                "alice:episode:stale",
                "alice",
                "stale",
                "episode",
                "stale memory",
            )
        ]
    )
    store = RebuildStore(tmp_path, CountingBatchEmbedder(), sparse_index=sparse)

    status = store.rebuild_sparse_projection()

    assert status["document_count"] == 1
    assert sparse.search(user_identifier="alice", query="stale", limit=10) == []
    assert [
        hit.source_id
        for hit in sparse.search(user_identifier="alice", query="canonical", limit=10)
    ] == ["canonical"]


def test_rebuild_vector_projection_reembeds_each_active_canonical_kind(tmp_path: Path) -> None:
    class RebuildStore(RecordingMemoryStore):
        def _canonical_vector_records(
            self, user_identifier: str
        ) -> dict[str, list[tuple[str, str]]]:
            assert user_identifier == "alice"
            return {
                "memory": [("m1", "episode text")],
                "document": [("chunk1", "document text")],
                "entity": [("e1", "entity text")],
                "fact": [("f1", "fact text")],
                "community": [("c1", "community text")],
            }

        def _ensure_vector_index(self, name: str) -> None:
            return

    embedder = CountingBatchEmbedder()
    store = RebuildStore(tmp_path, embedder)

    result = store.rebuild_vector_projection(user_identifier="alice")

    assert result["counts"] == {
        "memory": 1,
        "document": 1,
        "entity": 1,
        "fact": 1,
        "community": 1,
    }
    assert result["total"] == 5
    assert embedder.embed_many_calls == [
        ["episode text"],
        ["document text"],
        ["entity text"],
        ["fact text"],
        ["community text"],
    ]
    assert [index for index, _rows in store.indexed_vector_loads] == [
        store.memory_index,
        store.document_index,
        store.entity_index,
        store.fact_index,
        store.community_index,
    ]
    assert [rows[0][0] for _index, rows in store.indexed_vector_loads] == [
        store._memory_vector_id("alice", "m1"),
        store._document_vector_id("alice", "chunk1"),
        store._entity_vector_id("alice", "e1"),
        store._fact_vector_id("alice", "f1"),
        store._community_vector_id("alice", "c1"),
    ]


def test_ingest_document_text_batches_chunk_embeddings_and_vector_loads(tmp_path: Path) -> None:
    embedder = CountingBatchEmbedder()
    store = RecordingDocumentStore(tmp_path, embedder)

    document = store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-batch",
        title="Batch Document",
        text=(
            "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi "
            "omicron pi rho sigma tau upsilon phi chi psi omega"
        ),
        chunk_chars=35,
        source="wiki",
        tags=["batch"],
    )

    assert document.chunk_count > 1
    assert len(embedder.embed_many_calls) == 1
    assert len(embedder.embed_many_calls[0]) == document.chunk_count
    assert embedder.embed_calls == []
    assert len(store.vector_loads) == 1
    assert len(store.vector_loads[0]) == document.chunk_count
