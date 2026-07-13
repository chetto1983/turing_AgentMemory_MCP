from __future__ import annotations

import asyncio
import json
import sys
import types
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fastmcp import Client

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.models import MemoryItem
from turing_agentmemory_mcp.server import create_mcp_app
from turing_agentmemory_mcp.store import TuringAgentMemory


class QueryRecordingClient:
    """ArcadeDB-shaped fake (04-06): session-agnostic (no read-your-writes
    modeling needed for these span-recording tests) but implements the
    `query`/`command`/`begin`/`commit`/`rollback`/`run_in_transaction`/
    `is_ready` surface `store_core.py`'s ported seam requires.
    """

    def __init__(self, vector_rows: list[dict[str, object]] | None = None) -> None:
        self.queries: list[tuple[str, dict[str, object] | None]] = []
        self.commands: list[tuple[str, dict[str, object] | None]] = []
        self.vector_rows = vector_rows or []
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
        if 'vectorNeighbors("Memory[embedding]"' in query:
            return list(self.vector_rows)
        return []

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
        self.calls: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.calls.append(text)
        return [1.0, float(len(text)), 0.0]


class RecordingReranker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str]]] = []

    def rerank(self, query: str, documents: list[str]) -> list[Any]:
        from turing_agentmemory_mcp.rerank import Scored

        self.calls.append((query, list(documents)))
        return [Scored(index=1, score=0.9), Scored(index=0, score=0.4)]


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    @contextmanager
    def span(self, name: str, attributes: dict[str, object] | None = None) -> Iterator[None]:
        event = {"name": name, "attributes": attributes or {}}
        try:
            yield
        except Exception as exc:
            event["success"] = False
            event["error_type"] = type(exc).__name__
            raise
        else:
            event["success"] = True
        finally:
            event["duration_ms"] = 0.0
            self.events.append(event)

    def names(self) -> list[str]:
        return [str(event["name"]) for event in self.events]

    def by_name(self, name: str) -> list[dict[str, object]]:
        return [event for event in self.events if event["name"] == name]


def _memory_row(memory_id: str, content: str, distance: float) -> dict[str, object]:
    return {
        "id": memory_id,
        "user_identifier": "alice",
        "kind": "message",
        "content": content,
        "session_id": "s1",
        "role": "user",
        "created_at": "2026-07-09T00:00:00Z",
        "updated_at": "2026-07-09T00:00:00Z",
        "source": "test",
        "tags_json": "[]",
        "metadata_json": "{}",
        "distance": distance,
    }


def test_store_message_records_embed_query_and_vector_load_spans(tmp_path: Path) -> None:
    observer = RecordingObserver()
    embedder = CountingEmbedder()
    client = QueryRecordingClient()
    store = TuringAgentMemory(
        client=client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=embedder,
        reranker=None,
        observer=observer,
    )

    item = store.store_message(
        user_identifier="alice",
        session_id="s1",
        role="user",
        content="observability memory marker",
    )

    assert item.content == "observability memory marker"
    assert "memory.store_message" in observer.names()
    assert "embed" in observer.names()
    assert "arcadedb.query" in observer.names()
    assert "arcadedb.write_batch" in observer.names()
    # ARC-05: the dense embedding is an inline `CREATE VERTEX Memory` property
    # -- no separate CSV vector-load span/step remains (matches this file's
    # already-ported `test_ingest_document_text_records_chunk_and_embed_spans`).
    assert "vector.load" not in observer.names()
    assert observer.by_name("embed")[0]["attributes"]["count"] == 1
    assert all(event["success"] is True for event in observer.events)


def test_search_memory_records_embed_query_and_rerank_spans(tmp_path: Path) -> None:
    observer = RecordingObserver()
    reranker = RecordingReranker()
    client = QueryRecordingClient(
        vector_rows=[
            _memory_row("m1", "first memory about latency", 0.29),
            _memory_row("m2", "second memory about spans", 0.31),
        ]
    )
    store = TuringAgentMemory(
        client=client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=CountingEmbedder(),
        reranker=reranker,  # type: ignore[arg-type]
        observer=observer,
    )

    hits = store.search_memory(user_identifier="alice", query="latency spans", limit=2)

    assert [hit.id for hit in hits] == ["m2", "m1"]
    assert "memory.search" in observer.names()
    assert "embed" in observer.names()
    assert "arcadedb.query" in observer.names()
    assert "rerank" in observer.names()
    assert observer.by_name("rerank")[0]["attributes"]["kind"] == "memory"
    assert observer.by_name("rerank")[0]["attributes"]["count"] == 2


def test_ingest_document_text_records_chunk_and_embed_spans(tmp_path: Path) -> None:
    observer = RecordingObserver()
    client = QueryRecordingClient()
    store = TuringAgentMemory(
        client=client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=CountingEmbedder(),
        reranker=None,
        observer=observer,
    )

    document = store.ingest_document_text(
        user_identifier="alice",
        title="Ops Runbook",
        text="alpha beta gamma delta epsilon zeta eta theta iota kappa lambda",
        document_id="doc-1",
        chunk_chars=20,
    )

    assert document.chunk_count > 1
    assert "document.ingest_text" in observer.names()
    assert "document.chunk" in observer.names()
    assert "embed" in observer.names()
    assert (
        observer.by_name("document.chunk")[0]["attributes"]["chunk_count"] == document.chunk_count
    )
    # ARC-05: chunk embeddings are inline `CREATE VERTEX Chunk` properties --
    # no separate CSV vector-load span/step remains.
    assert "vector.load" not in observer.names()
    chunk_creates = [
        params
        for stmt, params in client.commands
        if stmt.startswith("CREATE VERTEX Chunk") and params is not None
    ]
    assert len(chunk_creates) == document.chunk_count
    assert all("embedding" in params for params in chunk_creates)


def _payload(result: Any) -> Any:
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


class FakeToolMemory:
    def __init__(self) -> None:
        self.observer = RecordingObserver()

    def store_messages(
        self,
        *,
        user_identifier: str,
        messages: list[dict[str, object]],
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str = "",
    ) -> list[MemoryItem]:
        return [
            MemoryItem(
                id="batch-1",
                user_identifier=user_identifier,
                kind="message",
                content=str(messages[0]["content"]),
                session_id=str(messages[0]["session_id"]),
                role=str(messages[0]["role"]),
                score=1.0,
                source=source,
                tags=tags or [],
                metadata=metadata or {},
                expires_at=expires_at,
            )
        ]


def test_mcp_tool_records_latency_span() -> None:
    fake = FakeToolMemory()

    async def run() -> None:
        async with Client(create_mcp_app(fake)) as client:  # type: ignore[arg-type]
            result = _payload(
                await client.call_tool(
                    "memory_store_messages",
                    {
                        "user_identifier": "alice",
                        "messages": [
                            {
                                "session_id": "s1",
                                "role": "user",
                                "content": "batch message over MCP",
                            }
                        ],
                    },
                )
            )
            assert result[0]["id"] == "batch-1"

    asyncio.run(run())

    tool_events = fake.observer.by_name("mcp.tool")
    assert len(tool_events) == 1
    assert tool_events[0]["attributes"]["tool"] == "memory_store_messages"
    assert tool_events[0]["success"] is True
    assert "duration_ms" in tool_events[0]


def test_jsonl_span_recorder_writes_machine_readable_events(tmp_path: Path) -> None:
    from turing_agentmemory_mcp.observability import JsonlSpanRecorder

    path = tmp_path / "events.jsonl"
    recorder = JsonlSpanRecorder(path)

    with recorder.span("embed", {"count": 2, "provider": "local"}):
        pass

    event = json.loads(path.read_text(encoding="utf-8").strip())
    assert event["timestamp"]
    assert event["name"] == "embed"
    assert event["success"] is True
    assert event["duration_ms"] >= 0.0
    assert event["attributes"] == {"count": 2, "provider": "local"}


def test_in_memory_span_recorder_reports_metrics_snapshot() -> None:
    from turing_agentmemory_mcp.observability import InMemorySpanRecorder

    recorder = InMemorySpanRecorder()

    with recorder.span("embed", {"count": 1}):
        pass
    try:
        with recorder.span("embed", {"count": 1}):
            raise RuntimeError("provider down")
    except RuntimeError:
        pass

    metrics = recorder.metrics()
    assert metrics["embed"]["count"] == 2
    assert metrics["embed"]["success_rate"] == 0.5
    assert metrics["embed"]["p50_ms"] >= 0.0
    assert metrics["embed"]["p95_ms"] >= 0.0


def test_span_attributes_drop_content_and_query_values(tmp_path: Path) -> None:
    from turing_agentmemory_mcp.observability import JsonlSpanRecorder

    path = tmp_path / "private-events.jsonl"
    recorder = JsonlSpanRecorder(path)

    with recorder.span(
        "memory.search",
        {
            "query": "private medical query",
            "content": "private memory content",
            "text": "private source text",
            "query_length": 21,
            "count": 2,
        },
    ):
        pass

    event = json.loads(path.read_text(encoding="utf-8"))
    assert event["attributes"] == {"count": 2, "query_length": 21}
    assert "private" not in path.read_text(encoding="utf-8")
