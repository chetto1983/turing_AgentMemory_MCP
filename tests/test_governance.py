from __future__ import annotations

import asyncio
import json
import sys
import types
from pathlib import Path
from typing import Any

from fastmcp import Client

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.models import IngestedDocument, MemoryItem
from turing_agentmemory_mcp.server import create_mcp_app
from turing_agentmemory_mcp.store import TuringAgentMemory


class QueryClient:
    """ArcadeDB-shaped fake (04-06): a single `rows` bucket returned for any
    Memory- or Chunk-shaped read (mirrors the pre-port single-bucket design --
    each test below only ever populates rows for one record type at a time),
    plus the `command`/`begin`/`commit`/`rollback`/`run_in_transaction`/
    `is_ready` surface `store_core.py`'s ported seam requires.
    """

    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or []
        self.queries: list[tuple[str, dict[str, object] | None]] = []
        self.commands: list[tuple[str, dict[str, object] | None]] = []
        self._begin_calls = 0

    def is_ready(self) -> bool:
        return True

    def begin(self) -> str:
        self._begin_calls += 1
        return f"session-{self._begin_calls}"

    def commit(self, session_id: str) -> None:
        return

    def rollback(self, session_id: str) -> None:
        return

    def run_in_transaction(self, body: Any, *, commit_retries: int | None = None) -> Any:
        session_id = self.begin()
        result = body(session_id)
        self.commit(session_id)
        return result

    def query(
        self,
        query: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        self.queries.append((query, params))
        upper = query.upper()
        if "MEMORY" in upper or "CHUNK" in upper:
            return self._filtered(params)
        return []

    def _filtered(self, params: dict[str, object] | None) -> list[dict[str, object]]:
        # Bound-param names mirror the row's own property name (04-05
        # convention) -- narrow by any param key the row actually carries
        # (e.g. `id`/`user_identifier`), skipping vector/limit-only params
        # (`vec`/`k`/`qi`/`qv`) that don't correspond to a row property.
        if not params:
            return list(self.rows)
        return [
            row
            for row in self.rows
            if all(row.get(key) == value for key, value in params.items() if key in row)
        ]

    def command(
        self,
        query: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        self.commands.append((query, params))
        if query.strip().upper().startswith("SELECT"):
            return self.query(query, params=params, language=language, session_id=session_id)
        return []


class CountingEmbedder:
    dimensions = 3

    def __init__(self) -> None:
        self.embed_calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.embed_calls.append(text)
        return [1.0, float(len(text)), 0.0]


class RecordingAuditSink:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    def record(self, event: dict[str, object]) -> None:
        self.events.append(event)


class SecretRedactor:
    def redact(self, text: str) -> Any:
        from turing_agentmemory_mcp.governance import RedactedText

        return RedactedText(
            text=text.replace("sk-live-secret", "[SECRET]"),
            metadata={
                "redaction": {
                    "redacted": "sk-live-secret" in text,
                    "match_count": 1 if "sk-live-secret" in text else 0,
                    "labels": ["secret"] if "sk-live-secret" in text else [],
                }
            },
        )


def payload(result: Any) -> Any:
    if hasattr(result, "structured_content") and result.structured_content is not None:
        value = result.structured_content
        if isinstance(value, dict) and set(value) == {"result"}:
            return value["result"]
        return value
    if hasattr(result, "data") and result.data is not None:
        return result.data
    if hasattr(result, "content"):
        text = "".join(getattr(item, "text", "") for item in result.content)
        return json.loads(text)
    return result


class RecordingStore(TuringAgentMemory):
    def __init__(
        self,
        tmp_path: Path,
        *,
        audit_sink: RecordingAuditSink | None = None,
        redactor: SecretRedactor | None = None,
    ) -> None:
        super().__init__(
            client=QueryClient(),  # type: ignore[arg-type]
            turing_home=tmp_path,
            embedder=CountingEmbedder(),
            reranker=None,
            audit_sink=audit_sink,
            redactor=redactor,
        )
        self.memories: dict[tuple[str, str], MemoryItem] = {}
        self.write_queries: list[str] = []
        self.write_params: list[dict[str, object] | None] = []

    @property
    def counting_embedder(self) -> CountingEmbedder:
        return self.embedder  # type: ignore[return-value]

    def _ensure_user(self, user_identifier: str) -> None:
        return

    def get_memory(self, *, user_identifier: str, memory_id: str) -> MemoryItem | None:
        return self.memories.get((user_identifier, memory_id))

    def _write(self, query: str) -> None:
        self.write_queries.append(query)
        self.write_params.append(None)

    def _write_many(self, statements: list[Any]) -> None:
        # ArcadeDB-ported call sites (04-05/06) pass `list[tuple[str, params]]`;
        # record the statement text (matches this file's pre-port
        # `write_queries` convention) plus the bound params (content is now a
        # bound value, not interpolated into the text -- Pitfall 2).
        for entry in statements:
            if isinstance(entry, tuple):
                query, params = entry
            else:
                query, params = entry, None
            self.write_queries.append(query)
            self.write_params.append(params)

    def _load_vectors(
        self, index_name: str, rows: list[tuple[int, list[float]]], stem: str
    ) -> None:
        return

    def _write_memory(self, **kwargs: Any) -> MemoryItem:
        item = super()._write_memory(**kwargs)
        self.memories[(item.user_identifier, item.id)] = item
        return item


def test_store_message_applies_redaction_before_embedding_and_audits_without_content(
    tmp_path: Path,
) -> None:
    audit = RecordingAuditSink()
    store = RecordingStore(tmp_path, audit_sink=audit, redactor=SecretRedactor())

    item = store.store_message(
        user_identifier="alice",
        session_id="s1",
        role="user",
        content="rotate key sk-live-secret before release",
        source="ops",
    )

    assert item.content == "rotate key [SECRET] before release"
    assert item.metadata["redaction"] == {
        "redacted": True,
        "match_count": 1,
        "labels": ["secret"],
    }
    assert store.counting_embedder.embed_calls == ["rotate key [SECRET] before release"]
    assert "sk-live-secret" not in store.write_queries[0]
    assert audit.events[-1]["operation"] == "memory.store_message"
    assert audit.events[-1]["resource_type"] == "memory"
    assert audit.events[-1]["resource_id"] == item.id
    assert audit.events[-1]["user_identifier"] == "alice"
    assert "content" not in audit.events[-1]


def test_expired_memory_is_hidden_from_get_list_and_search(tmp_path: Path) -> None:
    expired_row = {
        "id": "expired",
        "user_identifier": "alice",
        "kind": "message",
        "content": "expired memory",
        "session_id": "s1",
        "role": "user",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "expires_at": "2020-01-01T00:00:00Z",
        "source": "test",
        "tags_json": "[]",
        "metadata_json": "{}",
        "distance": 0.01,
    }
    active_row = {
        **expired_row,
        "id": "active",
        "content": "active memory",
        "expires_at": "2099-01-01T00:00:00Z",
        "distance": 0.02,
    }
    client = QueryClient([expired_row, active_row])
    store = TuringAgentMemory(
        client=client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=CountingEmbedder(),
        reranker=None,
    )

    assert store.get_memory(user_identifier="alice", memory_id="expired") is None
    assert [item.id for item in store.list_memories(user_identifier="alice")] == ["active"]
    assert [
        item.id for item in store.search_memory(user_identifier="alice", query="memory", limit=5)
    ] == ["active"]


def test_jsonl_audit_sink_writes_machine_readable_events(tmp_path: Path) -> None:
    from turing_agentmemory_mcp.governance import JsonlAuditSink

    path = tmp_path / "audit.jsonl"
    sink = JsonlAuditSink(path)

    sink.record(
        {
            "operation": "memory.delete",
            "resource_type": "memory",
            "resource_id": "m1",
            "user_identifier": "alice",
            "success": True,
        }
    )

    event = json.loads(path.read_text(encoding="utf-8").strip())
    assert event["timestamp"]
    assert event["operation"] == "memory.delete"
    assert event["resource_id"] == "m1"
    assert event["success"] is True
    assert "content" not in event


def test_document_ingest_applies_redaction_expiry_and_audit(tmp_path: Path) -> None:
    audit = RecordingAuditSink()
    store = RecordingStore(tmp_path, audit_sink=audit, redactor=SecretRedactor())

    document = store.ingest_document_text(
        user_identifier="alice",
        document_id="doc-secret",
        title="Release Notes",
        text="remove sk-live-secret from the release notes",
        source="docs",
        expires_at="2099-01-01T00:00:00Z",
    )

    assert document.metadata["redaction"]["redacted"] is True
    assert document.expires_at == "2099-01-01T00:00:00Z"
    assert "sk-live-secret" not in "\n".join(store.write_queries)
    assert all(
        "sk-live-secret" not in str(value)
        for params in store.write_params
        if params
        for value in params.values()
    )
    document_creates = [
        params
        for query, params in zip(store.write_queries, store.write_params, strict=True)
        if query.startswith("CREATE VERTEX Document") and params is not None
    ]
    assert document_creates
    assert document_creates[0]["expires_at"] == "2099-01-01T00:00:00Z"
    assert audit.events[-1]["operation"] == "document.ingest_text"
    assert audit.events[-1]["resource_type"] == "document"
    assert audit.events[-1]["resource_id"] == "doc-secret"
    assert "text" not in audit.events[-1]


def test_expired_document_chunks_are_hidden_from_search(tmp_path: Path) -> None:
    expired_chunk = {
        "id": "doc-expired#1",
        "document_id": "doc-expired",
        "title": "Expired",
        "locator": "chunk=1",
        "text": "expired document chunk",
        "user_identifier": "alice",
        "expires_at": "2020-01-01T00:00:00Z",
        "source": "docs",
        "tags_json": "[]",
        "metadata_json": "{}",
    }
    active_chunk = {
        **expired_chunk,
        "id": "doc-active#1",
        "document_id": "doc-active",
        "title": "Active",
        "text": "active document chunk",
        "expires_at": "2099-01-01T00:00:00Z",
    }
    store = TuringAgentMemory(
        client=QueryClient([expired_chunk, active_chunk]),  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=CountingEmbedder(),
        reranker=None,
    )

    assert [
        hit.chunk_id
        for hit in store.search_documents(user_identifier="alice", query="document", limit=5)
    ] == ["doc-active#1"]


class ForwardingFakeMemory:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def store_message(
        self,
        *,
        user_identifier: str,
        session_id: str,
        role: str,
        content: str,
        expires_at: str = "",
        **kwargs: object,
    ) -> MemoryItem:
        self.calls.append({"tool": "memory_store_message", "expires_at": expires_at})
        return MemoryItem(
            id="m1",
            user_identifier=user_identifier,
            kind="message",
            content=content,
            session_id=session_id,
            role=role,
            score=1.0,
            expires_at=expires_at,
        )

    def ingest_document_text(
        self,
        *,
        user_identifier: str,
        title: str,
        text: str,
        expires_at: str | None = None,
        **kwargs: object,
    ) -> IngestedDocument:
        self.calls.append({"tool": "document_ingest_text", "expires_at": expires_at or ""})
        return IngestedDocument(
            document_id="doc1",
            title=title,
            chunk_count=1,
            user_identifier=user_identifier,
            expires_at=expires_at or "",
        )


def test_mcp_tools_forward_expires_at_to_store() -> None:
    fake = ForwardingFakeMemory()

    async def run() -> None:
        async with Client(create_mcp_app(fake)) as client:  # type: ignore[arg-type]
            memory = payload(
                await client.call_tool(
                    "memory_store_message",
                    {
                        "user_identifier": "alice",
                        "session_id": "s1",
                        "role": "user",
                        "content": "retained memory",
                        "expires_at": "2099-01-01T00:00:00Z",
                    },
                )
            )
            document = payload(
                await client.call_tool(
                    "document_ingest_text",
                    {
                        "user_identifier": "alice",
                        "title": "Retained",
                        "text": "retained document",
                        "expires_at": "2099-01-02T00:00:00Z",
                    },
                )
            )
            assert memory["expires_at"] == "2099-01-01T00:00:00Z"
            assert document["expires_at"] == "2099-01-02T00:00:00Z"

    asyncio.run(run())

    assert fake.calls == [
        {"tool": "memory_store_message", "expires_at": "2099-01-01T00:00:00Z"},
        {"tool": "document_ingest_text", "expires_at": "2099-01-02T00:00:00Z"},
    ]
