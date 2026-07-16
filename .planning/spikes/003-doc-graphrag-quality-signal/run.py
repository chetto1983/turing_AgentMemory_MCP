"""Spike 003 — doc-graphrag-quality-signal (targeted subset).

Question (Given/When/Then): GIVEN a runnable 001+002 prototype and the frozen
question yardstick, WHEN graph-channel results are compared to the dense+lexical
baseline on the entity-rich subset, THEN we quantify the lift the graph channel
adds (or identify where it helps).

Isolation design: for each frozen question we score THREE configs, all reranked by
the real BGE reranker over the same pool size, so the ONLY difference between the
two fused configs is the graph channel:
  - production   : store.search_documents (dense+lexical blend -> rerank)  [reference]
  - fused_base   : fuse_rankings(dense, lexical) -> rerank
  - fused_graph  : fuse_rankings(dense, lexical, multi_hop_graph) -> rerank

Subset (entity-rich text docs): 5 normattiva legal PDFs + ML-wikipedia + robot docx.
Real granite embed + GLiNER + BGE rerank + ArcadeDB. Isolated `spike_dgr3` DB.

Run: see README. Reads corpus from /corpus, frozen questions from /baseline.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
import time
from pathlib import Path

from turing_agentmemory_mcp.arcadedb_client import ArcadeDBClient
from turing_agentmemory_mcp.document_processing import convert_document_to_markdown
from turing_agentmemory_mcp.entity_extraction import (
    DEFAULT_METADATA_KEY,
    HTTPGLiNEREntityProcessor,
    NoopEntityProcessor,
)
from turing_agentmemory_mcp.ids import stable_id
from turing_agentmemory_mcp.models import RetrievalCandidate
from turing_agentmemory_mcp.retrieval_fusion import fuse_rankings
from turing_agentmemory_mcp.store import TuringAgentMemory
from turing_agentmemory_mcp.store_documents_queries import (
    chunk_lucene_search_statement,
    chunk_vector_search_statement,
)
from turing_agentmemory_mcp.temporal_graph import canonicalize_entity_name

import sys

sys.path.insert(0, "/spikes/_scoring")
from real_document_benchmark_scoring import (  # noqa: E402
    evidence_rank,
    load_frozen_questions,
    summarize_results,
)

USER = "spike-dgr3"
DB = "spike_dgr3"
HERE = Path(__file__).resolve().parent
CORPUS = Path("/corpus")
FROZEN = Path("/baseline/frozen-questions.json")
# Fast-signal subset: 3 Italian docs, each capped, to finish in minutes on the
# CPU sidecar and expose the current model's Italian entity yield (the diagnostic
# for whether a multilingual swap is warranted).
SUBSET = [
    "Corso Base Robot.docx",
    "apprendimento_automatico_wikipedia.html",
    "normattiva_DECRETO DEL PRESIDENTE DELLA REPUBBLICA_19730329_156_1973-05-03_073U0156_VIGENZA_2026-02-10_V0.pdf",
]
MAX_DOC_CHARS = 80_000  # cap ingested text/doc to bound chunk count on CPU
RERANK_POOL = 50
TOP_K = 20
MAX_HOPS = 2
HOP_CHUNK_CAP = 40
CHUNK_CHARS = 1200  # GLiNER-safe + evidence-quote-containable; shared by both configs
GLINER_MAX_CHARS = 1500  # truncate per-chunk text sent to GLiNER (avoid oversize 400)
GLINER_BATCH = 16  # small batches: one huge full-doc payload 400s the sidecar
GLINER: HTTPGLiNEREntityProcessor | None = None  # set in main()


def build_store() -> TuringAgentMemory:
    client = dataclasses.replace(ArcadeDBClient.from_env(), database=DB)
    try:
        client._server_command(f"drop database {DB}")
    except RuntimeError:
        pass
    client.create_database()
    home = Path(tempfile.mkdtemp(prefix="home-", dir=str(HERE)))
    store = TuringAgentMemory(client, turing_home=home, graph=DB)
    store.bootstrap()
    return store


def names_of(texts: list[str]) -> list[list[str]]:
    """Per-text entity surfaces via a dedicated GLiNER client. Each text is
    truncated to GLINER_MAX_CHARS -- sending a whole legal PDF in one call 400s
    the sidecar (see README finding)."""
    assert GLINER is not None
    clipped = [t[:GLINER_MAX_CHARS] for t in texts]
    out = []
    for i in range(0, len(clipped), GLINER_BATCH):
        for pt in GLINER.process_many(clipped[i : i + GLINER_BATCH]):
            payload = pt.metadata.get(DEFAULT_METADATA_KEY, {})
            ents = payload.get("entities", []) if isinstance(payload, dict) else []
            names = {canonicalize_entity_name(str(e.get("text", ""))) for e in ents if e.get("text")}
            out.append(sorted(n for n in names if n and len(n) > 1))
    return out


def eid(name: str) -> str:
    return stable_id("ent", USER, name)


def ingest_subset(store: TuringAgentMemory) -> dict:
    stats: dict = {"docs": [], "total_chunks": 0}
    for fname in SUBSET:
        path = CORPUS / fname
        if not path.exists():
            stats["docs"].append({"file": fname, "status": "MISSING"})
            continue
        converted = convert_document_to_markdown(path)
        text = converted.text[:MAX_DOC_CHARS]
        store.ingest_document_text(
            user_identifier=USER, title=fname, text=text,
            document_id=fname, chunk_chars=CHUNK_CHARS,
        )
        stats["docs"].append({"file": fname, "status": "ok", "chars": len(text)})
    chunks = store.client.query(
        "SELECT id, document_id, text FROM Chunk WHERE user_identifier = :u", params={"u": USER}
    )
    stats["total_chunks"] = len(chunks)
    return stats, chunks


def link_entities(store: TuringAgentMemory, chunks: list[dict]) -> dict:
    texts = [str(c["text"]) for c in chunks]
    per_chunk = names_of(texts)
    writes: list[tuple[str, dict]] = []
    seen: set[str] = set()
    edges = 0
    for chunk, names in zip(chunks, per_chunk, strict=True):
        for name in names:
            if eid(name) not in seen:
                seen.add(eid(name))
                writes.append((
                    "UPDATE Entity SET id = :id, user_identifier = :u, canonical_name = :c, "
                    "display_name = :c, content = :c UPSERT WHERE id = :id",
                    {"id": eid(name), "u": USER, "c": name},
                ))
        for name in names:
            writes.append((
                "CREATE EDGE MENTIONS FROM (SELECT FROM Chunk WHERE id = :cid AND "
                "user_identifier = :u) TO (SELECT FROM Entity WHERE id = :eid AND "
                "user_identifier = :u)",
                {"cid": str(chunk["id"]), "eid": eid(name), "u": USER},
            ))
            edges += 1
    # write in bounded batches to keep transactions reasonable
    for i in range(0, len(writes), 400):
        store._write_many(writes[i : i + 400])
    return {"entities": len(seen), "mentions_edges": edges}


def _row_cand(r: dict, info: dict) -> RetrievalCandidate:
    cid = str(r["id"])
    info[cid] = (str(r.get("text") or ""), str(r.get("document_id") or ""))
    return RetrievalCandidate(
        candidate_id=cid, kind="chunk", content=str(r.get("document_id") or "x"),
        source_memory_id=str(r.get("document_id") or ""),
    )


def dense(store, query, info):
    stmt, params = chunk_vector_search_statement(
        embedding=store.embedder.embed(query), k=RERANK_POOL, user_identifier=USER
    )
    rows = sorted(store.client.query(stmt, params=params), key=lambda r: float(r.get("distance") or 1.0))
    return [_row_cand(r, info) for r in rows]


def lexical(store, query, info):
    stmt, params = chunk_lucene_search_statement(query=query, limit=RERANK_POOL, user_identifier=USER)
    return [_row_cand(r, info) for r in store.client.query(stmt, params=params)]


def graph(store, query, info):
    frontier = [eid(n) for n in names_of([query])[0]]
    visited_e, chunk_hop = set(frontier), {}
    for hop in range(1, MAX_HOPS + 1):
        rows = []
        for e in frontier[:HOP_CHUNK_CAP]:
            rows += store.client.query(
                "SELECT id, document_id, text FROM (SELECT expand(in('MENTIONS')) FROM Entity "
                "WHERE id = :eid AND user_identifier = :u) WHERE user_identifier = :u LIMIT 60",
                params={"eid": e, "u": USER},
            )
        new_ids = []
        for r in rows:
            cid = str(r["id"])
            if cid not in chunk_hop:
                chunk_hop[cid] = hop
                _row_cand(r, info)
                new_ids.append(cid)
        next_e = set()
        for c in new_ids[:HOP_CHUNK_CAP]:
            for er in store.client.query(
                "SELECT id FROM (SELECT expand(out('MENTIONS')) FROM Chunk WHERE id = :cid AND "
                "user_identifier = :u) WHERE user_identifier = :u",
                params={"cid": c, "u": USER},
            ):
                next_e.add(str(er["id"]))
        frontier = sorted(next_e - visited_e)
        visited_e |= next_e
        if not frontier:
            break
    ranked = sorted(chunk_hop.items(), key=lambda kv: kv[1])
    return [
        RetrievalCandidate(candidate_id=cid, kind="chunk", content=info[cid][1] or "x",
                           source_memory_id=info[cid][1], raw_score=1.0 / hop)
        for cid, hop in ranked
    ]


def rerank_hits(store, query, cand_ids, info):
    ids = cand_ids[:RERANK_POOL]
    texts = [info[c][0] or " " for c in ids]
    if not texts:
        return []
    scored = store.reranker.rerank(query, texts)
    order = [s.index for s in scored] if scored else list(range(len(ids)))
    return [{"text": info[ids[i]][0], "document_id": info[ids[i]][1]} for i in order][:TOP_K]


def fused_ids(store, query, info, with_graph):
    d, x = dense(store, query, info), lexical(store, query, info)
    rankings = {"dense": d, "lexical": x}
    weights = {"dense": 1.0, "lexical": 1.0}
    if with_graph:
        rankings["graph"] = graph(store, query, info)
        weights["graph"] = 1.0
    fused = fuse_rankings(rankings, weights=weights)
    return [f.candidate.candidate_id for f in fused]


def run_question(store, q, fname) -> dict:
    query = q["question"]
    rows = {}
    for cfg, fn in (
        ("production", lambda: [
            {"text": h.text, "document_id": h.document_id}
            for h in store.search_documents(user_identifier=USER, query=query, limit=TOP_K)
        ]),
        ("fused_base", lambda: rerank_hits(store, query, fused_ids(store, query, _INFO, False), _INFO)),
        ("fused_graph", lambda: rerank_hits(store, query, fused_ids(store, query, _INFO, True), _INFO)),
    ):
        t0 = time.monotonic()
        try:
            hits = fn()
            rank, _ = evidence_rank(hits, evidence_quote=q["evidence_quote"], answer=q["answer"])
            rows[cfg] = {"document_id": fname, "evidence_rank": rank,
                         "latency_ms": (time.monotonic() - t0) * 1000.0}
        except Exception as exc:  # noqa: BLE001
            rows[cfg] = {"document_id": fname, "evidence_rank": 0, "error": str(exc)[:160],
                         "latency_ms": (time.monotonic() - t0) * 1000.0}
    return rows


_INFO: dict = {}


def main() -> int:
    global GLINER
    log: dict = {"spike": "003-doc-graphrag-quality-signal", "subset": SUBSET}
    store = build_store()
    # Dedicated GLiNER client for bounded per-chunk extraction; Noop the store's
    # ingest-time processor so ingest does NOT run GLiNER on whole-document text
    # (which 400s the sidecar on large docs -- see README finding).
    GLINER = HTTPGLiNEREntityProcessor.from_env()
    store.entity_processor = NoopEntityProcessor()
    ingest_stats, chunks = ingest_subset(store)
    log["ingest"] = ingest_stats
    log["link"] = link_entities(store, chunks)
    # Italian entity-yield diagnostic: avg entities/chunk + a sample of extracted
    # names (eyeball whether the current model handles Italian).
    total_chunks = max(1, log["ingest"]["total_chunks"])
    log["link"]["avg_entities_per_chunk"] = round(log["link"]["mentions_edges"] / total_chunks, 2)
    sample = store.client.query(
        "SELECT canonical_name FROM Entity WHERE user_identifier = :u LIMIT 40", params={"u": USER}
    )
    log["link"]["entity_sample"] = sorted({str(r.get("canonical_name")) for r in sample})
    print("ingest+link done:", json.dumps(log["ingest"]), json.dumps(log["link"], ensure_ascii=False),
          flush=True)

    frozen = load_frozen_questions(FROZEN)
    per_cfg = {"production": [], "fused_base": [], "fused_graph": []}
    n = 0
    for fname in SUBSET:
        for q in frozen.get(fname, []):
            global _INFO
            _INFO = {}
            rows = run_question(store, q, fname)
            for cfg in per_cfg:
                per_cfg[cfg].append(rows[cfg])
            n += 1
            print(f"q{n} [{fname[:24]}] "
                  f"prod={rows['production']['evidence_rank']} "
                  f"base={rows['fused_base']['evidence_rank']} "
                  f"graph={rows['fused_graph']['evidence_rank']}", flush=True)

    log["question_count"] = n
    log["metrics"] = {cfg: summarize_results(rows, cutoffs=(1, 5, 20)) for cfg, rows in per_cfg.items()}
    base_mrr = log["metrics"]["fused_base"]["mrr_at_20"]
    graph_mrr = log["metrics"]["fused_graph"]["mrr_at_20"]
    log["graph_lift"] = {
        "fused_base_mrr20": base_mrr,
        "fused_graph_mrr20": graph_mrr,
        "delta_mrr20": graph_mrr - base_mrr,
        "questions_improved": sum(
            1 for b, g in zip(per_cfg["fused_base"], per_cfg["fused_graph"], strict=True)
            if 0 < g.get("evidence_rank", 0) < (b.get("evidence_rank") or 999)
        ),
        "questions_regressed": sum(
            1 for b, g in zip(per_cfg["fused_base"], per_cfg["fused_graph"], strict=True)
            if 0 < (b.get("evidence_rank") or 0) < (g.get("evidence_rank") or 999)
        ),
    }
    (HERE / "results.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print("DONE", json.dumps(log["graph_lift"], indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
