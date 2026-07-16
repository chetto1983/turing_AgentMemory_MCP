"""Shared `_StoreCore` seam fixtures for the test_store_arcadedb_core* split
(not collected as tests). Extracted 05-09 (D-08 no-allowlist 600-LOC cap) when
Task 2's tenant-binding assertions pushed test_store_arcadedb_core.py over the
cap -- see tests/test_store_arcadedb_core.py and
tests/test_store_arcadedb_identity.py, which both import from here.

`_FakeArcadeDBClient` is a scripted session-aware in-memory stand-in for
`ArcadeDBClient` (mirrors the convention already established in
`tests/test_arcadedb_schema.py`) -- no live ArcadeDB container is required.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.store import TuringAgentMemory
from turing_agentmemory_mcp.store_core import _StoreCore
from turing_agentmemory_mcp.tenant_binding import TenantBinding

STORE_CORE_PATH = (
    Path(__file__).resolve().parents[1] / "src" / "turing_agentmemory_mcp" / "store_core.py"
)


class StubEmbedder:
    dimensions = 3


class TrackingSparseIndex:
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


class FakeArcadeDBClient:
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

    def sqlscript(
        self,
        body: str,
        *,
        params: dict[str, object] | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, object]]:
        # Self-contained (own BEGIN/COMMIT, spike-confirmed) -- unlike
        # `command()` above, no session bookkeeping is needed; callers (only
        # `store_rebuild.py::_replace_community_graph`) never re-query the
        # replaced Community rows within the same test, so recording the
        # call is sufficient to prove the write-batch span/audit path.
        self.commands.append((body, params, session_id))
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


def make_store(
    client: FakeArcadeDBClient,
    tmp_path: Path,
    *,
    observer: Any | None = None,
    sparse_index: Any | None = None,
) -> _StoreCore:
    return _StoreCore(
        client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=StubEmbedder(),  # type: ignore[arg-type]
        reranker=object(),  # type: ignore[arg-type]
        entity_processor=object(),  # type: ignore[arg-type]
        observer=observer,
        sparse_index=sparse_index,
    )


def make_full_store(
    client: FakeArcadeDBClient,
    tmp_path: Path,
    *,
    tenant_binding: TenantBinding | None = None,
) -> TuringAgentMemory:
    return TuringAgentMemory(
        client,  # type: ignore[arg-type]
        turing_home=tmp_path,
        embedder=StubEmbedder(),  # type: ignore[arg-type]
        reranker=object(),  # type: ignore[arg-type]
        entity_processor=object(),  # type: ignore[arg-type]
        tenant_binding=tenant_binding,
    )
