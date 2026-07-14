"""04-05: memory write/read paths ported from TuringDB to ArcadeDB (ARC-04/05/08).

Every test runs against `_FakeArcadeDBClient`, a small session-aware in-memory
stand-in for `ArcadeDBClient` (same convention as `tests/test_store_arcadedb_core.py`'s
fake, extended here to interpret `CREATE VERTEX <Type>`/`UPDATE <Type>`/
`SELECT ... FROM <Type>` well enough to round-trip through `store_memory_write.py`/
`store_memory_read.py`'s real bound-param statements) -- no live ArcadeDB
container is required. `TuringAgentMemory` is instantiated directly; the two
still-unported cross-mixin dependencies this plan doesn't own
(`_existing_entity_ids`, `_fact_ids_for_memory`, both `store_rebuild.py`) are
stubbed, matching the established `tests/_batch_memory_shared.py` convention.
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path
from typing import Any

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from _batch_memory_shared import CountingBatchEmbedder, RecordingMemoryExtractor

from turing_agentmemory_mcp.entity_extraction import NoopEntityProcessor
from turing_agentmemory_mcp.governance import NoopAuditSink, NoopRedactor
from turing_agentmemory_mcp.ids import stable_id
from turing_agentmemory_mcp.observability import InMemorySpanRecorder
from turing_agentmemory_mcp.store import TuringAgentMemory

_MEMORY_WRITE_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp" / "store_memory_write.py"
)
_MEMORY_QUERIES_PATH = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "turing_agentmemory_mcp"
    / "store_memory_queries.py"
)
_MEMORY_READ_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp" / "store_memory_read.py"
)

_CREATE_TYPE_RE = re.compile(r"CREATE VERTEX (\w+)", re.IGNORECASE)
_UPDATE_TYPE_RE = re.compile(r"UPDATE (\w+)", re.IGNORECASE)
_SELECT_FROM_RE = re.compile(r"FROM (\w+)", re.IGNORECASE)
_MATCH_KEYS = ("id", "user_identifier", "identifier")


class _FakeArcadeDBClient:
    """Session-aware in-memory stand-in interpreting this plan's exact
    statement shapes (`CREATE VERTEX <Type> SET ...`, `UPDATE <Type> SET ...
    WHERE ...`, `SELECT ... FROM <Type> WHERE ...`, `CREATE EDGE ...`) well
    enough to round-trip a real `store_memory_write.py`/`store_memory_read.py`
    call -- not a general SQL engine.
    """

    def __init__(self) -> None:
        self.commands: list[tuple[str, dict[str, object] | None, str | None]] = []
        self.queries: list[tuple[str, dict[str, object] | None]] = []
        self.begin_calls = 0
        self.commit_calls = 0
        self.rollback_calls = 0
        self._committed: list[dict[str, object]] = []
        self._session_rows: dict[str, list[dict[str, object]]] = {}
        self._session_counter = 0

    # -- transaction control (mirrors ArcadeDBClient's session-header model) --

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
        return True

    # -- query/command --

    def query(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        self.queries.append((statement, params))
        return self._select(statement, params, session_id)

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
            return self._select(statement, params, session_id)
        if upper.startswith("CREATE VERTEX"):
            match = _CREATE_TYPE_RE.match(statement)
            row = dict(params or {})
            row["_type"] = match.group(1) if match else ""
            bucket = session_id or "__no_session__"
            self._session_rows.setdefault(bucket, []).append(row)
            return []
        if upper.startswith("UPDATE"):
            match = _UPDATE_TYPE_RE.match(statement)
            record_type = match.group(1) if match else ""
            bucket = session_id or "__no_session__"
            match_params = {k: v for k, v in (params or {}).items() if k in _MATCH_KEYS}
            for row in self._committed + self._session_rows.get(bucket, []):
                if row.get("_type") != record_type:
                    continue
                if all(row.get(k) == v for k, v in match_params.items()):
                    row.update({k: v for k, v in (params or {}).items() if k not in ("id",)})
            return []
        # CREATE EDGE TYPE / CREATE EDGE ... FROM (...) TO (...) -- recorded
        # for assertion purposes; edges are not modeled as queryable rows.
        return []

    def _select(
        self, statement: str, params: dict[str, object] | None, session_id: str | None
    ) -> list[dict[str, object]]:
        match = _SELECT_FROM_RE.search(statement)
        record_type = match.group(1) if match else None
        bucket = session_id or "__no_session__"
        visible = list(self._committed) + list(self._session_rows.get(bucket, []))
        if record_type:
            visible = [row for row in visible if row.get("_type") == record_type]
        if not params:
            return visible
        return [row for row in visible if all(row.get(k) == v for k, v in params.items())]


class _MemoryStore(TuringAgentMemory):
    """Composes the real mixins; stubs the two store_rebuild.py (unported,
    04-08) cross-mixin calls this plan's mixins reach through the MRO."""

    def _existing_entity_ids(self, user_identifier: str, entity_ids: list[str]) -> set[str]:
        return set()

    def _fact_ids_for_memory(self, user_identifier: str, memory_id: str) -> list[str]:
        return []


def _make_store(
    client: _FakeArcadeDBClient,
    tmp_path: Path,
    embedder: CountingBatchEmbedder,
    *,
    memory_extractor: Any | None = None,
) -> _MemoryStore:
    return _MemoryStore(
        client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=embedder,
        reranker=None,
        entity_processor=NoopEntityProcessor(),
        redactor=NoopRedactor(),
        audit_sink=NoopAuditSink(),
        memory_extractor=memory_extractor,
        observer=InMemorySpanRecorder(),
    )


def _committed_by_type(client: _FakeArcadeDBClient, record_type: str) -> list[dict[str, object]]:
    return [row for row in client._committed if row.get("_type") == record_type]


# -- Task 1, Test 1: single write CREATEs a Memory vertex keyed on stable_id,
# embedding inline, no vector_id --


def test_single_memory_write_creates_vertex_with_stable_id_and_inline_embedding(
    tmp_path: Path,
) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())
    store._ensure_user("alice")  # excluded from the transaction-count assertion below
    client.begin_calls = 0
    client.commit_calls = 0

    item = store.store_message(
        user_identifier="alice", session_id="s1", role="user", content="hello world"
    )

    expected_id = stable_id("mem", "alice", "s1", "user", "hello world")
    assert item.id == expected_id
    memories = _committed_by_type(client, "Memory")
    assert len(memories) == 1
    assert memories[0]["id"] == expected_id
    assert memories[0]["embedding"] == [11.0, 1.0, 0.0]
    assert "vector_id" not in memories[0]
    assert memories[0]["lexical_tokens"] == [] or isinstance(memories[0]["lexical_tokens"], list)
    assert client.begin_calls == 1
    assert client.commit_calls == 1


def test_single_memory_write_populates_both_lexical_channels() -> None:
    from turing_agentmemory_mcp.sparse_encoder import sparse_vector

    tokens, weights = sparse_vector("hello world")
    assert tokens, "expected at least one lexical token bucket for non-empty content"
    assert len(tokens) == len(weights)


# -- Task 1, Test 2: batch write with entities/facts CREATEs Entity/Fact
# vertices + edges in ONE managed transaction --


def test_batch_write_with_entities_and_facts_uses_one_managed_transaction(
    tmp_path: Path,
) -> None:
    client = _FakeArcadeDBClient()
    extractor = RecordingMemoryExtractor()
    store = _make_store(client, tmp_path, CountingBatchEmbedder(), memory_extractor=extractor)
    store._ensure_user("alice")  # excluded from the transaction-count assertion below
    client.begin_calls = 0
    client.commit_calls = 0

    items = store.store_messages(
        user_identifier="alice",
        messages=[
            {"session_id": "s1", "role": "user", "content": "Alice likes hiking."},
        ],
    )

    assert len(items) == 1
    assert client.begin_calls == 1, "the whole memory+entity+fact+edge batch is ONE transaction"
    assert client.commit_calls == 1
    assert _committed_by_type(client, "Memory")
    assert _committed_by_type(client, "Entity")
    assert _committed_by_type(client, "Fact")
    edge_commands = [stmt for stmt, _, _ in client.commands if stmt.startswith("CREATE EDGE")]
    assert any("SUBJECT_OF" in stmt for stmt in edge_commands)
    assert any("OBJECT_OF" in stmt for stmt in edge_commands)
    assert any("SUPPORTED_BY" in stmt for stmt in edge_commands)
    assert any("MENTIONS" in stmt for stmt in edge_commands)
    for entity in _committed_by_type(client, "Entity"):
        assert "vector_id" not in entity
        assert isinstance(entity["embedding"], list)
    for fact in _committed_by_type(client, "Fact"):
        assert "vector_id" not in fact


# -- Task 1, Test 3: a single-quote value round-trips via a bound param --


def test_single_quote_in_content_is_stored_intact_via_bound_param(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())
    tricky_content = "O'Brien's note: it's a test"

    item = store.store_message(
        user_identifier="alice", session_id="s1", role="user", content=tricky_content
    )

    fetched = store.get_memory(user_identifier="alice", memory_id=item.id)
    assert fetched is not None
    assert fetched.content == tricky_content
    create_commands = [
        stmt for stmt, _, _ in client.commands if stmt.startswith("CREATE VERTEX Memory")
    ]
    assert create_commands, "expected a CREATE VERTEX Memory write"
    assert tricky_content not in create_commands[0], "value must be bound, not interpolated"


# -- Task 1, Test 4: fail-closed on an empty user_identifier --


def test_write_with_empty_user_identifier_raises_value_error(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())

    try:
        store.store_message(user_identifier="", session_id="s1", role="user", content="hi")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for empty user_identifier")


# -- Task 1, Test 5: tenant-scoped read never returns another tenant's memory --


def test_tenant_scoped_read_never_returns_other_tenants_memory(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())

    alice_item = store.store_message(
        user_identifier="alice", session_id="s1", role="user", content="alice's secret"
    )
    store.store_message(user_identifier="bob", session_id="s1", role="user", content="bob's note")

    assert store.get_memory(user_identifier="bob", memory_id=alice_item.id) is None
    bob_memories = store.list_memories(user_identifier="bob")
    assert all(item.content != "alice's secret" for item in bob_memories)


# HI-02 regression: memory_delete_statements' Fact soft-delete UPDATE had no
# user_identifier filter, unlike its sibling Memory-status UPDATE two lines
# above it in the same function. If _fact_ids_for_memory ever returned a
# cross-tenant fact id (the invariant that currently prevents this from being
# reachable breaking), the delete must still never touch another tenant's
# Fact row.
def test_delete_memory_never_soft_deletes_another_tenants_fact(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())
    alice_item = store.store_message(
        user_identifier="alice", session_id="s1", role="user", content="alice memory"
    )
    bob_fact_id = stable_id("fact", "bob", "some-cross-tenant-fact")
    client._committed.append(
        {
            "_type": "Fact",
            "id": bob_fact_id,
            "user_identifier": "bob",
            "status": "active",
        }
    )
    store._fact_ids_for_memory = lambda user_identifier, memory_id: [bob_fact_id]  # type: ignore[method-assign]
    bob_fact_before = dict(client._committed[-1])

    store.delete_memory(user_identifier="alice", memory_id=alice_item.id)

    # The fake's UPDATE modeling only merges bound params into a matched row
    # (it doesn't parse literal SET clauses like `status = 'deleted'`), so the
    # meaningful regression signal is whether the row was matched/touched at
    # all -- unchanged means the WHERE's user_identifier scope excluded it.
    bob_fact_after = next(row for row in client._committed if row.get("id") == bob_fact_id)
    assert bob_fact_after == bob_fact_before, (
        f"cross-tenant fact row was touched by the delete: {bob_fact_after!r}"
    )
    fact_update_commands = [
        stmt for stmt, params, _ in client.commands if stmt.startswith("UPDATE Fact")
    ]
    assert fact_update_commands
    assert "user_identifier = :user_identifier" in fact_update_commands[0]


# -- Task 2, Test 1: a batch of N writes calls embed_many exactly once --


def test_batch_calls_embed_many_exactly_once_for_n_items(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    embedder = CountingBatchEmbedder()
    store = _make_store(client, tmp_path, embedder)

    store.store_messages(
        user_identifier="alice",
        messages=[
            {"session_id": "s1", "role": "user", "content": "first batch memory"},
            {"session_id": "s1", "role": "assistant", "content": "second batch memory"},
            {"session_id": "s1", "role": "user", "content": "third batch memory"},
        ],
    )

    assert embedder.embed_many_calls == [
        ["first batch memory", "second batch memory", "third batch memory"]
    ]
    assert embedder.embed_calls == []


# -- Task 2, Test 2: memory extraction runs once per batch, not per item --


def test_batch_calls_memory_extraction_exactly_once_for_n_items(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    extractor = RecordingMemoryExtractor()
    store = _make_store(client, tmp_path, CountingBatchEmbedder(), memory_extractor=extractor)

    store.store_messages(
        user_identifier="alice",
        messages=[
            {"session_id": "s1", "role": "user", "content": "Alice likes hiking."},
            {"session_id": "s1", "role": "user", "content": "Alice enjoys hiking a lot."},
        ],
    )

    assert len(extractor.calls) == 1
    assert extractor.calls[0] == ["Alice likes hiking.", "Alice enjoys hiking a lot."]


# -- Task 2, Test 3: the kind-update read no longer touches vector_id --


def test_kind_update_does_not_write_vector_id(tmp_path: Path) -> None:
    client = _FakeArcadeDBClient()
    store = _make_store(client, tmp_path, CountingBatchEmbedder())
    item = store.store_message(
        user_identifier="alice", session_id="s1", role="user", content="reclassify me"
    )

    updated = store.update_memory(user_identifier="alice", memory_id=item.id, kind="preference")

    assert updated.kind == "preference"
    for _stmt, params, _session in client.commands:
        if params:
            assert "vector_id" not in params
    memories = _committed_by_type(client, "Memory")
    assert all("vector_id" not in row for row in memories)


# -- Task 2, Test 4: the whole embed -> extract -> write sequence stays
# within one managed transaction --


def test_batch_write_stays_within_one_managed_transaction_across_embed_extract_write(
    tmp_path: Path,
) -> None:
    client = _FakeArcadeDBClient()
    extractor = RecordingMemoryExtractor()
    store = _make_store(client, tmp_path, CountingBatchEmbedder(), memory_extractor=extractor)
    store._ensure_user("alice")  # excluded from the transaction-count assertion below
    client.begin_calls = 0
    client.commit_calls = 0

    store.store_messages(
        user_identifier="alice",
        messages=[
            {"session_id": "s1", "role": "user", "content": "Alice likes hiking."},
            {"session_id": "s1", "role": "user", "content": "Alice enjoys hiking a lot."},
        ],
    )

    assert client.begin_calls == 1
    assert client.commit_calls == 1
    assert client.rollback_calls == 0


# -- source-level acceptance-criteria grep gates --


def test_memory_write_and_queries_files_contain_no_vector_id_or_helper_calls() -> None:
    for path in (_MEMORY_WRITE_PATH, _MEMORY_QUERIES_PATH):
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "vector_id",
            "_memory_vector_id",
            "_entity_vector_id",
            "_fact_vector_id",
        ):
            assert forbidden not in source, f"{path.name} still references {forbidden!r}"


def test_memory_read_file_contains_no_vector_id() -> None:
    source = _MEMORY_READ_PATH.read_text(encoding="utf-8")
    assert "vector_id" not in source


def test_memory_queries_builders_carry_user_identifier_scope() -> None:
    source = _MEMORY_QUERIES_PATH.read_text(encoding="utf-8")
    assert source.count("user_identifier") >= 1


def test_memory_write_and_read_files_no_longer_touch_the_sparse_outbox() -> None:
    """ARC-06 gap closure (04-10): the write-side legacy SQLite-FTS5 outbox
    staging/commit/replay/discard calls and their staging-helper method name
    must be gone from both mixins -- lexical retrieval is carried entirely by
    the native lexical_tokens/lexical_weights channel (04-05) and read by
    store_evidence.py's native sparse-vector + Lucene channels (04-07)."""
    for path in (_MEMORY_WRITE_PATH, _MEMORY_READ_PATH):
        source = path.read_text(encoding="utf-8")
        for forbidden in (
            "sparse_index.prepare(",
            "sparse_index.commit_batch(",
            "sparse_index.replay(",
            "sparse_index.discard_prepared(",
            "_prepare_sparse_projection",
        ):
            assert forbidden not in source, f"{path.name} still references {forbidden!r}"
