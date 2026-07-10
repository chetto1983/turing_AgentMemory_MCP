from __future__ import annotations

import json
import math
import os
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from starlette.responses import JSONResponse
from turingdb import TuringDB

from turing_agentmemory_mcp.community_detection import NativeLeidenDetector
from turing_agentmemory_mcp.document_processing import convert_document_to_markdown
from turing_agentmemory_mcp.entity_extraction import NoopEntityProcessor
from turing_agentmemory_mcp.memory_extraction import (
    MEMORY_EXTRACTION_SCHEMA_VERSION,
    HTTPMemoryExtractor,
)
from turing_agentmemory_mcp.provider_config import store_embedding_dimensions
from turing_agentmemory_mcp.search_controls import validate_fusion_weights
from turing_agentmemory_mcp.sparse_index import SparseIndex
from turing_agentmemory_mcp.store import TuringAgentMemory
from turing_agentmemory_mcp.warning_filters import suppress_fastmcp_authlib_warning


def auth_from_env() -> Any | None:
    tokens = _env_list("AGENTMEMORY_AUTH_TOKENS")
    single_token = os.environ.get("AGENTMEMORY_AUTH_TOKEN", "").strip()
    if single_token:
        tokens.insert(0, single_token)
    tokens = list(dict.fromkeys(token for token in tokens if token))
    if not tokens:
        return None

    suppress_fastmcp_authlib_warning()
    from fastmcp.server.auth import StaticTokenVerifier

    client_id = os.environ.get("AGENTMEMORY_AUTH_CLIENT_ID", "agentmemory-client")
    scopes = _env_list("AGENTMEMORY_AUTH_SCOPES")
    required_scopes = _env_list("AGENTMEMORY_AUTH_REQUIRED_SCOPES")
    token_data = {
        token: {
            "client_id": client_id,
            "scopes": scopes,
        }
        for token in tokens
    }
    return StaticTokenVerifier(tokens=token_data, required_scopes=required_scopes)


def _env_list(name: str) -> list[str]:
    value = os.environ.get(name, "")
    if not value.strip():
        return []
    normalized = value.replace(",", " ")
    return [item.strip() for item in normalized.split() if item.strip()]


def _env_bool(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean")


def _env_int(name: str, *, default: int, minimum: int = 0) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _env_float(name: str, *, default: float, minimum_exclusive: float = 0.0) -> float:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc
    if not math.isfinite(value) or value <= minimum_exclusive:
        raise ValueError(f"{name} must be a finite number greater than {minimum_exclusive}")
    return value


def _fusion_weights_from_env() -> dict[str, float] | None:
    raw = os.environ.get("AGENTMEMORY_FUSION_WEIGHTS", "").strip()
    if not raw:
        return None
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("AGENTMEMORY_FUSION_WEIGHTS must be valid JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError("AGENTMEMORY_FUSION_WEIGHTS must be a JSON object")
    return validate_fusion_weights(decoded)


def store_from_env() -> TuringAgentMemory:
    url = os.environ.get("TURINGDB_URL", "http://127.0.0.1:6666")
    token = os.environ.get("TURINGDB_AUTH_TOKEN") or None
    graph = os.environ.get("TURINGDB_GRAPH", "agent_memory")
    home = Path(os.environ.get("TURINGDB_HOME", "/turing"))
    dimensions = int(store_embedding_dimensions())
    index_prefix = graph.replace("-", "_")
    fusion_enabled = _env_bool("AGENTMEMORY_FUSION_ENABLED", default=False)
    sparse_path = Path(
        os.environ.get(
            "AGENTMEMORY_SPARSE_PATH",
            str(home / "data" / "agent-memory-fts.sqlite3"),
        )
    )
    memory_extractor = None
    entity_processor = None
    if fusion_enabled:
        schema = os.environ.get(
            "GLINER_MEMORY_SCHEMA", MEMORY_EXTRACTION_SCHEMA_VERSION
        ).strip()
        if schema != MEMORY_EXTRACTION_SCHEMA_VERSION:
            raise ValueError(
                f"GLINER_MEMORY_SCHEMA must be {MEMORY_EXTRACTION_SCHEMA_VERSION}"
            )
        memory_extractor = HTTPMemoryExtractor(
            base_url=os.environ.get(
                "GLINER_BASE_URL", "http://agentmemory-gliner:8080"
            ),
            model_name=os.environ.get("GLINER_MODEL", "fastino/gliner2-base-v1"),
            threshold=float(os.environ.get("GLINER_THRESHOLD", "0.5")),
            timeout_s=_env_float("GLINER_TIMEOUT_SECONDS", default=30.0),
        )
        entity_processor = NoopEntityProcessor()
    community_detector = NativeLeidenDetector(
        seed=_env_int("AGENTMEMORY_LEIDEN_SEED", default=42),
        resolution=_env_float("AGENTMEMORY_LEIDEN_RESOLUTION", default=1.0),
        randomness=_env_float("AGENTMEMORY_LEIDEN_RANDOMNESS", default=0.001),
        iterations=_env_int("AGENTMEMORY_LEIDEN_ITERATIONS", default=2, minimum=1),
        max_cluster_size=_env_int(
            "AGENTMEMORY_LEIDEN_MAX_CLUSTER_SIZE", default=100, minimum=1
        ),
    )
    client = TuringDB(type="json", host=url, token=token)
    store = TuringAgentMemory(
        client,
        turing_home=home,
        graph=graph,
        dimensions=dimensions,
        memory_index=os.environ.get(
            "TURINGDB_MEMORY_INDEX", f"{index_prefix}_episode_vectors_{dimensions}"
        ),
        document_index=os.environ.get(
            "TURINGDB_DOCUMENT_INDEX", f"{index_prefix}_document_vectors_{dimensions}"
        ),
        entity_index=os.environ.get(
            "TURINGDB_ENTITY_INDEX", f"{index_prefix}_entity_vectors_{dimensions}"
        ),
        fact_index=os.environ.get(
            "TURINGDB_FACT_INDEX", f"{index_prefix}_fact_vectors_{dimensions}"
        ),
        community_index=os.environ.get(
            "TURINGDB_COMMUNITY_INDEX", f"{index_prefix}_community_vectors_{dimensions}"
        ),
        entity_processor=entity_processor,
        memory_extractor=memory_extractor,
        sparse_index=SparseIndex(sparse_path) if fusion_enabled else None,
        fusion_enabled=fusion_enabled,
        fusion_weights=_fusion_weights_from_env(),
        community_detector=community_detector,
        community_rebuild_on_batch=_env_bool(
            "AGENTMEMORY_COMMUNITY_REBUILD_ON_BATCH", default=fusion_enabled
        ),
    )
    store.bootstrap()
    return store


def create_mcp_app(store: TuringAgentMemory | None = None) -> FastMCP:
    memory = store or store_from_env()

    def _tool_span(tool: str) -> Any:
        observer = getattr(memory, "observer", None)
        span = getattr(observer, "span", None)
        if callable(span):
            return span("mcp.tool", {"tool": tool})
        return nullcontext()

    app = FastMCP(
        "turing-agentmemory-mcp",
        instructions=(
            "Scoped memory and document retrieval backed by TuringDB. "
            "Always pass user_identifier from the caller identity."
        ),
        auth=auth_from_env(),
    )

    @app.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_request: Any) -> JSONResponse:
        runtime_status = getattr(memory, "runtime_status", None)
        runtime = runtime_status() if callable(runtime_status) else {"stages": {}}
        graph = runtime.get("stages", {}).get("graph", {}) if isinstance(runtime, dict) else {}
        ready = not graph or bool(graph.get("ready"))
        return JSONResponse(
            {"status": "ok" if ready else "degraded", "runtime": runtime},
            status_code=200 if ready else 503,
        )

    @app.tool()
    def memory_store_message(
        session_id: str,
        role: str,
        content: str,
        user_identifier: str = "default",
        memory_id: str | None = None,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str = "",
    ) -> dict[str, Any]:
        """Store a scoped conversation message in long-lived memory."""
        with _tool_span("memory_store_message"):
            return memory.store_message(
                user_identifier=user_identifier,
                session_id=session_id,
                role=role,
                content=content,
                memory_id=memory_id,
                source=source,
                tags=tags,
                metadata=metadata,
                expires_at=expires_at,
            ).to_dict()

    @app.tool()
    def memory_runtime_status() -> dict[str, object]:
        """Return content-free readiness, projection, and degradation status."""
        status = getattr(memory, "runtime_status", None)
        if not callable(status):
            return {"stages": {}, "projections": {}, "degraded_channel_counts": {}}
        return status()

    @app.tool()
    def memory_store_messages(
        messages: list[dict[str, object]],
        user_identifier: str = "default",
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str = "",
    ) -> list[dict[str, Any]]:
        """Store conversation messages in one duplicate-safe batch."""
        with _tool_span("memory_store_messages"):
            return [
                item.to_dict()
                for item in memory.store_messages(
                    user_identifier=user_identifier,
                    messages=messages,
                    source=source,
                    tags=tags,
                    metadata=metadata,
                    expires_at=expires_at,
                )
            ]

    @app.tool()
    def memory_get(
        memory_id: str,
        user_identifier: str = "default",
    ) -> dict[str, Any] | None:
        """Fetch one active scoped memory by id."""
        with _tool_span("memory_get"):
            item = memory.get_memory(user_identifier=user_identifier, memory_id=memory_id)
            return item.to_dict() if item is not None else None

    @app.tool()
    def memory_list(
        user_identifier: str = "default",
        limit: int = 25,
        session_id: str = "",
        memory_types: list[str] | None = None,
        source: str = "",
        tags: list[str] | None = None,
        created_after: str = "",
        created_before: str = "",
        updated_after: str = "",
        updated_before: str = "",
    ) -> list[dict[str, Any]]:
        """List active scoped memories with optional metadata and date filters."""
        with _tool_span("memory_list"):
            return [
                item.to_dict()
                for item in memory.list_memories(
                    user_identifier=user_identifier,
                    limit=limit,
                    session_id=session_id,
                    memory_types=memory_types,
                    source=source,
                    tags=tags,
                    created_after=created_after,
                    created_before=created_before,
                    updated_after=updated_after,
                    updated_before=updated_before,
                )
            ]

    @app.tool()
    def memory_update(
        memory_id: str,
        user_identifier: str = "default",
        content: str | None = None,
        kind: str | None = None,
        session_id: str | None = None,
        role: str | None = None,
        source: str | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Update active scoped memory content or metadata."""
        with _tool_span("memory_update"):
            return memory.update_memory(
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
            ).to_dict()

    @app.tool()
    def memory_delete(
        memory_id: str,
        user_identifier: str = "default",
    ) -> dict[str, object]:
        """Soft-delete one scoped memory so it is hidden from retrieval."""
        with _tool_span("memory_delete"):
            return memory.delete_memory(user_identifier=user_identifier, memory_id=memory_id)

    @app.tool()
    def memory_search(
        query: str,
        user_identifier: str = "default",
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
    ) -> list[dict[str, Any]]:
        """Search scoped memory with fused dense, BM25, entity, graph, and rerank signals."""
        with _tool_span("memory_search"):
            return [
                item.to_dict()
                for item in memory.search_memory(
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
                    explain=explain,
                )
            ]

    @app.tool()
    def memory_get_context(
        query: str,
        user_identifier: str = "default",
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
    ) -> dict[str, Any]:
        """Return prompt-ready scoped memory context for a query."""
        with _tool_span("memory_get_context"):
            return memory.get_context(
                user_identifier=user_identifier,
                query=query,
                session_id=session_id,
                memory_types=memory_types,
                source=source,
                tags=tags,
                created_after=created_after,
                created_before=created_before,
                updated_after=updated_after,
                updated_before=updated_before,
                limit=limit,
                threshold=threshold,
            )

    @app.tool()
    def memory_add_entity(
        name: str,
        entity_type: str,
        description: str = "",
        user_identifier: str = "default",
    ) -> dict[str, Any]:
        """Store an entity memory."""
        with _tool_span("memory_add_entity"):
            return memory.add_entity(
                user_identifier=user_identifier,
                name=name,
                entity_type=entity_type,
                description=description,
            ).to_dict()

    @app.tool()
    def memory_add_preference(
        category: str,
        preference: str,
        context: str = "",
        user_identifier: str = "default",
    ) -> dict[str, Any]:
        """Store a user preference memory."""
        with _tool_span("memory_add_preference"):
            return memory.add_preference(
                user_identifier=user_identifier,
                category=category,
                preference=preference,
                context=context,
            ).to_dict()

    @app.tool()
    def memory_add_fact(
        subject: str,
        predicate: str,
        object: str,  # noqa: A002 - MCP wire compatibility
        context: str = "",
        user_identifier: str = "default",
    ) -> dict[str, Any]:
        """Store a durable fact memory."""
        with _tool_span("memory_add_fact"):
            return memory.add_fact(
                user_identifier=user_identifier,
                subject=subject,
                predicate=predicate,
                object_value=object,
                context=context,
            ).to_dict()

    @app.tool()
    def document_ingest_text(
        title: str,
        text: str,
        user_identifier: str = "default",
        document_id: str | None = None,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Ingest text as a cited document graph with chunk vectors."""
        with _tool_span("document_ingest_text"):
            return memory.ingest_document_text(
                user_identifier=user_identifier,
                title=title,
                text=text,
                document_id=document_id,
                source=source,
                tags=tags,
                metadata=metadata,
                expires_at=expires_at,
            ).to_dict()

    @app.tool()
    def document_ingest_file(
        title: str,
        path: str,
        user_identifier: str = "default",
        document_id: str | None = None,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Convert a local file to Markdown with MarkItDown, then ingest it with citations."""
        with _tool_span("document_ingest_file"):
            converted = convert_document_to_markdown(path)
            enriched_metadata = dict(metadata or {})
            enriched_metadata["document_processing"] = converted.metadata
            return memory.ingest_document_text(
                user_identifier=user_identifier,
                title=title,
                text=converted.text,
                document_id=document_id,
                source=source,
                tags=tags,
                metadata=enriched_metadata,
                expires_at=expires_at,
            ).to_dict()

    @app.tool()
    def document_reindex_text(
        document_id: str,
        title: str,
        text: str,
        user_identifier: str = "default",
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Replace one scoped document's chunks and vectors with fresh text."""
        with _tool_span("document_reindex_text"):
            return memory.reindex_document_text(
                user_identifier=user_identifier,
                document_id=document_id,
                title=title,
                text=text,
                source=source,
                tags=tags,
                metadata=metadata,
                expires_at=expires_at,
            ).to_dict()

    @app.tool()
    def document_delete(
        document_id: str,
        user_identifier: str = "default",
    ) -> dict[str, object]:
        """Soft-delete one scoped document so its chunks are hidden from retrieval."""
        with _tool_span("document_delete"):
            return memory.delete_document(user_identifier=user_identifier, document_id=document_id)

    @app.tool()
    def document_search(
        query: str,
        user_identifier: str = "default",
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
    ) -> list[dict[str, Any]]:
        """Search scoped document chunks and return cited context with optional metadata filters."""
        with _tool_span("document_search"):
            return [
                item.to_dict()
                for item in memory.search_documents(
                    user_identifier=user_identifier,
                    query=query,
                    limit=limit,
                    document_id=document_id,
                    source=source,
                    tags=tags,
                    created_after=created_after,
                    created_before=created_before,
                    updated_after=updated_after,
                    updated_before=updated_before,
                    threshold=threshold,
                    explain=explain,
                )
            ]

    return app
