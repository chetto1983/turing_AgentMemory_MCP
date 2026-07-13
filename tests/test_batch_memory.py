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
        hit.source_id for hit in sparse.search(user_identifier="alice", query="canonical", limit=10)
    ] == ["canonical"]


# `test_rebuild_vector_projection_reembeds_each_active_canonical_kind` and
# `test_canonical_vector_records_use_active_document_chunk_text` were deleted
# here (04-08): both asserted retired TuringDB-shaped behavior --
# `_ensure_vector_index`/`_memory_vector_id`/`_document_vector_id`/etc.
# overrides, an `indexed_vector_loads` CSV-vector-load recording, and Cypher
# `"c.id"`/`"c.text"` row keys from a `MATCH (c:Chunk)` query -- all retired
# by the D-07 versioned atomic-swap port (no more separate vector-load step,
# no synthetic-integer join property, bound-param ArcadeDB SELECT with bare
# row keys). Superseded by
# `tests/test_store_arcadedb_rebuild.py::test_rebuild_reembeds_every_active_
# canonical_kind_from_its_own_text_property`, which asserts the equivalent
# behavior end-to-end against the new architecture. See 04-08-SUMMARY.md.
