"""Memory/document search + rerank pipeline mixin for TuringAgentMemory.

Split out of store.py (D-08/D-09, phase 01-02). `_rerank_documents`/
`_reranked_score_details` moved here (rather than store_documents.py) per the
RESEARCH.md sub-split note, to keep store_documents.py under the 600-LOC cap.

Ported to ArcadeDB (04-07, ARC-04/ARC-05): the non-fused dense seed channel
reads native HNSW (`vectorNeighbors`, D-03 over-fetch-then-filter) with no
legacy synthetic-integer join property; rows come back keyed by ArcadeDB's bare (unqualified)
property names (`"id"`, `"content"`, ...), matching `store_memory_read.py`'s
04-05 convention (retiring the Cypher `RETURN m.id` alias shape this module
used to consume). The fused path's seed-channel candidates now come entirely
from `store_evidence.py`'s ArcadeDB-native collectors -- `retrieval_fusion.py`'s
weighted RRF and `rerank.py`'s guard/blend below are UNCHANGED, only the
upstream candidate fetch moved.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from turing_agentmemory_mcp.hybrid import blend_hybrid_score, lexical_score
from turing_agentmemory_mcp.models import (
    DocumentHit,
    MemoryItem,
    RetrievalCandidate,
    RetrievalEvidence,
)
from turing_agentmemory_mcp.rerank import RerankResult, apply_rerank_guard, assemble_rerank_document
from turing_agentmemory_mcp.retrieval_fusion import diversify_fused, fuse_rankings
from turing_agentmemory_mcp.search_controls import (
    build_score_details,
    passes_threshold,
    validate_search_query,
    validate_threshold,
)
from turing_agentmemory_mcp.store_memory_queries import MEMORY_FIELDS
from turing_agentmemory_mcp.store_retrieval_queries import dense_search_statement

# The non-fused dense channel below feeds `dense_search_statement`'s rows
# straight into `_memory_from_row` with no second full-row fetch -- it must
# request every field that mixin reads, not just `id`/`distance` (Rule 1 bug:
# the row was previously missing content/kind/session_id/... whenever a
# memory was found via the dense channel, which is virtually always).
_MEMORY_DENSE_EXTRA_FIELDS = tuple(field for field in MEMORY_FIELDS if field != "id")


class _SearchMixin:
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
            embedding = self._embed_text(query, operation="memory.search")
            # D-03: adaptive over-fetch-then-filter default -- filtered ANN
            # k-underfills post-filter (spike-confirmed), matching
            # store_documents.py's search_documents precedent.
            statement, params = dense_search_statement(
                type_name="Memory",
                embedding=embedding,
                k=max(limit * 4, limit),
                user_identifier=user_identifier,
                extra_fields=_MEMORY_DENSE_EXTRA_FIELDS,
            )
            vector_rows = self._records(
                self._query(statement, operation="memory.vector_search", params=params)
            )
            allowed = set(memory_types or [])
            rows_by_id: dict[str, dict[str, Any]] = {}
            semantic_by_id: dict[str, float] = {}
            for row in vector_rows:
                if self._row_is_expired(row, "expires_at"):
                    continue
                memory_id = str(row.get("id", ""))
                if not memory_id:
                    continue
                # vectorNeighbors returns a cosine distance (0 = identical);
                # convert to a similarity-style score for blend_hybrid_score.
                semantic_score = max(0.0, 1.0 - float(row.get("distance") or 0.0))
                semantic_by_id[memory_id] = max(semantic_by_id.get(memory_id, 0.0), semantic_score)
                rows_by_id[memory_id] = row
            for row in self._active_memory_rows(user_identifier):
                memory_id = str(row.get("id", ""))
                if memory_id and memory_id not in rows_by_id:
                    rows_by_id[memory_id] = row

            seeds: list[MemoryItem] = []
            for memory_id, row in rows_by_id.items():
                if self._row_is_expired(row, "expires_at"):
                    continue
                kind = str(row.get("kind", ""))
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
                    self._row_search_text(row, text_key="content", metadata_key="metadata_json"),
                )
                final_score = blend_hybrid_score(
                    semantic_score=semantic_score, lexical_score=lexical
                )
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
            if self._row_is_expired(row, "expires_at"):
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
