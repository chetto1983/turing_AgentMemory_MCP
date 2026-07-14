"""Phase 4 Plan 09, Task 3 (D-10 / T-04-09-03): a real ArcadeDB container is
force-restarted mid-test, proving the store degrades visibly while it is
down, reconnects WITHOUT a manual runbook step once it is back, and returns
correct (not empty/stale) search results immediately after recovery.

Requires the `arcadedb` compose service reachable at `ARCADEDB_URL`
(default `http://127.0.0.1:2480`) and `docker compose` on PATH -- start it
with `docker compose up -d arcadedb` before running this hard-gate test.
Marked `@pytest.mark.integration`: a skip is silent-green locally when
Docker/ArcadeDB is unavailable, but a hard CI failure under CI=true
(tests/conftest.py's no-skip-as-green guard) -- this test must never pass
green in CI without actually restarting the pinned container.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

import pytest

from turing_agentmemory_mcp.arcadedb_client import ArcadeDBClient
from turing_agentmemory_mcp.embeddings import HashingEmbedder
from turing_agentmemory_mcp.governance import NoopAuditSink, NoopRedactor
from turing_agentmemory_mcp.observability import InMemorySpanRecorder
from turing_agentmemory_mcp.store import TuringAgentMemory

TEST_DATABASE = "arcadedb_chaos_restart_test"
_READY_TIMEOUT_S = 60.0
_DOWN_TIMEOUT_S = 20.0


def _client() -> ArcadeDBClient:
    return ArcadeDBClient(
        base_url=os.environ.get("ARCADEDB_URL", "http://127.0.0.1:2480"),
        database=TEST_DATABASE,
        username=os.environ.get("ARCADEDB_USER", "root"),
        password=os.environ.get("ARCADEDB_PASSWORD", "agentmemory-arcadedb-dev"),
    )


def _docker_compose_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(["docker", "compose", "version"], capture_output=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _compose(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["docker", "compose", *args],
        capture_output=True,
        timeout=120,
    )


def _wait_until(predicate: object, *, timeout_s: float, interval_s: float = 0.5) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate():  # type: ignore[operator]
            return True
        time.sleep(interval_s)
    return predicate()  # type: ignore[operator]


@pytest.fixture
def chaos_store(tmp_path):
    if not _docker_compose_available():
        pytest.skip("docker compose is not available on PATH -- cannot chaos-restart arcadedb")
    client = _client()
    if not client.is_ready():
        pytest.skip(
            f"ArcadeDB not reachable at {client.base_url} -- start it with "
            "`docker compose up -d arcadedb` before running this hard-gate test."
        )
    try:
        client._server_command(f"drop database {TEST_DATABASE}")
    except RuntimeError:
        pass
    client.ensure_database()

    store = TuringAgentMemory(
        client,
        turing_home=tmp_path,
        embedder=HashingEmbedder(dimensions=32),
        reranker=None,
        redactor=NoopRedactor(),
        audit_sink=NoopAuditSink(),
        observer=InMemorySpanRecorder(),
    )
    store.bootstrap()
    yield store
    # Restore the service to a healthy state for any later test in this run,
    # then drop the throwaway database.
    _compose("start", "arcadedb")
    _wait_until(lambda: _client().is_ready(), timeout_s=_READY_TIMEOUT_S)
    try:
        _client()._server_command(f"drop database {TEST_DATABASE}")
    except RuntimeError:
        pass


@pytest.mark.integration
def test_store_survives_arcadedb_restart_and_recovers_correct_search(chaos_store) -> None:
    store = chaos_store

    written = store.store_message(
        user_identifier="chaos-alice",
        session_id="s1",
        role="user",
        content="Chaos restart canary: espresso reset procedure stays searchable after recovery.",
    )
    before_hits = store.search_memory(
        user_identifier="chaos-alice", query="espresso reset procedure canary", limit=3
    )
    assert before_hits and before_hits[0].id == written.id

    assert store.runtime_status()["stages"]["graph"]["ready"] is True

    # -- force-restart the arcadedb container --
    stop_result = _compose("stop", "arcadedb")
    assert stop_result.returncode == 0, stop_result.stderr.decode("utf-8", errors="replace")

    went_degraded = _wait_until(
        lambda: store.runtime_status()["stages"]["graph"]["ready"] is False,
        timeout_s=_DOWN_TIMEOUT_S,
    )
    assert went_degraded, "the graph stage must report not-ready while ArcadeDB is stopped"

    start_result = _compose("start", "arcadedb")
    assert start_result.returncode == 0, start_result.stderr.decode("utf-8", errors="replace")

    reconnected = _wait_until(lambda: store.reconnect(), timeout_s=_READY_TIMEOUT_S)
    assert reconnected, "store.reconnect() must recover without a manual runbook step"
    assert store.runtime_status()["stages"]["graph"]["ready"] is True

    after_hits = store.search_memory(
        user_identifier="chaos-alice", query="espresso reset procedure canary", limit=3
    )
    assert after_hits, "search must return results (not empty) immediately after recovery"
    assert after_hits[0].id == written.id
    assert after_hits[0].content == written.content
    assert all(item.user_identifier == "chaos-alice" for item in after_hits)
