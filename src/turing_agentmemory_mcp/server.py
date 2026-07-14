from __future__ import annotations

import atexit
import json
import math
import os
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from starlette.responses import JSONResponse

from turing_agentmemory_mcp.arcadedb_client import ArcadeDBClient
from turing_agentmemory_mcp.community_detection import NativeLeidenDetector
from turing_agentmemory_mcp.document_job_manager import (
    DocumentIngestManager,
    document_ingest_manager_from_env,
)
from turing_agentmemory_mcp.entity_extraction import NoopEntityProcessor
from turing_agentmemory_mcp.file_upload import (
    DocumentUploadStore,
    document_upload_store_from_env,
)
from turing_agentmemory_mcp.memory_extraction import (
    MEMORY_EXTRACTION_SCHEMA_VERSION,
    HTTPMemoryExtractor,
)
from turing_agentmemory_mcp.provider_config import store_embedding_dimensions
from turing_agentmemory_mcp.search_controls import validate_fusion_weights
from turing_agentmemory_mcp.server_document_tools import register_document_tools
from turing_agentmemory_mcp.server_memory_tools import register_memory_tools
from turing_agentmemory_mcp.sparse_index import SparseIndex
from turing_agentmemory_mcp.store import TuringAgentMemory


def auth_from_env() -> Any | None:
    tokens = _env_list("AGENTMEMORY_AUTH_TOKENS")
    single_token = os.environ.get("AGENTMEMORY_AUTH_TOKEN", "").strip()
    if single_token:
        tokens.insert(0, single_token)
    tokens = list(dict.fromkeys(token for token in tokens if token))
    if not tokens:
        return None

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
        schema = os.environ.get("GLINER_MEMORY_SCHEMA", MEMORY_EXTRACTION_SCHEMA_VERSION).strip()
        if schema != MEMORY_EXTRACTION_SCHEMA_VERSION:
            raise ValueError(f"GLINER_MEMORY_SCHEMA must be {MEMORY_EXTRACTION_SCHEMA_VERSION}")
        memory_extractor = HTTPMemoryExtractor(
            base_url=os.environ.get("GLINER_BASE_URL", "http://agentmemory-gliner:8080"),
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
        max_cluster_size=_env_int("AGENTMEMORY_LEIDEN_MAX_CLUSTER_SIZE", default=100, minimum=1),
    )
    # ARCADEDB_*_INDEX supersedes TURINGDB_*_INDEX for the ArcadeDB-backed store
    # (ARC-02); the TURINGDB_* connection vars above stay unread here -- the
    # turingdb service/dependency is retained for coexistence (Phase 7/ARC-10)
    # but the store no longer connects through it.
    client = ArcadeDBClient.from_env()
    store = TuringAgentMemory(
        client,
        turing_home=home,
        graph=graph,
        dimensions=dimensions,
        memory_index=os.environ.get(
            "ARCADEDB_MEMORY_INDEX", f"{index_prefix}_episode_vectors_{dimensions}"
        ),
        document_index=os.environ.get(
            "ARCADEDB_DOCUMENT_INDEX", f"{index_prefix}_document_vectors_{dimensions}"
        ),
        entity_index=os.environ.get(
            "ARCADEDB_ENTITY_INDEX", f"{index_prefix}_entity_vectors_{dimensions}"
        ),
        fact_index=os.environ.get(
            "ARCADEDB_FACT_INDEX", f"{index_prefix}_fact_vectors_{dimensions}"
        ),
        community_index=os.environ.get(
            "ARCADEDB_COMMUNITY_INDEX", f"{index_prefix}_community_vectors_{dimensions}"
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


def create_mcp_app(
    store: TuringAgentMemory | None = None,
    *,
    upload_store: DocumentUploadStore | None = None,
    document_manager: DocumentIngestManager | None = None,
    start_document_worker: bool | None = None,
) -> FastMCP:
    production_store = store is None
    memory = store or store_from_env()
    uploads = upload_store or document_upload_store_from_env()
    manager = document_manager
    if manager is None and production_store:
        manager = document_ingest_manager_from_env(store_factory=store_from_env)
    should_start_worker = (
        production_store if start_document_worker is None else start_document_worker
    )
    if manager is not None and should_start_worker:
        manager.start()
        atexit.register(manager.stop)

    def _document_manager() -> DocumentIngestManager:
        if manager is None:
            raise RuntimeError("asynchronous document ingestion is not configured")
        return manager

    def _tool_span(tool: str) -> Any:
        observer = getattr(memory, "observer", None)
        span = getattr(observer, "span", None)
        if callable(span):
            return span("mcp.tool", {"tool": tool})
        return nullcontext()

    app = FastMCP(
        "turing-agentmemory-mcp",
        instructions=(
            "Scoped memory and document retrieval backed by ArcadeDB. "
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
        document_jobs = manager.runtime_status() if manager is not None else {"configured": False}
        return JSONResponse(
            {
                "status": "ok" if ready else "degraded",
                "runtime": runtime,
                "document_ingest": document_jobs,
            },
            status_code=200 if ready else 503,
        )

    register_memory_tools(app, memory, _tool_span)
    register_document_tools(app, memory, uploads, _document_manager, _tool_span)

    return app
