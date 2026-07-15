"""04-02 mocked-HTTP unit tests for `ArcadeDBClient`'s transport/retry/
readiness surface (split out of `test_arcadedb_client.py`, MD-03, 600-LOC cap
-- that file's live-container D-02 hard-gate smoke tests stay put).

These exercise `ArcadeDBClient` against a scripted fake `urlopen`, capturing
every `Request` issued so behavior (paths, headers, bound params, retry
counts) is asserted directly rather than inferred from a live server -- no
live container required.
"""

from __future__ import annotations

import base64
import io
import json
from urllib.error import HTTPError, URLError

import pytest

from turing_agentmemory_mcp.arcadedb_client import ArcadeDBClient


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


# MD-03 regression: a malformed/non-UTF-8 2xx response must raise RuntimeError
# (routed through run_in_transaction's rollback contract), not an unwrapped
# UnicodeDecodeError/json.JSONDecodeError bypassing it.


def test_undecodable_2xx_response_raises_runtime_error_not_json_decode_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedUrlopen(
        [_FakeResponse(status=200, body=b"<html>not json, a proxy health page</html>")]
    )
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)
    client = _unit_client()

    with pytest.raises(RuntimeError, match="undecodable response"):
        client.query("SELECT 1 as x")


def test_undecodable_2xx_response_inside_transaction_triggers_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedUrlopen(
        [
            _FakeResponse(status=204, session_id="AS-1"),  # begin
            _FakeResponse(status=200, body=b"\xff\xfe not valid utf-8 or json"),  # command
            _FakeResponse(status=204),  # rollback (best-effort cleanup)
        ]
    )
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)
    client = _unit_client()

    def body(session_id: str) -> str:
        client.command("INSERT INTO Chunk SET id = 'x'", session_id=session_id)
        return "ok"

    with pytest.raises(RuntimeError, match="undecodable response"):
        client.run_in_transaction(body)

    rollback_urls = [
        c.full_url for c in transport.calls if c.full_url.endswith("/rollback/unit_test")
    ]
    assert rollback_urls, "run_in_transaction must attempt rollback, not leave the session dangling"
    commit_urls = [c.full_url for c in transport.calls if c.full_url.endswith("/commit/unit_test")]
    assert not commit_urls


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


# -- 05-04 server lifecycle commands used by ready-last tenant provisioning --


def _assert_server_request(request: object, command: str) -> None:
    assert request.method == "POST"
    assert request.full_url == "http://127.0.0.1:2480/api/v1/server"
    assert json.loads(request.data.decode("utf-8")) == {"command": command}
    expected_auth = "Basic " + base64.b64encode(b"root:pw").decode("ascii")
    assert request.headers["Authorization"] == expected_auth
    assert request.headers["Content-type"] == "application/json"
    assert request.headers.get("Arcadedb-session-id") is None


def test_list_databases_posts_authenticated_server_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedUrlopen(
        [
            _FakeResponse(
                status=200,
                body=json.dumps({"result": ["agentmem_t_v1_a", "agentmem_t_v1_b"]}).encode(),
            )
        ]
    )
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)

    result = _unit_client().list_databases()

    assert result == frozenset({"agentmem_t_v1_a", "agentmem_t_v1_b"})
    _assert_server_request(transport.calls[0], "list databases")


@pytest.mark.parametrize(
    "result",
    [None, {}, "unit_test", ["unit_test", 3]],
)
def test_list_databases_rejects_malformed_results(
    monkeypatch: pytest.MonkeyPatch, result: object
) -> None:
    transport = _ScriptedUrlopen(
        [_FakeResponse(status=200, body=json.dumps({"result": result}).encode())]
    )
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)

    with pytest.raises(RuntimeError, match="database list"):
        _unit_client().list_databases()

    assert len(transport.calls) == 1


def test_create_database_posts_bound_authenticated_server_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _ScriptedUrlopen(
        [_FakeResponse(status=200, body=json.dumps({"result": "ok"}).encode())]
    )
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)

    assert _unit_client().create_database() is None

    _assert_server_request(transport.calls[0], "create database unit_test")


@pytest.mark.parametrize("operation", ["list", "create"])
def test_lifecycle_command_retries_identical_request_then_decodes_success(
    monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    result: object = ["unit_test"] if operation == "list" else "ok"
    transport = _ScriptedUrlopen(
        [
            URLError("temporary"),
            _FakeResponse(status=200, body=json.dumps({"result": result}).encode()),
        ]
    )
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.time.sleep", lambda _delay: None)
    client = _unit_client(max_attempts=2)

    decoded = client.list_databases() if operation == "list" else client.create_database()

    expected = frozenset({"unit_test"}) if operation == "list" else None
    command = "list databases" if operation == "list" else "create database unit_test"
    assert decoded == expected
    assert len(transport.calls) == 2
    for request in transport.calls:
        _assert_server_request(request, command)


@pytest.mark.parametrize(
    ("script", "message"),
    [
        ([URLError("down"), URLError("still down")], "unavailable"),
        ([_http_error(400, {"detail": "bad command"})], "HTTP 400"),
        ([_FakeResponse(status=200, body=b"not-json")], "undecodable response"),
    ],
)
def test_lifecycle_transport_failures_preserve_runtime_error_classification(
    monkeypatch: pytest.MonkeyPatch,
    script: list[object],
    message: str,
) -> None:
    transport = _ScriptedUrlopen(script)
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.urlopen", transport)
    monkeypatch.setattr("turing_agentmemory_mcp.arcadedb_client.time.sleep", lambda _delay: None)
    client = _unit_client(max_attempts=2)

    with pytest.raises(RuntimeError, match=message):
        client.list_databases()

    assert len(transport.calls) == len(script)
