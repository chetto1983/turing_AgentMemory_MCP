"""D-04/D-05 bake-off harness (Phase 4 Wave 1, the D-02 spike's second half).

Re-runnable: indexes a small fixture corpus in a live ArcadeDB 26.7.1 container
with BOTH D-04 lexical-channel candidates (native Lucene full-text via
SEARCH_INDEX, and native LSM_SPARSE_VECTOR BM25-style scoring via
vector.sparseNeighbors), scores both against
`baseline/03-turingdb/frozen-questions.json` PLUS hand-authored lexical-stress
queries derived from the same corpus, and prototypes the 2-hop
entity->fact->memory traversal in both SQL MATCH and openCypher (D-05).

The corpus itself: `baseline/03-turingdb/`'s actual document bytes are not
committed (external path, D-06), but each frozen question's `evidence_quote`
IS a committed, real, verbatim excerpt from that corpus -- so this harness
indexes exactly those excerpts as its fixture chunks. This keeps the bake-off
grounded in real corpus text without requiring the uncommitted source files.

Usage: python scripts/arcadedb_spike.py --out .benchmarks/arcadedb-spike.json
Requires: docker compose up -d arcadedb (this script does not manage the
container's lifecycle; it fails loudly, not silently, if ArcadeDB is unreachable).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from turing_agentmemory_mcp.arcadedb_client import ArcadeDBClient

try:
    from real_document_benchmark_scoring import (  # noqa: F401 - some re-exported for tests
        evidence_rank,
        load_frozen_questions,
        normalized_tokens,
        summarize_results,
    )
except ImportError:  # running as `python scripts/arcadedb_spike.py` directly
    from scripts.real_document_benchmark_scoring import (  # noqa: F401
        evidence_rank,
        load_frozen_questions,
        normalized_tokens,
        summarize_results,
    )

ROOT = Path(__file__).resolve().parents[1]
FROZEN_QUESTIONS_PATH = ROOT / "baseline" / "03-turingdb" / "frozen-questions.json"
SPIKE_DATABASE = "arcadedb_spike_bakeoff"
VOCAB_SIZE = 4096
TOP_K = 20
CODE_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9./_-]{3,}")


def _token_id(token: str, vocab_size: int) -> int:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=4).digest()
    return int.from_bytes(digest, "big") % vocab_size


def _sparse_vector(text: str, idf: dict[str, float]) -> tuple[list[int], list[float]]:
    counts = Counter(normalized_tokens(text))
    by_bucket: dict[int, float] = {}
    for token, count in counts.items():
        bucket = _token_id(token, VOCAB_SIZE)
        weight = count * idf.get(token, 1.0)
        by_bucket[bucket] = by_bucket.get(bucket, 0.0) + weight
    if not by_bucket:
        return [], []
    buckets = sorted(by_bucket)
    return buckets, [by_bucket[bucket] for bucket in buckets]


def build_corpus_rows(frozen: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for filename, questions in frozen.items():
        for row in questions:
            rows.append(
                {
                    "document_id": filename,
                    "source_id": row["source_id"],
                    "chunk_id": f"{filename}::{row['source_id']}",
                    "text": row["evidence_quote"],
                    "question": row["question"],
                    "answer": row["answer"],
                    "evidence_quote": row["evidence_quote"],
                }
            )
    return rows


def build_lexical_stress_queries(
    rows: list[dict[str, str]], *, count: int = 8
) -> list[dict[str, str]]:
    """Derive keyword/error-code/exact-phrase stress queries from real corpus
    tokens (not fabricated text) -- one distinctive code-like token per row,
    picked across as many distinct documents as possible."""
    stress: list[dict[str, str]] = []
    seen_documents: set[str] = set()
    for row in rows:
        if len(stress) >= count:
            break
        candidates = [
            token
            for token in CODE_TOKEN_RE.findall(row["text"])
            if any(char.isdigit() for char in token) or token.isupper()
        ]
        if not candidates:
            continue
        if row["document_id"] in seen_documents and len(seen_documents) < 8:
            continue
        token = max(candidates, key=len)
        seen_documents.add(row["document_id"])
        stress.append(
            {
                "document_id": row["document_id"],
                "source_id": row["source_id"],
                "question": token,
                "answer": token,
                "evidence_quote": row["evidence_quote"],
            }
        )
    return stress


def index_corpus(client: ArcadeDBClient, rows: list[dict[str, str]]) -> dict[str, float]:
    client.command("CREATE VERTEX TYPE SpikeChunk")
    client.command("CREATE PROPERTY SpikeChunk.chunk_id STRING")
    client.command("CREATE PROPERTY SpikeChunk.document_id STRING")
    client.command("CREATE PROPERTY SpikeChunk.content STRING")
    client.command("CREATE PROPERTY SpikeChunk.tokens ARRAY_OF_INTEGERS")
    client.command("CREATE PROPERTY SpikeChunk.weights ARRAY_OF_FLOATS")
    client.command("CREATE INDEX ON SpikeChunk (chunk_id) UNIQUE")
    client.command("CREATE INDEX ON SpikeChunk (content) FULL_TEXT")
    client.command("CREATE INDEX ON SpikeChunk (tokens, weights) LSM_SPARSE_VECTOR")

    document_frequency: Counter[str] = Counter()
    for row in rows:
        for token in set(normalized_tokens(row["text"])):
            document_frequency[token] += 1
    total_docs = len(rows)
    idf = {token: math.log(1 + total_docs / count) for token, count in document_frequency.items()}

    for row in rows:
        tokens, weights = _sparse_vector(row["text"], idf)
        client.command(
            "INSERT INTO SpikeChunk SET chunk_id = :chunk_id, document_id = :document_id, "
            "content = :content, tokens = :tokens, weights = :weights",
            params={
                "chunk_id": row["chunk_id"],
                "document_id": row["document_id"],
                "content": row["text"],
                "tokens": tokens,
                "weights": weights,
            },
        )
    return idf


def query_lucene(client: ArcadeDBClient, query_text: str, *, limit: int) -> list[dict[str, Any]]:
    rows = client.query(
        "SELECT content, document_id, $score FROM SpikeChunk "
        'WHERE SEARCH_INDEX("SpikeChunk[content]", :q) ORDER BY $score DESC LIMIT :limit',
        params={"q": query_text, "limit": limit},
    )
    return [{"text": row["content"], "document_id": row["document_id"]} for row in rows]


def query_sparse(
    client: ArcadeDBClient, query_text: str, idf: dict[str, float], *, limit: int
) -> list[dict[str, Any]]:
    tokens, weights = _sparse_vector(query_text, idf)
    if not tokens:
        return []
    rows = client.query(
        'SELECT expand(vector.sparseNeighbors("SpikeChunk[tokens,weights]", :qi, :qv, :limit))',
        params={"qi": tokens, "qv": weights, "limit": limit},
    )
    return [{"text": row["content"], "document_id": row["document_id"]} for row in rows]


def _score_channel(
    client: ArcadeDBClient,
    query_fn: Any,
    questions: list[dict[str, str]],
    *,
    label: str,
) -> dict[str, Any]:
    scored_rows: list[dict[str, Any]] = []
    for row in questions:
        start = time.perf_counter()
        try:
            hits = query_fn(client, row["question"], limit=TOP_K)
            error = None
        except Exception as exc:  # noqa: BLE001 -- bake-off must record, not crash, per-row failures
            hits, error = [], str(exc)
        latency_ms = (time.perf_counter() - start) * 1000.0
        rank, matched_by = (
            evidence_rank(hits, evidence_quote=row["evidence_quote"], answer=row["answer"])
            if not error
            else (0, "error")
        )
        scored_rows.append(
            {
                "document_id": row["document_id"],
                "evidence_rank": rank,
                "matched_by": matched_by,
                "latency_ms": latency_ms,
                "error": error,
            }
        )
    summary = summarize_results(scored_rows)
    summary["channel"] = label
    return summary


def run_lexical_bakeoff(
    client: ArcadeDBClient,
    idf: dict[str, float],
    frozen_rows: list[dict[str, str]],
    stress_rows: list[dict[str, str]],
) -> dict[str, Any]:
    def lucene(client: ArcadeDBClient, query_text: str, *, limit: int) -> list[dict[str, Any]]:
        return query_lucene(client, query_text, limit=limit)

    def sparse(client: ArcadeDBClient, query_text: str, *, limit: int) -> list[dict[str, Any]]:
        return query_sparse(client, query_text, idf, limit=limit)

    return {
        "frozen_questions": {
            "lucene_full_text": _score_channel(
                client, lucene, frozen_rows, label="lucene_full_text"
            ),
            "lsm_sparse_vector": _score_channel(
                client, sparse, frozen_rows, label="lsm_sparse_vector"
            ),
        },
        "lexical_stress_queries": {
            "lucene_full_text": _score_channel(
                client, lucene, stress_rows, label="lucene_full_text"
            ),
            "lsm_sparse_vector": _score_channel(
                client, sparse, stress_rows, label="lsm_sparse_vector"
            ),
        },
    }


def run_graph_surface_bakeoff(client: ArcadeDBClient) -> dict[str, Any]:
    client.command("CREATE VERTEX TYPE SpikeEntity")
    client.command("CREATE VERTEX TYPE SpikeFact")
    client.command("CREATE VERTEX TYPE SpikeMemory")
    client.command("CREATE EDGE TYPE SUBJECT_OF")
    client.command("CREATE EDGE TYPE SUPPORTED_BY")
    client.command(
        "BEGIN;\n"
        'LET $e = CREATE VERTEX SpikeEntity SET id = "ent-1", name = "Acme";\n'
        'LET $f = CREATE VERTEX SpikeFact SET id = "fact-1", text = "Acme makes widgets";\n'
        'LET $m = CREATE VERTEX SpikeMemory SET id = "mem-1", text = "Acme makes widgets, said Bob";\n'
        "CREATE EDGE SUBJECT_OF FROM $e TO $f;\n"
        "CREATE EDGE SUPPORTED_BY FROM $f TO $m;\n"
        "COMMIT;\n",
        language="sqlscript",
    )

    sql_result: dict[str, Any] = {"binds_params": False, "two_hop_succeeds": False}
    try:
        rows = client.query(
            "MATCH {type: SpikeEntity, as: e, where: (id = :id)}"
            '.out("SUBJECT_OF"){as: f}.out("SUPPORTED_BY"){as: m} '
            "RETURN m.id, f.id, e.id",
            params={"id": "ent-1"},
        )
        sql_result["binds_params"] = True
        sql_result["two_hop_succeeds"] = bool(rows) and rows[0]["m.id"] == "mem-1"
    except Exception as exc:  # noqa: BLE001
        sql_result["error"] = str(exc)

    cypher_result: dict[str, Any] = {"binds_params": False, "two_hop_succeeds": False}
    try:
        rows = client.query(
            "MATCH (e:SpikeEntity {id: $id})-[:SUBJECT_OF]->(f:SpikeFact)"
            "-[:SUPPORTED_BY]->(m:SpikeMemory) RETURN m.id",
            params={"id": "ent-1"},
            language="opencypher",
        )
        cypher_result["binds_params"] = True
        cypher_result["two_hop_succeeds"] = bool(rows) and rows[0]["m.id"] == "mem-1"
    except Exception as exc:  # noqa: BLE001
        cypher_result["error"] = str(exc)

    return {
        "sql_match": {
            **sql_result,
            "composes_with_vector_and_fulltext_in_one_statement": True,
            "note": "SQL is the same language as vectorNeighbors/SEARCH_INDEX -- a single "
            "query can traverse AND rank by vector/full-text in one statement.",
        },
        "opencypher": {
            **cypher_result,
            "composes_with_vector_and_fulltext_in_one_statement": False,
            "note": "openCypher is a separate `language` identifier from `sql` -- it cannot "
            "call vectorNeighbors()/SEARCH_INDEX() inline in the same statement.",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / ".benchmarks" / "arcadedb-spike.json"))
    parser.add_argument(
        "--frozen-questions", default=str(FROZEN_QUESTIONS_PATH), help="D-06 yardstick source"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env_client = ArcadeDBClient.from_env()
    client = ArcadeDBClient(
        base_url=env_client.base_url,
        username=env_client.username,
        password=env_client.password,
        database=SPIKE_DATABASE,
    )
    if not client.is_ready():
        print(
            f"ArcadeDB not reachable at {client.base_url} -- run "
            "`docker compose up -d arcadedb` before this bake-off.",
            file=sys.stderr,
        )
        return 1

    try:
        client._server_command(f"drop database {SPIKE_DATABASE}")
    except RuntimeError:
        pass
    client.ensure_database()

    frozen = load_frozen_questions(Path(args.frozen_questions))
    frozen_rows = build_corpus_rows(frozen)
    stress_rows = build_lexical_stress_queries(frozen_rows)

    idf = index_corpus(client, frozen_rows)
    lexical = run_lexical_bakeoff(client, idf, frozen_rows, stress_rows)
    graph = run_graph_surface_bakeoff(client)

    payload = {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "image": "arcadedata/arcadedb:26.7.1",
        "corpus": {
            "source": str(args.frozen_questions),
            "chunk_count": len(frozen_rows),
            "document_count": len(frozen),
            "stress_query_count": len(stress_rows),
        },
        "resolved_capabilities": {
            "endpoint_prefix": "/api/v1/{query,command,begin,commit,rollback}/<database>",
            "auth": "HTTP Basic (root + rootPassword via JAVA_OPTS)",
            "vector_function": 'vectorNeighbors("Type[property]", vec, k)',
            "vector_ddl": "CREATE INDEX ON Type (prop) LSM_VECTOR METADATA "
            '{"dimensions": N, "similarity": "cosine", "maxConnections": N, "beamWidth": N}',
            "read_your_writes": "confirmed via arcadedb-session-id header session model",
        },
        "lexical_channel_bakeoff": lexical,
        "graph_query_surface_bakeoff": graph,
        "notes": [
            "SEARCH_INDEX(...) parses its query argument as raw Lucene query syntax: "
            "unescaped '?'/'*'/parentheses/apostrophes in natural-language questions can "
            "raise IndexException (observed live: 2/60 frozen questions failed this way). "
            "CONTAINSTEXT and LSM_SPARSE_VECTOR take/produce structured input and do not "
            "share this fragility -- see 04-SPIKE-FINDINGS.md D-04.",
        ],
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(f"wrote {out_path}")

    try:
        client._server_command(f"drop database {SPIKE_DATABASE}")
    except RuntimeError:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
