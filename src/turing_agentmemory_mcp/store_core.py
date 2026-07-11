"""Init/bootstrap and low-level query-write infra mixin for TuringAgentMemory.

Split out of store.py (D-08/D-09, phase 01-01). Owns `__init__` (and therefore every
`self.<attr>` the other `store_<concern>.py` mixins read), plus the TuringDB
query/write/span/audit primitives every other mixin builds on.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from turingdb import TuringDB

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
from turing_agentmemory_mcp.ids import cypher_var, quote
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
        document_graph_batch_chunks: int = 250,
        document_graph_batch_bytes: int = 256 << 10,
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
        if document_graph_batch_chunks < 1:
            raise ValueError("document_graph_batch_chunks must be positive")
        if document_graph_batch_bytes < 1_024:
            raise ValueError("document_graph_batch_bytes must be at least 1024")
        self.document_graph_batch_chunks = document_graph_batch_chunks
        self.document_graph_batch_bytes = document_graph_batch_bytes
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

    def load_graph_after_restart(self) -> None:
        self.client.load_graph(self.graph, raise_if_loaded=False)
        self.client.set_graph(self.graph)

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
            "turingdb.write_batch",
            {"graph": self.graph, "statement_count": len(queries)},
        ):
            # Later chunk batches MATCH nodes created by earlier batches. TuringDB
            # only exposes those nodes after CHANGE SUBMIT, so each bounded batch
            # is its own transaction.
            for query in queries:
                self._write(query)

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
    def _now_iso() -> str:
        return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

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
    def _require_user(user_identifier: str) -> None:
        if not user_identifier.strip():
            raise ValueError("user_identifier is required")
