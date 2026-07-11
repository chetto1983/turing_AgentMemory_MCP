from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any

JsonDict = dict[str, Any]

DEFAULT_UTCP_MCP_COMMAND = ["turing-agentmemory-mcp", "serve", "--transport", "stdio"]


def _string(default: str | None = None) -> JsonDict:
    schema: JsonDict = {"type": "string"}
    if default is not None:
        schema["default"] = default
    return schema


def _integer(default: int | None = None, minimum: int | None = None) -> JsonDict:
    schema: JsonDict = {"type": "integer"}
    if default is not None:
        schema["default"] = default
    if minimum is not None:
        schema["minimum"] = minimum
    return schema


def _number(default: float | None = None, minimum: float | None = None) -> JsonDict:
    schema: JsonDict = {"type": "number"}
    if default is not None:
        schema["default"] = default
    if minimum is not None:
        schema["minimum"] = minimum
    return schema


def _boolean(default: bool | None = None) -> JsonDict:
    schema: JsonDict = {"type": "boolean"}
    if default is not None:
        schema["default"] = default
    return schema


def _string_array() -> JsonDict:
    return {"type": "array", "items": {"type": "string"}}


def _object() -> JsonDict:
    return {"type": "object", "additionalProperties": True}


def _message_array() -> JsonDict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "session_id": _string(),
                "role": _string(),
                "content": _string(),
                "memory_id": _string(),
            },
            "required": ["session_id", "role", "content"],
            "additionalProperties": True,
        },
    }


def _date_range_properties() -> JsonDict:
    return {
        "created_after": _string(""),
        "created_before": _string(""),
        "updated_after": _string(""),
        "updated_before": _string(""),
    }


def _schema(properties: JsonDict, required: list[str] | None = None) -> JsonDict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


MEMORY_ITEM_OUTPUT: JsonDict = {
    "type": "object",
    "properties": {
        "id": _string(),
        "user_identifier": _string(),
        "kind": _string(),
        "content": _string(),
        "score": _number(),
        "session_id": _string(),
        "role": _string(),
        "created_at": _string(),
        "updated_at": _string(),
        "expires_at": _string(),
        "source": _string(),
        "tags": _string_array(),
        "metadata": _object(),
    },
    "additionalProperties": True,
}

DOCUMENT_OUTPUT: JsonDict = {
    "type": "object",
    "properties": {
        "document_id": _string(),
        "title": _string(),
        "chunk_count": _integer(),
        "user_identifier": _string(),
        "created_at": _string(),
        "updated_at": _string(),
        "expires_at": _string(),
        "source": _string(),
        "tags": _string_array(),
        "metadata": _object(),
        "text_hash": _string(),
        "chunk_chars": _integer(),
    },
    "additionalProperties": True,
}

DOCUMENT_JOB_OUTPUT: JsonDict = {
    "type": "object",
    "properties": {
        "job_id": _string(),
        "user_identifier": _string(),
        "document_id": _string(),
        "title": _string(),
        "filename": _string(),
        "status": _string(),
        "stage": _string(),
        "progress_current": _integer(),
        "progress_total": _integer(),
        "attempt": _integer(),
        "max_attempts": _integer(),
        "error_code": _string(),
        "error_message": _string(),
        "result": _object(),
        "created_at": _string(),
        "updated_at": _string(),
        "started_at": _string(),
        "completed_at": _string(),
    },
    "additionalProperties": True,
}

DOCUMENT_HIT_OUTPUT: JsonDict = {
    "type": "object",
    "properties": {
        "chunk_id": _string(),
        "document_id": _string(),
        "title": _string(),
        "locator": _string(),
        "text": _string(),
        "score": _number(),
        "context": {"type": "array", "items": _object()},
        "expires_at": _string(),
        "source": _string(),
        "tags": _string_array(),
        "metadata": _object(),
    },
    "additionalProperties": True,
}

DELETE_OUTPUT: JsonDict = {
    "type": "object",
    "properties": {"deleted": _boolean(), "id": _string()},
    "additionalProperties": True,
}

AGENTMEMORY_TOOL_SPECS: list[JsonDict] = [
    {
        "name": "memory_store_message",
        "description": "Store a scoped conversation message in long-lived memory.",
        "tags": ["memory", "write", "conversation"],
        "inputs": _schema(
            {
                "session_id": _string(),
                "role": _string(),
                "content": _string(),
                "user_identifier": _string("default"),
                "memory_id": _string(),
                "source": _string(""),
                "tags": _string_array(),
                "metadata": _object(),
                "expires_at": _string(""),
            },
            ["session_id", "role", "content"],
        ),
        "outputs": MEMORY_ITEM_OUTPUT,
    },
    {
        "name": "memory_store_messages",
        "description": "Store conversation messages in one duplicate-safe batch.",
        "tags": ["memory", "write", "batch", "conversation"],
        "inputs": _schema(
            {
                "messages": _message_array(),
                "user_identifier": _string("default"),
                "source": _string(""),
                "tags": _string_array(),
                "metadata": _object(),
                "expires_at": _string(""),
            },
            ["messages"],
        ),
        "outputs": {"type": "array", "items": MEMORY_ITEM_OUTPUT},
    },
    {
        "name": "memory_get",
        "description": "Fetch one active scoped memory by id.",
        "tags": ["memory", "read", "lifecycle"],
        "inputs": _schema(
            {"memory_id": _string(), "user_identifier": _string("default")}, ["memory_id"]
        ),
        "outputs": MEMORY_ITEM_OUTPUT,
    },
    {
        "name": "memory_list",
        "description": "List active scoped memories with optional session, type, source, and tag filters.",
        "tags": ["memory", "read", "lifecycle"],
        "inputs": _schema(
            {
                "user_identifier": _string("default"),
                "limit": _integer(25, minimum=1),
                "session_id": _string(""),
                "memory_types": _string_array(),
                "source": _string(""),
                "tags": _string_array(),
                **_date_range_properties(),
            }
        ),
        "outputs": {"type": "array", "items": MEMORY_ITEM_OUTPUT},
    },
    {
        "name": "memory_update",
        "description": "Update active scoped memory content or metadata.",
        "tags": ["memory", "write", "lifecycle"],
        "inputs": _schema(
            {
                "memory_id": _string(),
                "user_identifier": _string("default"),
                "content": _string(),
                "kind": _string(),
                "session_id": _string(),
                "role": _string(),
                "source": _string(),
                "tags": _string_array(),
                "metadata": _object(),
                "expires_at": _string(),
            },
            ["memory_id"],
        ),
        "outputs": MEMORY_ITEM_OUTPUT,
    },
    {
        "name": "memory_delete",
        "description": "Soft-delete one scoped memory so it is hidden from retrieval.",
        "tags": ["memory", "delete", "lifecycle"],
        "inputs": _schema(
            {"memory_id": _string(), "user_identifier": _string("default")}, ["memory_id"]
        ),
        "outputs": DELETE_OUTPUT,
    },
    {
        "name": "memory_search",
        "description": "Search scoped memory with fused dense, BM25, entity, graph, and rerank signals.",
        "tags": ["memory", "search", "retrieval"],
        "inputs": _schema(
            {
                "query": _string(),
                "user_identifier": _string("default"),
                "limit": _integer(5, minimum=1),
                "memory_types": _string_array(),
                "session_id": _string(""),
                "source": _string(""),
                "tags": _string_array(),
                **_date_range_properties(),
                "threshold": _number(0.0, minimum=0.0),
                "explain": _boolean(False),
            },
            ["query"],
        ),
        "outputs": {"type": "array", "items": MEMORY_ITEM_OUTPUT},
    },
    {
        "name": "memory_get_context",
        "description": "Return prompt-ready scoped memory context for a query.",
        "tags": ["memory", "search", "context"],
        "inputs": _schema(
            {
                "query": _string(),
                "user_identifier": _string("default"),
                "session_id": _string(""),
                "memory_types": _string_array(),
                "source": _string(""),
                "tags": _string_array(),
                **_date_range_properties(),
                "limit": _integer(5, minimum=1),
                "threshold": _number(0.0, minimum=0.0),
            },
            ["query"],
        ),
        "outputs": _object(),
    },
    {
        "name": "memory_add_entity",
        "description": "Store an entity memory.",
        "tags": ["memory", "write", "entity"],
        "inputs": _schema(
            {
                "name": _string(),
                "entity_type": _string(),
                "description": _string(""),
                "user_identifier": _string("default"),
            },
            ["name", "entity_type"],
        ),
        "outputs": MEMORY_ITEM_OUTPUT,
    },
    {
        "name": "memory_add_preference",
        "description": "Store a user preference memory.",
        "tags": ["memory", "write", "preference"],
        "inputs": _schema(
            {
                "category": _string(),
                "preference": _string(),
                "context": _string(""),
                "user_identifier": _string("default"),
            },
            ["category", "preference"],
        ),
        "outputs": MEMORY_ITEM_OUTPUT,
    },
    {
        "name": "memory_add_fact",
        "description": "Store a durable fact memory.",
        "tags": ["memory", "write", "fact"],
        "inputs": _schema(
            {
                "subject": _string(),
                "predicate": _string(),
                "object": _string(),
                "context": _string(""),
                "user_identifier": _string("default"),
            },
            ["subject", "predicate", "object"],
        ),
        "outputs": MEMORY_ITEM_OUTPUT,
    },
    {
        "name": "document_ingest_text",
        "description": "Ingest text as a cited document graph with chunk vectors.",
        "tags": ["document", "write", "ingest", "citations"],
        "inputs": _schema(
            {
                "title": _string(),
                "text": _string(),
                "user_identifier": _string("default"),
                "document_id": _string(),
                "source": _string(""),
                "tags": _string_array(),
                "metadata": _object(),
                "expires_at": _string(),
            },
            ["title", "text"],
        ),
        "outputs": DOCUMENT_OUTPUT,
    },
    {
        "name": "document_ingest_file",
        "description": "Durably enqueue a local file for background conversion and cited ingestion.",
        "tags": ["document", "write", "ingest", "citations", "async"],
        "inputs": _schema(
            {
                "title": _string(),
                "path": _string(),
                "user_identifier": _string("default"),
                "document_id": _string(),
                "source": _string(""),
                "tags": _string_array(),
                "metadata": _object(),
                "expires_at": _string(),
            },
            ["title", "path"],
        ),
        "outputs": DOCUMENT_JOB_OUTPUT,
    },
    {
        "name": "document_ingest_status",
        "description": "Return tenant-scoped state and progress for a document ingestion job.",
        "tags": ["document", "ingest", "async", "status"],
        "inputs": _schema(
            {"job_id": _string(), "user_identifier": _string("default")},
            ["job_id"],
        ),
        "outputs": DOCUMENT_JOB_OUTPUT,
    },
    {
        "name": "document_ingest_cancel",
        "description": "Cancel a queued job or request cancellation of a running ingestion job.",
        "tags": ["document", "ingest", "async", "cancel"],
        "inputs": _schema(
            {"job_id": _string(), "user_identifier": _string("default")},
            ["job_id"],
        ),
        "outputs": DOCUMENT_JOB_OUTPUT,
    },
    {
        "name": "document_ingest_retry",
        "description": "Requeue a failed document ingestion job from durable staging.",
        "tags": ["document", "ingest", "async", "retry"],
        "inputs": _schema(
            {"job_id": _string(), "user_identifier": _string("default")},
            ["job_id"],
        ),
        "outputs": DOCUMENT_JOB_OUTPUT,
    },
    {
        "name": "document_reindex_text",
        "description": "Replace one scoped document's chunks and vectors with fresh text.",
        "tags": ["document", "write", "reindex", "citations"],
        "inputs": _schema(
            {
                "document_id": _string(),
                "title": _string(),
                "text": _string(),
                "user_identifier": _string("default"),
                "source": _string(""),
                "tags": _string_array(),
                "metadata": _object(),
                "expires_at": _string(),
            },
            ["document_id", "title", "text"],
        ),
        "outputs": DOCUMENT_OUTPUT,
    },
    {
        "name": "document_delete",
        "description": "Soft-delete one scoped document so its chunks are hidden from retrieval.",
        "tags": ["document", "delete", "lifecycle"],
        "inputs": _schema(
            {"document_id": _string(), "user_identifier": _string("default")},
            ["document_id"],
        ),
        "outputs": DELETE_OUTPUT,
    },
    {
        "name": "document_search",
        "description": "Search scoped document chunks and return citations with neighbor context.",
        "tags": ["document", "search", "retrieval", "citations"],
        "inputs": _schema(
            {
                "query": _string(),
                "user_identifier": _string("default"),
                "limit": _integer(5, minimum=1),
                "document_id": _string(""),
                "source": _string(""),
                "tags": _string_array(),
                **_date_range_properties(),
                "threshold": _number(0.0, minimum=0.0),
                "explain": _boolean(False),
            },
            ["query"],
        ),
        "outputs": {"type": "array", "items": DOCUMENT_HIT_OUTPUT},
    },
]


def build_utcp_manual(
    *,
    server_name: str = "turing-agentmemory-mcp",
    command: list[str] | None = None,
    manual_version: str = "1.0.0",
    utcp_version: str = "1.0.2",
    auth_env: str | None = None,
) -> JsonDict:
    """Build a UTCP manual that exposes the AgentMemory MCP tools through MCP stdio."""
    mcp_command = list(command or DEFAULT_UTCP_MCP_COMMAND)
    tool_call_template: JsonDict = {
        "name": server_name,
        "call_template_type": "mcp",
        "allowed_communication_protocols": ["mcp"],
        "config": {
            "mcpServers": {
                server_name: {
                    "transport": "stdio",
                    "command": mcp_command,
                }
            }
        },
    }
    if auth_env:
        tool_call_template["auth"] = {
            "auth_type": "api_key",
            "api_key": f"Bearer ${{{auth_env}}}",
            "var_name": "Authorization",
            "location": "header",
        }

    return {
        "manual_version": manual_version,
        "utcp_version": utcp_version,
        "tools": [
            {**deepcopy(spec), "tool_call_template": deepcopy(tool_call_template)}
            for spec in AGENTMEMORY_TOOL_SPECS
        ],
    }


def utcp_manual_from_env() -> JsonDict:
    server_name = os.environ.get("AGENTMEMORY_UTCP_SERVER_NAME", "turing-agentmemory-mcp")
    command = _command_from_env()
    return build_utcp_manual(
        server_name=server_name,
        command=command,
        auth_env=_auth_env_placeholder(),
    )


def _command_from_env() -> list[str]:
    raw = os.environ.get("AGENTMEMORY_UTCP_MCP_COMMAND", "").strip()
    if not raw:
        return list(DEFAULT_UTCP_MCP_COMMAND)
    return parse_command_json(raw)


def parse_command_json(raw: str) -> list[str]:
    value = json.loads(raw)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError("command JSON must be a JSON array of strings")
    if not value:
        raise ValueError("command JSON must contain at least one string")
    return value


def _auth_env_placeholder() -> str | None:
    explicit = os.environ.get("AGENTMEMORY_UTCP_AUTH_ENV", "").strip()
    if explicit:
        return explicit
    if os.environ.get("AGENTMEMORY_AUTH_TOKEN"):
        return "AGENTMEMORY_AUTH_TOKEN"
    return None
