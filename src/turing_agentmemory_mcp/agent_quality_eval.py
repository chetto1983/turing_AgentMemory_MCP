from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from turing_agentmemory_mcp.benchmark import _git_commit

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_USER = "davide-agent-quality"
MAX_DOCUMENT_CHARS = 30_000


@dataclass(frozen=True)
class AgentQualityMemory:
    memory_id: str
    content: str
    tags: list[str]


@dataclass(frozen=True)
class AgentQualityDocument:
    document_id: str
    title: str
    relative_path: str
    text: str
    tags: list[str]

    @property
    def source(self) -> str:
        return f"aura:{self.relative_path}"


@dataclass(frozen=True)
class AgentQualityCase:
    query_id: str
    kind: str
    query: str
    expected_id: str


@dataclass(frozen=True)
class AgentQualityCorpus:
    memories: list[AgentQualityMemory]
    documents: list[AgentQualityDocument]
    cases: list[AgentQualityCase]


AURA_DOCUMENT_SPECS: tuple[tuple[str, str, str, list[str]], ...] = (
    (
        "aura-readme",
        "Aura README",
        "README.md",
        ["aura", "docs", "readme"],
    ),
    (
        "aura-claude-guidance",
        "Aura Claude Guidance",
        "CLAUDE.md",
        ["aura", "docs", "guidance"],
    ),
    (
        "aura-web-autospeak",
        "Aura Web AutoSpeak",
        "web/src/chat/voice/AutoSpeak.tsx",
        ["aura", "web", "voice"],
    ),
    (
        "aura-web-voice-runtime",
        "Aura Web Voice Runtime",
        "web/src/chat/voice/useVoiceRuntime.ts",
        ["aura", "web", "voice"],
    ),
    (
        "aura-web-external-store-chat",
        "Aura ExternalStoreChat",
        "web/src/chat/ExternalStoreChat.tsx",
        ["aura", "web", "chat"],
    ),
    (
        "aura-web-external-store-messages",
        "Aura ExternalStoreChat Messages",
        "web/src/chat/ExternalStoreChat_messages.tsx",
        ["aura", "web", "chat"],
    ),
)


def build_agent_quality_corpus(aura_root: Path) -> AgentQualityCorpus:
    aura_root = aura_root.resolve()
    memories = [
        AgentQualityMemory(
            memory_id="agentmemory-docker-stdio",
            content=(
                "AgentMemory MCP installed stdio command: docker.exe compose -f "
                "D:\\turing_AgentMemory_MCP\\compose.yaml run --rm -T "
                "turing-agentmemory-mcp serve --transport stdio."
            ),
            tags=["agent-quality", "mcp", "docker"],
        ),
        AgentQualityMemory(
            memory_id="davide-entity-extraction-priority",
            content=(
                "Davide said: I do not care about privacy for this slice, I care about "
                "entity extraction quality. GLiNER and GLiNER2 entity extraction should improve memory."
            ),
            tags=["agent-quality", "entities", "gliner"],
        ),
        AgentQualityMemory(
            memory_id="agentmemory-score-gate",
            content=(
                "The AgentMemory validation gate expects score 10.0, score_gate 10/10, "
                "and verdict VALIDATED_10_10; anything below 9.8 needs attention."
            ),
            tags=["agent-quality", "e2e", "score"],
        ),
        AgentQualityMemory(
            memory_id="aura-readonly-boundary",
            content=(
                "D:\\Aura is the Aura repo. AgentMemory work must not touch Aura files unless explicitly "
                "needed; for agent-quality evaluation Aura is a read-only corpus source."
            ),
            tags=["agent-quality", "aura", "boundary"],
        ),
    ]
    documents: list[AgentQualityDocument] = []
    for document_id, title, relative_path, tags in AURA_DOCUMENT_SPECS:
        path = aura_root / relative_path
        if not path.exists() or not path.is_file():
            continue
        body = path.read_text(encoding="utf-8", errors="replace")
        clipped = body[:MAX_DOCUMENT_CHARS]
        text = (
            f"Aura corpus file: {relative_path}\n"
            f"Aura corpus document id: {document_id}\n\n"
            f"{clipped}"
        )
        documents.append(
            AgentQualityDocument(
                document_id=document_id,
                title=title,
                relative_path=relative_path,
                text=text,
                tags=tags,
            )
        )

    cases = [
        AgentQualityCase(
            query_id="memory-docker-stdio-command",
            kind="memory",
            query="AgentMemory MCP Docker stdio command compose file serve transport stdio",
            expected_id="agentmemory-docker-stdio",
        ),
        AgentQualityCase(
            query_id="memory-gliner-entity-priority",
            kind="memory",
            query="Davide cares about GLiNER entity extraction quality not privacy",
            expected_id="davide-entity-extraction-priority",
        ),
        AgentQualityCase(
            query_id="memory-e2e-score-gate",
            kind="memory",
            query="expected score_gate 10/10 verdict VALIDATED_10_10",
            expected_id="agentmemory-score-gate",
        ),
        AgentQualityCase(
            query_id="memory-aura-boundary",
            kind="memory",
            query="which repo is read-only unless explicitly needed Aura",
            expected_id="aura-readonly-boundary",
        ),
    ]
    available_document_ids = {document.document_id for document in documents}
    document_cases = [
        AgentQualityCase(
            query_id="doc-aura-readme-local-first",
            kind="document",
            query="Aura local-first provider-neutral AI agent platform in Go graph-backed memory",
            expected_id="aura-readme",
        ),
        AgentQualityCase(
            query_id="doc-aura-claude-prd-first",
            kind="document",
            query="Senza PRD completo non si scrive una riga di codice truth-source",
            expected_id="aura-claude-guidance",
        ),
        AgentQualityCase(
            query_id="doc-aura-autospeak",
            kind="document",
            query="Aura corpus file AutoSpeak.tsx AutoSpeak voice chat component",
            expected_id="aura-web-autospeak",
        ),
        AgentQualityCase(
            query_id="doc-aura-voice-runtime",
            kind="document",
            query="Aura useVoiceRuntime voice runtime hook microphone speech audio",
            expected_id="aura-web-voice-runtime",
        ),
        AgentQualityCase(
            query_id="doc-aura-external-store-chat",
            kind="document",
            query="Aura ExternalStoreChat web chat component external store messages",
            expected_id="aura-web-external-store-chat",
        ),
    ]
    cases.extend(case for case in document_cases if case.expected_id in available_document_ids)
    return AgentQualityCorpus(memories=memories, documents=documents, cases=cases)


def evaluate_case(
    *,
    query_id: str,
    kind: str,
    query: str,
    expected_id: str,
    hit_ids: Sequence[str],
    latency_ms: float,
    top_score: float,
) -> dict[str, Any]:
    return {
        "query_id": query_id,
        "kind": kind,
        "query": query,
        "expected_id": expected_id,
        "hit_ids": list(hit_ids),
        "top1": bool(hit_ids and hit_ids[0] == expected_id),
        "top3": expected_id in list(hit_ids)[:3],
        "latency_ms": round(latency_ms, 3),
        "top_score": round(top_score, 4),
    }


def summarize_case_results(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    count = len(rows)
    top1 = sum(1 for row in rows if row.get("top1"))
    top3 = sum(1 for row in rows if row.get("top3"))
    latencies = [float(row.get("latency_ms") or 0.0) for row in rows]
    top1_accuracy = round(top1 / count, 4) if count else 0.0
    top3_accuracy = round(top3 / count, 4) if count else 0.0
    verdict = "VALIDATED_AGENT_QUALITY" if count and top1_accuracy >= 0.875 and top3_accuracy == 1.0 else "NEEDS_ATTENTION"
    return {
        "count": count,
        "top1_accuracy": top1_accuracy,
        "top3_accuracy": top3_accuracy,
        "p50_ms": _percentile(latencies, 50),
        "p95_ms": _percentile(latencies, 95),
        "verdict": verdict,
    }


def default_agent_quality_out() -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / ".benchmarks" / f"agent-quality-{stamp}.json"


def run_agent_quality_eval(
    *,
    aura_root: Path,
    out: Path,
    use_external_embed: bool = False,
    use_external_rerank: bool = False,
    keep_home: bool = False,
    top_k: int = 3,
) -> dict[str, Any]:
    from turing_agentmemory_mcp.e2e_score import LocalEmbedServer, LocalRerankServer, TuringDaemon
    from turing_agentmemory_mcp.store import TuringAgentMemory

    try:
        from turingdb import __version__ as turingdb_version
    except ModuleNotFoundError:
        turingdb_version = "unavailable"

    corpus = build_agent_quality_corpus(aura_root)
    if not corpus.documents:
        raise RuntimeError(f"no Aura corpus files found under {aura_root}")

    timestamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    home = Path(os.environ.get("TURINGDB_AGENT_QUALITY_HOME", ROOT / ".turingdb" / "agent-quality"))
    if home.exists() and not keep_home:
        shutil.rmtree(home)
    graph = f"agent_quality_{int(time.time())}"
    daemon = TuringDaemon(home)
    embed_server: Any | None = None
    rerank_server: Any | None = None
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
    cleanup: dict[str, Any] = {}
    case_rows: list[dict[str, Any]] = []
    try:
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

        daemon.start()
        store = TuringAgentMemory(daemon.client(), turing_home=home, graph=graph)
        store.bootstrap()
        store.store_messages(
            user_identifier=DEFAULT_USER,
            messages=[
                {
                    "memory_id": memory.memory_id,
                    "session_id": "agent-quality",
                    "role": "system",
                    "content": memory.content,
                    "source": "agent-quality",
                    "tags": memory.tags,
                    "metadata": {"eval": "agent-quality"},
                }
                for memory in corpus.memories
            ],
        )
        for document in corpus.documents:
            store.ingest_document_text(
                user_identifier=DEFAULT_USER,
                document_id=document.document_id,
                title=document.title,
                text=document.text,
                source=document.source,
                tags=document.tags,
                metadata={"relative_path": document.relative_path, "eval": "agent-quality"},
            )

        for case in corpus.cases:
            started = time.perf_counter()
            if case.kind == "memory":
                hits = store.search_memory(
                    user_identifier=DEFAULT_USER,
                    query=case.query,
                    limit=top_k,
                    tags=["agent-quality"],
                    explain=True,
                )
                hit_ids = [hit.id for hit in hits]
                top_score = hits[0].score if hits else 0.0
            else:
                doc_hits = store.search_documents(
                    user_identifier=DEFAULT_USER,
                    query=case.query,
                    limit=top_k,
                    tags=["aura"],
                    explain=True,
                )
                hit_ids = _unique_document_ids(doc_hits)
                top_score = doc_hits[0].score if doc_hits else 0.0
            case_rows.append(
                evaluate_case(
                    query_id=case.query_id,
                    kind=case.kind,
                    query=case.query,
                    expected_id=case.expected_id,
                    hit_ids=hit_ids,
                    latency_ms=(time.perf_counter() - started) * 1000,
                    top_score=top_score,
                )
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

    summary = summarize_case_results(case_rows)
    result = {
        "timestamp": timestamp,
        "git_commit": _git_commit(),
        "turingdb_version": turingdb_version,
        "embedding_model": os.environ.get("EMBED_MODEL") or "external" if use_external_embed else "local-embedding",
        "rerank_model": os.environ.get("RERANK_MODEL") or "external" if use_external_rerank else "local-rerank",
        "aura_root": str(aura_root.resolve()),
        "graph": graph,
        "memory_count": len(corpus.memories),
        "document_count": len(corpus.documents),
        "case_count": len(case_rows),
        "summary": summary,
        "cases": case_rows,
        "cleanup": cleanup,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agent-quality-eval")
    parser.add_argument("--aura-root", default=r"D:\Aura")
    parser.add_argument("--out", default=None)
    parser.add_argument("--keep-home", action="store_true")
    parser.add_argument("--use-external-embed", action="store_true")
    parser.add_argument("--use-external-rerank", action="store_true")
    args = parser.parse_args(argv)
    result = run_agent_quality_eval(
        aura_root=Path(args.aura_root),
        out=Path(args.out) if args.out else default_agent_quality_out(),
        keep_home=args.keep_home,
        use_external_embed=args.use_external_embed,
        use_external_rerank=args.use_external_rerank,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["summary"]["verdict"] == "VALIDATED_AGENT_QUALITY" else 1


def _unique_document_ids(hits: Sequence[Any]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for hit in hits:
        document_id = str(getattr(hit, "document_id", ""))
        if document_id and document_id not in seen:
            seen.add(document_id)
            ids.append(document_id)
    return ids


def _percentile(values: Sequence[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    rank = (len(ordered) - 1) * (percentile / 100)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = rank - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * fraction, 3)
