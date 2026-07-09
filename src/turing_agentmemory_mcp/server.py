from __future__ import annotations

import os
from contextlib import nullcontext
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from turingdb import TuringDB

from turing_agentmemory_mcp.provider_config import store_embedding_dimensions
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


def store_from_env() -> TuringAgentMemory:
    url = os.environ.get("TURINGDB_URL", "http://127.0.0.1:6666")
    token = os.environ.get("TURINGDB_AUTH_TOKEN") or None
    graph = os.environ.get("TURINGDB_GRAPH", "agent_memory")
    home = Path(os.environ.get("TURINGDB_HOME", "/turing"))
    dimensions = int(store_embedding_dimensions())
    client = TuringDB(type="json", host=url, token=token)
    store = TuringAgentMemory(client, turing_home=home, graph=graph, dimensions=dimensions)
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
    ) -> list[dict[str, Any]]:
        """List active scoped memories with optional session, type, source, and tag filters."""
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
        threshold: float = 0.0,
        explain: bool = False,
    ) -> list[dict[str, Any]]:
        """Search scoped memory by semantic similarity, with optional threshold and score details."""
        with _tool_span("memory_search"):
            return [
                item.to_dict()
                for item in memory.search_memory(
                    user_identifier=user_identifier,
                    query=query,
                    limit=limit,
                    memory_types=memory_types,
                    threshold=threshold,
                    explain=explain,
                )
            ]

    @app.tool()
    def memory_get_context(
        query: str,
        user_identifier: str = "default",
        session_id: str = "",
        limit: int = 5,
        threshold: float = 0.0,
    ) -> dict[str, Any]:
        """Return prompt-ready scoped memory context for a query."""
        with _tool_span("memory_get_context"):
            return memory.get_context(
                user_identifier=user_identifier,
                query=query,
                session_id=session_id,
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
        threshold: float = 0.0,
        explain: bool = False,
    ) -> list[dict[str, Any]]:
        """Search scoped document chunks and return cited context, with optional score details."""
        with _tool_span("document_search"):
            return [
                item.to_dict()
                for item in memory.search_documents(
                    user_identifier=user_identifier,
                    query=query,
                    limit=limit,
                    document_id=document_id,
                    threshold=threshold,
                    explain=explain,
                )
            ]

    return app
