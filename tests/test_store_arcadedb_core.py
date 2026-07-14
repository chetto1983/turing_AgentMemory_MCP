"""04-04: store_core seam ported from TuringDB to ArcadeDB (D-08 single-transaction
writes with read-your-writes, D-10 probe-driven readiness).

Every test here runs against `_FakeArcadeDBClient`, a scripted session-aware
in-memory stand-in for `ArcadeDBClient` (mirrors the `_FakeArcadeDBClient`
convention already established in `tests/test_arcadedb_schema.py`) -- no live
ArcadeDB container is required. `_StoreCore` (the seam mixin) is instantiated
directly, bypassing `TuringAgentMemory`'s other eight mixins entirely, since
this plan ports only the choke point (`_query`/`_write`/`_write_many`/
`bootstrap`/readiness) -- the mixins themselves still emit TuringDB-shaped
query strings until Wave 4.

`server.py` still imports `from turingdb import TuringDB` until this same
plan's Task 3 rewires `store_from_env`; the `turingdb` package has no Windows
wheel, so the health tests below stub `sys.modules["turingdb"]` first,
matching the convention already used by `tests/test_runtime_pipeline.py` and
siblings.
"""

from __future__ import annotations

import asyncio
import re
import sys
import types
from pathlib import Path
from typing import Any

import httpx

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.observability import InMemorySpanRecorder
from turing_agentmemory_mcp.store_core import _StoreCore

_STORE_CORE_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp" / "store_core.py"
)


class _StubEmbedder:
    dimensions = 3


class _TrackingSparseIndex:
    """Fake `SparseIndex` -- proves `bootstrap()` no longer replays the FTS5
    outbox (ARC-06: ArcadeDB's native Lucene/LSM_SPARSE_VECTOR is ACID, no
    crash-recovery replay step needed)."""

    def __init__(self) -> None:
        self.initialize_called = False
        self.replay_called = False

    def initialize(self) -> None:
        self.initialize_called = True

    def replay(self) -> None:
        self.replay_called = True

    def status(self) -> dict[str, object]:
        return {"status": "ready"}


class _FakeArcadeDBClient:
    """Session-aware in-memory stand-in for `ArcadeDBClient`.

    Proves the seam's transaction plumbing (D-08) without a live container:
    `command()` calls are visible to a later `SELECT`-shaped `command()`/
    `query()` in the SAME session before commit (read-your-writes, spike-
    confirmed A5), but NOT to a different/no session, matching the real
    session-header semantics documented in `arcadedb_client.py`.
    """

    def __init__(self, *, probe_sequence: list[bool] | None = None) -> None:
        self.commands: list[tuple[str, dict[str, object] | None, str | None]] = []
        self.queries: list[tuple[str, dict[str, object] | None]] = []
        self.begin_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0
        self._committed: list[dict[str, object]] = []
        self._session_rows: dict[str, list[dict[str, object]]] = {}
        self._session_counter = 0
        self._probe_sequence = list(probe_sequence) if probe_sequence is not None else None

    def query(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        self.queries.append((statement, params))
        return self._select(params, session_id)

    def command(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        self.commands.append((statement, params, session_id))
        upper = statement.strip().upper()
        if upper.startswith("SELECT"):
            rows = self._select(params, session_id)
            if params and not rows:
                raise AssertionError(
                    f"read-your-writes failed: no row visible for {params} "
                    f"in session {session_id!r}"
                )
            return rows
        if upper.startswith("CREATE VERTEX") and params:
            bucket = session_id or "__no_session__"
            self._session_rows.setdefault(bucket, []).append(dict(params))
        return []

    def _select(
        self, params: dict[str, object] | None, session_id: str | None
    ) -> list[dict[str, object]]:
        bucket = session_id or "__no_session__"
        visible = list(self._committed) + list(self._session_rows.get(bucket, []))
        if not params:
            return visible
        return [row for row in visible if all(row.get(k) == v for k, v in params.items())]

    def begin(self) -> str:
        self.begin_calls += 1
        self._session_counter += 1
        session_id = f"session-{self._session_counter}"
        self._session_rows[session_id] = []
        return session_id

    def commit(self, session_id: str) -> None:
        self.commit_calls += 1
        self._committed.extend(self._session_rows.pop(session_id, []))

    def rollback(self, session_id: str) -> None:
        self.rollback_calls += 1
        self._session_rows.pop(session_id, None)

    def run_in_transaction(self, body: Any, *, commit_retries: int | None = None) -> Any:
        session_id = self.begin()
        try:
            result = body(session_id)
        except Exception:
            self.rollback(session_id)
            raise
        self.commit(session_id)
        return result

    def is_ready(self) -> bool:
        # Pop queued probe results one at a time until a single value remains,
        # then hold that last value persistently (rather than defaulting back
        # to True) -- lets a test script "N failures then recovery" while
        # still supporting repeated /health-style polling of a steady state.
        if len(self._probe_sequence or []) > 1:
            return self._probe_sequence.pop(0)
        if self._probe_sequence:
            return self._probe_sequence[0]
        return True


def _make_store(
    client: _FakeArcadeDBClient,
    tmp_path: Path,
    *,
    observer: InMemorySpanRecorder | None = None,
    sparse_index: Any | None = None,
) -> _StoreCore:
    return _StoreCore(
        client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=_StubEmbedder(),  # type: ignore[arg-type]
        reranker=object(),  # type: ignore[arg-type]
        entity_processor=object(),  # type: ignore[arg-type]
        observer=observer,
        sparse_index=sparse_index,
    )


# -- Task 1, Test 1: _query delegates to arcadedb_client.query inside an
# arcadedb.query span --


def test_query_delegates_to_client_inside_arcadedb_query_span(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    observer = InMemorySpanRecorder()
    store = _make_store(client, tmp_path, observer=observer)

    rows = store._query(
        "SELECT identifier FROM User WHERE identifier = :identifier",
        operation="user.ensure",
        params={"identifier": "alice"},
    )

    assert rows == []
    assert client.queries == [
        ("SELECT identifier FROM User WHERE identifier = :identifier", {"identifier": "alice"})
    ]
    span_names = [str(event["name"]) for event in observer.events]
    assert "arcadedb.query" in span_names
    assert "turingdb.query" not in span_names


# -- Task 1, Test 2: _write_many opens ONE managed transaction and commits once --


def test_write_many_opens_one_managed_transaction_and_commits_once(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path)

    store._write_many(
        [
            ("CREATE VERTEX Chunk SET id = :id", {"id": "c1"}),
            ("CREATE VERTEX Chunk SET id = :id", {"id": "c2"}),
            ("CREATE VERTEX Chunk SET id = :id", {"id": "c3"}),
        ]
    )

    assert client.begin_calls == 1
    assert client.commit_calls == 1
    assert client.rollback_calls == 0
    session_ids = {session_id for _, _, session_id in client.commands if session_id}
    assert session_ids == {"session-1"}, "every statement in one batch must share one session"


# -- Task 1, Test 3: read-your-writes within the same batch --


def test_write_many_read_your_writes_within_same_transaction(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path)

    # If the seam opened a separate transaction per statement (the retired
    # TuringDB submit-before-match model), the SELECT below would not see the
    # CREATE's row and the fake client would raise -- this asserts it doesn't.
    store._write_many(
        [
            ("CREATE VERTEX Chunk SET id = :id", {"id": "chunk-1"}),
            ("SELECT id FROM Chunk WHERE id = :id", {"id": "chunk-1"}),
        ]
    )

    assert client.begin_calls == 1
    assert client.commit_calls == 1


# -- Task 1, Test 4: _ensure_user binds the identifier as a param --


def test_ensure_user_binds_identifier_as_param_not_a_string_literal(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path)
    tricky_identifier = "o'brien\" ; DROP TABLE User; --"

    store._ensure_user(tricky_identifier)

    select_stmt, select_params = client.queries[0]
    assert tricky_identifier not in select_stmt
    assert select_params == {"identifier": tricky_identifier}

    create_calls = [
        entry
        for entry in client.commands
        if entry[0].strip().upper().startswith("CREATE VERTEX USER")
    ]
    assert create_calls, "expected a CREATE VERTEX User write"
    create_stmt, create_params, session_id = create_calls[0]
    assert tricky_identifier not in create_stmt
    assert create_params == {"identifier": tricky_identifier}
    assert session_id is not None

    # Idempotent: a second call sees the now-committed row via the bound
    # param lookup and does not attempt a second CREATE.
    store._ensure_user(tricky_identifier)
    create_calls_after = [
        entry
        for entry in client.commands
        if entry[0].strip().upper().startswith("CREATE VERTEX USER")
    ]
    assert len(create_calls_after) == 1


# -- Task 1, Test 5: no CSV vector-load mechanism remains --


def test_no_csv_vector_load_mechanism_remains(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path)

    assert not hasattr(store, "_load_vectors")

    store._write_many(
        [
            (
                "CREATE VERTEX Chunk SET id = :id, embedding = :embedding",
                {"id": "c1", "embedding": [0.1, 0.2]},
            )
        ]
    )

    assert list(store.data_dir.glob("*.csv")) == []


def test_seam_contains_no_turingdb_write_primitives_or_csv_vector_load() -> None:
    source = _STORE_CORE_PATH.read_text(encoding="utf-8")
    for forbidden in ("new_change", "CHANGE SUBMIT", "checkout(", "LOAD VECTOR", "from turingdb"):
        assert forbidden not in source, f"forbidden TuringDB primitive still present: {forbidden!r}"
    assert "arcadedb_client" in source or "ArcadeDBClient" in source


def test_records_accepts_plain_list_of_dicts_not_a_dataframe() -> None:
    rows = [{"id": "a", "score": 1.0}, {"id": "b", "score": float("nan")}]

    cleaned = _StoreCore._records(rows)

    assert cleaned[0] == {"id": "a", "score": 1.0}
    assert cleaned[1]["score"] is None


# -- Task 2, Test 1: bootstrap() sets the graph stage from a live probe --


def test_bootstrap_sets_graph_ready_when_probe_succeeds(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient(probe_sequence=[True])
    store = _make_store(client, tmp_path)

    store.bootstrap()

    assert store.runtime_signals.snapshot()["stages"]["graph"]["ready"] is True
    ddl = "\n".join(stmt for stmt, _, _ in client.commands)
    assert "CREATE VERTEX TYPE User IF NOT EXISTS" in ddl
    assert "CREATE INDEX ON Memory (embedding) LSM_VECTOR" in ddl


def test_bootstrap_leaves_graph_not_ready_when_probe_fails(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient(probe_sequence=[False])
    store = _make_store(client, tmp_path)

    store.bootstrap()

    assert store.runtime_signals.snapshot()["stages"]["graph"]["ready"] is False


# -- Task 2, Test 2: reconnect is a re-probe, no manual load step --


def test_reconnect_reprobe_recovers_readiness_after_transient_failure(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient(probe_sequence=[False])
    store = _make_store(client, tmp_path)
    store.bootstrap()
    assert store.runtime_signals.snapshot()["stages"]["graph"]["ready"] is False

    client._probe_sequence = [True]

    assert store.reconnect() is True
    assert store.runtime_signals.snapshot()["stages"]["graph"]["ready"] is True


# -- Task 2, Test 3: /health gates on a live probe, not a boot-time latch --


def test_health_returns_503_when_not_ready_and_200_once_probe_recovers(tmp_path: Path) -> None:
    from turing_agentmemory_mcp.server import create_mcp_app

    client = _FakeArcadeDBClient(probe_sequence=[False])
    store = _make_store(client, tmp_path)
    store.bootstrap()
    app = create_mcp_app(store)  # type: ignore[arg-type]

    async def _get_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=app.http_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            return await ac.get("/health")

    response = asyncio.run(_get_health())
    assert response.status_code == 503
    assert response.json()["status"] == "degraded"

    client._probe_sequence = [True]
    response = asyncio.run(_get_health())
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# -- Task 2, Test 4: bootstrap() no longer replays the FTS5 outbox (ARC-06) --


def test_bootstrap_does_not_replay_fts5_outbox(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient(probe_sequence=[True])
    sparse = _TrackingSparseIndex()
    store = _make_store(client, tmp_path, sparse_index=sparse)

    store.bootstrap()

    assert sparse.initialize_called is False
    assert sparse.replay_called is False


def test_readiness_path_has_no_load_graph_or_bare_exception_swallow() -> None:
    source = _STORE_CORE_PATH.read_text(encoding="utf-8")
    assert "load_graph" not in source
    assert "list_loaded_graphs" not in source
    assert re.search(r"except Exception:\s*$", source, flags=re.MULTILINE) is None


def test_sparse_outbox_replay_calls_absent_from_source() -> None:
    source = _STORE_CORE_PATH.read_text(encoding="utf-8")
    assert "sparse_index.initialize" not in source
    assert "sparse_index.replay" not in source


# MD-01: document_graph_batch_chunks/document_graph_batch_bytes were validated
# and env-wired but never consulted -- every document was already committed
# as one unbounded transaction regardless of the setting. Removed rather than
# wired into real batch splitting, since splitting would open a
# partial-document-visible-mid-ingest window with no status guard to close it.
def test_document_graph_batch_knobs_are_removed(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path)

    assert not hasattr(store, "document_graph_batch_chunks")
    assert not hasattr(store, "document_graph_batch_bytes")
    try:
        _StoreCore(
            client,  # type: ignore[arg-type]
            turing_home=tmp_path,
            embedder=_StubEmbedder(),  # type: ignore[arg-type]
            reranker=object(),  # type: ignore[arg-type]
            entity_processor=object(),  # type: ignore[arg-type]
            document_graph_batch_chunks=50,  # type: ignore[call-arg]
        )
    except TypeError:
        pass
    else:
        raise AssertionError("document_graph_batch_chunks must no longer be a constructor kwarg")


def test_document_graph_batch_knobs_absent_from_source_and_env_wiring() -> None:
    server_path = (
        Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp" / "server.py"
    )
    for path in (_STORE_CORE_PATH, server_path):
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "document_graph_batch_chunks",
            "document_graph_batch_bytes",
            "AGENTMEMORY_DOCUMENT_GRAPH_BATCH_CHUNKS",
            "AGENTMEMORY_DOCUMENT_GRAPH_BATCH_BYTES",
        ):
            assert forbidden not in source, f"{path.name} still references {forbidden!r}"
