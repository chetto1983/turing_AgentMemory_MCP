"""Thin stdlib-`urllib` HTTP/JSON client for ArcadeDB (D-02 spike, grown in 04-02).

Mirrors the `OpenAICompatibleEmbedder`/`OpenAICompatibleReranker` convention
(`embeddings.py`/`rerank.py`): a frozen dataclass config, a `from_env()` factory,
`urllib.request` transport, exponential-backoff retry, raise-hard on exhaustion
(ArcadeDB is canonical this milestone -- no soft degrade, matching `embeddings.py`).

Every endpoint path, header name, and syntax choice below was empirically
confirmed against a live `arcadedata/arcadedb:26.7.1` container as part of the
D-02 hard-gate spike -- NOT sourced from documentation alone, which disagreed
across sources (see `.planning/phases/04-arcadedb-direct-port/04-SPIKE-FINDINGS.md`).
Do not change the endpoint prefix, session-header transaction model, or the
`vectorNeighbors`/`SEARCH_INDEX` function spellings without re-running
`tests/test_arcadedb_client.py` against a live container.

Full method surface (04-02): `query`/`command`/`sqlscript`/`begin`/`commit`/
`rollback`, `run_in_transaction` (D-08 managed-transaction + bounded MVCC
commit-retry-N wrapper), `is_ready`/`probe` (D-10 readiness), and
`ensure_database` (bootstrap glue the smoke test needs; the full idempotent
schema bootstrap is D-09, a later wave). ArcadeDB's native record identity is
never captured or returned as an identifier by this client -- callers
pass/receive only the `id`/`stable_id()` property values they supply.

MVCC conflict signal (04-02 follow-up spike, empirically confirmed live, not
in 04-SPIKE-FINDINGS.md which deferred it): a commit that loses an optimistic-
concurrency race returns HTTP 503 with a JSON body whose `exception` field is
`com.arcadedb.exception.ConcurrentModificationException`. Retrying that exact
commit call again does NOT recover -- ArcadeDB invalidates the session on any
failure, so the next call on the same session (commit, rollback, or command)
returns a *different* error (`com.arcadedb.exception.TransactionException`,
"Transaction not begun"). Two consequences drive this module's design:
1. `_request`'s generic transport retry loop must skip retrying when the
   error body is this conflict signal -- otherwise it silently retries into
   the masking "Transaction not begun" error and the real conflict is lost.
2. Recovering from a conflict requires redoing the *whole* begin -> body ->
   commit cycle from a fresh session, not just re-POSTing `commit` -- this is
   what `run_in_transaction` does, bounded by `ARCADEDB_COMMIT_RETRIES`.
"""

from __future__ import annotations

import base64
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from turing_agentmemory_mcp.provider_config import provider_env

DEFAULT_BASE_URL = "http://127.0.0.1:2480"
_RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
_SESSION_HEADER = "arcadedb-session-id"
_MVCC_CONFLICT_MARKER = "com.arcadedb.exception.ConcurrentModificationException"

T = TypeVar("T")


def is_mvcc_conflict(detail: str) -> bool:
    """True when an ArcadeDB HTTP error body is the MVCC optimistic-concurrency
    conflict signal (`ConcurrentModificationException`), not some other error.

    Empirically confirmed live (04-02, see module docstring): this is the ONE
    signal `_request`'s generic transport retry must not blindly retry past,
    and the ONE signal `run_in_transaction`'s commit-retry-N wrapper redoes
    the whole transaction for. Any other error (including a same-coded but
    differently-caused HTTP 500/503) is not a conflict and must not trigger
    either retry path.
    """
    return _MVCC_CONFLICT_MARKER in detail


@dataclass(frozen=True)
class ArcadeDBClient:
    """Thin urllib wrapper over ArcadeDB's `/api/v1/...` HTTP/JSON API.

    The `/api/v1/...` prefix (not the unversioned `/query/graph/<db>` form some
    ArcadeDB docs show) and HTTP Basic Auth are both spike-confirmed for 26.7.1.
    """

    base_url: str = DEFAULT_BASE_URL
    database: str = "agent_memory"
    username: str = "root"
    password: str = ""
    timeout_s: float = 30.0
    max_attempts: int = 3
    retry_base_s: float = 0.5
    commit_retries: int = 3

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ValueError("ArcadeDB base_url is required")
        if not self.database.strip():
            raise ValueError("ArcadeDB database is required")
        if isinstance(self.max_attempts, bool) or self.max_attempts <= 0:
            raise ValueError("ArcadeDB max attempts must be positive")
        if self.retry_base_s < 0:
            raise ValueError("ArcadeDB retry base seconds must not be negative")
        if isinstance(self.commit_retries, bool) or self.commit_retries <= 0:
            raise ValueError("ArcadeDB commit retries must be positive")

    @classmethod
    def from_env(cls) -> ArcadeDBClient:
        return cls(
            base_url=provider_env("ARCADEDB_URL", default=DEFAULT_BASE_URL),
            database=provider_env("ARCADEDB_DATABASE", default="agent_memory"),
            username=provider_env("ARCADEDB_USER", default="root"),
            password=provider_env("ARCADEDB_PASSWORD", default=""),
            timeout_s=float(provider_env("ARCADEDB_TIMEOUT_SECONDS", default="30")),
            max_attempts=int(provider_env("ARCADEDB_MAX_ATTEMPTS", default="3")),
            retry_base_s=float(provider_env("ARCADEDB_RETRY_BASE_SECONDS", default="0.5")),
            commit_retries=int(provider_env("ARCADEDB_COMMIT_RETRIES", default="3")),
        )

    # -- transaction control (D-08; the session header is the
    # empirically-confirmed read-your-writes mechanism -- see SPIKE-FINDINGS §3) --

    def begin(self) -> str:
        _decoded, session_id = self._request("POST", f"/api/v1/begin/{self.database}")
        if not session_id:
            raise RuntimeError("ArcadeDB begin did not return a session id")
        return session_id

    def commit(self, session_id: str) -> None:
        self._request("POST", f"/api/v1/commit/{self.database}", session_id=session_id)

    def rollback(self, session_id: str) -> None:
        self._request("POST", f"/api/v1/rollback/{self.database}", session_id=session_id)

    def run_in_transaction(
        self,
        body: Callable[[str], T],
        *,
        commit_retries: int | None = None,
    ) -> T:
        """Run `body(session_id)` inside one managed begin/commit transaction
        (D-08), retrying the WHOLE begin -> body -> commit cycle up to
        `commit_retries` times when commit loses an MVCC conflict.

        Empirically confirmed live (04-02, see module docstring): retrying
        `commit` alone on the same session after a conflict does NOT recover
        -- the session is invalidated server-side, so the entire transaction
        must be redone from a fresh `begin()`. Any non-conflict failure from
        `body` or `commit` propagates immediately after a best-effort
        `rollback` -- this wrapper only retries the one MVCC signal.
        """
        attempts = commit_retries if commit_retries is not None else self.commit_retries
        if isinstance(attempts, bool) or attempts <= 0:
            raise ValueError("ArcadeDB commit retries must be positive")
        last_exc: RuntimeError | None = None
        for attempt in range(attempts):
            session_id = self.begin()
            try:
                result = body(session_id)
                self.commit(session_id)
                return result
            except RuntimeError as exc:
                try:
                    self.rollback(session_id)
                except RuntimeError:
                    pass  # session already invalidated by the failure above
                if is_mvcc_conflict(str(exc)) and attempt + 1 < attempts:
                    last_exc = exc
                    continue
                raise
        raise last_exc or RuntimeError("ArcadeDB managed transaction exhausted commit retries")

    # -- query/command --

    def query(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._execute(
            "query", statement, params=params, language=language, session_id=session_id
        )

    def command(
        self,
        statement: str,
        *,
        params: dict[str, object] | None = None,
        language: str = "sql",
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self._execute(
            "command", statement, params=params, language=language, session_id=session_id
        )

    def sqlscript(
        self,
        body: str,
        *,
        params: dict[str, object] | None = None,
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Multi-statement `BEGIN;...;COMMIT;` batch submitted in ONE call
        (Pattern 1 / SPIKE-FINDINGS §3) -- a distinct, self-contained
        mechanism from the session-header transaction model above; no
        cross-call session is created or required.
        """
        return self._execute(
            "command", body, params=params, language="sqlscript", session_id=session_id
        )

    def _execute(
        self,
        verb: str,
        statement: str,
        *,
        params: dict[str, object] | None,
        language: str,
        session_id: str | None,
    ) -> list[dict[str, Any]]:
        payload: dict[str, object] = {"language": language, "command": statement}
        if params:
            payload["params"] = params
        decoded, _session = self._request(
            "POST", f"/api/v1/{verb}/{self.database}", payload=payload, session_id=session_id
        )
        result = decoded.get("result")
        return result if isinstance(result, list) else []

    # -- readiness --

    def is_ready(self) -> bool:
        """Cheap reachability probe against `/api/v1/ready` (204, no auth needed).

        Soft/degraded by design (D-10) -- never raises, unlike query/command.
        """
        try:
            req = Request(self.base_url.rstrip("/") + "/api/v1/ready", method="GET")
            with urlopen(req, timeout=self.timeout_s) as resp:
                return 200 <= resp.status < 300
        except Exception:
            return False

    probe = is_ready

    # -- bootstrap glue (the smoke test's own setup; full D-09 bootstrap is later) --

    def ensure_database(self) -> None:
        """Idempotently create `self.database` on the server if absent."""
        decoded, _session = self._server_command("list databases")
        existing = decoded.get("result")
        if isinstance(existing, list) and self.database in existing:
            return
        self._server_command(f"create database {self.database}")

    def _server_command(self, command: str) -> tuple[dict[str, Any], str | None]:
        return self._request("POST", "/api/v1/server", payload={"command": command})

    # -- transport --

    def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, object] | None = None,
        session_id: str | None = None,
    ) -> tuple[dict[str, Any], str | None]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = Request(
            self.base_url.rstrip("/") + path,
            data=body,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        req.add_header("Authorization", _basic_auth_header(self.username, self.password))
        if session_id:
            req.add_header(_SESSION_HEADER, session_id)
        for attempt in range(self.max_attempts):
            try:
                with urlopen(req, timeout=self.timeout_s) as resp:
                    raw = resp.read()
                    returned_session = resp.headers.get(_SESSION_HEADER)
                    decoded = json.loads(raw.decode("utf-8")) if raw else {}
                    if not isinstance(decoded, dict):
                        raise RuntimeError(f"ArcadeDB {path} returned a non-object response")
                    return decoded, returned_session
            except HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                # An MVCC conflict must never be blindly retried at this transport
                # layer: retrying the identical request masks it behind a later,
                # unrelated "Transaction not begun" error (see module docstring).
                # `run_in_transaction` owns retry policy for that ONE signal.
                if (
                    exc.code in _RETRYABLE_HTTP_CODES
                    and not is_mvcc_conflict(detail)
                    and attempt + 1 < self.max_attempts
                ):
                    time.sleep(self.retry_base_s * (2**attempt))
                    continue
                raise RuntimeError(f"ArcadeDB HTTP {exc.code} at {path}: {detail}") from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt + 1 < self.max_attempts:
                    time.sleep(self.retry_base_s * (2**attempt))
                    continue
                raise RuntimeError(f"ArcadeDB unavailable at {self.base_url}") from exc
        raise RuntimeError(f"ArcadeDB request to {path} exhausted retries")


def _basic_auth_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
    return f"Basic {token}"
