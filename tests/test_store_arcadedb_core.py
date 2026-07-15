"""04-04: store_core seam ported from TuringDB to ArcadeDB (D-08 single-transaction
writes with read-your-writes, D-10 probe-driven readiness).

Every test here runs against `FakeArcadeDBClient` (see
`tests/_store_arcadedb_core_shared.py`), a scripted session-aware in-memory
stand-in for `ArcadeDBClient` -- no live ArcadeDB container is required.
`_StoreCore` (the seam mixin) is instantiated directly, bypassing
`TuringAgentMemory`'s other eight mixins entirely, since this plan ports only
the choke point (`_query`/`_write`/`_write_many`/`bootstrap`/readiness) -- the
mixins themselves still emit TuringDB-shaped query strings until Wave 4.

Tenant-identity/binding-boundary tests (`_require_user`, shared-dependency
bundling) live in `tests/test_store_arcadedb_identity.py` -- split out 05-09
when Task 2's tenant-binding assertions pushed this file over the no-allowlist
600-LOC cap (D-08); both files import their fixtures from
`tests/_store_arcadedb_core_shared.py`.
"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path

import httpx
from _store_arcadedb_core_shared import (
    STORE_CORE_PATH,
    FakeArcadeDBClient,
    TrackingSparseIndex,
    make_store,
)

from turing_agentmemory_mcp.observability import InMemorySpanRecorder
from turing_agentmemory_mcp.store_core import _StoreCore

_STORE_CORE_PATH = STORE_CORE_PATH


# -- Task 1, Test 1: _query delegates to arcadedb_client.query inside an
# arcadedb.query span --


def test_query_delegates_to_client_inside_arcadedb_query_span(tmp_path: Path) -> None:
    client = FakeArcadeDBClient()
    observer = InMemorySpanRecorder()
    store = make_store(client, tmp_path, observer=observer)

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
    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path)

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
    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path)

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
    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path)
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
    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path)

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
    client = FakeArcadeDBClient(probe_sequence=[True])
    store = make_store(client, tmp_path)

    store.bootstrap()

    assert store.runtime_signals.snapshot()["stages"]["graph"]["ready"] is True
    ddl = "\n".join(stmt for stmt, _, _ in client.commands)
    assert "CREATE VERTEX TYPE User IF NOT EXISTS" in ddl
    assert "CREATE INDEX ON Memory (embedding) LSM_VECTOR" in ddl


def test_bootstrap_leaves_graph_not_ready_when_probe_fails(tmp_path: Path) -> None:
    client = FakeArcadeDBClient(probe_sequence=[False])
    store = make_store(client, tmp_path)

    store.bootstrap()

    assert store.runtime_signals.snapshot()["stages"]["graph"]["ready"] is False


# -- Task 2, Test 2: reconnect is a re-probe, no manual load step --


def test_reconnect_reprobe_recovers_readiness_after_transient_failure(tmp_path: Path) -> None:
    client = FakeArcadeDBClient(probe_sequence=[False])
    store = make_store(client, tmp_path)
    store.bootstrap()
    assert store.runtime_signals.snapshot()["stages"]["graph"]["ready"] is False

    client._probe_sequence = [True]

    assert store.reconnect() is True
    assert store.runtime_signals.snapshot()["stages"]["graph"]["ready"] is True


# -- Task 2, Test 3: /health gates on a live probe, not a boot-time latch --


def test_health_returns_503_when_not_ready_and_200_once_probe_recovers(tmp_path: Path) -> None:
    from turing_agentmemory_mcp.server import create_mcp_app

    client = FakeArcadeDBClient(probe_sequence=[False])
    store = make_store(client, tmp_path)
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
    client = FakeArcadeDBClient(probe_sequence=[True])
    sparse = TrackingSparseIndex()
    store = make_store(client, tmp_path, sparse_index=sparse)

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
    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path)

    assert not hasattr(store, "document_graph_batch_chunks")
    assert not hasattr(store, "document_graph_batch_bytes")
    try:
        _StoreCore(
            client,  # type: ignore[arg-type]
            turing_home=tmp_path,
            embedder=object(),  # type: ignore[arg-type]
            reranker=object(),  # type: ignore[arg-type]
            entity_processor=object(),  # type: ignore[arg-type]
            document_graph_batch_chunks=50,  # type: ignore[call-arg]
        )
    except TypeError:
        pass
    else:
        raise AssertionError("document_graph_batch_chunks must no longer be a constructor kwarg")


# LO-01: _ensure_vector_index/_ensure_tenant_vector_index were an explicit
# "back-compat shim for unported mixins (Wave 4)" -- Wave 4 (04-05..04-08) is
# complete and no mixin calls either method anymore. _tenant_vector_index is
# kept: test_batch_memory.py's
# test_tenant_vector_index_names_are_deterministic_and_isolated calls it
# directly.
def test_dead_vector_index_shims_are_removed_but_tenant_vector_index_remains(
    tmp_path: Path,
) -> None:
    client = FakeArcadeDBClient()
    store = make_store(client, tmp_path)

    assert not hasattr(store, "_ensure_vector_index")
    assert not hasattr(store, "_ensure_tenant_vector_index")
    assert hasattr(store, "_tenant_vector_index")
    assert store._tenant_vector_index("base", "alice") == store._tenant_vector_index(
        "base", "alice"
    )


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
