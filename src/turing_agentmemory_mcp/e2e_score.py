"""Deterministic E2E score gate. `main`/`run_e2e` are the CLI entrypoint and are
imported unchanged by `scripts/e2e_score.py` and `cli.py` — do not remove them.

Split by concern per D-08/D-09: the in-process stub embed/rerank HTTP servers and
the local TuringDB daemon wrapper live in `e2e_score_stubs.py`; the MCP scenario
checks live in `e2e_score_scenarios.py`. This module wires them together and owns
the top-level run/score/CLI orchestration.
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
    LocalEmbedServer,
    LocalRerankServer,
    TuringDaemon,
    free_port,
    wait_rest,
)
from turing_agentmemory_mcp.rerank import truncate_runes
from turing_agentmemory_mcp.store import TuringAgentMemory

ROOT = Path(__file__).resolve().parents[2]


def run_e2e(out: Path) -> dict[str, Any]:
    home = Path(os.environ.get("TURINGDB_E2E_HOME", ROOT / ".turingdb" / "e2e"))
    if home.exists():
        shutil.rmtree(home)
    daemon = TuringDaemon(home)
    embed_server: LocalEmbedServer | None = None
    rerank_server: LocalRerankServer | None = None
    checks: list[dict[str, Any]] = []
    cleanup: dict[str, Any] = {}
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
            daemon.start()
            store = TuringAgentMemory(daemon.client(), turing_home=home, graph="e2e_agent_memory")
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
                "port": daemon.port,
                "graph": store.graph,
                "embedding_base_url": os.environ.get("EMBED_BASE_URL"),
                "embedding_dimensions": len(vector),
                "rerank_base_url": os.environ.get("RERANK_BASE_URL"),
                "rerank_top_index": scored[0].index,
            }

        check(checks, "turingdb_starts_schema_embed_and_rerank_contracts", start_infra)
        store = store_holder.get("store")
        if store is not None:
            asyncio.run(run_mcp_checks(store, checks))
            cleanup = daemon.stop()

            daemon = TuringDaemon(home)
            daemon.start()
            restarted = TuringAgentMemory(
                daemon.client(), turing_home=home, graph="e2e_agent_memory"
            )
            restarted.load_graph_after_restart()
            memory = restarted.search_memory(
                user_identifier="alice", query="espresso TuringDB memory", limit=1
            )
            docs = restarted.search_documents(
                user_identifier="alice", query="green reset token lockout", limit=1
            )
            check(
                checks,
                "restart_preserves_memory_and_document_retrieval",
                lambda: (
                    memory[0].content.startswith("Davide prefers espresso")
                    and docs[0].chunk_id == "doc-machine-safety#1"
                ),
            )
    finally:
        cleanup = daemon.stop()
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
