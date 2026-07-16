"""Shared recording fixtures for the test_batch_memory* split (not collected as tests)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from turing_agentmemory_mcp.memory_extraction import (
    Classification,
    EntityMention,
    MemoryExtraction,
    RelationMention,
)
from turing_agentmemory_mcp.models import IngestedDocument, MemoryItem
from turing_agentmemory_mcp.sparse_index import SparseIndex
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
        # ArcadeDB-ported call sites (04-05, store_memory_write.py/store_memory_read.py)
        # pass `_write_many` a `list[tuple[str, params]]`; unported call sites
        # (store_documents.py, 04-06) still pass a plain `list[str]`. Both shapes are
        # normalized into `write_queries` (statement text only, preserving the old
        # one-entry-per-statement convention every existing assertion relies on) plus
        # this new parallel `write_params` list for tests that need the bound values
        # (e.g. an inline `embedding` -- there is no separate vector-load step anymore).
        self.write_params: list[dict[str, object] | None] = []

    def _ensure_user(self, user_identifier: str) -> None:
        return

    def get_memory(self, *, user_identifier: str, memory_id: str) -> MemoryItem | None:
        return self.memories.get((user_identifier, memory_id))

    def _existing_entity_ids(self, user_identifier: str, entity_ids: list[str]) -> set[str]:
        return set()

    def _write(self, query: str) -> None:
        self.write_queries.append(query)
        self.write_params.append(None)

    def _write_many(self, statements: list[Any]) -> None:
        for entry in statements:
            if isinstance(entry, tuple) and len(entry) == 2 and isinstance(entry[0], str):
                query, params = entry
            else:
                query, params = entry, None
            self.write_queries.append(query)
            self.write_params.append(params)

    def _load_vectors(
        self, index_name: str, rows: list[tuple[int, list[float]]], stem: str
    ) -> None:
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
