"""Init/bootstrap and low-level query-write infra mixin for TuringAgentMemory.

Split out of store.py (D-08/D-09, phase 01-01). Owns `__init__` (and therefore every
`self.<attr>` the other `store_<concern>.py` mixins read), plus the ArcadeDB
query/write/span/audit primitives every other mixin builds on (ported 04-04 from
TuringDB -- see `.planning/phases/04-arcadedb-direct-port/04-SPIKE-FINDINGS.md`).

D-08: `_write_many` is ONE managed `begin`/`command`/`commit-retry-N` transaction
(`ArcadeDBClient.run_in_transaction`), not TuringDB's per-batch submit-before-match
loop -- the session-header transaction model gives read-your-writes across every
`command` call scoped to that one session (spike-confirmed, not `sqlscript`'s
self-contained `LET` chaining).

MD-01: a document is committed as one unbounded `_write_many` transaction.
This mixin used to also validate and store a pair of TuringDB-era
transaction-size constructor knobs (see CHANGELOG.md's Removed section for
the retired names) that nothing ever consulted -- deleted rather than wired
into `_create_document`'s statement list, because splitting a document's
statements across multiple `_write_many` calls would open a partial-
document-visible-mid-ingest window (a concurrent reader could see a
`Document` row claiming a total chunk count with only some of its `Chunk`
rows committed) -- there is no document-level "searchable only once fully
committed" status guard in this model, only the transaction boundary itself.
Building one was judged a larger, riskier change than documenting
unbounded-per-document as the accepted design for this milestone.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from turing_agentmemory_mcp.arcadedb_client import ArcadeDBClient
from turing_agentmemory_mcp.arcadedb_schema import bootstrap as schema_bootstrap
from turing_agentmemory_mcp.arcadedb_schema import versioned_vector_index
from turing_agentmemory_mcp.community_detection import NativeLeidenDetector
from turing_agentmemory_mcp.embeddings import Embedder, OpenAICompatibleEmbedder
from turing_agentmemory_mcp.entity_extraction import EntityProcessor, entity_processor_from_env
from turing_agentmemory_mcp.governance import (
    AuditSink,
    Redactor,
    audit_event,
    audit_sink_from_env,
    redactor_from_env,
)
from turing_agentmemory_mcp.memory_extraction import (
    MEMORY_EXTRACTION_SCHEMA_VERSION,
    MemoryExtractor,
)
from turing_agentmemory_mcp.observability import (
    RuntimeSignals,
    SpanRecorder,
    span_recorder_from_env,
)
from turing_agentmemory_mcp.provider_config import provider_env
from turing_agentmemory_mcp.rerank import OpenAICompatibleReranker
from turing_agentmemory_mcp.search_controls import validate_fusion_weights
from turing_agentmemory_mcp.sparse_index import SparseIndex


class _StoreCore:
    def __init__(
        self,
        client: ArcadeDBClient,
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
        self._schema_bootstrapped = False
        self._schema_version = 1  # D-07 versioned-index foundation; 04-08 bumps this.
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
                **{f"{channel}_weight": weight for channel, weight in self.fusion_weights.items()},
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
        self._ensure_schema()
        self._refresh_graph_readiness()

    def reconnect(self) -> bool:
        """D-10: reconnect is a reachability re-probe, not TuringDB's
        load-graph-after-restart step -- the public entry point external
        callers (benchmark/e2e harnesses) use after restarting the backend.
        """
        return self._refresh_graph_readiness()

    def runtime_status(self) -> dict[str, object]:
        self._refresh_graph_readiness()
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

    def _refresh_graph_readiness(self) -> bool:
        """D-10: the graph stage tracks a live probe, not a boot-time latch --
        `/health` calls this (via `runtime_status`) on every request, so an
        ArcadeDB outage surfaces immediately and a later successful probe
        flips it back to ready without any manual reconnect step."""
        ready = self.client.is_ready()
        self.runtime_signals.configure_stage("graph", ready=ready, identity={"graph": self.graph})
        return ready

    def _ensure_schema(self) -> None:
        """Idempotently bootstrap the full ArcadeDB schema (D-09, delegated to
        `arcadedb_schema.bootstrap`) once per process. Replaces the old
        per-index-name `CREATE VECTOR INDEX` DDL loop -- ArcadeDB uses one
        shared Type-level vector/lexical channel filtered by
        `user_identifier`, not a separate named index per tenant."""
        if self._schema_bootstrapped:
            return
        schema_bootstrap(self.client, dimensions=self.dimensions, version=self._schema_version)
        self._schema_bootstrapped = True

    def _ensure_vector_index(self, name: str) -> None:
        """Back-compat shim for unported mixins (Wave 4) that still call this
        by per-tenant index name -- delegates to the shared schema bootstrap
        instead of issuing an inline DDL string."""
        self._ensure_schema()

    @staticmethod
    def _tenant_vector_index(base_name: str, user_identifier: str) -> str:
        return versioned_vector_index(base_name, user_identifier, version=1)

    def _ensure_tenant_vector_index(
        self,
        base_name: str,
        user_identifier: str,
    ) -> str:
        name = self._tenant_vector_index(base_name, user_identifier)
        self._ensure_schema()
        return name

    def _ensure_user(self, user_identifier: str) -> None:
        rows = self._records(
            self._query(
                "SELECT identifier FROM User WHERE identifier = :identifier",
                operation="user.ensure",
                params={"identifier": user_identifier},
            )
        )
        if rows:
            return
        self._write(
            "CREATE VERTEX User SET identifier = :identifier, display = :identifier",
            params={"identifier": user_identifier},
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

    def _query(
        self, query: str, *, operation: str, params: dict[str, object] | None = None
    ) -> list[dict[str, Any]]:
        statement = query.lstrip().split(None, 1)[0].upper() if query.strip() else ""
        with self._span(
            "arcadedb.query",
            {"operation": operation, "statement": statement, "graph": self.graph},
        ):
            return self.client.query(query, params=params)

    def _write(self, query: str, *, params: dict[str, object] | None = None) -> None:
        with self._span("arcadedb.write_transaction", {"graph": self.graph}):
            self._run_write_batch([(query, params)])

    def _write_many(self, statements: list[tuple[str, dict[str, object] | None]]) -> None:
        if not statements:
            return
        with self._span(
            "arcadedb.write_batch",
            {"graph": self.graph, "statement_count": len(statements)},
        ):
            self._run_write_batch(statements)

    def _run_write_batch(self, statements: list[tuple[str, dict[str, object] | None]]) -> None:
        # D-08: one managed begin/command(s)/commit-retry-N transaction. The
        # session-header model gives read-your-writes across every `command`
        # call scoped to the same session (spike-confirmed) -- a later
        # statement in this same batch can find an earlier one's write by
        # ordinary property filter, not just a `sqlscript` `$var` reference.
        def _run(session_id: str) -> None:
            for statement, params in statements:
                self.client.command(statement, params=params, session_id=session_id)

        self.client.run_in_transaction(_run)

    @staticmethod
    def _records(rows: Any) -> list[dict[str, Any]]:
        def clean(value: Any) -> Any:
            if isinstance(value, float) and value != value:
                return None
            return value

        if not isinstance(rows, list):
            return []
        return [
            {str(key): clean(value) for key, value in row.items()}
            for row in rows
            if isinstance(row, dict)
        ]

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _json_dumps(value: object) -> str:
        return json.dumps(
            value, ensure_ascii=True, sort_keys=True, separators=(",", ":"), default=str
        )

    @staticmethod
    def _json_loads(value: object, fallback: object) -> object:
        if not isinstance(value, str) or not value:
            return fallback
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback

    @staticmethod
    def _require_user(user_identifier: str) -> None:
        if not user_identifier.strip():
            raise ValueError("user_identifier is required")
