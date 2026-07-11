from __future__ import annotations

import asyncio
import json
import sys
import types
from typing import Any

from fastmcp import Client

if "turingdb" not in sys.modules:
    sys.modules["turingdb"] = types.SimpleNamespace(TuringDB=object, __version__="test")

from turing_agentmemory_mcp.models import MemoryItem
from turing_agentmemory_mcp.server import create_mcp_app


class FakeMemory:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def store_messages(
        self,
        *,
        user_identifier: str,
        messages: list[dict[str, object]],
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str = "",
    ) -> list[MemoryItem]:
        self.calls.append(
            {
                "user_identifier": user_identifier,
                "messages": messages,
                "source": source,
                "tags": tags,
                "metadata": metadata,
                "expires_at": expires_at,
            }
        )
        return [
            MemoryItem(
                id="batch-1",
                user_identifier=user_identifier,
                kind="message",
                content=str(messages[0]["content"]),
                session_id=str(messages[0]["session_id"]),
                role=str(messages[0]["role"]),
                score=1.0,
                source=source,
                tags=tags or [],
                metadata=metadata or {},
                expires_at=expires_at,
            )
        ]

    def rebuild_communities(self, *, user_identifier: str) -> dict[str, object]:
        self.calls.append({"rebuild_user_identifier": user_identifier})
        return {"community_count": 2}

    def rebuild_vector_projection(self, *, user_identifier: str) -> dict[str, object]:
        self.calls.append({"rebuild_vector_user_identifier": user_identifier})
        return {"total": 5}


def _payload(result: Any) -> Any:
    if hasattr(result, "structured_content") and result.structured_content is not None:
        value = result.structured_content
        if isinstance(value, dict) and set(value) == {"result"}:
            return value["result"]
        return value
    if hasattr(result, "data") and result.data is not None:
        return result.data
    if hasattr(result, "content"):
        text = "".join(getattr(item, "text", "") for item in result.content)
        return json.loads(text)
    return result


def test_memory_store_messages_tool_exposes_batch_store() -> None:
    fake = FakeMemory()

    async def run() -> None:
        async with Client(create_mcp_app(fake)) as client:
            tools = await client.list_tools()
            assert "memory_store_messages" in {tool.name for tool in tools}
            result = _payload(
                await client.call_tool(
                    "memory_store_messages",
                    {
                        "user_identifier": "alice",
                        "messages": [
                            {
                                "session_id": "s1",
                                "role": "user",
                                "content": "batch message over MCP",
                            }
                        ],
                        "source": "chat",
                        "tags": ["batch"],
                        "metadata": {"request_id": "r1"},
                    },
                )
            )
            assert result[0]["id"] == "batch-1"

    asyncio.run(run())
    assert fake.calls == [
        {
            "user_identifier": "alice",
            "messages": [
                {
                    "session_id": "s1",
                    "role": "user",
                    "content": "batch message over MCP",
                }
            ],
            "source": "chat",
            "tags": ["batch"],
            "metadata": {"request_id": "r1"},
            "expires_at": "",
        }
    ]


def test_memory_rebuild_communities_tool_exposes_derived_repair() -> None:
    fake = FakeMemory()

    async def run() -> None:
        async with Client(create_mcp_app(fake)) as client:
            result = _payload(
                await client.call_tool(
                    "memory_rebuild_communities",
                    {"user_identifier": "alice"},
                )
            )
            assert result == {"community_count": 2}

    asyncio.run(run())
    assert fake.calls == [{"rebuild_user_identifier": "alice"}]


def test_memory_rebuild_vector_projection_tool_exposes_recoverable_reindex() -> None:
    fake = FakeMemory()

    async def run() -> None:
        async with Client(create_mcp_app(fake)) as client:
            tools = await client.list_tools()
            assert "memory_rebuild_vector_projection" in {tool.name for tool in tools}
            result = _payload(
                await client.call_tool(
                    "memory_rebuild_vector_projection",
                    {"user_identifier": "alice"},
                )
            )
            assert result == {"total": 5}

    asyncio.run(run())
    assert fake.calls == [{"rebuild_vector_user_identifier": "alice"}]
