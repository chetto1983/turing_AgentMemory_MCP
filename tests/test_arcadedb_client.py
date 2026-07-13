"""D-02 hard-gate smoke test (live) + 04-02 mocked-HTTP unit tests for the full
`ArcadeDBClient` transaction/retry/readiness surface.

The live-container tests below resolve the five §3 capability unknowns against a
LIVE `arcadedata/arcadedb:26.7.1` container (not a mock, not a doc-sourced guess)
and are each marked `integration` individually (pyproject.toml): a skip is
silent-green locally when ArcadeDB isn't running, but a CI failure under CI=true
(tests/conftest.py's no-skip-as-green guard) -- this hard gate must never pass
green without actually exercising the pinned image.

Resolves (see 04-SPIKE-FINDINGS.md for the full write-up):
  1. `vectorNeighbors('Type[property]', vec, k)` is the winning HNSW spelling.
  2. Filtered-ANN k-underfill IS present (post-filter, not pushdown) -- D-03's
     over-fetch-then-filter default stays.
  3. Intra-transaction read-your-writes (property-filtered SELECT, not just
     `$var`) works via the `arcadedb-session-id` header session model.
  4. `SEARCH_INDEX('Type[property]', query)` exposes an orderable `$score`;
     `CONTAINSTEXT` is boolean-only (returns 0.0 for `$score`).
  5. `arcadedata/arcadedb` requires `-Darcadedb.server.rootPassword`; wrong/absent
     credentials are rejected (401/403), confirmed live below.

The mocked-HTTP unit tests below (04-02, Task 1/2) are NOT marked `integration`:
they exercise `ArcadeDBClient`'s transaction/retry/readiness surface entirely
against a scripted fake `urlopen`, so they run in the fast/default tier with no
live container required. (The module previously applied `pytestmark =
pytest.mark.integration` at module scope, marking every test in the file; that
is moved to per-function `@pytest.mark.integration` decorators here so the new
unit tests are not incorrectly gated behind a live dependency they don't need.)
"""

from __future__ import annotations

import io
import json
import os
from urllib.error import HTTPError, URLError

import pytest

from turing_agentmemory_mcp.arcadedb_client import ArcadeDBClient

TEST_DATABASE = "arcadedb_client_smoke"


def _client() -> ArcadeDBClient:
    return ArcadeDBClient(
        base_url=os.environ.get("ARCADEDB_URL", "http://127.0.0.1:2480"),
        database=TEST_DATABASE,
        username=os.environ.get("ARCADEDB_USER", "root"),
        password=os.environ.get("ARCADEDB_PASSWORD", "agentmemory-arcadedb-dev"),
    )


@pytest.fixture(scope="module")
def client() -> ArcadeDBClient:
    candidate = _client()
    if not candidate.is_ready():
        pytest.skip(
            f"ArcadeDB not reachable at {candidate.base_url} -- start it with "
            "`docker compose up -d arcadedb` before running this hard-gate smoke test.",
            allow_module_level=True,
        )
    return candidate


@pytest.fixture(scope="module", autouse=True)
def _fresh_database(client: ArcadeDBClient):
    try:
        client._server_command(f"drop database {TEST_DATABASE}")
    except RuntimeError:
        pass
    client.ensure_database()
    client.command("CREATE VERTEX TYPE Chunk")
    client.command("CREATE PROPERTY Chunk.id STRING")
    client.command("CREATE PROPERTY Chunk.content STRING")
    client.command("CREATE PROPERTY Chunk.embedding ARRAY_OF_FLOATS")
    client.command("CREATE PROPERTY Chunk.status STRING")
    client.command(
        "CREATE INDEX ON Chunk (embedding) LSM_VECTOR METADATA "
        '{"dimensions": 4, "similarity": "cosine", "maxConnections": 16, "beamWidth": 100}'
    )
    client.command("CREATE INDEX ON Chunk (id) UNIQUE")
    client.command("CREATE INDEX ON Chunk (content) FULL_TEXT")
    client.command("CREATE EDGE TYPE NextChunk")
    yield
    try:
        client._server_command(f"drop database {TEST_DATABASE}")
    except RuntimeError:
        pass


def _insert_chunk(
    client: ArcadeDBClient, *, id_: str, content: str, embedding: list[float], status: str
) -> None:
    client.command(
        "INSERT INTO Chunk SET id = :id, content = :content, embedding = :embedding, "
        "status = :status",
        params={"id": id_, "content": content, "embedding": embedding, "status": status},
    )


# -- Unknown 1 (+ A4 vector DDL, + the vector-literal-is-bindable correction) --


@pytest.mark.integration
def test_vector_neighbors_resolves_and_returns_record_plus_score(client: ArcadeDBClient) -> None:
    _insert_chunk(
        client, id_="v1", content="alpha", embedding=[1.0, 0.0, 0.0, 0.0], status="active"
    )
    _insert_chunk(client, id_="v2", content="beta", embedding=[0.0, 1.0, 0.0, 0.0], status="active")
    _insert_chunk(
        client, id_="v3", content="gamma", embedding=[0.9, 0.1, 0.0, 0.0], status="active"
    )

    # The query vector is bound as a named param (`:vec`) -- CONTEXT.md's locked
    # assumption that vector literals must be inlined is WRONG for 26.7.1;
    # corrected here and recorded in 04-SPIKE-FINDINGS.md.
    rows = client.query(
        'SELECT expand(vectorNeighbors("Chunk[embedding]", :vec, :k))',
        params={"vec": [1.0, 0.0, 0.0, 0.0], "k": 3},
    )

    assert [row["id"] for row in rows] == ["v1", "v3", "v2"]
    assert rows[0]["distance"] == pytest.approx(0.0, abs=1e-6)
    assert rows[0]["distance"] < rows[1]["distance"] < rows[2]["distance"]


# -- Unknown 2 (D-03 filtered-ANN k-underfill) --


@pytest.mark.integration
def test_filtered_vector_search_underfills_k_confirming_d03_overfetch_default(
    client: ArcadeDBClient,
) -> None:
    for index in range(7):
        _insert_chunk(
            client,
            id_=f"inactive{index}",
            content=f"inactive-{index}",
            embedding=[0.95, 0.05, 0.0, 0.0],
            status="inactive",
        )
    # 3 active fixtures (v1/v2/v3) already exist from the previous test; only
    # v1/v3 are near [1,0,0,0], v2 is far -- exactly the shape that exposes
    # post-filter k-underfill if the WHERE predicate does not push into HNSW.
    small_k = client.query(
        "SELECT id, status FROM "
        '(SELECT expand(vectorNeighbors("Chunk[embedding]", :vec, :k))) '
        "WHERE status = :status",
        params={"vec": [1.0, 0.0, 0.0, 0.0], "k": 2, "status": "active"},
    )
    large_k = client.query(
        "SELECT id, status FROM "
        '(SELECT expand(vectorNeighbors("Chunk[embedding]", :vec, :k))) '
        "WHERE status = :status",
        params={"vec": [1.0, 0.0, 0.0, 0.0], "k": 20, "status": "active"},
    )

    # k=2 under-fills: only 1 of the 3 active records surfaces because the
    # filter is applied AFTER the top-2 ANN results, not pushed into the search.
    assert len(small_k) < 3
    # Over-fetching (k=20) recovers all 3 active records -- confirms D-03's
    # locked over-fetch-then-filter default must stay; do not switch to native
    # predicate pushdown.
    assert len(large_k) == 3


# -- Unknown 4 (full-text analyzer + score exposure) --


@pytest.mark.integration
def test_search_index_exposes_orderable_score_but_containstext_does_not(
    client: ArcadeDBClient,
) -> None:
    matched = client.query(
        'SELECT id, $score FROM Chunk WHERE SEARCH_INDEX("Chunk[content]", :q) ORDER BY $score DESC',
        params={"q": "alpha"},
    )
    assert matched
    assert matched[0]["id"] == "v1"
    assert matched[0]["$score"] > 0.0

    contains_text = client.query(
        "SELECT id, $score FROM Chunk WHERE content CONTAINSTEXT :q",
        params={"q": "alpha"},
    )
    assert contains_text
    assert contains_text[0]["id"] == "v1"
    # CONTAINSTEXT is a boolean filter -- $score is NOT populated through it
    # (winning form for D-04/D-06 scoring is SEARCH_INDEX, not CONTAINSTEXT).
    assert contains_text[0]["$score"] == 0.0


# -- Unknown 3 (A5 intra-transaction read-your-writes) --


@pytest.mark.integration
def test_intra_transaction_read_your_writes_by_property_filter(client: ArcadeDBClient) -> None:
    session_id = client.begin()
    try:
        client.command(
            "CREATE VERTEX Chunk SET id = :id, content = :content, embedding = :embedding, "
            "status = :status",
            params={
                "id": "tx-a",
                "content": "tx-content",
                "embedding": [0.5, 0.5, 0.0, 0.0],
                "status": "active",
            },
            session_id=session_id,
        )

        in_tx = client.query(
            "SELECT id FROM Chunk WHERE id = :id", params={"id": "tx-a"}, session_id=session_id
        )
        assert [row["id"] for row in in_tx] == ["tx-a"]

        outside_tx_before_commit = client.query(
            "SELECT id FROM Chunk WHERE id = :id", params={"id": "tx-a"}
        )
        assert outside_tx_before_commit == []

        client.commit(session_id)
    except Exception:
        client.rollback(session_id)
        raise

    outside_tx_after_commit = client.query(
        "SELECT id FROM Chunk WHERE id = :id", params={"id": "tx-a"}
    )
    assert [row["id"] for row in outside_tx_after_commit] == ["tx-a"]


# -- Unknown 5 (auth requirement) --


@pytest.mark.integration
def test_credentials_are_required_and_enforced(client: ArcadeDBClient) -> None:
    # Empty credentials still send a (malformed) Basic Auth header, so ArcadeDB
    # rejects with 403 here, not the header-omitted 401 confirmed manually
    # against the raw HTTP API (see 04-SPIKE-FINDINGS.md) -- both paths prove
    # T-04-01-01's mitigation (no default-open access) holds.
    unauthenticated = ArcadeDBClient(
        base_url=client.base_url, database=client.database, username="", password=""
    )
    with pytest.raises(RuntimeError, match="ArcadeDB HTTP 403"):
        unauthenticated.query("SELECT 1 as x")

    wrong_password = ArcadeDBClient(
        base_url=client.base_url,
        database=client.database,
        username=client.username,
        password="definitely-not-the-password",
    )
    with pytest.raises(RuntimeError, match="ArcadeDB HTTP 403"):
        wrong_password.query("SELECT 1 as x")


# -- sqlscript LET-chaining (Pattern 1 groundwork; graph edge creation in one tx) --


@pytest.mark.integration
def test_sqlscript_let_chaining_creates_edge_across_two_new_vertices(
    client: ArcadeDBClient,
) -> None:
    client.command(
        "BEGIN;\n"
        'LET $a = CREATE VERTEX Chunk SET id = "scr-a", content = "scrA", '
        'embedding = [0.1,0.2,0.0,0.0], status = "active";\n'
        'LET $b = CREATE VERTEX Chunk SET id = "scr-b", content = "scrB", '
        'embedding = [0.2,0.1,0.0,0.0], status = "active";\n'
        "CREATE EDGE NextChunk FROM $a TO $b;\n"
        "COMMIT;\n",
        language="sqlscript",
    )

    rows = client.query(
        'SELECT out("NextChunk").id as nxt FROM Chunk WHERE id = :id', params={"id": "scr-a"}
    )
    assert rows[0]["nxt"] == ["scr-b"]


# -- D-05 groundwork: both graph-query surfaces bind params cleanly --


@pytest.mark.integration
def test_sql_match_and_opencypher_both_bind_params_for_two_hop_traversal(
    client: ArcadeDBClient,
) -> None:
    sql_rows = client.query(
        'MATCH {type: Chunk, as: c, where: (id = :id)}.out("NextChunk"){as: n} RETURN n.id',
        params={"id": "scr-a"},
    )
    assert sql_rows[0]["n.id"] == "scr-b"

    cypher_rows = client.query(
        "MATCH (c:Chunk {id: $id})-[:NextChunk]->(n:Chunk) RETURN n.id",
        params={"id": "scr-a"},
        language="opencypher",
    )
    assert cypher_rows[0]["n.id"] == "scr-b"


# ---------------------------------------------------------------------------
# 04-02 mocked-HTTP unit tests -- no live container required.
#
# These exercise `ArcadeDBClient` against a scripted fake `urlopen`, capturing
# every `Request` issued so behavior (paths, headers, bound params, retry
# counts) is asserted directly rather than inferred from a live server.
# ---------------------------------------------------------------------------


class _FakeResponse:
    """Stand-in for `http.client.HTTPResponse` as a context manager."""

    def __init__(self, *, status: int = 200, body: bytes = b"", session_id: str | None = None):
        self.status = status
        self._body = body
        self.headers: dict[str, str] = {}
        if session_id:
            self.headers["arcadedb-session-id"] = session_id

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool:
        return False


def _http_error(code: int, body: dict[str, object]) -> HTTPError:
    payload = json.dumps(body).encode("utf-8")
    return HTTPError(
        url="http://unit-test", code=code, msg="err", hdrs=None, fp=io.BytesIO(payload)
    )


class _ScriptedUrlopen:
    """A scripted replacement for `arcadedb_client.urlopen`: pops one entry
    per call (a `_FakeResponse` to return, or an exception to raise) and
    records every `Request` issued for assertions."""

    def __init__(self, script: list[object]):
        self._script = list(script)
        self.calls: list[object] = []

    def __call__(self, request: object, timeout: float | None = None) -> _FakeResponse:
        self.calls.append(request)
        if not self._script:
            raise AssertionError("scripted urlopen exhausted -- more calls than expected")
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


_CONFLICT_BODY = {
    "error": "Cannot execute command",
    "detail": "Concurrent modification on page ... please retry the operation",
    "exception": "com.arcadedb.exception.ConcurrentModificationException",
}
_NON_CONFLICT_500_BODY = {
    "error": "Cannot execute command",
    "detail": "boom",
    "exception": "com.arcadedb.exception.SomeOtherException",
}


def _unit_client(**overrides: object) -> ArcadeDBClient:
    defaults: dict[str, object] = {"database": "unit_test", "password": "pw"}
    defaults.update(overrides)
    return ArcadeDBClient(**defaults)


# -- Task 1, Test 1: begin -> command -> commit issue calls in order --


def test_begin_command_commit_issue_calls_in_order(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _ScriptedUrlopen(
        [
            _FakeResponse(status=204, session_id="AS-1"),
            _FakeResponse(status=200, body=json.dumps({"result": [{"ok": True}]}).encode()),
            _FakeResponse(status=204),
        ]
    )
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)
    client = _unit_client()

    session_id = client.begin()
    rows = client.command(
        "INSERT INTO Chunk SET id = :id", params={"id": "a"}, session_id=session_id
    )
    client.commit(session_id)

    assert session_id == "AS-1"
    assert rows == [{"ok": True}]
    assert [request.full_url for request in transport.calls] == [
        "http://127.0.0.1:2480/api/v1/begin/unit_test",
        "http://127.0.0.1:2480/api/v1/command/unit_test",
        "http://127.0.0.1:2480/api/v1/commit/unit_test",
    ]
    assert transport.calls[0].headers.get("Arcadedb-session-id") is None
    assert transport.calls[1].headers.get("Arcadedb-session-id") == "AS-1"
    assert transport.calls[2].headers.get("Arcadedb-session-id") == "AS-1"


# -- Task 1, Test 2: sqlscript posts one multi-statement body --


def test_sqlscript_posts_single_multi_statement_body(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _ScriptedUrlopen(
        [_FakeResponse(status=200, body=json.dumps({"result": [{"nxt": ["b"]}]}).encode())]
    )
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)
    client = _unit_client()

    rows = client.sqlscript(
        'BEGIN;\nLET $a = CREATE VERTEX Chunk SET id = "a";\nCOMMIT;\n', params={"x": 1}
    )

    assert rows == [{"nxt": ["b"]}]
    assert len(transport.calls) == 1
    request = transport.calls[0]
    assert request.full_url == "http://127.0.0.1:2480/api/v1/command/unit_test"
    payload = json.loads(request.data.decode("utf-8"))
    assert payload["language"] == "sqlscript"
    assert payload["params"] == {"x": 1}


# -- Task 1, Test 3: a conflicted commit retries the WHOLE transaction, bounded --


def test_commit_conflict_retries_whole_transaction_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedUrlopen(
        [
            _FakeResponse(status=204, session_id="AS-1"),  # begin (attempt 1)
            _FakeResponse(status=200, body=json.dumps({"result": []}).encode()),  # command
            _http_error(503, _CONFLICT_BODY),  # commit -> MVCC conflict
            _FakeResponse(status=204),  # rollback (best-effort cleanup)
            _FakeResponse(status=204, session_id="AS-2"),  # begin (attempt 2)
            _FakeResponse(status=200, body=json.dumps({"result": []}).encode()),  # command
            _FakeResponse(status=204),  # commit -> success
        ]
    )
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)
    client = _unit_client(commit_retries=2)
    seen_sessions: list[str] = []

    def body(session_id: str) -> str:
        seen_sessions.append(session_id)
        client.command("INSERT INTO Chunk SET id = 'x'", session_id=session_id)
        return "ok"

    result = client.run_in_transaction(body)

    assert result == "ok"
    # Exactly one retry cycle -- the entire begin/command/commit sequence was
    # redone from a fresh session, not just the failed commit re-posted.
    assert seen_sessions == ["AS-1", "AS-2"]
    begin_urls = [c.full_url for c in transport.calls if c.full_url.endswith("/begin/unit_test")]
    assert len(begin_urls) == 2


def test_commit_conflict_exhausts_bounded_retry_budget_then_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # commit_retries=2 -> two whole-transaction attempts, both conflict, then raise.
    transport = _ScriptedUrlopen(
        [
            _FakeResponse(status=204, session_id="AS-1"),
            _FakeResponse(status=200, body=json.dumps({"result": []}).encode()),
            _http_error(503, _CONFLICT_BODY),
            _FakeResponse(status=204),  # rollback
            _FakeResponse(status=204, session_id="AS-2"),
            _FakeResponse(status=200, body=json.dumps({"result": []}).encode()),
            _http_error(503, _CONFLICT_BODY),
            _FakeResponse(status=204),  # rollback
        ]
    )
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)
    client = _unit_client(commit_retries=2)

    def body(session_id: str) -> str:
        client.command("INSERT INTO Chunk SET id = 'x'", session_id=session_id)
        return "ok"

    with pytest.raises(RuntimeError, match="ConcurrentModificationException"):
        client.run_in_transaction(body)

    begin_urls = [c.full_url for c in transport.calls if c.full_url.endswith("/begin/unit_test")]
    assert len(begin_urls) == 2  # bounded -- never an unbounded retry loop


# -- Task 1, Test 4: a non-conflict HTTP 500 is only retried by the transport
# loop, not by the MVCC wrapper (the two loops are distinct) --


def test_non_conflict_500_is_not_retried_by_the_mvcc_wrapper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedUrlopen(
        [
            _FakeResponse(status=204, session_id="AS-1"),
            _FakeResponse(status=200, body=json.dumps({"result": []}).encode()),
            _http_error(500, _NON_CONFLICT_500_BODY),  # commit attempt 1 (transport retry)
            _http_error(500, _NON_CONFLICT_500_BODY),  # commit attempt 2 (transport exhausts)
            _FakeResponse(status=204),  # rollback
        ]
    )
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)
    client = _unit_client(max_attempts=2, commit_retries=3)

    def body(session_id: str) -> str:
        client.command("INSERT INTO Chunk SET id = 'x'", session_id=session_id)
        return "ok"

    with pytest.raises(RuntimeError, match="ArcadeDB HTTP 500"):
        client.run_in_transaction(body)

    # Only ONE begin -- the MVCC wrapper did not redo the transaction for a
    # non-conflict error; the transport loop already had its (separate) two
    # attempts at the commit call itself.
    begin_urls = [c.full_url for c in transport.calls if c.full_url.endswith("/begin/unit_test")]
    assert len(begin_urls) == 1


# -- Task 1, Test 5: params bind separately from statement text --


def test_params_bind_and_do_not_corrupt_statement(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _ScriptedUrlopen(
        [_FakeResponse(status=200, body=json.dumps({"result": []}).encode())]
    )
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)
    client = _unit_client()
    tricky_value = "O'Brien; DROP TYPE Chunk"

    client.command(
        "INSERT INTO Chunk SET id = :id, content = :content",
        params={"id": "x", "content": tricky_value},
    )

    payload = json.loads(transport.calls[0].data.decode("utf-8"))
    assert payload["command"] == "INSERT INTO Chunk SET id = :id, content = :content"
    assert payload["params"] == {"id": "x", "content": tricky_value}
    assert tricky_value not in payload["command"]


# -- Task 2, Test 1: is_ready() True when the probe succeeds --


def test_is_ready_returns_true_when_probe_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _ScriptedUrlopen([_FakeResponse(status=204)])
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)
    client = _unit_client()

    assert client.is_ready() is True


# -- Task 2, Test 2: is_ready() False (never raises) when unreachable --


def test_is_ready_returns_false_without_raising_when_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedUrlopen([URLError("connection refused")])
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)
    client = _unit_client()

    assert client.is_ready() is False


# -- Task 2, Test 3: probe() reflects recovery after a transient failure --


def test_probe_reflects_recovery_after_transient_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _ScriptedUrlopen([URLError("down"), _FakeResponse(status=204)])
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)
    client = _unit_client()

    assert client.probe() is False
    assert client.probe() is True
