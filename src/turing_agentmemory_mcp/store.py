from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from turingdb import TuringDB

from turing_agentmemory_mcp.community_detection import (
    CommunityEntity,
    CommunityFact,
    CommunityProjection,
    NativeLeidenDetector,
    WeightedEntityEdge,
    build_community_projection,
)
from turing_agentmemory_mcp.embeddings import Embedder, OpenAICompatibleEmbedder
from turing_agentmemory_mcp.entity_extraction import (
    EntityProcessor,
    ProcessedText,
    entity_metadata_search_text,
    entity_processor_from_env,
)
from turing_agentmemory_mcp.governance import (
    AuditSink,
    Redactor,
    audit_event,
    audit_sink_from_env,
    redactor_from_env,
)
from turing_agentmemory_mcp.hybrid import blend_hybrid_score, lexical_score
from turing_agentmemory_mcp.ids import cypher_var, quote, stable_id, vector_id
from turing_agentmemory_mcp.memory_extraction import (
    MEMORY_EXTRACTION_SCHEMA_VERSION,
    MemoryExtractor,
)
from turing_agentmemory_mcp.models import (
    DocumentHit,
    IngestedDocument,
    MemoryItem,
    RetrievalCandidate,
    RetrievalEvidence,
)
from turing_agentmemory_mcp.observability import (
    RuntimeSignals,
    SpanRecorder,
    span_recorder_from_env,
)
from turing_agentmemory_mcp.provider_config import provider_env
from turing_agentmemory_mcp.rerank import (
    OpenAICompatibleReranker,
    RerankResult,
    apply_rerank_guard,
    assemble_rerank_document,
)
from turing_agentmemory_mcp.retrieval_fusion import diversify_fused, fuse_rankings
from turing_agentmemory_mcp.search_controls import (
    build_score_details,
    passes_threshold,
    validate_fusion_weights,
    validate_search_query,
    validate_threshold,
)
from turing_agentmemory_mcp.sparse_index import (
    SparseDocument,
    SparseIndex,
    SparseMutation,
)
from turing_agentmemory_mcp.temporal_graph import (
    EdgeProjection,
    EntityProjection,
    EpisodeContext,
    TemporalProjection,
    canonicalize_entity_name,
    canonicalize_entity_type,
    plan_temporal_projection,
)

_MISSING = object()


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
        entity_index: str = "agent_memory_entity_vectors",
        fact_index: str = "agent_memory_fact_vectors",
        community_index: str = "agent_memory_community_vectors",
        embedder: Embedder | None = None,
        reranker: OpenAICompatibleReranker | None = None,
        entity_processor: EntityProcessor | None = None,
        memory_extractor: MemoryExtractor | None = None,
        sparse_index: SparseIndex | None = None,
        fusion_enabled: bool | None = None,
        fusion_weights: dict[str, float] | None = None,
        community_detector: NativeLeidenDetector | None = None,
        community_rebuild_on_batch: bool = False,
        runtime_signals: RuntimeSignals | None = None,
        observer: SpanRecorder | None = None,
        redactor: Redactor | None = None,
        audit_sink: AuditSink | None = None,
        rerank_threshold: float | None = None,
        rerank_blend: bool | None = None,
        rerank_preserve_seed_margin: float | None = None,
        rerank_candidate_limit: int | None = None,
    ) -> None:
        self.client = client
        self.turing_home = Path(turing_home)
        self.graph = graph
        self.dimensions = getattr(embedder, "dimensions", dimensions)
        self.memory_index = memory_index
        self.document_index = document_index
        self.entity_index = entity_index
        self.fact_index = fact_index
        self.community_index = community_index
        self._ensured_vector_indexes: set[str] = set()
        self.embedder = embedder or OpenAICompatibleEmbedder.from_env(dimensions=self.dimensions)
        self.reranker = reranker or OpenAICompatibleReranker.from_env()
        self.rerank_candidate_limit = max(
            2,
            int(
                provider_env("RERANK_CANDIDATE_LIMIT", default="50")
                if rerank_candidate_limit is None
                else rerank_candidate_limit
            ),
        )
        self.entity_processor = entity_processor or entity_processor_from_env()
        self.memory_extractor = memory_extractor
        self.sparse_index = sparse_index
        if fusion_enabled is not None and not isinstance(fusion_enabled, bool):
            raise ValueError("fusion_enabled must be a boolean")
        self.fusion_enabled = sparse_index is not None if fusion_enabled is None else fusion_enabled
        self.fusion_weights = validate_fusion_weights(
            fusion_weights
            or {
                "episode_dense": 1.5,
                "fact_dense": 0.75,
                "entity_dense": 0.5,
                "bm25": 2.0,
                "graph": 0.5,
                "community": 0.25,
            }
        )
        self.community_detector = community_detector or NativeLeidenDetector()
        if not isinstance(community_rebuild_on_batch, bool):
            raise ValueError("community_rebuild_on_batch must be a boolean")
        self.community_rebuild_on_batch = community_rebuild_on_batch
        self.runtime_signals = runtime_signals or RuntimeSignals()
        self.runtime_signals.configure_stage("graph", ready=False, identity={"graph": graph})
        self.runtime_signals.configure_stage(
            "extraction",
            ready=memory_extractor is not None,
            identity={
                "model": getattr(memory_extractor, "model_name", "disabled"),
                "schema_version": (
                    MEMORY_EXTRACTION_SCHEMA_VERSION if memory_extractor is not None else "disabled"
                ),
            },
        )
        self.runtime_signals.configure_stage(
            "sparse", ready=sparse_index is not None, identity={"backend": "sqlite-fts5"}
        )
        self.runtime_signals.configure_stage(
            "fusion",
            ready=self.fusion_enabled,
            identity={
                "algorithm": "weighted-rrf",
                **{
                    f"{channel}_weight": weight
                    for channel, weight in self.fusion_weights.items()
                },
            },
        )
        self.runtime_signals.configure_stage(
            "embedding",
            ready=True,
            identity={
                "model": getattr(self.embedder, "model", type(self.embedder).__name__),
                "dimensions": self.dimensions,
            },
        )
        self.runtime_signals.configure_stage(
            "rerank",
            ready=self.reranker is not None,
            identity={
                "model": (
                    getattr(self.reranker, "model", type(self.reranker).__name__)
                    if self.reranker is not None
                    else "disabled"
                ),
                "candidate_limit": self.rerank_candidate_limit,
            },
        )
        self.runtime_signals.configure_stage(
            "community",
            ready=self.fusion_enabled,
            identity={"backend": "graspologic-native", "seed": self.community_detector.seed},
        )
        self.observer = observer or span_recorder_from_env()
        self.redactor = redactor or redactor_from_env()
        self.audit_sink = audit_sink or audit_sink_from_env()
        self.rerank_threshold = (
            float(provider_env("RERANK_THRESHOLD", default="0"))
            if rerank_threshold is None
            else rerank_threshold
        )
        self.rerank_blend = (
            provider_env("RERANK_BLEND").lower() in {"1", "true", "yes", "on"}
            if rerank_blend is None
            else rerank_blend
        )
        self.rerank_preserve_seed_margin = (
            max(0.0, float(provider_env("RERANK_PRESERVE_SEED_MARGIN", default="0.05")))
            if rerank_preserve_seed_margin is None
            else max(0.0, rerank_preserve_seed_margin)
        )
        self.data_dir = self.turing_home / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def bootstrap(self) -> None:
        self.turing_home.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_graph_loaded()
        self._ensure_vector_index(self.memory_index)
        self._ensure_vector_index(self.document_index)
        self._ensure_vector_index(self.entity_index)
        self._ensure_vector_index(self.fact_index)
        self._ensure_vector_index(self.community_index)
        if self.sparse_index is not None:
            self.sparse_index.initialize()
            self.sparse_index.replay()
        self.runtime_signals.configure_stage("graph", ready=True, identity={"graph": self.graph})

    def store_message(
        self,
        *,
        user_identifier: str,
        session_id: str,
        role: str,
        content: str,
        memory_id: str | None = None,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str = "",
    ) -> MemoryItem:
        with self._span("memory.store_message", {"user_identifier": user_identifier, "source": source}):
            self._require_user(user_identifier)
            if self.memory_extractor is not None:
                return self.store_messages(
                    user_identifier=user_identifier,
                    messages=[
                        {
                            "memory_id": memory_id or "",
                            "session_id": session_id,
                            "role": role,
                            "content": content,
                            "source": source,
                            "tags": tags,
                            "metadata": metadata,
                            "expires_at": expires_at,
                        }
                    ],
                    _audit_operation="memory.store_message",
                )[0]
            content, metadata = self._process_text_for_storage(content, metadata)
            memory_id = memory_id or stable_id("mem", user_identifier, session_id, role, content)
            item = self._write_memory(
                user_identifier=user_identifier,
                memory_id=memory_id,
                kind="message",
                content=content,
                session_id=session_id,
                role=role,
                source=source,
                tags=tags,
                metadata=metadata,
                expires_at=expires_at,
            )
            self._audit(
                operation="memory.store_message",
                user_identifier=user_identifier,
                resource_type="memory",
                resource_id=item.id,
            )
            return item

    def store_messages(
        self,
        *,
        user_identifier: str,
        messages: list[dict[str, object]],
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str = "",
        refresh_communities: bool = True,
        _audit_operation: str = "memory.store_messages",
    ) -> list[MemoryItem]:
        with self._span(
            "memory.store_messages",
            {"user_identifier": user_identifier, "source": source, "count": len(messages)},
        ):
            self._require_user(user_identifier)
            if not isinstance(refresh_communities, bool):
                raise ValueError("refresh_communities must be a boolean")
            if not messages:
                return []
            prepared: list[dict[str, object]] = []
            raw_rows: list[tuple[str, dict[str, object]]] = []
            for idx, message in enumerate(messages):
                if not isinstance(message, dict):
                    raise ValueError(f"messages[{idx}] must be an object")
                session_id = str(message.get("session_id") or "")
                role = str(message.get("role") or "")
                content = str(message.get("content") or "")
                if not session_id.strip():
                    raise ValueError(f"messages[{idx}].session_id is required")
                if not role.strip():
                    raise ValueError(f"messages[{idx}].role is required")
                if not content.strip():
                    raise ValueError(f"messages[{idx}].content is required")
                item_source = str(message.get("source") if "source" in message else source)
                item_tags = self._clean_tags(
                    message.get("tags") if "tags" in message else tags  # type: ignore[arg-type]
                )
                item_metadata = dict(
                    message.get("metadata") if isinstance(message.get("metadata"), dict) else metadata or {}
                )
                item_expires_at = str(message.get("expires_at") if "expires_at" in message else expires_at)
                prepared.append(
                    {
                        "memory_id": str(message.get("memory_id") or ""),
                        "session_id": session_id,
                        "role": role,
                        "content": content,
                        "source": item_source,
                        "tags": item_tags,
                        "metadata": item_metadata,
                        "expires_at": item_expires_at,
                    }
                )
                raw_rows.append((content, item_metadata))

            processed_rows = self._process_texts_for_storage(raw_rows)
            unique_by_id: dict[str, dict[str, object]] = {}
            for payload, (content, item_metadata) in zip(prepared, processed_rows, strict=True):
                payload["content"] = content
                payload["metadata"] = item_metadata
                memory_id = str(payload["memory_id"]) or stable_id(
                    "mem",
                    user_identifier,
                    str(payload["session_id"]),
                    str(payload["role"]),
                    content,
                )
                payload["memory_id"] = memory_id
                existing_payload = unique_by_id.get(memory_id)
                if existing_payload is not None and self._batch_payload_key(
                    existing_payload
                ) != self._batch_payload_key(payload):
                    raise ValueError(f"conflicting duplicate memory_id in batch: {memory_id}")
                unique_by_id.setdefault(memory_id, payload)

            unique_payloads = list(unique_by_id.values())
            existing_by_id = {
                str(payload["memory_id"]): self.get_memory(
                    user_identifier=user_identifier,
                    memory_id=str(payload["memory_id"]),
                )
                for payload in unique_payloads
            }
            if self.memory_extractor is not None:
                for payload in unique_payloads:
                    existing_item = existing_by_id[str(payload["memory_id"])]
                    if existing_item is not None and not self._memory_matches_payload(
                        existing_item,
                        payload,
                    ):
                        raise ValueError(
                            f"immutable temporal episode cannot be changed: {payload['memory_id']}"
                        )
            needs_embedding = [
                payload
                for payload in unique_payloads
                if existing_by_id[str(payload["memory_id"])] is None
                or existing_by_id[str(payload["memory_id"])].content != str(payload["content"])
            ]
            new_payloads = [
                payload
                for payload in unique_payloads
                if existing_by_id[str(payload["memory_id"])] is None
            ]
            for payload in new_payloads:
                payload["created_at"] = self._now_iso()
            projections = self._plan_memory_projections(
                user_identifier=user_identifier,
                payloads=new_payloads,
            )
            entities = self._unique_projection_entities(
                user_identifier=user_identifier,
                projections=projections,
            )
            facts = [fact for projection in projections for fact in projection.facts]
            embedding_texts = (
                [str(payload["content"]) for payload in needs_embedding]
                + [entity.content for entity in entities]
                + [fact.content for fact in facts]
            )
            vectors = self._embed_many(embedding_texts)
            raw_end = len(needs_embedding)
            entity_end = raw_end + len(entities)
            raw_vectors = vectors[:raw_end]
            entity_vectors = vectors[raw_end:entity_end]
            fact_vectors = vectors[entity_end:]
            vector_by_id = {
                str(payload["memory_id"]): vector
                for payload, vector in zip(needs_embedding, raw_vectors, strict=True)
            }

            item_by_id: dict[str, MemoryItem] = {}
            vector_rows: list[tuple[int, list[float]]] = []
            sparse_batch_id = self._prepare_sparse_projection(
                user_identifier=user_identifier,
                payloads=new_payloads,
                projections=projections,
                entities=entities,
            )
            try:
                for item in self._create_memories_batch(
                    user_identifier=user_identifier,
                    payloads=new_payloads,
                    projections=projections,
                    entities=entities,
                ):
                    item_by_id[item.id] = item
            except Exception as exc:
                if sparse_batch_id is not None and self.sparse_index is not None:
                    try:
                        self.sparse_index.discard_prepared(sparse_batch_id)
                    except Exception as discard_exc:
                        exc.add_note(f"sparse prepared-batch cleanup failed: {discard_exc}")
                raise
            if sparse_batch_id is not None and self.sparse_index is not None:
                self.sparse_index.commit_batch(sparse_batch_id)
                self.sparse_index.replay(batch_id=sparse_batch_id)
            for payload in unique_payloads:
                memory_id = str(payload["memory_id"])
                if memory_id in item_by_id:
                    continue
                existing_item = existing_by_id[memory_id]
                if existing_item is not None and self._memory_matches_payload(
                    existing_item,
                    payload,
                ):
                    item_by_id[memory_id] = existing_item
                    continue
                vector = vector_by_id.get(memory_id)
                item = self._write_memory(
                    user_identifier=user_identifier,
                    memory_id=memory_id,
                    kind="message",
                    content=str(payload["content"]),
                    session_id=str(payload["session_id"]),
                    role=str(payload["role"]),
                    source=str(payload["source"]),
                    tags=payload["tags"],  # type: ignore[arg-type]
                    metadata=payload["metadata"],  # type: ignore[arg-type]
                    expires_at=str(payload["expires_at"]),
                    existing=existing_by_id[memory_id],
                    vector=vector,
                    load_vector=False,
                )
                item_by_id[memory_id] = item
            for memory_id, vector in vector_by_id.items():
                vector_rows.append((self._memory_vector_id(user_identifier, memory_id), vector))
            if vector_rows:
                self._load_vectors(
                    self._tenant_vector_index(self.memory_index, user_identifier),
                    vector_rows,
                    "memory_batch",
                )
            if entity_vectors:
                self._load_vectors(
                    self._tenant_vector_index(self.entity_index, user_identifier),
                    [
                        (self._entity_vector_id(user_identifier, entity.id), vector)
                        for entity, vector in zip(entities, entity_vectors, strict=True)
                    ],
                    "entity_batch",
                )
            if fact_vectors:
                self._load_vectors(
                    self._tenant_vector_index(self.fact_index, user_identifier),
                    [
                        (self._fact_vector_id(user_identifier, fact.id), vector)
                        for fact, vector in zip(facts, fact_vectors, strict=True)
                    ],
                    "fact_batch",
                )
            if new_payloads and refresh_communities:
                self._refresh_communities_after_batch(user_identifier)
            items = [item_by_id[str(payload["memory_id"])] for payload in prepared]
            self._audit(
                operation=_audit_operation,
                user_identifier=user_identifier,
                resource_type="memory",
                resource_id=items[0].id if _audit_operation == "memory.store_message" else "",
                details={"count": len(items)},
            )
            return items

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
        session_id: str = "",
        source: str = "",
        tags: list[str] | None = None,
        created_after: str = "",
        created_before: str = "",
        updated_after: str = "",
        updated_before: str = "",
        threshold: float = 0.0,
        explain: bool = False,
    ) -> list[MemoryItem]:
        with self._span(
            "memory.search",
            {
                "user_identifier": user_identifier,
                "limit": limit,
                "session_id": session_id,
                "source": source,
            },
        ):
            self._require_user(user_identifier)
            query = validate_search_query(query)
            limit = self._clean_limit(limit)
            threshold = validate_threshold(threshold)
            created_after_dt = self._parse_filter_datetime(created_after, "created_after")
            created_before_dt = self._parse_filter_datetime(created_before, "created_before")
            updated_after_dt = self._parse_filter_datetime(updated_after, "updated_after")
            updated_before_dt = self._parse_filter_datetime(updated_before, "updated_before")
            if self.fusion_enabled:
                return self._search_memory_fused(
                    user_identifier=user_identifier,
                    query=query,
                    limit=limit,
                    memory_types=memory_types,
                    session_id=session_id,
                    source=source,
                    tags=tags,
                    created_after=created_after_dt,
                    created_before=created_before_dt,
                    updated_after=updated_after_dt,
                    updated_before=updated_before_dt,
                    threshold=threshold,
                    explain=explain,
                )
            literal = self._vector_literal(self._embed_text(query, operation="memory.search"))
            memory_index = self._ensure_tenant_vector_index(
                self.memory_index, user_identifier
            )
            try:
                vector_rows = self._records(
                    self._query(
                        f"VECTOR SEARCH IN {memory_index} FOR {max(limit * 4, limit)} {literal} "
                        f"YIELD ids, score MATCH (m:Memory) "
                        f'WHERE m.vector_id = ids AND m.user_identifier = "{quote(user_identifier)}" '
                        'AND m.status = "active" '
                        "RETURN m.id, m.user_identifier, m.kind, m.content, m.session_id, m.role, "
                        "m.created_at, m.updated_at, m.expires_at, m.source, "
                        "m.tags_json, m.metadata_json, score",
                        operation="memory.vector_search",
                    )
                )
            except Exception as exc:
                if "Unknown label: Memory" not in str(exc):
                    raise
                return []
            allowed = set(memory_types or [])
            rows_by_id: dict[str, dict[str, Any]] = {}
            semantic_by_id: dict[str, float] = {}
            for row in vector_rows:
                if self._row_is_expired(row, "m.expires_at"):
                    continue
                memory_id = str(row.get("m.id", ""))
                if not memory_id:
                    continue
                semantic_by_id[memory_id] = max(
                    semantic_by_id.get(memory_id, 0.0),
                    float(row.get("score") or 0.0),
                )
                rows_by_id[memory_id] = row
            for row in self._active_memory_rows(user_identifier):
                memory_id = str(row.get("m.id", ""))
                if memory_id and memory_id not in rows_by_id:
                    rows_by_id[memory_id] = row

            seeds: list[MemoryItem] = []
            for memory_id, row in rows_by_id.items():
                if self._row_is_expired(row, "m.expires_at"):
                    continue
                kind = str(row.get("m.kind", ""))
                item = self._memory_from_row(row)
                if not self._memory_matches_filters(
                    item,
                    session_id=session_id,
                    memory_types=memory_types,
                    source=source,
                    tags=tags,
                    created_after=created_after_dt,
                    created_before=created_before_dt,
                    updated_after=updated_after_dt,
                    updated_before=updated_before_dt,
                ):
                    continue
                semantic_score = semantic_by_id.get(memory_id, 0.0)
                lexical = lexical_score(
                    query,
                    self._row_search_text(row, text_key="m.content", metadata_key="m.metadata_json"),
                )
                final_score = blend_hybrid_score(semantic_score=semantic_score, lexical_score=lexical)
                if allowed and kind not in allowed:
                    continue
                if semantic_score <= 0.0 and lexical <= 0.0:
                    continue
                if not passes_threshold(final_score, threshold):
                    continue
                item = MemoryItem(
                    id=item.id,
                    user_identifier=item.user_identifier,
                    kind=item.kind,
                    content=item.content,
                    session_id=item.session_id,
                    role=item.role,
                    score=final_score,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    expires_at=item.expires_at,
                    source=item.source,
                    tags=item.tags,
                    metadata=item.metadata,
                )
                if explain:
                    item = MemoryItem(
                        **{
                            **item.to_dict(),
                            "score_details": build_score_details(
                                semantic_score=semantic_score,
                                lexical_score=lexical,
                                threshold=threshold,
                                final_score=final_score,
                            ),
                        }
                    )
                seeds.append(item)
            seeds = sorted(seeds, key=lambda item: item.score, reverse=True)[
                : max(limit * 3, limit)
            ]
            return self._rerank_memory(query, seeds)[:limit]

    def _search_memory_fused(
        self,
        *,
        user_identifier: str,
        query: str,
        limit: int,
        memory_types: list[str] | None,
        session_id: str,
        source: str,
        tags: list[str] | None,
        created_after: datetime | None,
        created_before: datetime | None,
        updated_after: datetime | None,
        updated_before: datetime | None,
        threshold: float,
        explain: bool,
    ) -> list[MemoryItem]:
        candidate_limit = min(max(limit * 8, 40), 200)
        channels, degraded = self._collect_retrieval_evidence(
            user_identifier=user_identifier,
            query=query,
            candidate_limit=candidate_limit,
        )
        self.runtime_signals.record_degraded_channels(tuple(sorted(degraded)))
        source_ids = list(
            dict.fromkeys(
                evidence.source_memory_id
                for ranking in channels.values()
                for evidence in ranking
                if evidence.source_memory_id
            )
        )
        rows_by_id = self._memory_rows_for_ids(user_identifier, source_ids)
        items_by_id: dict[str, MemoryItem] = {}
        for source_id, row in rows_by_id.items():
            if self._row_is_expired(row, "m.expires_at"):
                continue
            item = self._memory_from_row(row)
            if not self._memory_matches_filters(
                item,
                session_id=session_id,
                memory_types=memory_types,
                source=source,
                tags=tags,
                created_after=created_after,
                created_before=created_before,
                updated_after=updated_after,
                updated_before=updated_before,
            ):
                continue
            items_by_id[source_id] = item

        rankings: dict[str, list[RetrievalCandidate]] = {}
        evidence_by_source: dict[str, list[RetrievalEvidence]] = {}
        for channel in sorted(channels):
            ranking: list[RetrievalCandidate] = []
            seen_sources: set[str] = set()
            for evidence in channels[channel]:
                source_id = evidence.source_memory_id
                item = items_by_id.get(source_id)
                if item is None:
                    continue
                evidence_by_source.setdefault(source_id, []).append(evidence)
                if source_id in seen_sources:
                    continue
                seen_sources.add(source_id)
                ranking.append(
                    RetrievalCandidate(
                        candidate_id=source_id,
                        kind=item.kind,
                        content=item.content,
                        source_memory_id=source_id,
                        raw_score=evidence.raw_score,
                    )
                )
            if ranking:
                rankings[channel] = ranking
        if not rankings:
            return []
        rerank_pool_limit = min(max(limit * 3, limit), candidate_limit)
        fused = diversify_fused(
            fuse_rankings(
                rankings,
                weights=self.fusion_weights,
                channel_caps=candidate_limit,
            ),
            limit=rerank_pool_limit,
            max_per_source=1,
        )
        results: list[MemoryItem] = []
        for fused_candidate in fused:
            if not passes_threshold(fused_candidate.score, threshold):
                continue
            source_id = fused_candidate.candidate.source_memory_id
            item = items_by_id[source_id]
            details: dict[str, object] = {
                "fusion_score": fused_candidate.score,
                "final_score": fused_candidate.score,
                "threshold": threshold,
            }
            if explain:
                evidence = evidence_by_source.get(source_id, [])
                details.update(
                    {
                    "channels": {
                        channel: score.to_dict()
                        for channel, score in fused_candidate.channels.items()
                    },
                    "evidence_ids": sorted(
                        {value.evidence_id for value in evidence if value.evidence_id}
                    ),
                    "max_hop": max((value.hop for value in evidence), default=0),
                    "degraded_channels": sorted(degraded),
                    }
                )
            results.append(
                MemoryItem(
                    id=item.id,
                    user_identifier=item.user_identifier,
                    kind=item.kind,
                    content=item.content,
                    score=fused_candidate.score,
                    session_id=item.session_id,
                    role=item.role,
                    created_at=item.created_at,
                    updated_at=item.updated_at,
                    expires_at=item.expires_at,
                    source=item.source,
                    tags=item.tags,
                    metadata=item.metadata,
                    score_details=details,
                )
            )
        return self._rerank_memory(query, results)[:limit]

    def _collect_retrieval_evidence(
        self,
        *,
        user_identifier: str,
        query: str,
        candidate_limit: int,
    ) -> tuple[dict[str, list[RetrievalEvidence]], dict[str, str]]:
        channels: dict[str, list[RetrievalEvidence]] = {}
        degraded: dict[str, str] = {}
        query_vector: list[float] | None = None
        try:
            query_vector = self._embed_text(query, operation="memory.search")
        except Exception as exc:
            for channel in ("episode_dense", "fact_dense", "entity_dense"):
                degraded[channel] = type(exc).__name__

        if query_vector is not None:
            for channel, collector in (
                (
                    "episode_dense",
                    lambda: self._episode_dense_evidence(
                        user_identifier, query_vector, candidate_limit
                    ),
                ),
                (
                    "fact_dense",
                    lambda: self._fact_dense_evidence(
                        user_identifier, query_vector, candidate_limit
                    ),
                ),
                (
                    "entity_dense",
                    lambda: self._entity_dense_evidence(
                        user_identifier, query_vector, candidate_limit
                    ),
                ),
            ):
                try:
                    values = collector()
                    if values:
                        channels[channel] = values
                except Exception as exc:
                    degraded[channel] = type(exc).__name__
            try:
                community_values = self._community_dense_evidence(
                    user_identifier, query_vector, candidate_limit
                )
                if community_values:
                    channels["community"] = community_values
            except Exception as exc:
                degraded["community"] = type(exc).__name__

        if self.sparse_index is not None:
            try:
                sparse_values = self._sparse_evidence(
                    user_identifier, query, candidate_limit
                )
                if sparse_values:
                    channels["bm25"] = sparse_values
            except Exception as exc:
                degraded["bm25"] = type(exc).__name__

        if self.memory_extractor is not None:
            try:
                graph_values = self._query_graph_evidence(
                    user_identifier, query, candidate_limit
                )
                if graph_values:
                    channels["graph"] = graph_values
            except Exception as exc:
                degraded["graph"] = type(exc).__name__
        for channel, values in channels.items():
            channels[channel] = sorted(
                values,
                key=lambda item: (
                    -item.raw_score,
                    item.hop,
                    item.source_memory_id,
                    item.evidence_id,
                ),
            )
        return channels, degraded

    def _episode_dense_evidence(
        self,
        user_identifier: str,
        query_vector: list[float],
        limit: int,
    ) -> list[RetrievalEvidence]:
        index_name = self._ensure_tenant_vector_index(
            self.memory_index, user_identifier
        )
        rows = self._records(
            self._query(
                f"VECTOR SEARCH IN {index_name} FOR {limit} "
                f"{self._vector_literal(query_vector)} YIELD ids, score "
                "MATCH (m:Memory) "
                f'WHERE m.vector_id = ids AND m.user_identifier = "{quote(user_identifier)}" '
                'AND m.status = "active" RETURN m.id, score',
                operation="memory.vector_search.fused",
            )
        )
        return [
            RetrievalEvidence(
                source_memory_id=str(row.get("m.id")),
                evidence_id=str(row.get("m.id")),
                evidence_kind="episode",
                raw_score=float(row.get("score") or 0.0),
            )
            for row in rows
            if row.get("m.id")
        ]

    def _fact_dense_evidence(
        self,
        user_identifier: str,
        query_vector: list[float],
        limit: int,
    ) -> list[RetrievalEvidence]:
        index_name = self._ensure_tenant_vector_index(
            self.fact_index, user_identifier
        )
        rows = self._records(
            self._query(
                f"VECTOR SEARCH IN {index_name} FOR {limit} "
                f"{self._vector_literal(query_vector)} YIELD ids, score "
                "MATCH (f:Fact) "
                f'WHERE f.vector_id = ids AND f.user_identifier = "{quote(user_identifier)}" '
                'AND f.status = "active" RETURN f.id, f.source_memory_id, score',
                operation="fact.vector_search",
            )
        )
        return [
            RetrievalEvidence(
                source_memory_id=str(row.get("f.source_memory_id")),
                evidence_id=str(row.get("f.id")),
                evidence_kind="fact",
                raw_score=float(row.get("score") or 0.0),
            )
            for row in rows
            if row.get("f.id") and row.get("f.source_memory_id")
        ]

    def _entity_dense_evidence(
        self,
        user_identifier: str,
        query_vector: list[float],
        limit: int,
    ) -> list[RetrievalEvidence]:
        index_name = self._ensure_tenant_vector_index(
            self.entity_index, user_identifier
        )
        rows = self._records(
            self._query(
                f"VECTOR SEARCH IN {index_name} FOR {limit} "
                f"{self._vector_literal(query_vector)} YIELD ids, score "
                "MATCH (e:Entity) "
                f'WHERE e.vector_id = ids AND e.user_identifier = "{quote(user_identifier)}" '
                'AND e.status = "active" RETURN e.id, score',
                operation="entity.vector_search",
            )
        )
        seeds = {
            str(row.get("e.id")): float(row.get("score") or 0.0)
            for row in rows
            if row.get("e.id")
        }
        return self._expand_entity_evidence(user_identifier, seeds, limit)

    def _sparse_evidence(
        self,
        user_identifier: str,
        query: str,
        limit: int,
    ) -> list[RetrievalEvidence]:
        if self.sparse_index is None:
            return []
        hits = self.sparse_index.search(
            user_identifier=user_identifier,
            query=query,
            limit=limit,
            kinds=["episode", "fact", "entity", "community"],
        )
        fact_ids = [hit.source_id for hit in hits if hit.kind == "fact"]
        fact_sources = self._fact_sources_by_ids(user_identifier, fact_ids)
        community_ids = [hit.source_id for hit in hits if hit.kind == "community"]
        community_sources = self._community_sources_by_ids(
            user_identifier, community_ids
        )
        entity_seeds = {
            hit.source_id: max(hit.score, 1e-12)
            for hit in hits
            if hit.kind == "entity"
        }
        entity_evidence = self._expand_entity_evidence(
            user_identifier, entity_seeds, limit
        )
        values: list[RetrievalEvidence] = []
        for hit in hits:
            if hit.kind == "episode":
                values.append(
                    RetrievalEvidence(
                        hit.source_id,
                        hit.source_id,
                        "episode",
                        hit.score,
                    )
                )
            elif hit.kind == "fact" and hit.source_id in fact_sources:
                values.append(
                    RetrievalEvidence(
                        fact_sources[hit.source_id],
                        hit.source_id,
                        "fact",
                        hit.score,
                    )
                )
            elif hit.kind == "community":
                for source_memory_id in community_sources.get(hit.source_id, ()):
                    values.append(
                        RetrievalEvidence(
                            source_memory_id,
                            hit.source_id,
                            "community",
                            hit.score,
                            metadata={"community_id": hit.source_id},
                        )
                    )
        values.extend(entity_evidence)
        return values[:limit]

    def _community_dense_evidence(
        self,
        user_identifier: str,
        query_vector: list[float],
        limit: int,
    ) -> list[RetrievalEvidence]:
        index_name = self._ensure_tenant_vector_index(
            self.community_index, user_identifier
        )
        rows = self._records(
            self._query(
                f"VECTOR SEARCH IN {index_name} FOR {limit} "
                f"{self._vector_literal(query_vector)} YIELD ids, score "
                "MATCH (c:Community) "
                f'WHERE c.vector_id = ids AND c.user_identifier = "{quote(user_identifier)}" '
                'AND c.status = "active" RETURN c.id, c.source_memory_ids_json, score',
                operation="community.vector_search",
            )
        )
        values: list[RetrievalEvidence] = []
        for row in rows:
            community_id = str(row.get("c.id") or "")
            source_ids = self._json_loads(
                row.get("c.source_memory_ids_json"), []
            )
            if not community_id or not isinstance(source_ids, list):
                continue
            for source_id in source_ids:
                if not isinstance(source_id, str) or not source_id:
                    continue
                values.append(
                    RetrievalEvidence(
                        source_memory_id=source_id,
                        evidence_id=community_id,
                        evidence_kind="community",
                        raw_score=float(row.get("score") or 0.0),
                        metadata={"community_id": community_id},
                    )
                )
                if len(values) >= limit:
                    return values
        return values

    def _query_graph_evidence(
        self,
        user_identifier: str,
        query: str,
        limit: int,
    ) -> list[RetrievalEvidence]:
        if self.memory_extractor is None:
            return []
        extractions = self.memory_extractor.extract_many([query])
        if not isinstance(extractions, tuple) or len(extractions) != 1:
            raise RuntimeError("query memory extractor returned an invalid result count")
        seeds: dict[str, float] = {}
        for entity in extractions[0].entities:
            entity_type = canonicalize_entity_type(entity.label)
            canonical_name = canonicalize_entity_name(entity.text)
            entity_id = stable_id(
                "ent", user_identifier, entity_type, canonical_name
            )
            seeds[entity_id] = max(seeds.get(entity_id, 0.0), entity.score)
        return self._expand_entity_evidence(user_identifier, seeds, limit)

    def _expand_entity_evidence(
        self,
        user_identifier: str,
        entity_scores: dict[str, float],
        limit: int,
    ) -> list[RetrievalEvidence]:
        if not entity_scores:
            return []
        condition = " OR ".join(
            f'e.id = "{quote(entity_id)}"' for entity_id in entity_scores
        )
        queries = (
            (
                "graph.entity_direct_subject",
                "MATCH (e:Entity)-[:SUBJECT_OF]->(f:Fact)-[:SUPPORTED_BY]->(m:Memory) ",
                1,
            ),
            (
                "graph.entity_direct_object",
                "MATCH (e:Entity)-[:OBJECT_OF]->(f:Fact)-[:SUPPORTED_BY]->(m:Memory) ",
                1,
            ),
            (
                "graph.entity_two_hop_subject",
                "MATCH (e:Entity)--(n:Entity)-[:SUBJECT_OF]->(f:Fact)-[:SUPPORTED_BY]->(m:Memory) ",
                2,
            ),
            (
                "graph.entity_two_hop_object",
                "MATCH (e:Entity)--(n:Entity)-[:OBJECT_OF]->(f:Fact)-[:SUPPORTED_BY]->(m:Memory) ",
                2,
            ),
        )
        values: list[RetrievalEvidence] = []
        for operation, prefix, hop in queries:
            rows = self._records(
                self._query(
                    prefix
                    + f'WHERE e.user_identifier = "{quote(user_identifier)}" '
                    + f'AND ({condition}) AND e.status = "active" '
                    + 'AND f.status = "active" AND m.status = "active" '
                    + "RETURN m.id, f.id, f.confidence, e.id",
                    operation=operation,
                )
            )
            for row in rows:
                source_memory_id = str(row.get("m.id") or "")
                evidence_id = str(row.get("f.id") or "")
                entity_id = str(row.get("e.id") or "")
                if not source_memory_id or not evidence_id:
                    continue
                seed_score = entity_scores.get(entity_id, max(entity_scores.values()))
                confidence = float(row.get("f.confidence") or 1.0)
                values.append(
                    RetrievalEvidence(
                        source_memory_id=source_memory_id,
                        evidence_id=evidence_id,
                        evidence_kind="fact",
                        raw_score=seed_score * confidence / hop,
                        hop=hop,
                        metadata={"entity_id": entity_id},
                    )
                )
                if len(values) >= limit:
                    return values
        return values

    def _fact_sources_by_ids(
        self,
        user_identifier: str,
        fact_ids: list[str],
    ) -> dict[str, str]:
        if not fact_ids:
            return {}
        condition = " OR ".join(
            f'f.id = "{quote(fact_id)}"' for fact_id in dict.fromkeys(fact_ids)
        )
        rows = self._records(
            self._query(
                "MATCH (f:Fact) "
                f'WHERE f.user_identifier = "{quote(user_identifier)}" '
                f'AND ({condition}) AND f.status = "active" '
                "RETURN f.id, f.source_memory_id, f.confidence",
                operation="fact.source_lookup",
            )
        )
        return {
            str(row.get("f.id")): str(row.get("f.source_memory_id"))
            for row in rows
            if row.get("f.id") and row.get("f.source_memory_id")
        }

    def _community_sources_by_ids(
        self,
        user_identifier: str,
        community_ids: list[str],
    ) -> dict[str, tuple[str, ...]]:
        if not community_ids:
            return {}
        condition = " OR ".join(
            f'c.id = "{quote(community_id)}"'
            for community_id in dict.fromkeys(community_ids)
        )
        rows = self._records(
            self._query(
                "MATCH (c:Community) "
                f'WHERE c.user_identifier = "{quote(user_identifier)}" '
                f'AND ({condition}) AND c.status = "active" '
                "RETURN c.id, c.source_memory_ids_json",
                operation="community.source_lookup",
            )
        )
        values: dict[str, tuple[str, ...]] = {}
        for row in rows:
            community_id = str(row.get("c.id") or "")
            source_ids = self._json_loads(
                row.get("c.source_memory_ids_json"), []
            )
            if community_id and isinstance(source_ids, list):
                values[community_id] = tuple(
                    source_id
                    for source_id in source_ids
                    if isinstance(source_id, str) and source_id
                )
        return values

    def _memory_rows_for_ids(
        self,
        user_identifier: str,
        memory_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        if not memory_ids:
            return {}
        condition = " OR ".join(
            f'm.id = "{quote(memory_id)}"'
            for memory_id in dict.fromkeys(memory_ids)
        )
        try:
            rows = self._records(
                self._query(
                    "MATCH (m:Memory) "
                    f'WHERE m.user_identifier = "{quote(user_identifier)}" '
                    f'AND ({condition}) AND m.status = "active" '
                    "RETURN m.id, m.user_identifier, m.kind, m.content, m.session_id, m.role, "
                    "m.created_at, m.updated_at, m.expires_at, m.source, "
                    "m.tags_json, m.metadata_json",
                    operation="memory.source_hydration",
                )
            )
        except Exception as exc:
            if "Unknown label: Memory" not in str(exc):
                raise
            return {}
        return {
            str(row.get("m.id")): row for row in rows if row.get("m.id")
        }

    def get_memory(self, *, user_identifier: str, memory_id: str) -> MemoryItem | None:
        self._require_user(user_identifier)
        if not memory_id.strip():
            raise ValueError("memory_id is required")
        try:
            rows = self._records(
                self._query(
                    f'MATCH (m:Memory) WHERE m.id = "{quote(memory_id)}" '
                    f'AND m.user_identifier = "{quote(user_identifier)}" AND m.status = "active" '
                    "RETURN m.id, m.user_identifier, m.kind, m.content, m.session_id, m.role, "
                    "m.created_at, m.updated_at, m.expires_at, m.source, m.tags_json, m.metadata_json",
                    operation="memory.get",
                )
            )
        except Exception as exc:
            if "Unknown label: Memory" not in str(exc):
                raise
            return None
        matching_rows = [
            row
            for row in rows
            if str(row.get("m.id", "")) == memory_id and not self._row_is_expired(row, "m.expires_at")
        ]
        return self._memory_from_row(matching_rows[0]) if matching_rows else None

    def list_memories(
        self,
        *,
        user_identifier: str,
        limit: int = 25,
        session_id: str = "",
        memory_types: list[str] | None = None,
        source: str = "",
        tags: list[str] | None = None,
        created_after: str = "",
        created_before: str = "",
        updated_after: str = "",
        updated_before: str = "",
    ) -> list[MemoryItem]:
        self._require_user(user_identifier)
        limit = self._clean_limit(limit)
        created_after_dt = self._parse_filter_datetime(created_after, "created_after")
        created_before_dt = self._parse_filter_datetime(created_before, "created_before")
        updated_after_dt = self._parse_filter_datetime(updated_after, "updated_after")
        updated_before_dt = self._parse_filter_datetime(updated_before, "updated_before")
        try:
            rows = self._records(
                self._query(
                    f'MATCH (m:Memory) WHERE m.user_identifier = "{quote(user_identifier)}" '
                    'AND m.status = "active" '
                    "RETURN m.id, m.user_identifier, m.kind, m.content, m.session_id, m.role, "
                    "m.created_at, m.updated_at, m.expires_at, m.source, m.tags_json, m.metadata_json",
                    operation="memory.list",
                )
            )
        except Exception as exc:
            if "Unknown label: Memory" not in str(exc):
                raise
            return []
        items = [self._memory_from_row(row) for row in rows if not self._row_is_expired(row, "m.expires_at")]
        items = [
            item
            for item in items
            if self._memory_matches_filters(
                item,
                session_id=session_id,
                memory_types=memory_types,
                source=source,
                tags=tags,
                created_after=created_after_dt,
                created_before=created_before_dt,
                updated_after=updated_after_dt,
                updated_before=updated_before_dt,
            )
        ]
        items.sort(key=lambda item: (item.updated_at, item.created_at, item.id), reverse=True)
        return items[:limit]

    def update_memory(
        self,
        *,
        user_identifier: str,
        memory_id: str,
        content: str | None = None,
        kind: str | None = None,
        session_id: str | None = None,
        role: str | None = None,
        source: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
        vector: list[float] | None = None,
        load_vector: bool = True,
    ) -> MemoryItem:
        existing = self.get_memory(user_identifier=user_identifier, memory_id=memory_id)
        if existing is None:
            raise ValueError(f"memory {memory_id} not found")
        if self.memory_extractor is not None and existing.kind == "message":
            requested = {
                "content": content,
                "kind": kind,
                "session_id": session_id,
                "role": role,
                "source": source,
                "tags": tags,
                "metadata": metadata,
                "expires_at": expires_at,
            }
            if any(value is not None for value in requested.values()):
                raise ValueError(f"immutable temporal episode cannot be changed: {memory_id}")
        next_content = existing.content if content is None else content
        if not next_content.strip():
            raise ValueError("content is required")
        next_kind = existing.kind if kind is None else kind
        next_session_id = existing.session_id if session_id is None else session_id
        next_role = existing.role if role is None else role
        next_source = existing.source if source is None else source
        next_tags = existing.tags if tags is None else self._clean_tags(tags)
        next_metadata = existing.metadata if metadata is None else dict(metadata)
        next_expires_at = existing.expires_at if expires_at is None else expires_at
        if content is not None:
            next_content, next_metadata = self._process_text_for_storage(next_content, next_metadata)
        updated_at = self._now_iso()
        vid = self._memory_vector_id(user_identifier, memory_id)
        sparse_batch_id = None
        if self.sparse_index is not None:
            sparse_batch_id = self.sparse_index.prepare(
                [
                    SparseMutation.upsert(
                        SparseDocument(
                            doc_key=self._sparse_doc_key(
                                user_identifier,
                                self._sparse_kind(next_kind),
                                memory_id,
                            ),
                            user_identifier=user_identifier,
                            source_id=memory_id,
                            kind=self._sparse_kind(next_kind),
                            content=next_content,
                            source=next_source,
                            session_id=next_session_id,
                            created_at=existing.created_at,
                            expires_at=next_expires_at,
                        )
                    )
                ]
            )
        try:
            self._write(
                f'MATCH (m:Memory) WHERE m.id = "{quote(memory_id)}" '
                f'AND m.user_identifier = "{quote(user_identifier)}" '
                f'SET m.vector_id = {vid}, m.kind = "{quote(next_kind)}", '
                f'm.content = "{quote(next_content)}", m.session_id = "{quote(next_session_id)}", '
                f'm.role = "{quote(next_role)}", m.source = "{quote(next_source)}", '
                f'm.tags_json = "{quote(self._json_dumps(next_tags))}", '
                f'm.metadata_json = "{quote(self._json_dumps(next_metadata))}", '
                f'm.expires_at = "{quote(next_expires_at)}", '
                f'm.updated_at = "{quote(updated_at)}", m.status = "active"'
            )
        except Exception:
            if sparse_batch_id is not None and self.sparse_index is not None:
                self.sparse_index.discard_prepared(sparse_batch_id)
            raise
        if sparse_batch_id is not None and self.sparse_index is not None:
            self.sparse_index.commit_batch(sparse_batch_id)
            self.sparse_index.replay(batch_id=sparse_batch_id)
        if load_vector and next_content != existing.content:
            self._load_vectors(
                self._tenant_vector_index(self.memory_index, user_identifier),
                [
                    (
                        vid,
                        vector
                        if vector is not None
                        else self._embed_text(next_content, operation="memory.update"),
                    )
                ],
                f"memory_{memory_id}",
            )
        item = MemoryItem(
            id=memory_id,
            user_identifier=user_identifier,
            kind=next_kind,
            content=next_content,
            session_id=next_session_id,
            role=next_role,
            score=1.0,
            created_at=existing.created_at,
            updated_at=updated_at,
            expires_at=next_expires_at,
            source=next_source,
            tags=next_tags,
            metadata=next_metadata,
        )
        self._audit(
            operation="memory.update",
            user_identifier=user_identifier,
            resource_type="memory",
            resource_id=memory_id,
        )
        return item

    def delete_memory(self, *, user_identifier: str, memory_id: str) -> dict[str, object]:
        existing = self.get_memory(user_identifier=user_identifier, memory_id=memory_id)
        if existing is None:
            return {"memory_id": memory_id, "deleted": False}
        updated_at = self._now_iso()
        fact_ids = self._fact_ids_for_memory(user_identifier, memory_id)
        sparse_batch_id = None
        if self.sparse_index is not None:
            sparse_batch_id = self.sparse_index.prepare(
                [
                    SparseMutation.delete(
                        self._sparse_doc_key(user_identifier, "episode", memory_id)
                    ),
                    *[
                        SparseMutation.delete(
                            self._sparse_doc_key(user_identifier, "fact", fact_id)
                        )
                        for fact_id in fact_ids
                    ],
                ]
            )
        match_nodes = ["(m:Memory)"] + [
            f"({cypher_var(fact_id)}:Fact)" for fact_id in fact_ids
        ]
        where_terms = [
            f'm.id = "{quote(memory_id)}"',
            f'm.user_identifier = "{quote(user_identifier)}"',
            *[
                f'{cypher_var(fact_id)}.id = "{quote(fact_id)}"'
                for fact_id in fact_ids
            ],
        ]
        set_terms = [
            'm.status = "deleted"',
            f'm.updated_at = "{quote(updated_at)}"',
            *[
                f'{cypher_var(fact_id)}.status = "deleted"'
                for fact_id in fact_ids
            ],
        ]
        try:
            self._write(
                "MATCH "
                + ", ".join(match_nodes)
                + " WHERE "
                + " AND ".join(where_terms)
                + " SET "
                + ", ".join(set_terms)
            )
        except Exception:
            if sparse_batch_id is not None and self.sparse_index is not None:
                self.sparse_index.discard_prepared(sparse_batch_id)
            raise
        if sparse_batch_id is not None and self.sparse_index is not None:
            self.sparse_index.commit_batch(sparse_batch_id)
            self.sparse_index.replay(batch_id=sparse_batch_id)
        self._audit(
            operation="memory.delete",
            user_identifier=user_identifier,
            resource_type="memory",
            resource_id=memory_id,
        )
        return {"memory_id": memory_id, "deleted": True, "updated_at": updated_at}

    def get_context(
        self,
        *,
        user_identifier: str,
        query: str,
        session_id: str = "",
        memory_types: list[str] | None = None,
        source: str = "",
        tags: list[str] | None = None,
        created_after: str = "",
        created_before: str = "",
        updated_after: str = "",
        updated_before: str = "",
        limit: int = 5,
        threshold: float = 0.0,
    ) -> dict[str, object]:
        items = self.search_memory(
            user_identifier=user_identifier,
            query=query,
            limit=limit,
            memory_types=memory_types,
            session_id=session_id,
            source=source,
            tags=tags,
            created_after=created_after,
            created_before=created_before,
            updated_after=updated_after,
            updated_before=updated_before,
            threshold=threshold,
        )
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
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> IngestedDocument:
        with self._span(
            "document.ingest_text",
            {"user_identifier": user_identifier, "document_id": document_id or "", "source": source},
        ):
            self._require_user(user_identifier)
            if not title.strip():
                raise ValueError("title is required")
            if not text.strip():
                raise ValueError("text is required")
            text, metadata = self._process_text_for_storage(text, metadata)
            document_id = document_id or stable_id("doc", user_identifier, title, text[:128])
            text_hash = self._document_text_hash(text)
            chunks = self._chunk_document_text(text, chunk_chars=chunk_chars)
            self._ensure_user(user_identifier)
            existing = self.get_document(user_identifier=user_identifier, document_id=document_id)
            if existing is not None:
                if existing.text_hash != text_hash or existing.chunk_chars != chunk_chars:
                    raise ValueError(
                        f"document {document_id} already exists with different text; use document_reindex_text"
                    )
                return self._update_document_metadata(
                    user_identifier=user_identifier,
                    document_id=document_id,
                    title=title,
                    source=source,
                    tags=tags,
                    metadata=metadata,
                    expires_at=expires_at,
                    preserve_updated_at=False,
                )
            item = self._create_document(
                user_identifier=user_identifier,
                document_id=document_id,
                title=title,
                text=text,
                chunks=chunks,
                chunk_chars=chunk_chars,
                text_hash=text_hash,
                source=source,
                tags=tags,
                metadata=metadata,
                expires_at=expires_at or "",
            )
            self._audit(
                operation="document.ingest_text",
                user_identifier=user_identifier,
                resource_type="document",
                resource_id=item.document_id,
            )
            return item

    def get_document(self, *, user_identifier: str, document_id: str) -> IngestedDocument | None:
        self._require_user(user_identifier)
        if not document_id.strip():
            raise ValueError("document_id is required")
        try:
            rows = self._records(
                self._query(
                    f'MATCH (d:Document) WHERE d.id = "{quote(document_id)}" '
                    f'AND d.user_identifier = "{quote(user_identifier)}" AND d.status = "searchable" '
                    "RETURN d.id, d.user_identifier, d.title, d.chunk_count, d.created_at, "
                    "d.updated_at, d.expires_at, d.source, d.tags_json, d.metadata_json, "
                    "d.text_hash, d.chunk_chars",
                    operation="document.get",
                )
            )
        except Exception as exc:
            if "Unknown label: Document" not in str(exc):
                raise
            return None
        matching_rows = [
            row
            for row in rows
            if str(row.get("d.id", "")) == document_id and not self._row_is_expired(row, "d.expires_at")
        ]
        return self._document_from_row(matching_rows[0]) if matching_rows else None

    def reindex_document_text(
        self,
        *,
        user_identifier: str,
        document_id: str,
        title: str,
        text: str,
        chunk_chars: int = 360,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> IngestedDocument:
        with self._span(
            "document.reindex_text",
            {"user_identifier": user_identifier, "document_id": document_id, "source": source},
        ):
            self._require_user(user_identifier)
            if not document_id.strip():
                raise ValueError("document_id is required")
            if not title.strip():
                raise ValueError("title is required")
            if not text.strip():
                raise ValueError("text is required")
            text, metadata = self._process_text_for_storage(text, metadata)
            existing = self.get_document(user_identifier=user_identifier, document_id=document_id)
            if existing is not None:
                self.delete_document(user_identifier=user_identifier, document_id=document_id)
            chunks = self._chunk_document_text(text, chunk_chars=chunk_chars)
            item = self._create_document(
                user_identifier=user_identifier,
                document_id=document_id,
                title=title,
                text=text,
                chunks=chunks,
                chunk_chars=chunk_chars,
                text_hash=self._document_text_hash(text),
                source=source,
                tags=tags,
                metadata=metadata,
                expires_at=expires_at if expires_at is not None else existing.expires_at if existing is not None else "",
                created_at=existing.created_at if existing is not None else None,
            )
            self._audit(
                operation="document.reindex_text",
                user_identifier=user_identifier,
                resource_type="document",
                resource_id=item.document_id,
            )
            return item

    def delete_document(self, *, user_identifier: str, document_id: str) -> dict[str, object]:
        existing = self.get_document(user_identifier=user_identifier, document_id=document_id)
        if existing is None:
            return {"document_id": document_id, "deleted": False}
        updated_at = self._now_iso()
        self._write(
            f'MATCH (d:Document) WHERE d.id = "{quote(document_id)}" '
            f'AND d.user_identifier = "{quote(user_identifier)}" '
            f'SET d.status = "deleted", d.updated_at = "{quote(updated_at)}"'
        )
        self._write(
            f'MATCH (c:Chunk) WHERE c.document_id = "{quote(document_id)}" '
            f'AND c.user_identifier = "{quote(user_identifier)}" '
            f'SET c.status = "deleted", c.updated_at = "{quote(updated_at)}"'
        )
        self._audit(
            operation="document.delete",
            user_identifier=user_identifier,
            resource_type="document",
            resource_id=document_id,
        )
        return {"document_id": document_id, "deleted": True, "updated_at": updated_at}

    def _create_document(
        self,
        *,
        user_identifier: str,
        document_id: str,
        title: str,
        text: str,
        chunks: list[str],
        chunk_chars: int,
        text_hash: str,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str = "",
        created_at: str | None = None,
    ) -> IngestedDocument:
        self._ensure_user(user_identifier)
        doc_var = cypher_var(document_id)
        created_at = created_at or self._now_iso()
        updated_at = self._now_iso()
        clean_tags = self._clean_tags(tags)
        clean_metadata = dict(metadata or {})
        nodes = [
            f'({doc_var}:Document {{id: "{quote(document_id)}", user_identifier: "{quote(user_identifier)}", '
            f'title: "{quote(title)}", chunk_count: {len(chunks)}, chunk_chars: {chunk_chars}, '
            f'text_hash: "{quote(text_hash)}", source: "{quote(source)}", '
            f'tags_json: "{quote(self._json_dumps(clean_tags))}", '
            f'metadata_json: "{quote(self._json_dumps(clean_metadata))}", '
            f'created_at: "{quote(created_at)}", updated_at: "{quote(updated_at)}", '
            f'expires_at: "{quote(expires_at)}", status: "searchable"}})'
        ]
        edges = [f"(u)-[:HAS_DOCUMENT]->({doc_var})"]
        vector_rows: list[tuple[int, list[float]]] = []
        vectors = self._embed_many(chunks)
        previous_var = ""
        for idx, (chunk_text, vector) in enumerate(zip(chunks, vectors, strict=True), start=1):
            chunk_id = f"{document_id}#{idx}"
            chunk_var = cypher_var(chunk_id)
            vid = self._document_vector_id(user_identifier, chunk_id)
            locator = f"chunk={idx}"
            nodes.append(
                f'({chunk_var}:Chunk {{chunk_id: "{quote(chunk_id)}", vector_id: {vid}, '
                f'document_id: "{quote(document_id)}", user_identifier: "{quote(user_identifier)}", '
                f'title: "{quote(title)}", ordinal: {idx}, locator: "{locator}", '
                f'source: "{quote(source)}", tags_json: "{quote(self._json_dumps(clean_tags))}", '
                f'metadata_json: "{quote(self._json_dumps(clean_metadata))}", '
                f'created_at: "{quote(created_at)}", updated_at: "{quote(updated_at)}", '
                f'expires_at: "{quote(expires_at)}", status: "active", text: "{quote(chunk_text)}"}})'
            )
            edges.append(f"({doc_var})-[:HAS_CHUNK {{ordinal: {idx}}}]->({chunk_var})")
            if previous_var:
                edges.append(f"({previous_var})-[:NEXT_CHUNK]->({chunk_var})")
            previous_var = chunk_var
            vector_rows.append((vid, vector))
        self._write(
            f'MATCH (u:User) WHERE u.identifier = "{quote(user_identifier)}" CREATE '
            + ", ".join(nodes + edges)
        )
        self._load_vectors(
            self._tenant_vector_index(self.document_index, user_identifier),
            vector_rows,
            f"document_{document_id}",
        )
        return IngestedDocument(
            document_id=document_id,
            title=title,
            chunk_count=len(chunks),
            user_identifier=user_identifier,
            created_at=created_at,
            updated_at=updated_at,
            expires_at=expires_at,
            source=source,
            tags=clean_tags,
            metadata=clean_metadata,
            text_hash=text_hash,
            chunk_chars=chunk_chars,
        )

    def _update_document_metadata(
        self,
        *,
        user_identifier: str,
        document_id: str,
        title: str,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
        preserve_updated_at: bool = False,
    ) -> IngestedDocument:
        existing = self.get_document(user_identifier=user_identifier, document_id=document_id)
        if existing is None:
            raise ValueError(f"document {document_id} not found")
        next_source = existing.source if source == "" else source
        next_tags = existing.tags if tags is None else self._clean_tags(tags)
        next_metadata = existing.metadata if metadata is None else dict(metadata)
        next_expires_at = existing.expires_at if expires_at is None else expires_at
        updated_at = existing.updated_at if preserve_updated_at else self._now_iso()
        self._write(
            f'MATCH (d:Document) WHERE d.id = "{quote(document_id)}" '
            f'AND d.user_identifier = "{quote(user_identifier)}" AND d.status = "searchable" '
            f'SET d.title = "{quote(title)}", d.source = "{quote(next_source)}", '
            f'd.tags_json = "{quote(self._json_dumps(next_tags))}", '
            f'd.metadata_json = "{quote(self._json_dumps(next_metadata))}", '
            f'd.expires_at = "{quote(next_expires_at)}", '
            f'd.updated_at = "{quote(updated_at)}"'
        )
        self._write(
            f'MATCH (c:Chunk) WHERE c.document_id = "{quote(document_id)}" '
            f'AND c.user_identifier = "{quote(user_identifier)}" AND c.status = "active" '
            f'SET c.title = "{quote(title)}", c.source = "{quote(next_source)}", '
            f'c.tags_json = "{quote(self._json_dumps(next_tags))}", '
            f'c.metadata_json = "{quote(self._json_dumps(next_metadata))}", '
            f'c.expires_at = "{quote(next_expires_at)}", '
            f'c.updated_at = "{quote(updated_at)}"'
        )
        return IngestedDocument(
            document_id=document_id,
            title=title,
            chunk_count=existing.chunk_count,
            user_identifier=user_identifier,
            created_at=existing.created_at,
            updated_at=updated_at,
            expires_at=next_expires_at,
            source=next_source,
            tags=next_tags,
            metadata=next_metadata,
            text_hash=existing.text_hash,
            chunk_chars=existing.chunk_chars,
        )

    def search_documents(
        self,
        *,
        user_identifier: str,
        query: str,
        limit: int = 5,
        document_id: str = "",
        source: str = "",
        tags: list[str] | None = None,
        created_after: str = "",
        created_before: str = "",
        updated_after: str = "",
        updated_before: str = "",
        threshold: float = 0.0,
        explain: bool = False,
    ) -> list[DocumentHit]:
        with self._span(
            "document.search",
            {"user_identifier": user_identifier, "document_id": document_id, "limit": limit},
        ):
            self._require_user(user_identifier)
            query = validate_search_query(query)
            limit = self._clean_limit(limit)
            threshold = validate_threshold(threshold)
            required_tags = set(self._clean_tags(tags))
            created_after_dt = self._parse_filter_datetime(created_after, "created_after")
            created_before_dt = self._parse_filter_datetime(created_before, "created_before")
            updated_after_dt = self._parse_filter_datetime(updated_after, "updated_after")
            updated_before_dt = self._parse_filter_datetime(updated_before, "updated_before")
            literal = self._vector_literal(self._embed_text(query, operation="document.search"))
            document_filter = ""
            if document_id:
                document_filter = f' AND c.document_id = "{quote(document_id)}"'
            document_index = self._ensure_tenant_vector_index(
                self.document_index, user_identifier
            )
            try:
                vector_rows = self._records(
                    self._query(
                        f"VECTOR SEARCH IN {document_index} FOR {max(limit * 4, limit)} {literal} "
                        f"YIELD ids, score MATCH (c:Chunk) "
                        f'WHERE c.vector_id = ids AND c.user_identifier = "{quote(user_identifier)}" '
                        f'AND c.status = "active"{document_filter} '
                        "RETURN c.chunk_id, c.document_id, c.title, c.locator, c.text, c.vector_id, "
                        "c.created_at, c.updated_at, c.expires_at, c.source, "
                        "c.tags_json, c.metadata_json, score",
                        operation="document.vector_search",
                    )
                )
            except Exception as exc:
                if "Unknown label: Chunk" not in str(exc):
                    raise
                return []
            rows_by_id: dict[str, dict[str, Any]] = {}
            semantic_by_id: dict[str, float] = {}
            for row in vector_rows:
                if self._row_is_expired(row, "c.expires_at"):
                    continue
                chunk_id = str(row.get("c.chunk_id", ""))
                if not chunk_id:
                    continue
                semantic_by_id[chunk_id] = max(
                    semantic_by_id.get(chunk_id, 0.0),
                    float(row.get("score") or 0.0),
                )
                rows_by_id[chunk_id] = row
            for row in self._active_chunk_rows(user_identifier, document_id=document_id):
                chunk_id = str(row.get("c.chunk_id", ""))
                if chunk_id and chunk_id not in rows_by_id:
                    rows_by_id[chunk_id] = row

            seeds: list[DocumentHit] = []
            for chunk_id, row in rows_by_id.items():
                if self._row_is_expired(row, "c.expires_at"):
                    continue
                if not self._row_matches_metadata_filters(
                    row,
                    prefix="c",
                    source=source,
                    required_tags=required_tags,
                    created_after=created_after_dt,
                    created_before=created_before_dt,
                    updated_after=updated_after_dt,
                    updated_before=updated_before_dt,
                ):
                    continue
                semantic_score = semantic_by_id.get(chunk_id, 0.0)
                lexical = lexical_score(
                    query,
                    self._row_search_text(row, text_key="c.text", metadata_key="c.metadata_json"),
                )
                final_score = blend_hybrid_score(semantic_score=semantic_score, lexical_score=lexical)
                if semantic_score <= 0.0 and lexical <= 0.0:
                    continue
                if not passes_threshold(final_score, threshold):
                    continue
                context = self._chunk_context(int(row.get("c.vector_id") or 0))
                tags = self._json_loads(row.get("c.tags_json"), [])
                metadata = self._json_loads(row.get("c.metadata_json"), {})
                seeds.append(
                    DocumentHit(
                        chunk_id=str(row.get("c.chunk_id", "")),
                        document_id=str(row.get("c.document_id", "")),
                        title=str(row.get("c.title", "")),
                        locator=str(row.get("c.locator", "")),
                        text=str(row.get("c.text", "")),
                        score=final_score,
                        context=context,
                        expires_at=str(row.get("c.expires_at") or ""),
                        source=str(row.get("c.source", "")),
                        tags=tags if isinstance(tags, list) else [],
                        metadata=metadata if isinstance(metadata, dict) else {},
                        score_details=(
                            build_score_details(
                                semantic_score=semantic_score,
                                lexical_score=lexical,
                                threshold=threshold,
                                final_score=final_score,
                            )
                            if explain
                            else None
                        ),
                    )
                )
            seeds = sorted(seeds, key=lambda item: item.score, reverse=True)[
                : max(limit * 3, limit)
            ]
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
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str = "",
        existing: MemoryItem | None | object = _MISSING,
        vector: list[float] | None = None,
        load_vector: bool = True,
    ) -> MemoryItem:
        self._ensure_user(user_identifier)
        if existing is _MISSING:
            existing = self.get_memory(user_identifier=user_identifier, memory_id=memory_id)
        if existing is not None:
            return self.update_memory(
                user_identifier=user_identifier,
                memory_id=memory_id,
                content=content,
                kind=kind,
                session_id=session_id,
                role=role,
                source=source,
                tags=tags,
                metadata=metadata,
                expires_at=expires_at,
                vector=vector,
                load_vector=load_vector,
            )
        vid = self._memory_vector_id(user_identifier, memory_id)
        mem_var = cypher_var(memory_id)
        created_at = self._now_iso()
        clean_tags = self._clean_tags(tags)
        clean_metadata = dict(metadata or {})
        self._write(
            f'MATCH (u:User) WHERE u.identifier = "{quote(user_identifier)}" '
            f'CREATE ({mem_var}:Memory {{id: "{quote(memory_id)}", vector_id: {vid}, '
            f'user_identifier: "{quote(user_identifier)}", kind: "{quote(kind)}", '
            f'content: "{quote(content)}", session_id: "{quote(session_id)}", '
            f'role: "{quote(role)}", source: "{quote(source)}", '
            f'tags_json: "{quote(self._json_dumps(clean_tags))}", '
            f'metadata_json: "{quote(self._json_dumps(clean_metadata))}", '
            f'created_at: "{quote(created_at)}", updated_at: "{quote(created_at)}", '
            f'expires_at: "{quote(expires_at)}", '
            'status: "active"}), '
            f"(u)-[:HAS_MEMORY]->({mem_var})"
        )
        if load_vector:
            self._load_vectors(
                self._tenant_vector_index(self.memory_index, user_identifier),
                [
                    (
                        vid,
                        vector
                        if vector is not None
                        else self._embed_text(content, operation="memory.store"),
                    )
                ],
                f"memory_{memory_id}",
            )
        return MemoryItem(
            id=memory_id,
            user_identifier=user_identifier,
            kind=kind,
            content=content,
            session_id=session_id,
            role=role,
            score=1.0,
            created_at=created_at,
            updated_at=created_at,
            expires_at=expires_at,
            source=source,
            tags=clean_tags,
            metadata=clean_metadata,
        )

    def _create_memories_batch(
        self,
        *,
        user_identifier: str,
        payloads: list[dict[str, object]],
        projections: list[TemporalProjection] | None = None,
        entities: list[EntityProjection] | None = None,
    ) -> list[MemoryItem]:
        if not payloads:
            return []
        self._ensure_user(user_identifier)
        projections = list(projections or [])
        new_entities = list(entities or [])
        nodes: list[str] = []
        edges: list[str] = []
        items: list[MemoryItem] = []
        for payload in payloads:
            memory_id = str(payload["memory_id"])
            mem_var = cypher_var(memory_id)
            vid = self._memory_vector_id(user_identifier, memory_id)
            created_at = str(payload.get("created_at") or self._now_iso())
            content = str(payload["content"])
            session_id = str(payload["session_id"])
            role = str(payload["role"])
            source = str(payload["source"])
            expires_at = str(payload.get("expires_at") or "")
            clean_tags = self._clean_tags(payload.get("tags"))  # type: ignore[arg-type]
            clean_metadata = dict(payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {})
            nodes.append(
                f'({mem_var}:Memory {{id: "{quote(memory_id)}", vector_id: {vid}, '
                f'user_identifier: "{quote(user_identifier)}", kind: "message", '
                f'content: "{quote(content)}", session_id: "{quote(session_id)}", '
                f'role: "{quote(role)}", source: "{quote(source)}", '
                f'tags_json: "{quote(self._json_dumps(clean_tags))}", '
                f'metadata_json: "{quote(self._json_dumps(clean_metadata))}", '
                f'created_at: "{quote(created_at)}", updated_at: "{quote(created_at)}", '
                f'expires_at: "{quote(expires_at)}", '
                'status: "active"})'
            )
            edges.append(f"(u)-[:HAS_MEMORY]->({mem_var})")
            items.append(
                MemoryItem(
                    id=memory_id,
                    user_identifier=user_identifier,
                    kind="message",
                    content=content,
                    session_id=session_id,
                    role=role,
                    score=1.0,
                    created_at=created_at,
                    updated_at=created_at,
                    expires_at=expires_at,
                    source=source,
                    tags=clean_tags,
                    metadata=clean_metadata,
                )
            )
        new_entity_ids = {entity.id for entity in new_entities}
        all_entity_ids = {
            entity.id
            for projection in projections
            for entity in projection.entities
        }
        existing_entity_ids = all_entity_ids - new_entity_ids
        for entity in new_entities:
            entity_var = cypher_var(entity.id)
            nodes.append(
                f'({entity_var}:Entity {{id: "{quote(entity.id)}", '
                f'vector_id: {self._entity_vector_id(user_identifier, entity.id)}, '
                f'user_identifier: "{quote(user_identifier)}", '
                f'entity_type: "{quote(entity.entity_type)}", '
                f'canonical_name: "{quote(entity.canonical_name)}", '
                f'display_name: "{quote(entity.display_name)}", '
                f'content: "{quote(entity.content)}", confidence: {entity.confidence:.8f}, '
                f'first_observed_at: "{quote(entity.observed_at)}", '
                f'last_observed_at: "{quote(entity.observed_at)}", '
                f'source_memory_id: "{quote(entity.source_memory_id)}", '
                f'schema_version: "{quote(entity.schema_version)}", '
                f'model: "{quote(entity.model)}", '
                f'expires_at: "{quote(entity.expires_at)}", status: "active"}})'
            )
        facts = [fact for projection in projections for fact in projection.facts]
        for fact in facts:
            fact_var = cypher_var(fact.id)
            nodes.append(
                f'({fact_var}:Fact {{id: "{quote(fact.id)}", '
                f'vector_id: {self._fact_vector_id(user_identifier, fact.id)}, '
                f'user_identifier: "{quote(user_identifier)}", '
                f'subject_entity_id: "{quote(fact.subject_entity_id)}", '
                f'predicate: "{quote(fact.predicate)}", '
                f'object_entity_id: "{quote(fact.object_entity_id)}", '
                f'content: "{quote(fact.content)}", confidence: {fact.confidence:.8f}, '
                f'observed_at: "{quote(fact.observed_at)}", '
                f'valid_from: "{quote(fact.valid_from)}", '
                f'valid_to: "{quote(fact.valid_to)}", '
                f'valid_time_precision: "{quote(fact.valid_time_precision)}", '
                f'source_memory_id: "{quote(fact.source_memory_id)}", '
                f'session_id: "{quote(fact.session_id)}", speaker: "{quote(fact.speaker)}", '
                f'source: "{quote(fact.source)}", '
                f'tags_json: "{quote(self._json_dumps(list(fact.tags)))}", '
                f'metadata_json: "{quote(self._json_dumps(fact.metadata))}", '
                f'schema_version: "{quote(fact.schema_version)}", model: "{quote(fact.model)}", '
                f'expires_at: "{quote(fact.expires_at)}", status: "active"}})'
            )
        for projection in projections:
            edges.extend(self._projection_edge_literals(projection.edges))
        match_nodes = ["(u:User)"] + [
            f"({cypher_var(entity_id)}:Entity)" for entity_id in sorted(existing_entity_ids)
        ]
        where_terms = [f'u.identifier = "{quote(user_identifier)}"'] + [
            f'{cypher_var(entity_id)}.id = "{quote(entity_id)}"'
            for entity_id in sorted(existing_entity_ids)
        ]
        self._write(
            "MATCH "
            + ", ".join(match_nodes)
            + " WHERE "
            + " AND ".join(where_terms)
            + " CREATE "
            + ", ".join(nodes + edges)
        )
        return items

    def _plan_memory_projections(
        self,
        *,
        user_identifier: str,
        payloads: list[dict[str, object]],
    ) -> list[TemporalProjection]:
        if not payloads or self.memory_extractor is None:
            return []
        texts = [str(payload["content"]) for payload in payloads]
        extractions = self.memory_extractor.extract_many(texts)
        if not isinstance(extractions, tuple) or len(extractions) != len(payloads):
            count = len(extractions) if isinstance(extractions, tuple) else 0
            raise RuntimeError(
                f"memory extractor returned {count} results for {len(payloads)} inputs"
            )
        return [
            plan_temporal_projection(
                EpisodeContext(
                    user_identifier=user_identifier,
                    memory_id=str(payload["memory_id"]),
                    content=str(payload["content"]),
                    session_id=str(payload["session_id"]),
                    role=str(payload["role"]),
                    observed_at=str(payload["created_at"]),
                    source=str(payload["source"]),
                    tags=tuple(payload["tags"]),  # type: ignore[arg-type]
                    metadata=dict(payload["metadata"]),  # type: ignore[arg-type]
                    expires_at=str(payload["expires_at"]),
                ),
                extraction,
            )
            for payload, extraction in zip(payloads, extractions, strict=True)
        ]

    def _prepare_sparse_projection(
        self,
        *,
        user_identifier: str,
        payloads: list[dict[str, object]],
        projections: list[TemporalProjection],
        entities: list[EntityProjection],
    ) -> str | None:
        if self.sparse_index is None or not payloads:
            return None
        payload_by_memory_id = {
            str(payload["memory_id"]): payload for payload in payloads
        }
        mutations: list[SparseMutation] = []
        for payload in payloads:
            source_id = str(payload["memory_id"])
            mutations.append(
                SparseMutation.upsert(
                    SparseDocument(
                        doc_key=self._sparse_doc_key(user_identifier, "episode", source_id),
                        user_identifier=user_identifier,
                        source_id=source_id,
                        kind="episode",
                        content=str(payload["content"]),
                        source=str(payload["source"]),
                        session_id=str(payload["session_id"]),
                        created_at=str(payload["created_at"]),
                        expires_at=str(payload["expires_at"]),
                    )
                )
            )
        for entity in entities:
            source_payload = payload_by_memory_id.get(entity.source_memory_id, {})
            mutations.append(
                SparseMutation.upsert(
                    SparseDocument(
                        doc_key=self._sparse_doc_key(user_identifier, "entity", entity.id),
                        user_identifier=user_identifier,
                        source_id=entity.id,
                        kind="entity",
                        content=entity.content,
                        source=str(source_payload.get("source") or ""),
                        session_id=str(source_payload.get("session_id") or ""),
                        created_at=entity.observed_at,
                        expires_at=entity.expires_at,
                    )
                )
            )
        for projection in projections:
            for fact in projection.facts:
                mutations.append(
                    SparseMutation.upsert(
                        SparseDocument(
                            doc_key=self._sparse_doc_key(user_identifier, "fact", fact.id),
                            user_identifier=user_identifier,
                            source_id=fact.id,
                            kind="fact",
                            content=fact.content,
                            source=fact.source,
                            session_id=fact.session_id,
                            created_at=fact.observed_at,
                            expires_at=fact.expires_at,
                        )
                    )
                )
        return self.sparse_index.prepare(mutations)

    @staticmethod
    def _sparse_doc_key(user_identifier: str, kind: str, source_id: str) -> str:
        return f"{user_identifier}:{kind}:{source_id}"

    @staticmethod
    def _sparse_kind(memory_kind: str) -> str:
        return "episode" if memory_kind == "message" else memory_kind

    def _fact_ids_for_memory(self, user_identifier: str, memory_id: str) -> list[str]:
        try:
            rows = self._records(
                self._query(
                    "MATCH (f:Fact) "
                    f'WHERE f.user_identifier = "{quote(user_identifier)}" '
                    f'AND f.source_memory_id = "{quote(memory_id)}" AND f.status = "active" '
                    "RETURN f.id",
                    operation="fact.ids_for_memory",
                )
            )
        except Exception as exc:
            if "Unknown label: Fact" not in str(exc):
                raise
            return []
        return [str(row.get("f.id")) for row in rows if row.get("f.id")]

    def rebuild_sparse_projection(self) -> dict[str, object]:
        if self.sparse_index is None:
            raise RuntimeError("sparse projection is not configured")
        documents = self._canonical_sparse_documents()
        self.sparse_index.rebuild(documents)
        return self.sparse_index.status()

    def rebuild_vector_projection(self, *, user_identifier: str) -> dict[str, object]:
        """Re-embed active tenant records into recoverable vector indexes."""
        self._require_user(user_identifier)
        canonical = self._canonical_vector_records(user_identifier)
        specifications = (
            ("memory", self.memory_index, self._memory_vector_id),
            ("document", self.document_index, self._document_vector_id),
            ("entity", self.entity_index, self._entity_vector_id),
            ("fact", self.fact_index, self._fact_vector_id),
            ("community", self.community_index, self._community_vector_id),
        )
        counts: dict[str, int] = {}
        for kind, base_index_name, id_factory in specifications:
            records = canonical.get(kind, [])
            index_name = self._ensure_tenant_vector_index(
                base_index_name, user_identifier
            )
            vectors = self._embed_many([content for _source_id, content in records])
            if vectors:
                self._load_vectors(
                    index_name,
                    [
                        (id_factory(user_identifier, source_id), vector)
                        for (source_id, _content), vector in zip(records, vectors, strict=True)
                    ],
                    f"{kind}_rebuild",
                )
            counts[kind] = len(records)
        result: dict[str, object] = {
            "user_identifier": user_identifier,
            "counts": counts,
            "total": sum(counts.values()),
            "dimensions": self.dimensions,
            "model": getattr(self.embedder, "model", type(self.embedder).__name__),
        }
        self._audit(
            operation="vector_projection.rebuild",
            user_identifier=user_identifier,
            resource_type="vector_projection",
            resource_id=user_identifier,
            details={"counts": counts, "total": result["total"]},
        )
        return result

    def rebuild_communities(self, *, user_identifier: str) -> dict[str, object]:
        self._require_user(user_identifier)
        entities, facts, mentions_by_memory = self._community_graph_inputs(
            user_identifier
        )
        edges = [
            WeightedEntityEdge(
                fact.subject_entity_id,
                fact.object_entity_id,
                max(fact.confidence, 1e-12),
                (fact.source_memory_id,) if fact.source_memory_id else (),
            )
            for fact in facts
            if fact.subject_entity_id in entities
            and fact.object_entity_id in entities
            and fact.subject_entity_id != fact.object_entity_id
        ]
        for memory_id, member_ids in mentions_by_memory.items():
            unique = tuple(sorted(set(member_ids)))
            for index, source_id in enumerate(unique):
                for target_id in unique[index + 1 :]:
                    edges.append(
                        WeightedEntityEdge(
                            source_id,
                            target_id,
                            0.25,
                            (memory_id,),
                        )
                    )
        detection = self.community_detector.detect(
            user_identifier,
            list(entities),
            edges,
        )
        projections = [
            build_community_projection(community, entities, facts)
            for community in detection.communities
        ]
        vectors = self._embed_many([projection.content for projection in projections])
        previous_ids = self._active_community_ids(user_identifier)
        sparse_batch_id = None
        if self.sparse_index is not None:
            mutations: list[SparseMutation] = [
                SparseMutation.delete(
                    self._sparse_doc_key(user_identifier, "community", community_id)
                )
                for community_id in sorted(previous_ids)
            ]
            mutations.extend(
                SparseMutation.upsert(
                    SparseDocument(
                        doc_key=self._sparse_doc_key(
                            user_identifier, "community", projection.id
                        ),
                        user_identifier=user_identifier,
                        source_id=projection.id,
                        kind="community",
                        content=projection.content,
                        created_at=self._now_iso(),
                    )
                )
                for projection in projections
            )
            if mutations:
                sparse_batch_id = self.sparse_index.prepare(mutations)
        try:
            self._replace_community_graph(user_identifier, projections)
        except Exception as exc:
            if sparse_batch_id is not None and self.sparse_index is not None:
                try:
                    self.sparse_index.discard_prepared(sparse_batch_id)
                except Exception as discard_exc:
                    exc.add_note(f"sparse community cleanup failed: {discard_exc}")
            raise
        if sparse_batch_id is not None and self.sparse_index is not None:
            self.sparse_index.commit_batch(sparse_batch_id)
            self.sparse_index.replay(batch_id=sparse_batch_id)
        if vectors:
            self._load_vectors(
                self._tenant_vector_index(self.community_index, user_identifier),
                [
                    (
                        self._community_vector_id(user_identifier, projection.id),
                        vector,
                    )
                    for projection, vector in zip(projections, vectors, strict=True)
                ],
                "community_batch",
            )
        result = {
            "user_identifier": user_identifier,
            "community_count": len(projections),
            "isolate_count": len(detection.isolates),
            "community_ids": [projection.id for projection in projections],
            "backend": detection.backend,
            "seed": detection.seed,
            "resolution": detection.resolution,
        }
        self.runtime_signals.record_projection(
            "community", success=True, item_count=len(projections)
        )
        return result

    def _refresh_communities_after_batch(self, user_identifier: str) -> None:
        if not self.community_rebuild_on_batch or self.memory_extractor is None:
            return
        try:
            self.rebuild_communities(user_identifier=user_identifier)
        except Exception as exc:
            self.runtime_signals.record_projection(
                "community", success=False, error_type=type(exc).__name__
            )

    def runtime_status(self) -> dict[str, object]:
        status = self.runtime_signals.snapshot()
        if self.sparse_index is not None:
            try:
                sparse = self.sparse_index.status()
            except Exception as exc:
                sparse = {"status": "degraded", "error_type": type(exc).__name__}
            projections = status.setdefault("projections", {})
            if isinstance(projections, dict):
                projections["sparse"] = sparse
        status["fusion_enabled"] = self.fusion_enabled
        status["community_rebuild_on_batch"] = self.community_rebuild_on_batch
        return status

    def _community_graph_inputs(
        self,
        user_identifier: str,
    ) -> tuple[
        dict[str, CommunityEntity],
        list[CommunityFact],
        dict[str, tuple[str, ...]],
    ]:
        entity_rows = self._records(
            self._query(
                "MATCH (e:Entity) "
                f'WHERE e.user_identifier = "{quote(user_identifier)}" AND e.status = "active" '
                "RETURN e.id, e.display_name, e.entity_type, e.confidence, e.source_memory_id",
                operation="community.inputs.entities",
            )
        )
        mention_rows = self._records(
            self._query(
                "MATCH (m:Memory)-[:MENTIONS]->(e:Entity) "
                f'WHERE m.user_identifier = "{quote(user_identifier)}" '
                'AND m.status = "active" AND e.status = "active" RETURN m.id, e.id',
                operation="community.inputs.mentions",
            )
        )
        sources_by_entity: dict[str, set[str]] = {}
        mentions_by_memory_sets: dict[str, set[str]] = {}
        for row in mention_rows:
            memory_id = str(row.get("m.id") or "")
            entity_id = str(row.get("e.id") or "")
            if not memory_id or not entity_id:
                continue
            sources_by_entity.setdefault(entity_id, set()).add(memory_id)
            mentions_by_memory_sets.setdefault(memory_id, set()).add(entity_id)
        entities = {
            str(row.get("e.id")): CommunityEntity(
                id=str(row.get("e.id")),
                display_name=str(row.get("e.display_name") or ""),
                entity_type=str(row.get("e.entity_type") or "entity"),
                confidence=float(row.get("e.confidence") or 0.0),
                source_memory_ids=tuple(
                    sorted(
                        sources_by_entity.get(
                            str(row.get("e.id")),
                            {str(row.get("e.source_memory_id") or "")}
                            - {""},
                        )
                    )
                ),
            )
            for row in entity_rows
            if row.get("e.id") and row.get("e.display_name")
        }
        fact_rows = self._records(
            self._query(
                "MATCH (f:Fact) "
                f'WHERE f.user_identifier = "{quote(user_identifier)}" AND f.status = "active" '
                "RETURN f.id, f.subject_entity_id, f.predicate, f.object_entity_id, f.content, "
                "f.confidence, f.observed_at, f.source_memory_id",
                operation="community.inputs.facts",
            )
        )
        facts = [
            CommunityFact(
                id=str(row.get("f.id")),
                subject_entity_id=str(row.get("f.subject_entity_id") or ""),
                predicate=str(row.get("f.predicate") or ""),
                object_entity_id=str(row.get("f.object_entity_id") or ""),
                content=str(row.get("f.content") or ""),
                confidence=float(row.get("f.confidence") or 0.0),
                observed_at=str(row.get("f.observed_at") or ""),
                source_memory_id=str(row.get("f.source_memory_id") or ""),
            )
            for row in fact_rows
            if row.get("f.id") and row.get("f.content")
        ]
        return (
            entities,
            facts,
            {
                memory_id: tuple(sorted(entity_ids))
                for memory_id, entity_ids in mentions_by_memory_sets.items()
            },
        )

    def _active_community_ids(self, user_identifier: str) -> set[str]:
        try:
            rows = self._records(
                self._query(
                    "MATCH (c:Community) "
                    f'WHERE c.user_identifier = "{quote(user_identifier)}" '
                    'AND c.status = "active" RETURN c.id',
                    operation="community.active_ids",
                )
            )
        except Exception as exc:
            if "Unknown label: Community" not in str(exc):
                raise
            return set()
        return {str(row.get("c.id")) for row in rows if row.get("c.id")}

    def _replace_community_graph(
        self,
        user_identifier: str,
        projections: list[CommunityProjection],
    ) -> None:
        existing_ids = self._active_community_ids(user_identifier)
        timestamp = self._now_iso()
        queries = [
            f'MATCH (c:Community) WHERE c.id = "{quote(community_id)}" '
            f'AND c.user_identifier = "{quote(user_identifier)}" '
            f'SET c.status = "stale", c.updated_at = "{quote(timestamp)}"'
            for community_id in sorted(existing_ids)
        ]
        for projection in projections:
            if projection.id in existing_ids:
                queries.append(
                    f'MATCH (c:Community) WHERE c.id = "{quote(projection.id)}" '
                    f'AND c.user_identifier = "{quote(user_identifier)}" '
                    f'SET c.vector_id = {self._community_vector_id(user_identifier, projection.id)}, '
                    f'c.content = "{quote(projection.content)}", '
                    f'c.member_ids_json = "{quote(self._json_dumps(list(projection.member_ids)))}", '
                    f'c.source_memory_ids_json = "{quote(self._json_dumps(list(projection.source_memory_ids)))}", '
                    f'c.fact_ids_json = "{quote(self._json_dumps(list(projection.fact_ids)))}", '
                    f'c.confidence = {projection.confidence:.8f}, c.level = {projection.level}, '
                    f'c.parent_id = "{quote(projection.parent_id)}", '
                    f'c.edge_weight = {projection.edge_weight:.8f}, '
                    f'c.updated_at = "{quote(timestamp)}", c.status = "active"'
                )
                continue
            member_vars = [cypher_var(member_id) for member_id in projection.member_ids]
            community_var = cypher_var(projection.id)
            match_nodes = ", ".join(
                f"({variable}:Entity)" for variable in member_vars
            )
            where_terms = " AND ".join(
                f'{variable}.id = "{quote(member_id)}"'
                for variable, member_id in zip(
                    member_vars, projection.member_ids, strict=True
                )
            )
            node = (
                f'({community_var}:Community {{id: "{quote(projection.id)}", '
                f'vector_id: {self._community_vector_id(user_identifier, projection.id)}, '
                f'user_identifier: "{quote(user_identifier)}", content: "{quote(projection.content)}", '
                f'member_ids_json: "{quote(self._json_dumps(list(projection.member_ids)))}", '
                f'source_memory_ids_json: "{quote(self._json_dumps(list(projection.source_memory_ids)))}", '
                f'fact_ids_json: "{quote(self._json_dumps(list(projection.fact_ids)))}", '
                f'confidence: {projection.confidence:.8f}, level: {projection.level}, '
                f'parent_id: "{quote(projection.parent_id)}", edge_weight: {projection.edge_weight:.8f}, '
                f'created_at: "{quote(timestamp)}", updated_at: "{quote(timestamp)}", status: "active"}})'
            )
            edges = [
                f"({variable})-[:IN_COMMUNITY]->({community_var})"
                for variable in member_vars
            ]
            queries.append(
                f"MATCH {match_nodes} WHERE {where_terms} CREATE "
                + ", ".join([node, *edges])
            )
        self._write_many(queries)

    def _canonical_sparse_documents(self) -> list[SparseDocument]:
        documents: list[SparseDocument] = []
        memory_rows = self._sparse_rebuild_rows(
            "Memory",
            "MATCH (m:Memory) WHERE m.status = \"active\" "
            "RETURN m.id, m.user_identifier, m.kind, m.content, m.source, m.session_id, "
            "m.created_at, m.expires_at",
            "sparse.rebuild.memory",
        )
        for row in memory_rows:
            source_id = str(row.get("m.id") or "")
            user_identifier = str(row.get("m.user_identifier") or "")
            kind = self._sparse_kind(str(row.get("m.kind") or "memory"))
            content = str(row.get("m.content") or "")
            if not source_id or not user_identifier or not content:
                continue
            documents.append(
                SparseDocument(
                    doc_key=self._sparse_doc_key(user_identifier, kind, source_id),
                    user_identifier=user_identifier,
                    source_id=source_id,
                    kind=kind,
                    content=content,
                    source=str(row.get("m.source") or ""),
                    session_id=str(row.get("m.session_id") or ""),
                    created_at=str(row.get("m.created_at") or ""),
                    expires_at=str(row.get("m.expires_at") or ""),
                )
            )
        for label, variable, kind, operation in (
            ("Entity", "e", "entity", "sparse.rebuild.entity"),
            ("Fact", "f", "fact", "sparse.rebuild.fact"),
            ("Community", "c", "community", "sparse.rebuild.community"),
        ):
            rows = self._sparse_rebuild_rows(
                label,
                f'MATCH ({variable}:{label}) WHERE {variable}.status = "active" '
                f"RETURN {variable}.id, {variable}.user_identifier, {variable}.content, "
                f"{variable}.source, {variable}.session_id, "
                f"{variable}.observed_at, {variable}.created_at, {variable}.expires_at",
                operation,
            )
            for row in rows:
                source_id = str(row.get(f"{variable}.id") or "")
                user_identifier = str(row.get(f"{variable}.user_identifier") or "")
                content = str(row.get(f"{variable}.content") or "")
                if not source_id or not user_identifier or not content:
                    continue
                created_at = str(
                    row.get(f"{variable}.observed_at")
                    or row.get(f"{variable}.created_at")
                    or ""
                )
                documents.append(
                    SparseDocument(
                        doc_key=self._sparse_doc_key(user_identifier, kind, source_id),
                        user_identifier=user_identifier,
                        source_id=source_id,
                        kind=kind,
                        content=content,
                        source=str(row.get(f"{variable}.source") or ""),
                        session_id=str(row.get(f"{variable}.session_id") or ""),
                        created_at=created_at,
                        expires_at=str(row.get(f"{variable}.expires_at") or ""),
                    )
                )
        return documents

    def _canonical_vector_records(
        self,
        user_identifier: str,
    ) -> dict[str, list[tuple[str, str]]]:
        records: dict[str, list[tuple[str, str]]] = {}
        for kind, label, variable, status, text_property in (
            ("memory", "Memory", "m", "active", "content"),
            ("document", "Chunk", "c", "active", "text"),
            ("entity", "Entity", "e", "active", "content"),
            ("fact", "Fact", "f", "active", "content"),
            ("community", "Community", "c", "active", "content"),
        ):
            rows = self._sparse_rebuild_rows(
                label,
                f"MATCH ({variable}:{label}) "
                f'WHERE {variable}.user_identifier = "{quote(user_identifier)}" '
                f'AND {variable}.status = "{status}" '
                f"RETURN {variable}.id, {variable}.{text_property}",
                f"vector.rebuild.{kind}",
            )
            records[kind] = [
                (
                    str(row[f"{variable}.id"]),
                    str(row[f"{variable}.{text_property}"]),
                )
                for row in rows
                if row.get(f"{variable}.id")
                and row.get(f"{variable}.{text_property}")
            ]
        return records

    def _sparse_rebuild_rows(
        self,
        label: str,
        query: str,
        operation: str,
    ) -> list[dict[str, Any]]:
        try:
            return self._records(self._query(query, operation=operation))
        except Exception as exc:
            if f"Unknown label: {label}" not in str(exc):
                raise
            return []

    def _unique_projection_entities(
        self,
        *,
        user_identifier: str,
        projections: list[TemporalProjection],
    ) -> list[EntityProjection]:
        by_id: dict[str, EntityProjection] = {}
        for projection in projections:
            for entity in projection.entities:
                previous = by_id.get(entity.id)
                if previous is None or entity.confidence > previous.confidence:
                    by_id[entity.id] = entity
        existing = self._existing_entity_ids(user_identifier, list(by_id))
        return [entity for entity_id, entity in by_id.items() if entity_id not in existing]

    def _existing_entity_ids(self, user_identifier: str, entity_ids: list[str]) -> set[str]:
        if not entity_ids:
            return set()
        conditions = " OR ".join(f'e.id = "{quote(entity_id)}"' for entity_id in entity_ids)
        try:
            rows = self._records(
                self._query(
                    "MATCH (e:Entity) "
                    f'WHERE e.user_identifier = "{quote(user_identifier)}" AND ({conditions}) '
                    "RETURN e.id",
                    operation="entity.exists_batch",
                )
            )
        except Exception as exc:
            if "Unknown label: Entity" not in str(exc):
                raise
            return set()
        return {str(row.get("e.id") or "") for row in rows if row.get("e.id")}

    @classmethod
    def _projection_edge_literals(cls, edges: tuple[EdgeProjection, ...]) -> list[str]:
        literals: list[str] = []
        for edge in edges:
            source_var = cypher_var(edge.source_id)
            target_var = cypher_var(edge.target_id)
            properties = {"id": edge.id, **edge.properties}
            property_text = ", ".join(
                f'{cypher_var(name)}: {cls._cypher_value(value)}'
                for name, value in properties.items()
            )
            literals.append(
                f"({source_var})-[:{edge.kind} {{{property_text}}}]->({target_var})"
            )
        return literals

    @staticmethod
    def _cypher_value(value: object) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return str(value)
        return f'"{quote(str(value))}"'

    def _process_text_for_storage(
        self,
        text: str,
        metadata: dict[str, object] | None,
    ) -> tuple[str, dict[str, object]]:
        return self._process_texts_for_storage([(text, dict(metadata or {}))])[0]

    def _process_texts_for_storage(
        self,
        rows: list[tuple[str, dict[str, object]]],
    ) -> list[tuple[str, dict[str, object]]]:
        if not rows:
            return []
        redacted_rows = [self._redact_for_storage(text, metadata) for text, metadata in rows]
        texts = [text for text, _ in redacted_rows]
        process_many = getattr(self.entity_processor, "process_many", None)
        processed = (
            process_many(texts)
            if callable(process_many)
            else [self.entity_processor.process(text) for text in texts]
        )
        if not isinstance(processed, list) or len(processed) != len(rows):
            count = len(processed) if isinstance(processed, list) else 0
            raise RuntimeError(f"entity processor returned {count} results for {len(rows)} inputs")
        if not all(isinstance(item, ProcessedText) for item in processed):
            raise RuntimeError("entity processor returned an invalid result")
        return [
            self._merge_entity_metadata(item, metadata)
            for item, (_, metadata) in zip(processed, redacted_rows, strict=True)
        ]

    def _redact_for_storage(
        self,
        text: str,
        metadata: dict[str, object],
    ) -> tuple[str, dict[str, object]]:
        clean_metadata = dict(metadata or {})
        redacted = self.redactor.redact(text)
        if redacted.metadata:
            clean_metadata.update(redacted.metadata)
        return redacted.text, clean_metadata

    def _merge_entity_metadata(
        self,
        processed: ProcessedText,
        metadata: dict[str, object],
    ) -> tuple[str, dict[str, object]]:
        clean_metadata = dict(metadata)
        if processed.metadata:
            clean_metadata.update(processed.metadata)
        else:
            for key in getattr(self.entity_processor, "metadata_keys", ()):
                clean_metadata.pop(str(key), None)
        return processed.text, clean_metadata

    def _row_search_text(self, row: dict[str, Any], *, text_key: str, metadata_key: str) -> str:
        text = str(row.get(text_key, ""))
        metadata = self._json_loads(row.get(metadata_key), {})
        if isinstance(metadata, dict):
            extra = entity_metadata_search_text(metadata)
            if extra:
                return f"{text}\n{extra}"
        return text

    def _embed_many(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        with self._span(
            "embed",
            {"count": len(texts), "dimensions": self.dimensions, "operation": "batch"},
        ):
            embed_documents = getattr(self.embedder, "embed_documents", None)
            if callable(embed_documents):
                return embed_documents(texts)
            embed_many = getattr(self.embedder, "embed_many", None)
            if callable(embed_many):
                return embed_many(texts)
            return [self.embedder.embed(text) for text in texts]

    def _embed_text(self, text: str, *, operation: str) -> list[float]:
        with self._span(
            "embed",
            {"count": 1, "dimensions": self.dimensions, "operation": operation},
        ):
            if operation in {"memory.search", "document.search"}:
                embed_query = getattr(self.embedder, "embed_query", None)
                if callable(embed_query):
                    return embed_query(text)
            else:
                embed_documents = getattr(self.embedder, "embed_documents", None)
                if callable(embed_documents):
                    return embed_documents([text])[0]
            return self.embedder.embed(text)

    def _batch_payload_key(self, payload: dict[str, object]) -> tuple[object, ...]:
        return (
            payload.get("session_id", ""),
            payload.get("role", ""),
            payload.get("content", ""),
            payload.get("source", ""),
            self._json_dumps(payload.get("tags") or []),
            self._json_dumps(payload.get("metadata") or {}),
            payload.get("expires_at", ""),
        )

    def _memory_matches_payload(
        self,
        item: MemoryItem,
        payload: dict[str, object],
    ) -> bool:
        return self._batch_payload_key(payload) == (
            item.session_id,
            item.role,
            item.content,
            item.source,
            self._json_dumps(item.tags),
            self._json_dumps(item.metadata),
            item.expires_at,
        )

    def _ensure_graph_loaded(self) -> None:
        try:
            loaded_graphs = self.client.list_loaded_graphs()
        except Exception:
            loaded_graphs = []
        if self.graph not in loaded_graphs:
            try:
                self.client.load_graph(self.graph, raise_if_loaded=False)
            except Exception:
                try:
                    self.client.create_graph(self.graph)
                except Exception:
                    pass
        self.client.set_graph(self.graph)

    def _ensure_vector_index(self, name: str) -> None:
        ensured = getattr(self, "_ensured_vector_indexes", None)
        if ensured is None:
            ensured = set()
            self._ensured_vector_indexes = ensured
        if name in ensured:
            return
        try:
            self._query(
                f"CREATE VECTOR INDEX {name} WITH DIMENSION {self.dimensions} METRIC COSINE",
                operation="vector_index.ensure",
            )
        except Exception:
            pass
        rows = self._records(
            self._query("SHOW VECTOR INDEXES", operation="vector_index.verify")
        )
        if not rows:
            ensured.add(name)
            return
        matching = [row for row in rows if str(row.get("name") or "") == name]
        if not matching:
            raise RuntimeError(f"vector index {name} was not created")
        actual = int(matching[0].get("dimension") or 0)
        if actual != self.dimensions:
            raise RuntimeError(
                f"vector index {name} dimension mismatch: "
                f"expected {self.dimensions}, found {actual}"
            )
        ensured.add(name)

    @staticmethod
    def _tenant_vector_index(base_name: str, user_identifier: str) -> str:
        digest = hashlib.blake2b(
            user_identifier.encode("utf-8"), digest_size=8
        ).hexdigest()
        return cypher_var(f"{base_name}_tenant_{digest}")

    def _ensure_tenant_vector_index(
        self,
        base_name: str,
        user_identifier: str,
    ) -> str:
        name = self._tenant_vector_index(base_name, user_identifier)
        self._ensure_vector_index(name)
        return name

    def _ensure_user(self, user_identifier: str) -> None:
        try:
            rows = self._records(
                self._query(
                    f'MATCH (u:User) WHERE u.identifier = "{quote(user_identifier)}" '
                    "RETURN u.identifier",
                    operation="user.ensure",
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

    def _span(self, name: str, attributes: dict[str, object] | None = None) -> Any:
        return self.observer.span(name, attributes or {})

    def _audit(
        self,
        *,
        operation: str,
        user_identifier: str,
        resource_type: str,
        resource_id: str,
        success: bool = True,
        details: dict[str, object] | None = None,
    ) -> None:
        self.audit_sink.record(
            audit_event(
                {
                    "operation": operation,
                    "user_identifier": user_identifier,
                    "resource_type": resource_type,
                    "resource_id": resource_id,
                    "success": success,
                    "details": details or {},
                }
            )
        )

    def _query(self, query: str, *, operation: str) -> Any:
        statement = query.lstrip().split(None, 1)[0].upper() if query.strip() else ""
        with self._span(
            "turingdb.query",
            {"operation": operation, "statement": statement, "graph": self.graph},
        ):
            return self.client.query(query)

    def _write(self, query: str) -> None:
        with self._span("turingdb.write_transaction", {"graph": self.graph}):
            self.client.new_change()
            try:
                self._query(query, operation="write")
                self._query("CHANGE SUBMIT", operation="write.submit")
            finally:
                self.client.checkout()

    def _write_many(self, queries: list[str]) -> None:
        if not queries:
            return
        with self._span(
            "turingdb.write_transaction",
            {"graph": self.graph, "statement_count": len(queries)},
        ):
            self.client.new_change()
            try:
                for query in queries:
                    self._query(query, operation="write")
                self._query("CHANGE SUBMIT", operation="write.submit")
            finally:
                self.client.checkout()

    def _load_vectors(self, index_name: str, rows: list[tuple[int, list[float]]], stem: str) -> None:
        if not rows:
            return
        self._ensure_vector_index(index_name)
        with self._span(
            "vector.load",
            {"index": index_name, "rows": len(rows), "stem": stem, "dimensions": self.dimensions},
        ):
            filename = f"{cypher_var(stem)}_{int(time.time() * 1000)}.csv"
            path = self.data_dir / filename
            with path.open("w", encoding="utf-8", newline="\n") as handle:
                for vid, vec in rows:
                    handle.write(str(vid))
                    handle.write(",")
                    handle.write(",".join(f"{value:.8f}" for value in vec))
                    handle.write("\n")
            self._query(f'LOAD VECTOR FROM "{filename}" IN {index_name}', operation="vector.load")

    def _chunk_context(self, vector: int) -> list[dict[str, object]]:
        if vector <= 0:
            return []
        rows = self._records(
            self._query(
                "MATCH (c:Chunk)-[:NEXT_CHUNK]->(n:Chunk) "
                f'WHERE c.vector_id = {vector} AND c.status = "active" AND n.status = "active" '
                "RETURN n.chunk_id, n.locator, n.text",
                operation="document.chunk_context",
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

    def _memory_from_row(self, row: dict[str, Any], *, score: float = 1.0) -> MemoryItem:
        tags = self._json_loads(row.get("m.tags_json"), [])
        metadata = self._json_loads(row.get("m.metadata_json"), {})
        created_at = str(row.get("m.created_at") or "")
        return MemoryItem(
            id=str(row.get("m.id", "")),
            user_identifier=str(row.get("m.user_identifier", "")),
            kind=str(row.get("m.kind", "")),
            content=str(row.get("m.content", "")),
            session_id=str(row.get("m.session_id", "")),
            role=str(row.get("m.role", "")),
            score=score,
            created_at=created_at,
            updated_at=str(row.get("m.updated_at") or created_at),
            expires_at=str(row.get("m.expires_at") or ""),
            source=str(row.get("m.source", "")),
            tags=tags if isinstance(tags, list) else [],
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    def _row_is_expired(self, row: dict[str, Any], key: str) -> bool:
        return self._is_expired(str(row.get(key) or ""))

    def _memory_matches_filters(
        self,
        item: MemoryItem,
        *,
        session_id: str = "",
        memory_types: list[str] | None = None,
        source: str = "",
        tags: list[str] | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
    ) -> bool:
        allowed = set(memory_types or [])
        required_tags = set(self._clean_tags(tags))
        if session_id and item.session_id != session_id:
            return False
        if allowed and item.kind not in allowed:
            return False
        if source and item.source != source:
            return False
        if required_tags and not required_tags <= set(item.tags):
            return False
        if not self._timestamp_in_range(
            item.created_at,
            after=created_after,
            before=created_before,
        ):
            return False
        return self._timestamp_in_range(
            item.updated_at,
            after=updated_after,
            before=updated_before,
        )

    def _row_matches_metadata_filters(
        self,
        row: dict[str, Any],
        *,
        prefix: str,
        source: str = "",
        required_tags: set[str] | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
    ) -> bool:
        if source and str(row.get(f"{prefix}.source", "")) != source:
            return False
        tags = self._json_loads(row.get(f"{prefix}.tags_json"), [])
        if required_tags and not required_tags <= set(tags if isinstance(tags, list) else []):
            return False
        if not self._timestamp_in_range(
            str(row.get(f"{prefix}.created_at") or ""),
            after=created_after,
            before=created_before,
        ):
            return False
        return self._timestamp_in_range(
            str(row.get(f"{prefix}.updated_at") or ""),
            after=updated_after,
            before=updated_before,
        )

    def _active_memory_rows(self, user_identifier: str) -> list[dict[str, Any]]:
        try:
            return self._records(
                self._query(
                    f'MATCH (m:Memory) WHERE m.user_identifier = "{quote(user_identifier)}" '
                    'AND m.status = "active" '
                    "RETURN m.id, m.user_identifier, m.kind, m.content, m.session_id, m.role, "
                    "m.created_at, m.updated_at, m.expires_at, m.source, m.tags_json, m.metadata_json",
                    operation="memory.active_rows",
                )
            )
        except Exception as exc:
            if "Unknown label: Memory" not in str(exc):
                raise
            return []

    def _active_chunk_rows(self, user_identifier: str, *, document_id: str = "") -> list[dict[str, Any]]:
        document_filter = ""
        if document_id:
            document_filter = f' AND c.document_id = "{quote(document_id)}"'
        try:
            return self._records(
                self._query(
                    f'MATCH (c:Chunk) WHERE c.user_identifier = "{quote(user_identifier)}" '
                    f'AND c.status = "active"{document_filter} '
                    "RETURN c.chunk_id, c.document_id, c.title, c.locator, c.text, c.vector_id, "
                    "c.created_at, c.updated_at, c.expires_at, c.source, c.tags_json, c.metadata_json",
                    operation="document.active_chunk_rows",
                )
            )
        except Exception as exc:
            if "Unknown label: Chunk" not in str(exc):
                raise
            return []

    def _document_from_row(self, row: dict[str, Any]) -> IngestedDocument:
        tags = self._json_loads(row.get("d.tags_json"), [])
        metadata = self._json_loads(row.get("d.metadata_json"), {})
        created_at = str(row.get("d.created_at") or "")
        return IngestedDocument(
            document_id=str(row.get("d.id", "")),
            title=str(row.get("d.title", "")),
            chunk_count=self._int_value(row.get("d.chunk_count")),
            user_identifier=str(row.get("d.user_identifier", "")),
            created_at=created_at,
            updated_at=str(row.get("d.updated_at") or created_at),
            expires_at=str(row.get("d.expires_at") or ""),
            source=str(row.get("d.source", "")),
            tags=tags if isinstance(tags, list) else [],
            metadata=metadata if isinstance(metadata, dict) else {},
            text_hash=str(row.get("d.text_hash", "")),
            chunk_chars=self._int_value(row.get("d.chunk_chars")),
        )

    def _rerank_memory(self, query: str, seeds: list[MemoryItem]) -> list[MemoryItem]:
        fused = any(
            item.score_details is not None and "fusion_score" in item.score_details
            for item in seeds
        )
        if len(seeds) < 2:
            return self._annotate_memory_rerank(
                seeds,
                [(item, None) for item in seeds],
                status="not_needed",
                model=str(getattr(self.reranker, "model", "")),
                fused=fused,
            )
        if self.reranker is None:
            return self._annotate_memory_rerank(
                seeds,
                [(item, None) for item in seeds],
                status="disabled",
                model="",
                fused=fused,
            )
        candidates = seeds[: self.rerank_candidate_limit]
        tail = seeds[self.rerank_candidate_limit :]
        documents = [self._memory_rerank_document(item) for item in candidates]
        status = "applied"
        model = str(getattr(self.reranker, "model", ""))
        try:
            with self._span("rerank", {"kind": "memory", "count": len(candidates)}):
                rerank_with_status = getattr(self.reranker, "rerank_with_status", None)
                if callable(rerank_with_status):
                    result = rerank_with_status(query, documents)
                    if not isinstance(result, RerankResult):
                        raise ValueError("reranker returned an invalid status result")
                    scored = result.scores
                    status = result.status
                    model = result.model
                else:
                    scored = self.reranker.rerank(query, documents)
        except Exception:
            scored = []
            status = "provider_error"
        ordered = (
            apply_rerank_guard(
                candidates,
                scored,
                threshold=self.rerank_threshold,
                blend=self.rerank_blend,
                seed_scores=[item.score for item in candidates],
                preserve_seed_margin=self.rerank_preserve_seed_margin,
            )
            if status == "applied"
            else [(item, None) for item in candidates]
        )
        reranked = self._annotate_memory_rerank(
            candidates,
            ordered,
            status=status,
            model=model,
            fused=fused,
        )
        if tail:
            reranked.extend(
                self._annotate_memory_rerank(
                    tail,
                    [(item, None) for item in tail],
                    status="candidate_limit",
                    model=model,
                    fused=fused,
                )
            )
        return reranked

    def _annotate_memory_rerank(
        self,
        seeds: list[MemoryItem],
        ordered: list[tuple[MemoryItem, float | None]],
        *,
        status: str,
        model: str,
        fused: bool,
    ) -> list[MemoryItem]:
        del seeds
        return [
            MemoryItem(
                id=item.id,
                user_identifier=item.user_identifier,
                kind=item.kind,
                content=item.content,
                session_id=item.session_id,
                role=item.role,
                score=float(score if score is not None else item.score),
                created_at=item.created_at,
                updated_at=item.updated_at,
                expires_at=item.expires_at,
                source=item.source,
                tags=item.tags,
                metadata=item.metadata,
                score_details=(
                    self._fused_rerank_score_details(
                        item.score_details,
                        fusion_score=item.score,
                        rerank_score=score,
                        status=status,
                        model=model,
                    )
                    if fused
                    else self._reranked_score_details(item.score_details, item.score, score)
                ),
            )
            for item, score in ordered
        ]

    @staticmethod
    def _memory_rerank_document(item: MemoryItem) -> str:
        provenance: dict[str, object] = {
            "memory_id": item.id,
            "kind": item.kind,
            "source": item.source,
            "session_id": item.session_id,
            "role": item.role,
            "created_at": item.created_at,
            "updated_at": item.updated_at,
        }
        for key in ("path", "locator", "conversation_id", "document_id"):
            if key in item.metadata:
                provenance[key] = item.metadata[key]
        if item.score_details is not None and "evidence_ids" in item.score_details:
            provenance["evidence_ids"] = item.score_details["evidence_ids"]
        return assemble_rerank_document(content=item.content, provenance=provenance)

    @staticmethod
    def _fused_rerank_score_details(
        score_details: dict[str, object] | None,
        *,
        fusion_score: float,
        rerank_score: float | None,
        status: str,
        model: str,
    ) -> dict[str, object]:
        details = dict(score_details or {})
        details.setdefault("fusion_score", fusion_score)
        details["rerank_status"] = status
        details["rerank_model"] = model
        if rerank_score is not None:
            details["rerank_score"] = rerank_score
        details["final_score"] = rerank_score if rerank_score is not None else fusion_score
        return details

    def _rerank_documents(self, query: str, seeds: list[DocumentHit]) -> list[DocumentHit]:
        if len(seeds) < 2 or self.reranker is None:
            return seeds
        with self._span("rerank", {"kind": "document", "count": len(seeds)}):
            scored = self.reranker.rerank(query, [item.text for item in seeds])
        ordered = apply_rerank_guard(
            seeds,
            scored,
            threshold=self.rerank_threshold,
            blend=self.rerank_blend,
            seed_scores=[item.score for item in seeds],
            preserve_seed_margin=self.rerank_preserve_seed_margin,
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
                expires_at=item.expires_at,
                source=item.source,
                tags=item.tags,
                metadata=item.metadata,
                score_details=self._reranked_score_details(item.score_details, item.score, score),
            )
            for item, score in ordered
        ]

    @staticmethod
    def _reranked_score_details(
        score_details: dict[str, object] | None,
        semantic_score: float,
        rerank_score: float | None,
    ) -> dict[str, object] | None:
        if score_details is None:
            return None
        threshold = float(score_details.get("threshold") or 0.0)
        final_score = float(rerank_score if rerank_score is not None else semantic_score)
        return build_score_details(
            semantic_score=float(score_details.get("semantic_score") or semantic_score),
            lexical_score=(
                float(score_details["lexical_score"]) if "lexical_score" in score_details else None
            ),
            threshold=threshold,
            final_score=final_score,
            rerank_score=rerank_score,
        )

    def _chunk_document_text(self, text: str, *, chunk_chars: int) -> list[str]:
        attributes: dict[str, object] = {
            "chunk_chars": chunk_chars,
            "text_chars": len(text),
            "chunk_count": 0,
        }
        with self._span("document.chunk", attributes):
            chunks = self._chunk_text(text, chunk_chars=chunk_chars)
            attributes["chunk_count"] = len(chunks)
            return chunks

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
        return min(limit, 200)

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _is_expired(expires_at: str) -> bool:
        if not expires_at.strip():
            return False
        try:
            expires = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except ValueError:
            return False
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return expires <= datetime.now(UTC)

    @classmethod
    def _parse_filter_datetime(cls, value: str, field_name: str) -> datetime | None:
        if not value.strip():
            return None
        parsed = cls._parse_datetime(value)
        if parsed is None:
            raise ValueError(f"{field_name} must be an ISO-8601 timestamp")
        return parsed

    @classmethod
    def _timestamp_in_range(
        cls,
        value: str,
        *,
        after: datetime | None,
        before: datetime | None,
    ) -> bool:
        if after is None and before is None:
            return True
        parsed = cls._parse_datetime(value)
        if parsed is None:
            return False
        if after is not None and parsed < after:
            return False
        return before is None or parsed <= before

    @staticmethod
    def _parse_datetime(value: str) -> datetime | None:
        if not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    @staticmethod
    def _json_dumps(value: object) -> str:
        return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str)

    @staticmethod
    def _json_loads(value: object, fallback: object) -> object:
        if not isinstance(value, str) or not value:
            return fallback
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback

    @staticmethod
    def _int_value(value: object) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _clean_tags(tags: list[str] | None) -> list[str]:
        clean: list[str] = []
        seen: set[str] = set()
        for tag in tags or []:
            value = str(tag).strip()
            if not value:
                continue
            key = value.casefold()
            if key in seen:
                continue
            seen.add(key)
            clean.append(value[:80])
        return clean[:20]

    @staticmethod
    def _memory_vector_id(user_identifier: str, memory_id: str) -> int:
        return vector_id("memory", f"{user_identifier}:{memory_id}")

    @staticmethod
    def _entity_vector_id(user_identifier: str, entity_id: str) -> int:
        return vector_id("entity", f"{user_identifier}:{entity_id}")

    @staticmethod
    def _fact_vector_id(user_identifier: str, fact_id: str) -> int:
        return vector_id("fact", f"{user_identifier}:{fact_id}")

    @staticmethod
    def _community_vector_id(user_identifier: str, community_id: str) -> int:
        return vector_id("community", f"{user_identifier}:{community_id}")

    @staticmethod
    def _document_vector_id(user_identifier: str, chunk_id: str) -> int:
        return vector_id("chunk", f"{user_identifier}:{chunk_id}")

    @staticmethod
    def _document_text_hash(text: str) -> str:
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def _require_user(user_identifier: str) -> None:
        if not user_identifier.strip():
            raise ValueError("user_identifier is required")
