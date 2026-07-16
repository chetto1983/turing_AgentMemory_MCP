"""Spike 001 — doc-entity-graph-substrate.

Question (Given/When/Then): GIVEN the ArcadeDB store where entities link only to
Memory vertices, WHEN we extract entities over document chunks with the existing
GLiNER EntityProcessor and write (:Chunk)-[:MENTIONS]->(:Entity) edges, THEN a
bound, tenant-scoped ArcadeDB SQL traversal reaches co-mentioning chunks across
different documents.

Runs inside a one-off container on the compose network (see README "How to Run")
so it reaches agentmemory-gliner / agentmemory-embed / arcadedb by service name.
Throwaway: everything lands in an isolated `spike_docgraphrag` database that is
dropped+recreated each run. Touches no production tenant data and no src/.

Emits a forensic JSON log to results.json in this directory.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from collections import defaultdict
from pathlib import Path

from turing_agentmemory_mcp.arcadedb_client import ArcadeDBClient
from turing_agentmemory_mcp.entity_extraction import DEFAULT_METADATA_KEY
from turing_agentmemory_mcp.ids import stable_id
from turing_agentmemory_mcp.store import TuringAgentMemory
from turing_agentmemory_mcp.temporal_graph import canonicalize_entity_name

USER = "spike-docgraph"
DB = "spike_docgraphrag"
HERE = Path(__file__).resolve().parent

# Controlled 3-doc set with deliberately shared entities so cross-doc traversal
# is verifiable. Real GLiNER runs over this text; 003 uses the real 12-doc corpus.
DOCS = [
    (
        "arcadedb-overview",
        "ArcadeDB overview",
        "ArcadeDB is a multi-model database created by Luca Garulli. ArcadeDB "
        "provides native HNSW vector search and Lucene full-text indexing. The "
        "Turing AgentMemory server stores document chunks inside ArcadeDB.",
    ),
    (
        "gliner-extraction",
        "GLiNER extraction",
        "GLiNER is an entity extraction model. The Turing AgentMemory server "
        "calls GLiNER over each memory to tag entities. ArcadeDB stores the "
        "entities that GLiNER extracts as Entity vertices.",
    ),
    (
        "fusion-retrieval",
        "Fusion retrieval",
        "Reciprocal Rank Fusion blends dense and sparse retrieval channels. The "
        "Turing AgentMemory server built by Davide fuses GLiNER entity signals "
        "with ArcadeDB vector search for better recall.",
    ),
]


def build_store() -> TuringAgentMemory:
    base = ArcadeDBClient.from_env()
    client = dataclasses.replace(base, database=DB)
    try:
        client._server_command(f"drop database {DB}")
    except RuntimeError:
        pass
    client.create_database()
    # Write the store's file-state (audit/spans/sparse) under this mounted dir --
    # the container rootfs may be read-only, but the bind mount is writable.
    home = Path(tempfile.mkdtemp(prefix="home-", dir=str(HERE)))
    store = TuringAgentMemory(client, turing_home=home, graph=DB)
    store.bootstrap()
    return store


def extract_entities(store: TuringAgentMemory, texts: list[str]) -> list[list[dict]]:
    proc = store.entity_processor
    if hasattr(proc, "process_many"):
        processed = proc.process_many(texts)
    else:
        processed = [proc.process(t) for t in texts]
    out: list[list[dict]] = []
    for pt in processed:
        payload = pt.metadata.get(DEFAULT_METADATA_KEY, {})
        ents = payload.get("entities", []) if isinstance(payload, dict) else []
        out.append([e for e in ents if isinstance(e, dict) and e.get("text")])
    return out


def bridge_count(docs_by_entity: dict[str, set[str]]) -> int:
    """How many entities are mentioned by chunks from >=2 distinct documents."""
    return sum(1 for docs in docs_by_entity.values() if len(docs) >= 2)


def main() -> int:
    log: dict = {"spike": "001-doc-entity-graph-substrate", "steps": []}
    store = build_store()
    log["steps"].append({"build_store": "ok", "database": DB})

    # 1. Ingest the docs the normal way (Document + Chunks + embeddings + HAS_CHUNK).
    for doc_id, title, text in DOCS:
        store.ingest_document_text(user_identifier=USER, title=title, text=text, document_id=doc_id)
    chunks = store.client.query(
        "SELECT id, document_id, ordinal, text FROM Chunk WHERE user_identifier = :u "
        "ORDER BY document_id, ordinal",
        params={"u": USER},
    )
    log["steps"].append({"ingest": "ok", "chunk_count": len(chunks)})

    # 2. Extract entities per chunk with the real GLiNER sidecar.
    per_chunk_entities = extract_entities(store, [str(c["text"]) for c in chunks])

    # 2b. Canonicalization comparison: (type, name) keying (what temporal_graph.py:137
    #     does for memories) vs name-only keying. Cross-doc bridges under each.
    typed_docs: dict[str, set[str]] = defaultdict(set)
    name_docs: dict[str, set[str]] = defaultdict(set)
    extracted_report: list[dict] = []
    for chunk, ents in zip(chunks, per_chunk_entities, strict=True):
        did = str(chunk["document_id"])
        names_here: list[str] = []
        for e in ents:
            name = canonicalize_entity_name(str(e.get("text", "")))
            etype = str(e.get("label", "")).strip().lower()
            if not name:
                continue
            typed_docs[f"{etype}|{name}"].add(did)
            name_docs[name].add(did)
            names_here.append(f"{name} ({etype})")
        extracted_report.append(
            {"document_id": did, "chunk_id": str(chunk["id"]), "entities": names_here}
        )
    log["extracted"] = extracted_report
    log["canonicalization_comparison"] = {
        "typed_key_entities": len(typed_docs),
        "typed_key_cross_doc_bridges": bridge_count(typed_docs),
        "name_key_entities": len(name_docs),
        "name_key_cross_doc_bridges": bridge_count(name_docs),
        "note": (
            "temporal_graph.py keys entity id on (entity_type, canonical_name); "
            "GLiNER type-drift on a shared surface splits it, shrinking the bridge count. "
            "Name-only resolution recovers the cross-doc bridges."
        ),
    }

    # 3. Build Entity upserts + (:Chunk)-[:MENTIONS]->(:Entity) edges (name-only
    #    resolution), one managed transaction via the store's own _write_many.
    writes: list[tuple[str, dict]] = []
    entity_seen: set[str] = set()
    edge_count = 0
    for chunk, ents in zip(chunks, per_chunk_entities, strict=True):
        cid = str(chunk["id"])
        ids_here: set[str] = set()
        for e in ents:
            name = canonicalize_entity_name(str(e.get("text", "")))
            if not name:
                continue
            eid = stable_id("ent", USER, name)
            ids_here.add(eid)
            if eid not in entity_seen:
                entity_seen.add(eid)
                writes.append(
                    (
                        "UPDATE Entity SET id = :id, user_identifier = :u, "
                        "entity_type = :t, canonical_name = :c, display_name = :d, "
                        "content = :c UPSERT WHERE id = :id",
                        {
                            "id": eid,
                            "u": USER,
                            "t": str(e.get("label", "")).strip().lower(),
                            "c": name,
                            "d": str(e.get("text")),
                        },
                    )
                )
        for eid in ids_here:
            writes.append(
                (
                    "CREATE EDGE MENTIONS FROM (SELECT FROM Chunk WHERE id = :cid AND "
                    "user_identifier = :u) TO (SELECT FROM Entity WHERE id = :eid AND "
                    "user_identifier = :u)",
                    {"cid": cid, "eid": eid, "u": USER},
                )
            )
            edge_count += 1
    store._write_many(writes)
    log["steps"].append(
        {"write_graph": "ok", "entity_vertices": len(entity_seen), "mentions_edges": edge_count}
    )

    # 4a. Entities of the seed chunk via out('MENTIONS').
    seed = chunks[0]
    first_cid, first_doc = str(seed["id"]), str(seed["document_id"])
    ents_of_first = store.client.query(
        "SELECT canonical_name, entity_type FROM (SELECT expand(out('MENTIONS')) FROM Chunk "
        "WHERE id = :cid AND user_identifier = :u)",
        params={"cid": first_cid, "u": USER},
    )

    # 4b. Cross-doc co-mention traversal: chunk -> entity -> other chunks.
    cross_doc = store.client.query(
        "SELECT id, document_id FROM (SELECT expand(out('MENTIONS').in('MENTIONS')) FROM Chunk "
        "WHERE id = :cid AND user_identifier = :u) WHERE user_identifier = :u AND id <> :cid",
        params={"cid": first_cid, "u": USER},
    )
    other_docs = sorted({str(r["document_id"]) for r in cross_doc} - {first_doc})
    log["traversal"] = {
        "seed_chunk": first_cid,
        "seed_document": first_doc,
        "entities_of_seed": [dict(r) for r in ents_of_first],
        "co_mention_chunk_count": len(cross_doc),
        "reached_other_documents": other_docs,
    }

    # 5. Which MATCH syntax works live on 26.7.1? (ArcadeDB GraphRAG doc uses arrow
    #    syntax; Phase-4 D-05 only confirmed object-notation. Resolve it.)
    match_syntax: dict[str, object] = {}
    try:
        rows = store.client.query(
            "MATCH (c:Chunk)-[:MENTIONS]->(e:Entity)<-[:MENTIONS]-(other:Chunk) "
            "WHERE c.id = :cid AND other.id <> :cid RETURN other.id AS oid, e.canonical_name AS en",
            params={"cid": first_cid},
        )
        match_syntax["cypher_arrow"] = {"ok": True, "rows": len(rows)}
    except Exception as exc:  # noqa: BLE001 - spike: record, don't crash
        match_syntax["cypher_arrow"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:160]}
    try:
        rows = store.client.query(
            "MATCH {type: Chunk, as: c, where: (id = :cid)}.out('MENTIONS'){as: e}"
            ".in('MENTIONS'){as: other, where: (id <> :cid)} RETURN other.id AS oid, "
            "e.canonical_name AS en",
            params={"cid": first_cid},
        )
        match_syntax["object_notation"] = {"ok": True, "rows": len(rows)}
    except Exception as exc:  # noqa: BLE001 - spike: record, don't crash
        match_syntax["object_notation"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:160]}
    log["match_syntax"] = match_syntax

    substrate_ok = len(entity_seen) > 0 and edge_count > 0 and len(other_docs) > 0
    log["verdict"] = {
        "substrate_ok": substrate_ok,
        "reason": (
            "Chunk->Entity MENTIONS edges written; cross-document co-mention traversal "
            "reached other documents (with name-only entity resolution)"
            if substrate_ok
            else "substrate did not produce a cross-document traversal path"
        ),
    }
    (HERE / "results.json").write_text(json.dumps(log, indent=2), encoding="utf-8")
    print(json.dumps(log, indent=2))
    return 0 if substrate_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
