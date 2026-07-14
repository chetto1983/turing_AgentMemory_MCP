"""Deterministic E2E score gate. `main`/`run_e2e` are the CLI entrypoint and are
imported unchanged by `scripts/e2e_score.py` and `cli.py` — do not remove them.

Split by concern per D-08/D-09: the in-process stub embed/rerank HTTP servers,
the local TuringDB daemon wrapper, and the ArcadeDB E2E backend live in
`e2e_score_stubs.py`; the MCP scenario checks live in `e2e_score_scenarios.py`.
This module wires them together and owns the top-level run/score/CLI
orchestration.

Rewired to ArcadeDB (04-09, scope item D): `run_e2e()` now drives the store
through `ArcadeE2EBackend` (a dedicated, drop-and-recreate database on the
already-running `arcadedb` compose service) instead of a local `turingdb` CLI
daemon — the store has spoken ArcadeDB exclusively since 04-04, so a
TuringDB-backed harness here would not exercise the real code path at all.
Requires `docker compose up -d arcadedb` to already be running; the restart
leg additionally requires `docker`/`docker compose` on PATH and host-level
control of that service (see `ArcadeE2EBackend.restart_backend_and_wait_ready`).
`TuringDaemon`/`LocalEmbedServer`/`LocalRerankServer`/`free_port`/`wait_rest`
stay re-exported unchanged: they are still imported directly from this module
by the legacy, still-TuringDB-backed `benchmark.py`/`agent_quality_eval.py`
harnesses (out of this milestone's scope; `turingdb` stays retained for
Phase 6/7 coexistence, ARC-10).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any

from turingdb import __version__ as turingdb_version

from turing_agentmemory_mcp.e2e_score_scenarios import check, run_mcp_checks
from turing_agentmemory_mcp.e2e_score_stubs import (  # noqa: F401 - preserved public import path
    ARCADEDB_E2E_IMAGE,
    ArcadeE2EBackend,
    LocalEmbedServer,
    LocalRerankServer,
    TuringDaemon,
    free_port,
    wait_rest,
)
from turing_agentmemory_mcp.ids import stable_id
from turing_agentmemory_mcp.rerank import truncate_runes
from turing_agentmemory_mcp.store import TuringAgentMemory

ROOT = Path(__file__).resolve().parents[2]


def run_e2e(out: Path) -> dict[str, Any]:
    # Local scratch dir for the store's non-ArcadeDB file state (governance
    # audit JSONL, observability spans, document staging) -- unrelated to the
    # ArcadeDB backend itself, which ArcadeE2EBackend owns via a dedicated
    # drop-and-recreate database on the already-running `arcadedb` service.
    home = Path(os.environ.get("ARCADEDB_E2E_HOME", ROOT / ".arcadedb" / "e2e"))
    if home.exists():
        shutil.rmtree(home)
    backend = ArcadeE2EBackend()
    embed_server: LocalEmbedServer | None = None
    rerank_server: LocalRerankServer | None = None
    checks: list[dict[str, Any]] = []
    store_holder: dict[str, TuringAgentMemory] = {}
    previous_env = {
        key: os.environ.get(key)
        for key in (
            "EMBED_BASE_URL",
            "EMBED_DIMENSIONS",
            "EMBED_MODEL",
            "RERANK_BASE_URL",
            "RERANK_MODEL",
        )
    }
    try:
        if os.environ.get("E2E_USE_EXTERNAL_EMBED") != "1":
            embed_server = LocalEmbedServer(dimensions=768)
            embed_server.start()
            os.environ["EMBED_BASE_URL"] = embed_server.base_url
            os.environ["EMBED_DIMENSIONS"] = "768"
            os.environ["EMBED_MODEL"] = "local-embedding"
        if os.environ.get("E2E_USE_EXTERNAL_RERANK") != "1":
            rerank_server = LocalRerankServer()
            rerank_server.start()
            os.environ["RERANK_BASE_URL"] = rerank_server.base_url
            os.environ["RERANK_MODEL"] = "local-rerank"

        def start_infra() -> dict[str, Any]:
            backend.start()
            store = TuringAgentMemory(backend.client, turing_home=home, graph="e2e_agent_memory")
            store.bootstrap()
            vector = store.embedder.embed("embedding provider contract ping")
            scored = store.reranker.rerank(
                "blue key interlock",
                [
                    "monthly maintenance logging",
                    truncate_runes("blue key interlock reset procedure", 480),
                ],
            )
            if not scored or scored[0].index != 1:
                raise RuntimeError(f"rerank provider did not reorder seed pool: {scored}")
            store_holder["store"] = store
            return {
                "arcadedb_url": backend.client.base_url,
                "graph": store.graph,
                "embedding_base_url": os.environ.get("EMBED_BASE_URL"),
                "embedding_dimensions": len(vector),
                "rerank_base_url": os.environ.get("RERANK_BASE_URL"),
                "rerank_top_index": scored[0].index,
            }

        check(checks, "arcadedb_starts_schema_embed_and_rerank_contracts", start_infra)
        store = store_holder.get("store")
        if store is not None:
            asyncio.run(run_mcp_checks(store, checks))

            def restart_and_verify_retrieval() -> bool:
                # The D-10 restart leg needs host-level `docker compose` control of
                # the arcadedb service. When docker is unavailable (e.g. this process
                # is nested inside a container without a docker socket), the restart
                # raises RuntimeError; running it INSIDE this check() callable means
                # check() records an honest failed check (ok=false) rather than
                # crashing run_e2e with no JSON output -- never a silent pass, never a
                # script crash. On the host (CI dockerized-integration, local) docker
                # is present, so a real restart happens and this returns true.
                backend.restart_backend_and_wait_ready()
                store.reconnect()
                memory = store.search_memory(
                    user_identifier="alice", query="espresso TuringDB memory", limit=1
                )
                docs = store.search_documents(
                    user_identifier="alice", query="green reset token lockout", limit=1
                )
                return (
                    memory[0].content.startswith("Davide prefers espresso")
                    # ARC-08: chunk ids are stable_id()-based, not the
                    # human-readable f"{document_id}#{ordinal}" a pre-port
                    # TuringDB stack used (04-09 fix, found live).
                    and docs[0].chunk_id == stable_id("chunk", "alice", "doc-machine-safety", "1")
                )

            check(
                checks,
                "restart_preserves_memory_and_document_retrieval",
                restart_and_verify_retrieval,
            )
    finally:
        cleanup = backend.stop()
        if embed_server is not None:
            embed_server.stop()
        if rerank_server is not None:
            rerank_server.stop()
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    total = sum(item["points"] for item in checks)
    earned = sum(item["points"] for item in checks if item["ok"])
    score = round((earned / total) * 10.0, 3) if total else 0.0
    result = {
        "verdict": "VALIDATED_10_10" if score >= 9.8 and len(checks) == 19 else "FAILED_SCORE_GATE",
        "score": score,
        "score_gate": "10/10",
        "check_count": len(checks),
        "backend": "arcadedb",
        "arcadedb_image": ARCADEDB_E2E_IMAGE,
        # Kept for baseline/03-turingdb field-shape parity (Phase-6
        # diffability, scope item D) -- turingdb stays an installed, retained
        # dependency (ARC-10) even though the store itself no longer connects
        # through it.
        "turingdb_version": turingdb_version,
        "checks": checks,
        "cleanup": cleanup,
    }
    out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="e2e-results.json")
    args = parser.parse_args()
    result = run_e2e(Path(args.out))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["score"] >= 9.8 and result["check_count"] == 19 else 1


if __name__ == "__main__":
    raise SystemExit(main())
