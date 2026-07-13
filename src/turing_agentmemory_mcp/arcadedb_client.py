"""Thin stdlib-`urllib` HTTP/JSON client for ArcadeDB (D-02 spike, spike-minimal scope).

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

Spike-minimal method surface only: `query`/`command`/`begin`/`commit`/`rollback`,
`is_ready`/`probe`, and `ensure_database` (bootstrap glue the smoke test needs;
the full idempotent schema bootstrap is D-09, a later wave). ArcadeDB's native
record identity is never captured or returned as an identifier by this client --
callers pass/receive only the `id`/`stable_id()` property values they supply.
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from turing_agentmemory_mcp.provider_config import provider_env

DEFAULT_BASE_URL = "http://127.0.0.1:2480"
_RETRYABLE_HTTP_CODES = frozenset({429, 500, 502, 503, 504})
_SESSION_HEADER = "arcadedb-session-id"


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

    def __post_init__(self) -> None:
        if not self.base_url.strip():
            raise ValueError("ArcadeDB base_url is required")
        if not self.database.strip():
            raise ValueError("ArcadeDB database is required")
        if isinstance(self.max_attempts, bool) or self.max_attempts <= 0:
            raise ValueError("ArcadeDB max attempts must be positive")
        if self.retry_base_s < 0:
            raise ValueError("ArcadeDB retry base seconds must not be negative")

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
        )

    # -- transaction control (D-08 groundwork; the session header is the
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
                if exc.code in _RETRYABLE_HTTP_CODES and attempt + 1 < self.max_attempts:
                    time.sleep(self.retry_base_s * (2**attempt))
                    continue
                detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
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
