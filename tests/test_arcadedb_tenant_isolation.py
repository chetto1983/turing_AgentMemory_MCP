"""Phase 4 Plan 09, Task 2 Tests 2-3: concurrent multi-tenant isolation guard
(T-04-09-01) exercised directly through the rewritten ArcadeDB memory
write/read query forms (`store_memory_write.py`/`store_memory_read.py`'s
bound-param `CREATE VERTEX`/`SELECT`/`UPDATE` statements) -- the
copy-paste-missed-`user_identifier`-scope failure mode Pitfall 5 warns
about, which has no DB-level defense-in-depth this phase (one shared
ArcadeDB database, app-layer scoping only).

`_ConcurrentFakeArcadeDBClient` is a small, lock-guarded in-memory stand-in
for `ArcadeDBClient` -- interprets exactly the bound-param `CREATE VERTEX`/
`SELECT ... WHERE ... AND ...`/`UPDATE ... WHERE ...` shapes
`store_memory_queries.py` builds, with each `run_in_transaction`/`query`
call holding the lock for its own duration so concurrent threads interleave
at realistic granularity (per-statement, not per-Python-object-mutation)
without a real ArcadeDB container.
"""

from __future__ import annotations

import re
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.governance import NoopAuditSink, NoopRedactor
from turing_agentmemory_mcp.observability import InMemorySpanRecorder
from turing_agentmemory_mcp.store import TuringAgentMemory

_CREATE_VERTEX_RE = re.compile(r"CREATE VERTEX (\w+) SET (.*)$", re.IGNORECASE)
_UPDATE_RE = re.compile(r"UPDATE (\w+) SET (.*?) WHERE (.*)$", re.IGNORECASE)
_SELECT_RE = re.compile(r"SELECT (.*?) FROM (\w+)(?: WHERE (.*))?$", re.IGNORECASE)
_TERM_RE = re.compile(r"\s*(\w+)\s*=\s*(:\w+|'[^']*')\s*")


def _resolve(token: str, params: dict[str, object]) -> object:
    token = token.strip()
    if token.startswith(":"):
        return params.get(token[1:])
    return token[1:-1]  # quoted literal, e.g. 'active'


def _split_where_terms(text: str) -> list[tuple[str, str]]:
    # WHERE clauses are AND-joined (`user_identifier = :x AND status = 'active'`).
    return [
        _TERM_RE.match(part.strip()).groups()
        for part in re.split(r"\bAND\b", text, flags=re.IGNORECASE)
    ]


def _split_set_terms(text: str) -> list[tuple[str, str]]:
    # SET clauses are comma-joined (`id = :id, user_identifier = :user_identifier, ...`).
    return [_TERM_RE.match(part.strip()).groups() for part in text.split(",")]


class _ConcurrentFakeArcadeDBClient:
    """Session-agnostic (no session-header emulation needed for this test --
    every `_write_many` batch here is a single CREATE/UPDATE), lock-guarded
    in-memory stand-in for `ArcadeDBClient`. Interprets `CREATE VERTEX <Type>
    SET ...`, `SELECT ... FROM <Type> WHERE <AND-terms>`, `UPDATE <Type> SET
    ... WHERE <AND-terms>`; any `CREATE EDGE ...` statement is accepted and
    discarded (edges are not read back by this test -- only tenant-scoped
    Memory rows are)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._rows: list[dict[str, object]] = []

    def is_ready(self) -> bool:
        return True

    def begin(self) -> str:
        return "session"

    def commit(self, session_id: str) -> None:
        return None

    def rollback(self, session_id: str) -> None:
        return None

    def run_in_transaction(self, body: Any, *, commit_retries: int | None = None) -> Any:
        with self._lock:
            return body("session")

    def query(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        with self._lock:
            return self._select(statement, params or {})

    def command(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        with self._lock:
            return self._apply(statement, params or {})

    def _apply(self, statement: str, params: dict[str, object]) -> list[dict[str, object]]:
        upper = statement.strip().upper()
        if upper.startswith("SELECT"):
            return self._select(statement, params)
        if upper.startswith("CREATE EDGE") or upper.startswith("CREATE VERTEX TYPE"):
            return []  # not read back by this test; accept and discard
        create_match = _CREATE_VERTEX_RE.match(statement.strip())
        if create_match:
            type_name, set_clause = create_match.groups()
            row: dict[str, object] = {"_type": type_name}
            for field, rhs in _split_set_terms(set_clause):
                row[field] = _resolve(rhs, params)
            self._rows.append(row)
            return []
        update_match = _UPDATE_RE.match(statement.strip())
        if update_match:
            type_name, set_clause, where_clause = update_match.groups()
            set_terms = _split_set_terms(set_clause)
            where_terms = _split_where_terms(where_clause)
            for row in self._rows:
                if row.get("_type") != type_name:
                    continue
                if not all(row.get(field) == _resolve(rhs, params) for field, rhs in where_terms):
                    continue
                for field, rhs in set_terms:
                    row[field] = _resolve(rhs, params)
            return []
        return []

    def _select(self, statement: str, params: dict[str, object]) -> list[dict[str, object]]:
        match = _SELECT_RE.match(statement.strip())
        if not match:
            return []
        fields_text, type_name, where_clause = match.groups()
        where_terms = _split_where_terms(where_clause) if where_clause else []
        fields = [item.strip() for item in fields_text.split(",")]
        results: list[dict[str, object]] = []
        for row in self._rows:
            if row.get("_type") != type_name:
                continue
            if not all(row.get(field) == _resolve(rhs, params) for field, rhs in where_terms):
                continue
            results.append({field: row.get(field) for field in fields})
        return results


class CountingEmbedder:
    dimensions = 3

    def embed(self, text: str) -> list[float]:
        return [float(len(text)), 1.0, 0.0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


def _make_store(client: _ConcurrentFakeArcadeDBClient, tmp_path: Path) -> TuringAgentMemory:
    return TuringAgentMemory(
        client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=CountingEmbedder(),
        reranker=None,
        redactor=NoopRedactor(),
        audit_sink=NoopAuditSink(),
        observer=InMemorySpanRecorder(),
    )


def _write_many_messages(store: TuringAgentMemory, *, user_identifier: str, count: int) -> None:
    for idx in range(count):
        store.store_message(
            user_identifier=user_identifier,
            session_id="concurrent",
            role="user",
            content=f"{user_identifier} marker {idx} distinctive tenant payload",
        )


def test_concurrent_multi_tenant_writes_never_leak_across_tenants(tmp_path: Path) -> None:
    client = _ConcurrentFakeArcadeDBClient()
    store = _make_store(client, tmp_path)

    threads = [
        threading.Thread(
            target=_write_many_messages, kwargs={"store": store, "user_identifier": t, "count": 20}
        )
        for t in ("alice", "bob")
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    alice_items = store.list_memories(user_identifier="alice", limit=50)
    bob_items = store.list_memories(user_identifier="bob", limit=50)

    assert len(alice_items) == 20
    assert len(bob_items) == 20
    assert all(item.user_identifier == "alice" for item in alice_items)
    assert all(item.user_identifier == "bob" for item in bob_items)
    assert all("alice marker" in item.content for item in alice_items)
    assert all("bob marker" in item.content for item in bob_items)


def test_concurrent_interleaved_reads_never_observe_cross_tenant_rows(tmp_path: Path) -> None:
    client = _ConcurrentFakeArcadeDBClient()
    store = _make_store(client, tmp_path)
    _write_many_messages(store, user_identifier="alice", count=10)
    _write_many_messages(store, user_identifier="bob", count=10)

    observed: list[tuple[str, list[str]]] = []
    observed_lock = threading.Lock()

    def reader(tenant: str) -> None:
        for _ in range(25):
            items = store.list_memories(user_identifier=tenant, limit=50)
            with observed_lock:
                observed.append((tenant, [item.user_identifier for item in items]))

    def writer(tenant: str) -> None:
        _write_many_messages(store, user_identifier=tenant, count=5)

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(reader, "alice"),
            pool.submit(reader, "bob"),
            pool.submit(writer, "alice"),
            pool.submit(writer, "bob"),
        ]
        for future in futures:
            future.result()

    assert observed, "reader threads must have observed at least one read"
    for tenant, seen_identifiers in observed:
        assert all(identifier == tenant for identifier in seen_identifiers), (
            f"tenant {tenant} observed a cross-tenant row: {seen_identifiers}"
        )


def test_empty_user_identifier_fails_closed_on_the_concurrent_path(tmp_path: Path) -> None:
    client = _ConcurrentFakeArcadeDBClient()
    store = _make_store(client, tmp_path)
    _write_many_messages(store, user_identifier="alice", count=3)

    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def attempt_empty_identifier_write() -> None:
        try:
            store.store_message(
                user_identifier="",
                session_id="s",
                role="user",
                content="should never be written",
            )
        except BaseException as exc:  # noqa: BLE001 - captured across threads for assertion
            with errors_lock:
                errors.append(exc)

    def attempt_empty_identifier_read() -> None:
        try:
            store.list_memories(user_identifier="")
        except BaseException as exc:  # noqa: BLE001 - captured across threads for assertion
            with errors_lock:
                errors.append(exc)

    threads = [threading.Thread(target=attempt_empty_identifier_write) for _ in range(3)] + [
        threading.Thread(target=attempt_empty_identifier_read) for _ in range(3)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(errors) == 6
    assert all(isinstance(exc, ValueError) for exc in errors)
    # No stray empty-identifier row was written despite the concurrent attempts.
    assert all(
        row.get("user_identifier") != "" for row in client._rows if row.get("_type") == "Memory"
    )
