from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.models import MemoryItem
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
    def __init__(self, tmp_path: Path, embedder: CountingBatchEmbedder) -> None:
        super().__init__(
            client=object(),  # type: ignore[arg-type]
            turing_home=tmp_path,
            embedder=embedder,
            reranker=None,
        )
        self.memories: dict[tuple[str, str], MemoryItem] = {}
        self.vector_loads: list[list[tuple[int, list[float]]]] = []
        self.write_queries: list[str] = []

    def _ensure_user(self, user_identifier: str) -> None:
        return

    def get_memory(self, *, user_identifier: str, memory_id: str) -> MemoryItem | None:
        return self.memories.get((user_identifier, memory_id))

    def _write(self, query: str) -> None:
        self.write_queries.append(query)

    def _load_vectors(self, index_name: str, rows: list[tuple[int, list[float]]], stem: str) -> None:
        self.vector_loads.append(rows)

    def _write_memory(self, **kwargs: Any) -> MemoryItem:
        item = super()._write_memory(**kwargs)
        self.memories[(item.user_identifier, item.id)] = item
        return item

    def _create_memories_batch(self, **kwargs: Any) -> list[MemoryItem]:
        items = super()._create_memories_batch(**kwargs)
        for item in items:
            self.memories[(item.user_identifier, item.id)] = item
        return items


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
