from __future__ import annotations

import sys
import types
from pathlib import Path

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from _batch_memory_shared import CountingBatchEmbedder, RecordingMemoryStore


def test_tenant_vector_index_names_are_deterministic_and_isolated(tmp_path: Path) -> None:
    store = RecordingMemoryStore(tmp_path, CountingBatchEmbedder())

    alice = store._tenant_vector_index(store.memory_index, "alice")

    assert alice == store._tenant_vector_index(store.memory_index, "alice")
    assert alice != store._tenant_vector_index(store.memory_index, "bob")
    assert alice.startswith(f"{store.memory_index}_tenant_")
    assert store.memory_index != alice


# `test_rebuild_sparse_projection_replaces_index_from_canonical_graph_documents`
# was deleted here (04-10, ARC-06 gap closure): it exercised
# `rebuild_sparse_projection`/`_canonical_sparse_documents`, the legacy
# SQLite-FTS5 outbox rebuild mixin (`store_rebuild_sparse.py`), which this
# plan deletes entirely -- nothing reads that projection anymore (04-07
# retired the read side; this plan retires the write side). Superseded by
# `tests/test_store_arcadedb_rebuild.py::test_community_rebuild_succeeds_with_
# uninitialized_sparse_index_and_populates_lexical_channels` and
# `tests/test_community_detection.py`'s updated
# `test_store_rebuilds_embeds_and_grounds_communities_via_native_lexical_channel`,
# which prove `rebuild_communities` succeeds without touching the outbox at all.


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
