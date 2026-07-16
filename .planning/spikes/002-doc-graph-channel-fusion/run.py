"""Spike 002 — doc-graph-channel-fusion.

Question (Given/When/Then): GIVEN the 001 Chunk->Entity MENTIONS substrate, WHEN
an entity-anchored graph-expansion channel is added beside the existing dense
(vectorNeighbors) + lexical (Lucene) channels and fused through the real
`retrieval_fusion.fuse_rankings` RRF, THEN document search returns graph-expanded
chunks and can surface an answer chunk that dense+lexical miss.

Sharper hypothesis (from 001): a SINGLE-hop co-mention channel ~= the lexical
channel (a shared single-token entity is also a shared lexical token). The graph
channel's distinct value is MULTI-HOP bridging. This spike tests both, on the
same 001 substrate, plus probes whether native `vector.fuse` runs on 26.7.1.

Run: see README. Isolated `spike_docgraphrag2` DB, dropped+recreated each run.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from pathlib import Path

from turing_agentmemory_mcp.arcadedb_client import ArcadeDBClient
from turing_agentmemory_mcp.entity_extraction import DEFAULT_METADATA_KEY
from turing_agentmemory_mcp.ids import stable_id
from turing_agentmemory_mcp.models import RetrievalCandidate
from turing_agentmemory_mcp.retrieval_fusion import fuse_rankings
from turing_agentmemory_mcp.store import TuringAgentMemory
from turing_agentmemory_mcp.store_documents_queries import (
    chunk_lucene_search_statement,
    chunk_vector_search_statement,
)
from turing_agentmemory_mcp.temporal_graph import canonicalize_entity_name

USER = "spike-docgraph2"
DB = "spike_docgraphrag2"
HERE = Path(__file__).resolve().parent

# Multi-hop bridge scenario. Query is about GraphRAG; the ANSWER (jvector-detail)
# names JVector/DiskANN and shares NO query vocabulary with the question. It is
# reachable only by hopping query-entity(graphrag) -> arcadedb -> jvector across
# co-mentions. Dense + lexical should both miss it; the graph channel should not.
DOCS = [
    ("graphrag-intro", "GraphRAG intro",
     "GraphRAG combines retrieval with knowledge graphs. GraphRAG systems store "
     "their documents inside ArcadeDB."),
    ("arcadedb-engine", "ArcadeDB engine",
     "ArcadeDB performs approximate nearest neighbor search with the JVector library."),
    ("jvector-detail", "JVector detail",
     "JVector implements the DiskANN construction with product quantization for "
     "billion scale similarity indexes."),
    ("rrf-note", "RRF note",
     "Reciprocal Rank Fusion merges several ranked lists using only rank positions."),
    ("lucene-note", "Lucene note",
     "Apache Lucene offers an inverted index and BM25 relevance scoring for text."),
]
QUERY = "Which nearest neighbor library does GraphRAG rely on?"
ANSWER_DOC = "jvector-detail"


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


def entities_of(store: TuringAgentMemory, texts: list[str]) -> list[list[str]]:
    proc = store.entity_processor
    processed = proc.process_many(texts) if hasattr(proc, "process_many") else [
        proc.process(t) for t in texts
    ]
    out = []
    for pt in processed:
        payload = pt.metadata.get(DEFAULT_METADATA_KEY, {})
        ents = payload.get("entities", []) if isinstance(payload, dict) else []
        names = {canonicalize_entity_name(str(e.get("text", ""))) for e in ents if e.get("text")}
        out.append(sorted(n for n in names if n))
    return out


def eid(name: str) -> str:
    return stable_id("ent", USER, name)


def ingest_and_link(store: TuringAgentMemory) -> None:
    for doc_id, title, text in DOCS:
        store.ingest_document_text(user_identifier=USER, title=title, text=text, document_id=doc_id)
    chunks = store.client.query(
        "SELECT id, document_id, text FROM Chunk WHERE user_identifier = :u", params={"u": USER}
    )
    per_chunk = entities_of(store, [str(c["text"]) for c in chunks])
    writes: list[tuple[str, dict]] = []
    seen: set[str] = set()
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
    store._write_many(writes)


def dense_channel(store: TuringAgentMemory) -> list[RetrievalCandidate]:
    stmt, params = chunk_vector_search_statement(
        embedding=store.embedder.embed(QUERY), k=10, user_identifier=USER
    )
    rows = store.client.query(stmt, params=params)
    ranked = sorted(rows, key=lambda r: float(r.get("distance") or 1.0))
    return [
        RetrievalCandidate(candidate_id=str(r["id"]), kind="chunk",
                           content=str(r.get("document_id") or "x"),
                           source_memory_id=str(r.get("document_id") or ""),
                           raw_score=1.0 - float(r.get("distance") or 0.0))
        for r in ranked
    ]


def lexical_channel(store: TuringAgentMemory) -> list[RetrievalCandidate]:
    stmt, params = chunk_lucene_search_statement(query=QUERY, limit=10, user_identifier=USER)
    rows = store.client.query(stmt, params=params)
    return [
        RetrievalCandidate(candidate_id=str(r["id"]), kind="chunk",
                           content=str(r.get("document_id") or "x"),
                           source_memory_id=str(r.get("document_id") or ""))
        for r in rows
    ]


def _chunks_of(store: TuringAgentMemory, entity_ids: list[str]) -> list[dict]:
    out = []
    for e in entity_ids:  # per-entity to avoid depending on IN-list param support
        out += store.client.query(
            "SELECT id, document_id, text FROM (SELECT expand(in('MENTIONS')) FROM Entity "
            "WHERE id = :eid AND user_identifier = :u) WHERE user_identifier = :u",
            params={"eid": e, "u": USER},
        )
    return out


def _entities_of(store: TuringAgentMemory, chunk_ids: list[str]) -> set[str]:
    got: set[str] = set()
    for c in chunk_ids:
        for r in store.client.query(
            "SELECT id FROM (SELECT expand(out('MENTIONS')) FROM Chunk WHERE id = :cid AND "
            "user_identifier = :u) WHERE user_identifier = :u",
            params={"cid": c, "u": USER},
        ):
            got.add(str(r["id"]))
    return got


def graph_channel(store: TuringAgentMemory, max_hops: int) -> tuple[list[RetrievalCandidate], dict]:
    """BFS over the MENTIONS bipartite graph from the query's entities. Chunks are
    ranked by hop distance (nearer first). Returns candidates + per-hop trace."""
    q_ents = entities_of(store, [QUERY])[0]
    frontier = [eid(n) for n in q_ents]
    visited_ent = set(frontier)
    chunk_hop: dict[str, tuple[int, str]] = {}  # chunk_id -> (hop, document_id)
    trace: dict = {"query_entities": q_ents, "hops": []}
    for hop in range(1, max_hops + 1):
        chunks = _chunks_of(store, frontier)
        new_ids = []
        for c in chunks:
            cid = str(c["id"])
            if cid not in chunk_hop:
                chunk_hop[cid] = (hop, str(c.get("document_id") or ""))
                new_ids.append(cid)
        next_ents = sorted(_entities_of(store, new_ids) - visited_ent)
        visited_ent |= set(next_ents)
        trace["hops"].append({
            "hop": hop, "new_chunk_docs": sorted({chunk_hop[c][1] for c in new_ids})
        })
        frontier = next_ents
        if not frontier:
            break
    ranked = sorted(chunk_hop.items(), key=lambda kv: kv[1][0])
    cands = [
        RetrievalCandidate(candidate_id=cid, kind="chunk", content=doc or "x",
                           source_memory_id=doc, raw_score=1.0 / hop)
        for cid, (hop, doc) in ranked
    ]
    return cands, trace


def rank_of_answer(fused, store: TuringAgentMemory) -> int:
    for i, f in enumerate(fused, 1):
        if f.candidate.source_memory_id == ANSWER_DOC:
            return i
    return -1


def probe_vector_fuse(store: TuringAgentMemory) -> dict:
    vec = store.embedder.embed(QUERY)
    stmt = (
        "SELECT expand(`vector.fuse`(`vector.neighbors`('Chunk[embedding]', :v, 10), "
        "`vector.neighbors`('Chunk[embedding]', :v, 10), { fusion: 'RRF' }))"
    )
    try:
        rows = store.client.query(stmt, params={"v": vec})
        return {"available": True, "rows": len(rows)}
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"[:200]}


def main() -> int:
    log: dict = {"spike": "002-doc-graph-channel-fusion", "query": QUERY, "answer_doc": ANSWER_DOC}
    store = build_store()
    ingest_and_link(store)

    dense = dense_channel(store)
    lexical = lexical_channel(store)
    graph1, trace1 = graph_channel(store, max_hops=1)
    graphN, traceN = graph_channel(store, max_hops=3)

    log["channels"] = {
        "dense_docs": [c.source_memory_id for c in dense],
        "lexical_docs": [c.source_memory_id for c in lexical],
        "graph_1hop_docs": [c.source_memory_id for c in graph1],
        "graph_3hop_docs": [c.source_memory_id for c in graphN],
        "graph_1hop_trace": trace1,
        "graph_3hop_trace": traceN,
    }

    w_base = {"dense": 1.0, "lexical": 1.0}
    w_graph = {"dense": 1.0, "lexical": 1.0, "graph": 1.0}
    fused_base = fuse_rankings({"dense": dense, "lexical": lexical}, weights=w_base)
    fused_graph = fuse_rankings(
        {"dense": dense, "lexical": lexical, "graph": graphN}, weights=w_graph
    )

    log["answer_rank"] = {
        "dense_only": next((i for i, c in enumerate(dense, 1) if c.source_memory_id == ANSWER_DOC), -1),
        "lexical_only": next((i for i, c in enumerate(lexical, 1) if c.source_memory_id == ANSWER_DOC), -1),
        "graph_3hop_only": next((i for i, c in enumerate(graphN, 1) if c.source_memory_id == ANSWER_DOC), -1),
        "fused_dense_lexical": rank_of_answer(fused_base, store),
        "fused_with_graph": rank_of_answer(fused_graph, store),
    }
    log["fused_with_graph_top"] = [
        {"doc": f.candidate.source_memory_id, "channels": sorted(f.channels)} for f in fused_graph[:5]
    ]
    log["native_vector_fuse"] = probe_vector_fuse(store)

    ar = log["answer_rank"]
    fusion_mechanics_ok = ar["fused_with_graph"] > 0
    graph_adds_value = (
        ar["fused_with_graph"] > 0
        and (ar["fused_dense_lexical"] < 0 or ar["fused_with_graph"] < ar["fused_dense_lexical"])
        and ar["graph_3hop_only"] > 0
    )
    log["verdict"] = {
        "fusion_mechanics_ok": fusion_mechanics_ok,
        "multihop_graph_adds_value": graph_adds_value,
        "single_hop_overlaps_lexical": sorted(
            set(c.source_memory_id for c in graph1) & set(c.source_memory_id for c in lexical)
        ),
    }
    (HERE / "results.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(json.dumps(log, indent=2))
    return 0 if fusion_mechanics_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
