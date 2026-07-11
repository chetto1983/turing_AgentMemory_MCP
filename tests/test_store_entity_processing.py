from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.entity_extraction import ProcessedText
from turing_agentmemory_mcp.models import IngestedDocument, MemoryItem
from turing_agentmemory_mcp.store import TuringAgentMemory


class CountingEmbedder:
    dimensions = 3

    def __init__(self) -> None:
        self.embed_calls: list[str] = []
        self.embed_many_calls: list[list[str]] = []

    def embed(self, text: str) -> list[float]:
        self.embed_calls.append(text)
        return [float(len(text)), 1.0, 0.0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        self.embed_many_calls.append(list(texts))
        return [[float(len(text)), 1.0, 0.0] for text in texts]


class PromptAwareEmbedder(CountingEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.document_calls: list[list[str]] = []
        self.query_calls: list[str] = []

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.document_calls.append(list(texts))
        return [[float(len(text)), 1.0, 0.0] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        self.query_calls.append(text)
        return [float(len(text)), 1.0, 0.0]


class ProjectEntityProcessor:
    def process(self, text: str) -> ProcessedText:
        entity = "TuringDB"
        if entity not in text:
            return ProcessedText(text=text, metadata={})
        start = text.index(entity)
        return ProcessedText(
            text=text,
            metadata={
                "entity_extraction": {
                    "backend": "test",
                    "redacted": False,
                    "entity_count": 1,
                    "entities": [
                        {
                            "text": entity,
                            "label": "project",
                            "start": start,
                            "end": start + len(entity),
                        }
                    ],
                }
            },
        )


class BatchEntityProcessor:
    metadata_keys = ("entity_extraction",)

    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[list[str]] = []

    def process(self, text: str) -> ProcessedText:
        raise AssertionError("batch store must use process_many")

    def process_many(self, texts: list[str]) -> list[ProcessedText]:
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("provider unavailable")
        return [ProcessedText(text=text, metadata={}) for text in texts]


class MalformedBatchEntityProcessor(BatchEntityProcessor):
    def process_many(self, texts: list[str]) -> list[object]:
        self.calls.append(list(texts))
        return [object() for _ in texts]


class RecordingStore(TuringAgentMemory):
    def __init__(
        self,
        tmp_path: Path,
        embedder: CountingEmbedder,
        entity_processor: object | None = None,
    ) -> None:
        super().__init__(
            client=object(),  # type: ignore[arg-type]
            turing_home=tmp_path,
            embedder=embedder,
            reranker=None,
            entity_processor=entity_processor or ProjectEntityProcessor(),  # type: ignore[arg-type]
        )
        self.memories: dict[tuple[str, str], MemoryItem] = {}
        self.documents: dict[tuple[str, str], IngestedDocument] = {}
        self.write_queries: list[str] = []
        self.vector_loads: list[list[tuple[int, list[float]]]] = []

    def _ensure_user(self, user_identifier: str) -> None:
        return

    def get_memory(self, *, user_identifier: str, memory_id: str) -> MemoryItem | None:
        return self.memories.get((user_identifier, memory_id))

    def get_document(self, *, user_identifier: str, document_id: str) -> IngestedDocument | None:
        return self.documents.get((user_identifier, document_id))

    def _write(self, query: str) -> None:
        self.write_queries.append(query)

    def _load_vectors(
        self, index_name: str, rows: list[tuple[int, list[float]]], stem: str
    ) -> None:
        self.vector_loads.append(rows)


def test_store_uses_specialized_document_and_query_embedding_methods(tmp_path: Path) -> None:
    embedder = PromptAwareEmbedder()
    store = RecordingStore(tmp_path, embedder)

    assert store._embed_many(["stored memory"]) == [[13.0, 1.0, 0.0]]
    assert store._embed_text("find stored memory", operation="memory.search") == [18.0, 1.0, 0.0]
    assert store._embed_text("updated memory", operation="memory.update") == [14.0, 1.0, 0.0]

    assert embedder.document_calls == [["stored memory"], ["updated memory"]]
    assert embedder.query_calls == ["find stored memory"]

    def _write_memory(self, **kwargs: Any) -> MemoryItem:
        item = super()._write_memory(**kwargs)
        self.memories[(item.user_identifier, item.id)] = item
        return item

    def _create_memories_batch(self, **kwargs: Any) -> list[MemoryItem]:
        items = super()._create_memories_batch(**kwargs)
        for item in items:
            self.memories[(item.user_identifier, item.id)] = item
        return items

    def _create_document(self, **kwargs: Any) -> IngestedDocument:
        item = super()._create_document(**kwargs)
        self.documents[(item.user_identifier, item.document_id)] = item
        return item


def test_store_message_extracts_entities_without_mutating_content(tmp_path: Path) -> None:
    embedder = CountingEmbedder()
    store = RecordingStore(tmp_path, embedder)

    item = store.store_message(
        user_identifier="alice",
        session_id="s1",
        role="user",
        content="TuringDB stores graph memory",
        metadata={"tenant": "acme"},
    )

    assert item.content == "TuringDB stores graph memory"
    assert item.metadata["tenant"] == "acme"
    assert item.metadata["entity_extraction"]["entity_count"] == 1
    assert item.metadata["entity_extraction"]["entities"][0]["text"] == "TuringDB"
    assert embedder.embed_calls == ["TuringDB stores graph memory"]
    assert "TuringDB stores graph memory" in store.write_queries[0]


def test_store_messages_batch_extracts_entities_before_batch_embedding(tmp_path: Path) -> None:
    embedder = CountingEmbedder()
    store = RecordingStore(tmp_path, embedder)

    items = store.store_messages(
        user_identifier="alice",
        messages=[
            {"session_id": "s1", "role": "user", "content": "TuringDB batch memory"},
            {"session_id": "s1", "role": "assistant", "content": "No named project"},
        ],
    )

    assert [item.content for item in items] == ["TuringDB batch memory", "No named project"]
    assert embedder.embed_many_calls == [["TuringDB batch memory", "No named project"]]
    assert items[0].metadata["entity_extraction"]["entities"][0]["label"] == "project"
    assert items[1].metadata == {}


def test_store_messages_uses_batch_entity_processor_once(tmp_path: Path) -> None:
    embedder = CountingEmbedder()
    processor = BatchEntityProcessor()
    store = RecordingStore(tmp_path, embedder, processor)

    store.store_messages(
        user_identifier="alice",
        messages=[
            {"session_id": "s1", "role": "user", "content": "First source text"},
            {"session_id": "s1", "role": "assistant", "content": "Second source text"},
        ],
    )

    assert processor.calls == [["First source text", "Second source text"]]


def test_store_messages_entity_extraction_failure_prevents_all_writes(tmp_path: Path) -> None:
    embedder = CountingEmbedder()
    processor = BatchEntityProcessor(fail=True)
    store = RecordingStore(tmp_path, embedder, processor)

    with pytest.raises(RuntimeError, match="provider unavailable"):
        store.store_messages(
            user_identifier="alice",
            messages=[
                {"session_id": "s1", "role": "user", "content": "First source text"},
                {"session_id": "s1", "role": "assistant", "content": "Second source text"},
            ],
        )

    assert processor.calls == [["First source text", "Second source text"]]
    assert store.write_queries == []
    assert store.vector_loads == []
    assert embedder.embed_calls == []
    assert embedder.embed_many_calls == []


def test_store_messages_malformed_batch_entity_result_prevents_all_writes(tmp_path: Path) -> None:
    embedder = CountingEmbedder()
    processor = MalformedBatchEntityProcessor()
    store = RecordingStore(tmp_path, embedder, processor)

    with pytest.raises(RuntimeError, match="invalid result"):
        store.store_messages(
            user_identifier="alice",
            messages=[{"session_id": "s1", "role": "user", "content": "First source text"}],
        )

    assert processor.calls == [["First source text"]]
    assert store.write_queries == []
    assert store.vector_loads == []
    assert embedder.embed_calls == []
    assert embedder.embed_many_calls == []


def test_ensure_graph_loaded_reuses_existing_graph_without_create_attempt(tmp_path: Path) -> None:
    class GraphClient:
        def __init__(self) -> None:
            self.calls: list[tuple[object, ...]] = []

        def list_loaded_graphs(self) -> list[str]:
            self.calls.append(("list_loaded",))
            return ["agent_memory"]

        def load_graph(self, graph: str, *, raise_if_loaded: bool) -> None:
            self.calls.append(("load", graph, raise_if_loaded))

        def create_graph(self, graph: str) -> None:
            self.calls.append(("create", graph))

        def set_graph(self, graph: str) -> None:
            self.calls.append(("set", graph))

    store = RecordingStore(tmp_path, CountingEmbedder())
    client = GraphClient()
    store.client = client  # type: ignore[assignment]

    store._ensure_graph_loaded()

    assert client.calls == [
        ("list_loaded",),
        ("set", store.graph),
    ]


def test_document_ingest_extracts_entities_before_chunking_hashing_and_persistence(
    tmp_path: Path,
) -> None:
    embedder = CountingEmbedder()
    store = RecordingStore(tmp_path, embedder)

    item = store.ingest_document_text(
        user_identifier="alice",
        title="Contact",
        text="TuringDB can store entity-rich documents",
        metadata={"classification": "internal"},
    )

    assert item.metadata["classification"] == "internal"
    assert item.metadata["entity_extraction"]["redacted"] is False
    assert item.text_hash == store._document_text_hash("TuringDB can store entity-rich documents")
    assert embedder.embed_many_calls == [["TuringDB can store entity-rich documents"]]
    assert embedder.embed_calls == []
    assert "TuringDB can store entity-rich documents" in store.write_queries[0]
