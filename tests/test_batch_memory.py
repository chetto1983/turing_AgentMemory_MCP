from __future__ import annotations

import sys
import types
from pathlib import Path

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from _batch_memory_shared import CountingBatchEmbedder, RecordingMemoryStore

from turing_agentmemory_mcp.sparse_index import SparseDocument, SparseIndex


def test_tenant_vector_index_names_are_deterministic_and_isolated(tmp_path: Path) -> None:
    store = RecordingMemoryStore(tmp_path, CountingBatchEmbedder())

    alice = store._tenant_vector_index(store.memory_index, "alice")

    assert alice == store._tenant_vector_index(store.memory_index, "alice")
    assert alice != store._tenant_vector_index(store.memory_index, "bob")
    assert alice.startswith(f"{store.memory_index}_tenant_")
    assert store.memory_index != alice


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
        store._tenant_vector_index(store.memory_index, "alice"),
        store._tenant_vector_index(store.document_index, "alice"),
        store._tenant_vector_index(store.entity_index, "alice"),
        store._tenant_vector_index(store.fact_index, "alice"),
        store._tenant_vector_index(store.community_index, "alice"),
    ]
    assert [rows[0][0] for _index, rows in store.indexed_vector_loads] == [
        store._memory_vector_id("alice", "m1"),
        store._document_vector_id("alice", "chunk1"),
        store._entity_vector_id("alice", "e1"),
        store._fact_vector_id("alice", "f1"),
        store._community_vector_id("alice", "c1"),
    ]


def test_canonical_vector_records_use_active_document_chunk_text(tmp_path: Path) -> None:
    class Rows:
        def __init__(self, values: list[dict[str, object]]) -> None:
            self.values = values

        def to_dict(self, orient: str) -> list[dict[str, object]]:
            assert orient == "records"
            return self.values

    class CanonicalStore(RecordingMemoryStore):
        def __init__(self) -> None:
            super().__init__(tmp_path, CountingBatchEmbedder())
            self.queries: list[str] = []

        def _query(self, query: str, *, operation: str) -> Rows:
            self.queries.append(query)
            if operation == "vector.rebuild.document":
                return Rows([{"c.id": "chunk-1", "c.text": "canonical chunk text"}])
            return Rows([])

    store = CanonicalStore()

    records = store._canonical_vector_records("alice")

    assert records["document"] == [("chunk-1", "canonical chunk text")]
    document_query = next(query for query in store.queries if "MATCH (c:Chunk)" in query)
    assert 'c.status = "active"' in document_query
    assert "RETURN c.id, c.text" in document_query
