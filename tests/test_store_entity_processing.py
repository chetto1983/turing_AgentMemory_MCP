from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

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


class RecordingStore(TuringAgentMemory):
    def __init__(self, tmp_path: Path, embedder: CountingEmbedder) -> None:
        super().__init__(
            client=object(),  # type: ignore[arg-type]
            turing_home=tmp_path,
            embedder=embedder,
            reranker=None,
            entity_processor=ProjectEntityProcessor(),
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
