from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from turingdb import TuringDB

from turing_agentmemory_mcp.embeddings import AuraLlamaEmbedder, Embedder
from turing_agentmemory_mcp.ids import cypher_var, quote, stable_id, vector_id
from turing_agentmemory_mcp.models import DocumentHit, IngestedDocument, MemoryItem
from turing_agentmemory_mcp.rerank import AuraReranker, apply_rerank_guard


class TuringAgentMemory:
    def __init__(
        self,
        client: TuringDB,
        *,
        turing_home: str | Path,
        graph: str = "agent_memory",
        dimensions: int = 768,
        memory_index: str = "agent_memory_vectors",
        document_index: str = "document_chunk_vectors",
        embedder: Embedder | None = None,
        reranker: AuraReranker | None = None,
        rerank_threshold: float | None = None,
        rerank_blend: bool | None = None,
    ) -> None:
        self.client = client
        self.turing_home = Path(turing_home)
        self.graph = graph
        self.dimensions = getattr(embedder, "dimensions", dimensions)
        self.memory_index = memory_index
        self.document_index = document_index
        self.embedder = embedder or AuraLlamaEmbedder.from_env(dimensions=self.dimensions)
        self.reranker = reranker or AuraReranker.from_env()
        self.rerank_threshold = (
            float(os.environ.get("AURA_RERANK_THRESHOLD", "0"))
            if rerank_threshold is None
            else rerank_threshold
        )
        self.rerank_blend = (
            os.environ.get("AURA_RERANK_BLEND", "").lower() in {"1", "true", "yes", "on"}
            if rerank_blend is None
            else rerank_blend
        )
        self.data_dir = self.turing_home / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def bootstrap(self) -> None:
        self.turing_home.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_graph_loaded()
        self._ensure_vector_index(self.memory_index)
        self._ensure_vector_index(self.document_index)

    def store_message(
        self,
        *,
        user_identifier: str,
        session_id: str,
        role: str,
        content: str,
        memory_id: str | None = None,
    ) -> MemoryItem:
        self._require_user(user_identifier)
        memory_id = memory_id or stable_id("mem", user_identifier, session_id, role, content)
        return self._write_memory(
            user_identifier=user_identifier,
            memory_id=memory_id,
            kind="message",
            content=content,
            session_id=session_id,
            role=role,
        )

    def add_entity(
        self,
        *,
        user_identifier: str,
        name: str,
        entity_type: str,
        description: str = "",
    ) -> MemoryItem:
        content = f"{name} ({entity_type}) {description}".strip()
        memory_id = stable_id("entity", user_identifier, name, entity_type)
        return self._write_memory(
            user_identifier=user_identifier,
            memory_id=memory_id,
            kind="entity",
            content=content,
            role="system",
        )

    def add_preference(
        self,
        *,
        user_identifier: str,
        category: str,
        preference: str,
        context: str = "",
    ) -> MemoryItem:
        content = f"{category}: {preference}. {context}".strip()
        memory_id = stable_id("pref", user_identifier, category, preference)
        return self._write_memory(
            user_identifier=user_identifier,
            memory_id=memory_id,
            kind="preference",
            content=content,
            role="system",
        )

    def add_fact(
        self,
        *,
        user_identifier: str,
        subject: str,
        predicate: str,
        object_value: str,
        context: str = "",
    ) -> MemoryItem:
        content = f"{subject} {predicate} {object_value}. {context}".strip()
        memory_id = stable_id("fact", user_identifier, subject, predicate, object_value)
        return self._write_memory(
            user_identifier=user_identifier,
            memory_id=memory_id,
            kind="fact",
            content=content,
            role="system",
        )

    def search_memory(
        self,
        *,
        user_identifier: str,
        query: str,
        limit: int = 5,
        memory_types: list[str] | None = None,
    ) -> list[MemoryItem]:
        self._require_user(user_identifier)
        limit = self._clean_limit(limit)
        literal = self._vector_literal(self.embedder.embed(query))
        rows = self._records(
            self.client.query(
                f"VECTOR SEARCH IN {self.memory_index} FOR {max(limit * 4, limit)} {literal} "
                f"YIELD ids, score MATCH (m:Memory) "
                f'WHERE m.vector_id = ids AND m.user_identifier = "{quote(user_identifier)}" '
                "RETURN m.id, m.user_identifier, m.kind, m.content, m.session_id, m.role, score"
            )
        )
        allowed = set(memory_types or [])
        seeds = [
            MemoryItem(
                id=str(row.get("m.id", "")),
                user_identifier=str(row.get("m.user_identifier", "")),
                kind=str(row.get("m.kind", "")),
                content=str(row.get("m.content", "")),
                session_id=str(row.get("m.session_id", "")),
                role=str(row.get("m.role", "")),
                score=float(row.get("score") or 0.0),
            )
            for row in rows
            if not allowed or str(row.get("m.kind", "")) in allowed
        ]
        seeds = sorted(seeds, key=lambda item: item.score, reverse=True)[: max(limit * 3, limit)]
        return self._rerank_memory(query, seeds)[:limit]

    def get_context(
        self,
        *,
        user_identifier: str,
        query: str,
        session_id: str = "",
        limit: int = 5,
    ) -> dict[str, object]:
        items = self.search_memory(user_identifier=user_identifier, query=query, limit=limit)
        if session_id:
            session_items = [item for item in items if item.session_id == session_id]
            other_items = [item for item in items if item.session_id != session_id]
            items = (session_items + other_items)[:limit]
        return {
            "query": query,
            "user_identifier": user_identifier,
            "items": [item.to_dict() for item in items],
            "context": "\n".join(f"- [{item.kind}] {item.content}" for item in items),
        }

    def ingest_document_text(
        self,
        *,
        user_identifier: str,
        title: str,
        text: str,
        document_id: str | None = None,
        chunk_chars: int = 360,
    ) -> IngestedDocument:
        self._require_user(user_identifier)
        if not title.strip():
            raise ValueError("title is required")
        if not text.strip():
            raise ValueError("text is required")
        document_id = document_id or stable_id("doc", user_identifier, title, text[:128])
        chunks = self._chunk_text(text, chunk_chars=chunk_chars)
        self._ensure_user(user_identifier)
        doc_var = cypher_var(document_id)
        nodes = [
            f'({doc_var}:Document {{id: "{quote(document_id)}", user_identifier: "{quote(user_identifier)}", '
            f'title: "{quote(title)}", chunk_count: {len(chunks)}, status: "searchable"}})'
        ]
        edges = [f"(u)-[:HAS_DOCUMENT]->({doc_var})"]
        vector_rows: list[tuple[int, list[float]]] = []
        previous_var = ""
        for idx, chunk_text in enumerate(chunks, start=1):
            chunk_id = f"{document_id}#{idx}"
            chunk_var = cypher_var(chunk_id)
            vid = vector_id("chunk", chunk_id)
            locator = f"chunk={idx}"
            nodes.append(
                f'({chunk_var}:Chunk {{chunk_id: "{quote(chunk_id)}", vector_id: {vid}, '
                f'document_id: "{quote(document_id)}", user_identifier: "{quote(user_identifier)}", '
                f'title: "{quote(title)}", ordinal: {idx}, locator: "{locator}", '
                f'status: "active", text: "{quote(chunk_text)}"}})'
            )
            edges.append(f"({doc_var})-[:HAS_CHUNK {{ordinal: {idx}}}]->({chunk_var})")
            if previous_var:
                edges.append(f"({previous_var})-[:NEXT_CHUNK]->({chunk_var})")
            previous_var = chunk_var
            vector_rows.append((vid, self.embedder.embed(chunk_text)))
        self._write(
            f'MATCH (u:User) WHERE u.identifier = "{quote(user_identifier)}" CREATE '
            + ", ".join(nodes + edges)
        )
        self._load_vectors(self.document_index, vector_rows, f"document_{document_id}")
        return IngestedDocument(
            document_id=document_id,
            title=title,
            chunk_count=len(chunks),
            user_identifier=user_identifier,
        )

    def search_documents(
        self,
        *,
        user_identifier: str,
        query: str,
        limit: int = 5,
        document_id: str = "",
    ) -> list[DocumentHit]:
        self._require_user(user_identifier)
        limit = self._clean_limit(limit)
        literal = self._vector_literal(self.embedder.embed(query))
        document_filter = ""
        if document_id:
            document_filter = f' AND c.document_id = "{quote(document_id)}"'
        rows = self._records(
            self.client.query(
                f"VECTOR SEARCH IN {self.document_index} FOR {max(limit * 4, limit)} {literal} "
                f"YIELD ids, score MATCH (c:Chunk) "
                f'WHERE c.vector_id = ids AND c.user_identifier = "{quote(user_identifier)}"{document_filter} '
                "RETURN c.chunk_id, c.document_id, c.title, c.locator, c.text, c.vector_id, score"
            )
        )
        seeds: list[DocumentHit] = []
        for row in sorted(rows, key=lambda value: float(value.get("score") or 0.0), reverse=True)[
            : max(limit * 3, limit)
        ]:
            context = self._chunk_context(int(row.get("c.vector_id") or 0))
            seeds.append(
                DocumentHit(
                    chunk_id=str(row.get("c.chunk_id", "")),
                    document_id=str(row.get("c.document_id", "")),
                    title=str(row.get("c.title", "")),
                    locator=str(row.get("c.locator", "")),
                    text=str(row.get("c.text", "")),
                    score=float(row.get("score") or 0.0),
                    context=context,
                )
            )
        return self._rerank_documents(query, seeds)[:limit]

    def load_graph_after_restart(self) -> None:
        self.client.load_graph(self.graph, raise_if_loaded=False)
        self.client.set_graph(self.graph)

    def _write_memory(
        self,
        *,
        user_identifier: str,
        memory_id: str,
        kind: str,
        content: str,
        session_id: str = "",
        role: str = "",
    ) -> MemoryItem:
        self._ensure_user(user_identifier)
        vid = vector_id("memory", memory_id)
        mem_var = cypher_var(memory_id)
        created_at = int(time.time())
        self._write(
            f'MATCH (u:User) WHERE u.identifier = "{quote(user_identifier)}" '
            f'CREATE ({mem_var}:Memory {{id: "{quote(memory_id)}", vector_id: {vid}, '
            f'user_identifier: "{quote(user_identifier)}", kind: "{quote(kind)}", '
            f'content: "{quote(content)}", session_id: "{quote(session_id)}", '
            f'role: "{quote(role)}", created_at: {created_at}}}), '
            f"(u)-[:HAS_MEMORY]->({mem_var})"
        )
        self._load_vectors(self.memory_index, [(vid, self.embedder.embed(content))], f"memory_{memory_id}")
        return MemoryItem(
            id=memory_id,
            user_identifier=user_identifier,
            kind=kind,
            content=content,
            session_id=session_id,
            role=role,
            score=1.0,
        )

    def _ensure_graph_loaded(self) -> None:
        try:
            self.client.create_graph(self.graph)
        except Exception:
            try:
                self.client.load_graph(self.graph, raise_if_loaded=False)
            except Exception:
                pass
        self.client.set_graph(self.graph)

    def _ensure_vector_index(self, name: str) -> None:
        try:
            self.client.query(
                f"CREATE VECTOR INDEX {name} WITH DIMENSION {self.dimensions} METRIC COSINE"
            )
        except Exception:
            pass

    def _ensure_user(self, user_identifier: str) -> None:
        try:
            rows = self._records(
                self.client.query(
                    f'MATCH (u:User) WHERE u.identifier = "{quote(user_identifier)}" '
                    "RETURN u.identifier"
                )
            )
        except Exception as exc:
            if "Unknown label: User" not in str(exc):
                raise
            rows = []
        if rows:
            return
        user_var = cypher_var(f"user_{user_identifier}")
        self._write(
            f'CREATE ({user_var}:User {{identifier: "{quote(user_identifier)}", '
            f'display: "{quote(user_identifier)}"}})'
        )

    def _write(self, query: str) -> None:
        self.client.new_change()
        try:
            self.client.query(query)
            self.client.query("CHANGE SUBMIT")
        finally:
            self.client.checkout()

    def _load_vectors(self, index_name: str, rows: list[tuple[int, list[float]]], stem: str) -> None:
        if not rows:
            return
        filename = f"{cypher_var(stem)}_{int(time.time() * 1000)}.csv"
        path = self.data_dir / filename
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for vid, vec in rows:
                handle.write(str(vid))
                handle.write(",")
                handle.write(",".join(f"{value:.8f}" for value in vec))
                handle.write("\n")
        self.client.query(f'LOAD VECTOR FROM "{filename}" IN {index_name}')

    def _chunk_context(self, vector: int) -> list[dict[str, object]]:
        if vector <= 0:
            return []
        rows = self._records(
            self.client.query(
                "MATCH (c:Chunk)-[:NEXT_CHUNK]->(n:Chunk) "
                f"WHERE c.vector_id = {vector} "
                "RETURN n.chunk_id, n.locator, n.text"
            )
        )
        return [
            {
                "chunk_id": row.get("n.chunk_id", ""),
                "locator": row.get("n.locator", ""),
                "text": row.get("n.text", ""),
            }
            for row in rows
        ]

    def _rerank_memory(self, query: str, seeds: list[MemoryItem]) -> list[MemoryItem]:
        if len(seeds) < 2 or self.reranker is None:
            return seeds
        scored = self.reranker.rerank(query, [item.content for item in seeds])
        ordered = apply_rerank_guard(
            seeds,
            scored,
            threshold=self.rerank_threshold,
            blend=self.rerank_blend,
        )
        return [
            MemoryItem(
                id=item.id,
                user_identifier=item.user_identifier,
                kind=item.kind,
                content=item.content,
                session_id=item.session_id,
                role=item.role,
                score=float(score if score is not None else item.score),
            )
            for item, score in ordered
        ]

    def _rerank_documents(self, query: str, seeds: list[DocumentHit]) -> list[DocumentHit]:
        if len(seeds) < 2 or self.reranker is None:
            return seeds
        scored = self.reranker.rerank(query, [item.text for item in seeds])
        ordered = apply_rerank_guard(
            seeds,
            scored,
            threshold=self.rerank_threshold,
            blend=self.rerank_blend,
        )
        return [
            DocumentHit(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                title=item.title,
                locator=item.locator,
                text=item.text,
                score=float(score if score is not None else item.score),
                context=item.context,
            )
            for item, score in ordered
        ]

    @staticmethod
    def _chunk_text(text: str, *, chunk_chars: int) -> list[str]:
        paragraphs = [part.strip() for part in text.split("\n") if part.strip()]
        chunks: list[str] = []
        for paragraph in paragraphs or [text.strip()]:
            while len(paragraph) > chunk_chars:
                split_at = paragraph.rfind(" ", 0, chunk_chars)
                if split_at < 80:
                    split_at = chunk_chars
                chunks.append(paragraph[:split_at].strip())
                paragraph = paragraph[split_at:].strip()
            if paragraph:
                chunks.append(paragraph)
        return chunks

    @staticmethod
    def _records(df: Any) -> list[dict[str, Any]]:
        def clean(value: Any) -> Any:
            if hasattr(value, "item"):
                try:
                    return value.item()
                except Exception:
                    pass
            if value is None:
                return None
            if isinstance(value, float) and value != value:
                return None
            if isinstance(value, (str, int, float, bool)):
                return value
            return str(value)

        return [{str(key): clean(value) for key, value in row.items()} for row in df.to_dict("records")]

    @staticmethod
    def _vector_literal(vec: list[float]) -> str:
        return "(" + ", ".join(f"{value:.8f}" for value in vec) + ")"

    @staticmethod
    def _clean_limit(limit: int) -> int:
        if limit <= 0:
            raise ValueError("limit must be positive")
        return min(limit, 25)

    @staticmethod
    def _require_user(user_identifier: str) -> None:
        if not user_identifier.strip():
            raise ValueError("user_identifier is required")
