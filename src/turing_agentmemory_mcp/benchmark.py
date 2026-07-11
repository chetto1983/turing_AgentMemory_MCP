"""Benchmark CLI entrypoint. `main`, `REQUIRED_FIELDS`, `make_result_row`, and
`_git_commit` are imported unchanged by `scripts/benchmark.py`,
`agent_quality_eval.py`, and `tests/test_benchmark.py` — do not remove them.

Split by concern per D-08/D-09: result-row schema/dataclasses live in
`benchmark_schema.py`, the synthetic-corpus pipeline stages live in
`benchmark_stages.py`, and the MemoryArena-bucket stage lives in
`benchmark_memoryarena.py`. This module owns the corpus runner
(`run_benchmarks`), the CLI (`main`), and git-commit resolution — `_git_commit`
stays here because it reads the module-level `ROOT` directly (tests monkeypatch
`benchmark.ROOT`).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from turing_agentmemory_mcp.benchmark_memoryarena import (  # noqa: F401 - preserved public import path
    _benchmark_memoryarena,
    _default_memoryarena_configs,
    _memoryarena_cases_from_sample,
    _parse_memoryarena_configs,
)
from turing_agentmemory_mcp.benchmark_schema import (  # noqa: F401 - preserved public import path
    REQUIRED_FIELDS,
    make_result_row,
)
from turing_agentmemory_mcp.benchmark_stages import (
    _benchmark_documents,
    _benchmark_memory_search,
    _benchmark_memory_store,
    _benchmark_memory_store_batch,
    _benchmark_rerank_comparison,
    _benchmark_restart,
)

ROOT = Path(__file__).resolve().parents[2]


def run_benchmarks(
    *,
    out: Path,
    memory_count: int = 40,
    search_count: int = 20,
    document_count: int = 5,
    top_k: int = 5,
    use_external_embed: bool = False,
    use_external_rerank: bool = False,
    keep_home: bool = False,
    memoryarena_index: int = 0,
    memoryarena_configs: Sequence[str] | None = None,
    memoryarena_samples_per_config: int = 1,
    memoryarena_cases_per_config: int = 8,
) -> list[dict[str, Any]]:
    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    git_commit = _git_commit()
    home = Path(os.environ.get("TURINGDB_BENCH_HOME", ROOT / ".turingdb" / "benchmark"))
    graph = f"benchmark_agent_memory_{int(time.time())}"
    from turing_agentmemory_mcp.e2e_score import (
        LocalEmbedServer,
        LocalRerankServer,
        TuringDaemon,
    )
    from turing_agentmemory_mcp.store import TuringAgentMemory

    embed_server: Any | None = None
    rerank_server: Any | None = None
    daemon = TuringDaemon(home)
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
    rows: list[dict[str, Any]] = []
    store: TuringAgentMemory | None = None

    try:
        if home.exists() and not keep_home:
            shutil.rmtree(home)
        if not use_external_embed:
            embed_server = LocalEmbedServer(dimensions=768)
            embed_server.start()
            os.environ["EMBED_BASE_URL"] = embed_server.base_url
            os.environ["EMBED_DIMENSIONS"] = "768"
            os.environ["EMBED_MODEL"] = "local-embedding"
        if not use_external_rerank:
            rerank_server = LocalRerankServer()
            rerank_server.start()
            os.environ["RERANK_BASE_URL"] = rerank_server.base_url
            os.environ["RERANK_MODEL"] = "local-rerank"

        embedding_model = os.environ.get("EMBED_MODEL", "local-embedding")
        rerank_model = os.environ.get("RERANK_MODEL", "local-rerank")

        daemon.start()
        store = TuringAgentMemory(daemon.client(), turing_home=home, graph=graph)
        store.bootstrap()

        rows.extend(
            _benchmark_memory_store(
                store,
                timestamp=timestamp,
                git_commit=git_commit,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
                memory_count=memory_count,
            )
        )
        rows.extend(
            _benchmark_memory_store_batch(
                store,
                timestamp=timestamp,
                git_commit=git_commit,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
                memory_count=memory_count,
            )
        )
        rows.extend(
            _benchmark_memory_search(
                store,
                timestamp=timestamp,
                git_commit=git_commit,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
                memory_count=memory_count,
                search_count=search_count,
                top_k=top_k,
            )
        )
        rows.extend(
            _benchmark_documents(
                store,
                timestamp=timestamp,
                git_commit=git_commit,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
                document_count=document_count,
                search_count=search_count,
                top_k=top_k,
            )
        )
        rows.extend(
            _benchmark_rerank_comparison(
                store,
                timestamp=timestamp,
                git_commit=git_commit,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
                memory_count=memory_count,
                search_count=max(8, min(search_count, 16)),
                top_k=top_k,
            )
        )
        rows.extend(
            _benchmark_memoryarena(
                store,
                timestamp=timestamp,
                git_commit=git_commit,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
                memoryarena_index=memoryarena_index,
                memoryarena_configs=list(memoryarena_configs or _default_memoryarena_configs()),
                samples_per_config=memoryarena_samples_per_config,
                cases_per_config=memoryarena_cases_per_config,
                top_k=top_k,
            )
        )
        rows.append(
            _benchmark_restart(
                daemon=daemon,
                home=home,
                graph=graph,
                timestamp=timestamp,
                git_commit=git_commit,
                embedding_model=embedding_model,
                rerank_model=rerank_model,
            )
        )
    finally:
        daemon.stop()
        if embed_server is not None:
            embed_server.stop()
        if rerank_server is not None:
            rerank_server.stop()
        for key, value in previous_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2, sort_keys=True), encoding="utf-8")
    return rows


def default_output_path() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / ".benchmarks" / f"benchmark-{stamp}.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=default_output_path())
    parser.add_argument("--memory-count", type=int, default=40)
    parser.add_argument("--search-count", type=int, default=20)
    parser.add_argument("--document-count", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--use-external-embed", action="store_true")
    parser.add_argument("--use-external-rerank", action="store_true")
    parser.add_argument("--keep-home", action="store_true")
    parser.add_argument("--memoryarena-index", type=int, default=0)
    parser.add_argument(
        "--memoryarena-configs",
        default=",".join(_default_memoryarena_configs()),
        help="Comma-separated MemoryArena configs, or 'none' to skip.",
    )
    parser.add_argument("--memoryarena-samples-per-config", type=int, default=1)
    parser.add_argument("--memoryarena-cases-per-config", type=int, default=8)
    args = parser.parse_args()
    memoryarena_configs = _parse_memoryarena_configs(args.memoryarena_configs)
    rows = run_benchmarks(
        out=args.out,
        memory_count=args.memory_count,
        search_count=args.search_count,
        document_count=args.document_count,
        top_k=args.top_k,
        use_external_embed=args.use_external_embed,
        use_external_rerank=args.use_external_rerank,
        keep_home=args.keep_home,
        memoryarena_index=args.memoryarena_index,
        memoryarena_configs=memoryarena_configs,
        memoryarena_samples_per_config=args.memoryarena_samples_per_config,
        memoryarena_cases_per_config=args.memoryarena_cases_per_config,
    )
    print(json.dumps({"out": str(args.out), "result_count": len(rows)}, sort_keys=True))
    return 0


def _git_commit() -> str:
    configured = os.environ.get("BENCHMARK_GIT_COMMIT") or os.environ.get("GIT_COMMIT")
    if configured:
        return configured
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.stdout.strip()
    except Exception:
        return _git_head_commit()


def _git_head_commit() -> str:
    head = ROOT / ".git" / "HEAD"
    try:
        value = head.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"
    if value.startswith("ref:"):
        ref_path = value.split(":", 1)[1].strip()
        try:
            value = (ROOT / ".git" / ref_path).read_text(encoding="utf-8").strip()
        except OSError:
            return "unknown"
    return value[:7] if value else "unknown"


if __name__ == "__main__":
    raise SystemExit(main())
