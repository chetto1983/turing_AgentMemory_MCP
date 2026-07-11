"""Memory-lifecycle MCP tool registrations for the FastMCP app."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP

from turing_agentmemory_mcp.store import TuringAgentMemory


def register_memory_tools(
    app: FastMCP,
    memory: TuringAgentMemory,
    tool_span: Callable[[str], Any],
) -> None:
    """Register every `memory_*` MCP tool on `app`."""

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
        with tool_span("memory_store_message"):
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
        refresh_communities: bool = True,
    ) -> list[dict[str, Any]]:
        """Store conversation messages in one duplicate-safe batch."""
        with tool_span("memory_store_messages"):
            store_arguments: dict[str, object] = {
                "user_identifier": user_identifier,
                "messages": messages,
                "source": source,
                "tags": tags,
                "metadata": metadata,
                "expires_at": expires_at,
            }
            if not refresh_communities:
                store_arguments["refresh_communities"] = False
            return [item.to_dict() for item in memory.store_messages(**store_arguments)]

    @app.tool()
    def memory_rebuild_communities(
        user_identifier: str = "default",
    ) -> dict[str, object]:
        """Rebuild derived Leiden communities after a bulk ingest."""
        with tool_span("memory_rebuild_communities"):
            return memory.rebuild_communities(user_identifier=user_identifier)

    @app.tool()
    def memory_rebuild_vector_projection(
        user_identifier: str = "default",
    ) -> dict[str, object]:
        """Rebuild active tenant vectors from canonical graph records."""
        with tool_span("memory_rebuild_vector_projection"):
            return memory.rebuild_vector_projection(user_identifier=user_identifier)

    @app.tool()
    def memory_get(
        memory_id: str,
        user_identifier: str = "default",
    ) -> dict[str, Any] | None:
        """Fetch one active scoped memory by id."""
        with tool_span("memory_get"):
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
        with tool_span("memory_list"):
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
        with tool_span("memory_update"):
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
        with tool_span("memory_delete"):
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
        with tool_span("memory_search"):
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
        with tool_span("memory_get_context"):
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
        with tool_span("memory_add_entity"):
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
        with tool_span("memory_add_preference"):
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
        with tool_span("memory_add_fact"):
            return memory.add_fact(
                user_identifier=user_identifier,
                subject=subject,
                predicate=predicate,
                object_value=object,
                context=context,
            ).to_dict()
