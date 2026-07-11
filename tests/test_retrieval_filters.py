from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from typing import Any

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.store import TuringAgentMemory


class Rows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return self.rows


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
        chunk_rows: list[dict[str, object]] | None = None,
    ) -> None:
        super().__init__(
            client=object(),  # type: ignore[arg-type]
            turing_home=tmp_path,
            embedder=NullEmbedder(),
            reranker=None,
        )
        self.memory_rows = memory_rows or []
        self.chunk_rows = chunk_rows or []

    def _query(self, query: str, *, operation: str) -> Rows:
        if operation == "memory.vector_search":
            return Rows(self.memory_rows)
        if operation == "document.vector_search":
            return Rows(self.chunk_rows)
        return Rows([])

    def _active_memory_rows(self, user_identifier: str) -> list[dict[str, Any]]:
        return [row for row in self.memory_rows if row["m.user_identifier"] == user_identifier]

    def _active_chunk_rows(self, user_identifier: str, *, document_id: str = "") -> list[dict[str, Any]]:
        return [
            row
            for row in self.chunk_rows
            if row["c.user_identifier"] == user_identifier
            and (not document_id or row["c.document_id"] == document_id)
        ]

    def _chunk_context(self, vector: int) -> list[dict[str, object]]:
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
    score: float = 0.7,
) -> dict[str, object]:
    return {
        "m.id": memory_id,
        "m.user_identifier": "alice",
        "m.kind": kind,
        "m.content": content,
        "m.session_id": session_id,
        "m.role": "user",
        "m.created_at": created_at,
        "m.updated_at": updated_at or created_at,
        "m.expires_at": "",
        "m.source": source,
        "m.tags_json": json.dumps(tags),
        "m.metadata_json": "{}",
        "score": score,
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
    score: float = 0.7,
) -> dict[str, object]:
    return {
        "c.chunk_id": chunk_id,
        "c.document_id": document_id,
        "c.title": document_id,
        "c.locator": "chunk=1",
        "c.text": text,
        "c.vector_id": 100,
        "c.user_identifier": "alice",
        "c.created_at": created_at,
        "c.updated_at": updated_at or created_at,
        "c.expires_at": "",
        "c.source": source,
        "c.tags_json": json.dumps(tags),
        "c.metadata_json": "{}",
        "score": score,
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
    store = FilterStore(
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


def test_chunk_context_treats_missing_next_chunk_edge_type_as_empty(tmp_path: Path) -> None:
    class MissingNextChunkStore(FilterStore):
        _chunk_context = TuringAgentMemory._chunk_context

        def _query(self, query: str, *, operation: str) -> Rows:
            assert operation == "document.chunk_context"
            raise RuntimeError("ANALYZE_ERROR: Unknown edge type: NEXT_CHUNK")

    store = MissingNextChunkStore(tmp_path)

    assert store._chunk_context(100) == []


def test_chunk_context_does_not_hide_unrelated_database_errors(tmp_path: Path) -> None:
    class BrokenContextStore(FilterStore):
        _chunk_context = TuringAgentMemory._chunk_context

        def _query(self, query: str, *, operation: str) -> Rows:
            assert operation == "document.chunk_context"
            raise RuntimeError("database connection lost")

    store = BrokenContextStore(tmp_path)

    try:
        store._chunk_context(100)
    except RuntimeError as exc:
        assert str(exc) == "database connection lost"
    else:
        raise AssertionError("unrelated context query errors must propagate")
