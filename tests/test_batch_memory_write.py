from __future__ import annotations

import sys
import types
from pathlib import Path

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from _batch_memory_shared import CountingBatchEmbedder, RecordingDocumentStore, RecordingMemoryStore

from turing_agentmemory_mcp.store import TuringAgentMemory


def test_store_messages_batches_embeddings_and_writes_inline_vectors(tmp_path: Path) -> None:
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
    # ARC-05: no separate vector-load step remains -- the embedding is an
    # inline `CREATE VERTEX Memory` property, bound as a param on that write.
    assert store.vector_loads == []
    memory_creates = [
        params
        for query, params in zip(store.write_queries, store.write_params, strict=True)
        if query.startswith("CREATE VERTEX Memory") and params is not None
    ]
    assert len(memory_creates) == 2
    assert all("embedding" in params and "vector_id" not in params for params in memory_creates)


def test_store_messages_replay_is_duplicate_safe_without_reembedding(tmp_path: Path) -> None:
    embedder = CountingBatchEmbedder()
    store = RecordingMemoryStore(tmp_path, embedder)
    messages = [
        {"session_id": "s1", "role": "user", "content": "retry-safe memory"},
        {
            "memory_id": "manual-id",
            "session_id": "s1",
            "role": "assistant",
            "content": "manual id memory",
        },
    ]

    first = store.store_messages(user_identifier="alice", messages=messages)
    second = store.store_messages(user_identifier="alice", messages=messages)

    assert [item.id for item in second] == [item.id for item in first]
    assert [item.content for item in second] == [item.content for item in first]
    assert len(store.memories) == 2
    assert embedder.embed_many_calls == [["retry-safe memory", "manual id memory"]]
    assert embedder.embed_calls == []
    # A replayed batch finds both memories already existing (`get_memory` is
    # overridden to consult `self.memories`), so no second write happens at all.
    memory_creates = [
        query for query in store.write_queries if query.startswith("CREATE VERTEX Memory")
    ]
    assert len(memory_creates) == 2


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


def test_ingest_document_text_batches_graph_queries_below_payload_limit(tmp_path: Path) -> None:
    store = RecordingDocumentStore(tmp_path, CountingBatchEmbedder())
    store.document_graph_batch_bytes = 1_400

    document = store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-large",
        title="Large Document",
        text=" ".join(f"section-{index:04d}" for index in range(500)),
        chunk_chars=200,
        source="manual",
        tags=["large"],
    )

    assert len(store.write_queries) > 2
    assert all(len(query.encode("utf-8")) <= 1_400 for query in store.write_queries)
    graph_writes = "\n".join(store.write_queries)
    assert graph_writes.count(":Document {") == 1
    assert graph_writes.count(":Chunk {") == document.chunk_count
    assert graph_writes.count(":HAS_CHUNK") == document.chunk_count
    assert graph_writes.count(":NEXT_CHUNK") == document.chunk_count - 1


def test_document_chunking_packs_short_lines_to_the_configured_budget() -> None:
    chunks = TuringAgentMemory._chunk_text(
        "alpha beta\ngamma delta\nepsilon zeta",
        chunk_chars=24,
    )

    assert chunks == ["alpha beta\n\ngamma delta", "epsilon zeta"]


def test_document_chunking_preserves_pdf_page_boundaries_and_markers() -> None:
    chunks = TuringAgentMemory._chunk_text(
        "<!-- page 7 -->\n\nalpha beta gamma delta\n\n<!-- page 8 -->\n\nepsilon zeta",
        chunk_chars=34,
    )

    assert chunks == [
        "<!-- page 7 -->\n\nalpha beta gamma",
        "<!-- page 7 -->\n\ndelta",
        "<!-- page 8 -->\n\nepsilon zeta",
    ]
