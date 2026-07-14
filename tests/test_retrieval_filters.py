from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.store import TuringAgentMemory


class NullEmbedder:
    dimensions = 3

    def embed(self, text: str) -> list[float]:
        return [1.0, 0.0, 0.0]


class FilterStore(TuringAgentMemory):
    def __init__(
        self,
        tmp_path: Path,
        *,
        memory_rows: list[dict[str, object]] | None = None,
    ) -> None:
        super().__init__(
            client=object(),  # type: ignore[arg-type]
            turing_home=tmp_path,
            embedder=NullEmbedder(),
            reranker=None,
        )
        self.memory_rows = memory_rows or []

    def _query(
        self, query: str, *, operation: str, params: dict[str, object] | None = None
    ) -> list[dict[str, object]]:
        if operation == "memory.vector_search":
            return list(self.memory_rows)
        return []

    def _active_memory_rows(self, user_identifier: str) -> list[dict[str, Any]]:
        return [row for row in self.memory_rows if row["user_identifier"] == user_identifier]


class DocumentFilterStore(TuringAgentMemory):
    """ArcadeDB-shaped document-search fixture (04-06): dispatches on the
    `operation=` tag `store_documents.py`'s ported `_query` calls carry --
    `chunk_rows` stand in for the native HNSW vector channel's results; the
    Lucene lexical channel returns no extra candidates (not exercised by this
    filter-only scenario).
    """

    def __init__(
        self, tmp_path: Path, *, chunk_rows: list[dict[str, object]] | None = None
    ) -> None:
        super().__init__(
            client=object(),  # type: ignore[arg-type]
            turing_home=tmp_path,
            embedder=NullEmbedder(),
            reranker=None,
        )
        self.chunk_rows = chunk_rows or []

    def _query(
        self, query: str, *, operation: str, params: dict[str, object] | None = None
    ) -> list[dict[str, object]]:
        if operation == "document.vector_search":
            return list(self.chunk_rows)
        return []

    def _chunk_context(self, chunk_id: str, *, user_identifier: str) -> list[dict[str, object]]:
        return []


def _memory_row(
    memory_id: str,
    content: str,
    *,
    session_id: str,
    kind: str = "message",
    source: str,
    tags: list[str],
    created_at: str,
    updated_at: str | None = None,
    distance: float = 0.3,
) -> dict[str, object]:
    return {
        "id": memory_id,
        "user_identifier": "alice",
        "kind": kind,
        "content": content,
        "session_id": session_id,
        "role": "user",
        "created_at": created_at,
        "updated_at": updated_at or created_at,
        "expires_at": "",
        "source": source,
        "tags_json": json.dumps(tags),
        "metadata_json": "{}",
        "distance": distance,
    }


def _chunk_row(
    chunk_id: str,
    text: str,
    *,
    document_id: str,
    source: str,
    tags: list[str],
    created_at: str,
    updated_at: str | None = None,
    distance: float = 0.3,
) -> dict[str, object]:
    return {
        "id": chunk_id,
        "document_id": document_id,
        "title": document_id,
        "locator": "chunk=1",
        "text": text,
        "user_identifier": "alice",
        "created_at": created_at,
        "updated_at": updated_at or created_at,
        "expires_at": "",
        "source": source,
        "tags_json": json.dumps(tags),
        "metadata_json": "{}",
        "distance": distance,
    }


def test_memory_search_filters_by_session_source_tags_and_created_range(tmp_path: Path) -> None:
    store = FilterStore(
        tmp_path,
        memory_rows=[
            _memory_row(
                "keep",
                "incident INC-7781 stable router fix",
                session_id="ops-1",
                source="slack",
                tags=["incident", "stable"],
                created_at="2026-07-09T10:00:00Z",
            ),
            _memory_row(
                "wrong-session",
                "incident INC-7781 stable router fix",
                session_id="ops-2",
                source="slack",
                tags=["incident", "stable"],
                created_at="2026-07-09T10:00:00Z",
            ),
            _memory_row(
                "wrong-tag",
                "incident INC-7781 stable router fix",
                session_id="ops-1",
                source="slack",
                tags=["incident"],
                created_at="2026-07-09T10:00:00Z",
            ),
            _memory_row(
                "too-old",
                "incident INC-7781 stable router fix",
                session_id="ops-1",
                source="slack",
                tags=["incident", "stable"],
                created_at="2026-06-30T23:59:59Z",
            ),
        ],
    )

    hits = store.search_memory(
        user_identifier="alice",
        query="INC-7781 router",
        limit=10,
        session_id="ops-1",
        source="slack",
        tags=["stable"],
        created_after="2026-07-01T00:00:00Z",
        created_before="2026-07-31T23:59:59Z",
    )

    assert [hit.id for hit in hits] == ["keep"]


def test_memory_get_context_applies_same_filters_as_memory_search(tmp_path: Path) -> None:
    store = FilterStore(
        tmp_path,
        memory_rows=[
            _memory_row(
                "keep",
                "deployment window is Tuesday",
                session_id="release",
                source="runbook",
                tags=["deploy"],
                created_at="2026-07-09T10:00:00Z",
            ),
            _memory_row(
                "wrong-source",
                "deployment window is Wednesday",
                session_id="release",
                source="chat",
                tags=["deploy"],
                created_at="2026-07-09T10:00:00Z",
            ),
        ],
    )

    context = store.get_context(
        user_identifier="alice",
        query="deployment window",
        session_id="release",
        source="runbook",
        tags=["deploy"],
    )

    assert [item["id"] for item in context["items"]] == ["keep"]
    assert "Wednesday" not in context["context"]


def test_document_search_filters_by_source_tags_and_updated_range(tmp_path: Path) -> None:
    store = DocumentFilterStore(
        tmp_path,
        chunk_rows=[
            _chunk_row(
                "doc-keep#1",
                "incident INC-7781 documented mitigation",
                document_id="doc-keep",
                source="wiki",
                tags=["incident", "stable"],
                created_at="2026-07-01T10:00:00Z",
                updated_at="2026-07-09T10:00:00Z",
            ),
            _chunk_row(
                "doc-wrong-source#1",
                "incident INC-7781 documented mitigation",
                document_id="doc-wrong-source",
                source="chat",
                tags=["incident", "stable"],
                created_at="2026-07-01T10:00:00Z",
                updated_at="2026-07-09T10:00:00Z",
            ),
            _chunk_row(
                "doc-too-old#1",
                "incident INC-7781 documented mitigation",
                document_id="doc-too-old",
                source="wiki",
                tags=["incident", "stable"],
                created_at="2026-07-01T10:00:00Z",
                updated_at="2026-06-30T23:59:59Z",
            ),
        ],
    )

    hits = store.search_documents(
        user_identifier="alice",
        query="INC-7781 mitigation",
        limit=10,
        source="wiki",
        tags=["stable"],
        updated_after="2026-07-01T00:00:00Z",
        updated_before="2026-07-31T23:59:59Z",
    )

    assert [hit.chunk_id for hit in hits] == ["doc-keep#1"]
