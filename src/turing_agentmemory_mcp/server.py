from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastmcp import FastMCP
from turingdb import TuringDB

from turing_agentmemory_mcp.store import TuringAgentMemory


def store_from_env() -> TuringAgentMemory:
    url = os.environ.get("TURINGDB_URL", "http://127.0.0.1:6666")
    token = os.environ.get("TURINGDB_AUTH_TOKEN") or None
    graph = os.environ.get("TURINGDB_GRAPH", "agent_memory")
    home = Path(os.environ.get("TURINGDB_HOME", "/turing"))
    dimensions = int(os.environ.get("AURA_EMBED_DIMENSIONS", os.environ.get("TURINGDB_EMBED_DIMENSIONS", "768")))
    client = TuringDB(type="json", host=url, token=token)
    store = TuringAgentMemory(client, turing_home=home, graph=graph, dimensions=dimensions)
    store.bootstrap()
    return store


def create_mcp_app(store: TuringAgentMemory | None = None) -> FastMCP:
    memory = store or store_from_env()
    app = FastMCP(
        "turing-agentmemory-mcp",
        instructions=(
            "Scoped memory and document retrieval backed by TuringDB. "
            "Always pass user_identifier from the caller identity."
        ),
    )

    @app.tool()
    def memory_store_message(
        session_id: str,
        role: str,
        content: str,
        user_identifier: str = "default",
    ) -> dict[str, Any]:
        """Store a scoped conversation message in long-lived memory."""
        return memory.store_message(
            user_identifier=user_identifier,
            session_id=session_id,
            role=role,
            content=content,
        ).to_dict()

    @app.tool()
    def memory_search(
        query: str,
        user_identifier: str = "default",
        limit: int = 5,
        memory_types: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search scoped memory by semantic similarity."""
        return [
            item.to_dict()
            for item in memory.search_memory(
                user_identifier=user_identifier,
                query=query,
                limit=limit,
                memory_types=memory_types,
            )
        ]

    @app.tool()
    def memory_get_context(
        query: str,
        user_identifier: str = "default",
        session_id: str = "",
        limit: int = 5,
    ) -> dict[str, Any]:
        """Return prompt-ready scoped memory context for a query."""
        return memory.get_context(
            user_identifier=user_identifier,
            query=query,
            session_id=session_id,
            limit=limit,
        )

    @app.tool()
    def memory_add_entity(
        name: str,
        entity_type: str,
        description: str = "",
        user_identifier: str = "default",
    ) -> dict[str, Any]:
        """Store an entity memory."""
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
    ) -> dict[str, Any]:
        """Ingest text as a cited document graph with chunk vectors."""
        return memory.ingest_document_text(
            user_identifier=user_identifier,
            title=title,
            text=text,
            document_id=document_id,
        ).to_dict()

    @app.tool()
    def document_search(
        query: str,
        user_identifier: str = "default",
        limit: int = 5,
        document_id: str = "",
    ) -> list[dict[str, Any]]:
        """Search scoped document chunks and return cited context."""
        return [
            item.to_dict()
            for item in memory.search_documents(
                user_identifier=user_identifier,
                query=query,
                limit=limit,
                document_id=document_id,
            )
        ]

    return app
