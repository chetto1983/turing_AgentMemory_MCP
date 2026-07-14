"""Deterministic MCP scenario checks exercised by the E2E score gate (`e2e_score.py`).

`payload`/`check` are the small result-shaping and scoring helpers shared by every
scenario; `run_mcp_checks` drives the full tool-surface scenario against a live
in-process MCP client and records one `check()` entry per scenario assertion.
"""

from __future__ import annotations

import json
from typing import Any

from fastmcp import Client

from turing_agentmemory_mcp.e2e_score_check import check, payload  # noqa: F401 - re-exported
from turing_agentmemory_mcp.ids import stable_id
from turing_agentmemory_mcp.memoryarena import answer_marker, load_sample
from turing_agentmemory_mcp.server import create_mcp_app
from turing_agentmemory_mcp.store import TuringAgentMemory


def _chunk_id(user_identifier: str, document_id: str, ordinal: int) -> str:
    # Mirrors store_documents.py's stable_id() chunk-id construction (ARC-08)
    # -- not the retired f"{document_id}#{ordinal}" literal (04-09 fix).
    return stable_id("chunk", user_identifier, document_id, str(ordinal))


async def run_mcp_checks(store: TuringAgentMemory, checks: list[dict[str, Any]]) -> None:
    app = create_mcp_app(store)
    async with Client(app) as client:
        tools = await client.list_tools()
        tool_names = {tool.name for tool in tools}
        expected = {
            "memory_search",
            "memory_get_context",
            "memory_get",
            "memory_list",
            "memory_update",
            "memory_delete",
            "memory_store_message",
            "memory_store_messages",
            "memory_add_entity",
            "memory_add_preference",
            "memory_add_fact",
            "document_ingest_text",
            "document_reindex_text",
            "document_delete",
            "document_search",
        }
        check(checks, "mcp_exposes_expected_tool_surface", lambda: expected <= tool_names)

        alice_message = payload(
            await client.call_tool(
                "memory_store_message",
                {
                    "user_identifier": "alice",
                    "session_id": "s1",
                    "role": "user",
                    "content": "Davide prefers espresso after lunch when reviewing TuringDB memory.",
                },
            )
        )
        payload(
            await client.call_tool(
                "memory_store_message",
                {
                    "user_identifier": "bob",
                    "session_id": "s2",
                    "role": "user",
                    "content": "Bob tracks espresso grinder prices but not TuringDB memory.",
                },
            )
        )
        check(
            checks,
            "memory_store_message_writes_scoped_memory",
            lambda: (
                alice_message["user_identifier"] == "alice" and alice_message["kind"] == "message"
            ),
        )

        batch_messages = payload(
            await client.call_tool(
                "memory_store_messages",
                {
                    "user_identifier": "alice",
                    "source": "e2e-batch",
                    "tags": ["batch", "idempotent"],
                    "metadata": {"request_id": "batch-1"},
                    "messages": [
                        {
                            "session_id": "batch",
                            "role": "user",
                            "content": "Batch memory marker BATCH-42 stores retry-safe grouped writes.",
                        },
                        {
                            "session_id": "batch",
                            "role": "assistant",
                            "content": "Batch memory marker BATCH-43 stays searchable after vector load.",
                        },
                        {
                            "session_id": "batch",
                            "role": "user",
                            "content": "Batch memory marker BATCH-42 stores retry-safe grouped writes.",
                        },
                    ],
                },
            )
        )
        batch_search = payload(
            await client.call_tool(
                "memory_search",
                {
                    "user_identifier": "alice",
                    "query": "BATCH-43 vector load searchable",
                    "limit": 3,
                },
            )
        )
        check(
            checks,
            "memory_store_messages_batches_idempotent_searchable_writes",
            lambda: (
                len(batch_messages) == 3
                and batch_messages[0]["id"] == batch_messages[2]["id"]
                and batch_messages[0]["source"] == "e2e-batch"
                and "idempotent" in batch_messages[0]["tags"]
                and batch_search[0]["content"].startswith("Batch memory marker BATCH-43")
            ),
        )

        alice_search = payload(
            await client.call_tool(
                "memory_search",
                {"user_identifier": "alice", "query": "espresso TuringDB memory", "limit": 3},
            )
        )
        check(
            checks,
            "memory_search_retrieves_alice_exact_top1",
            lambda: alice_search[0]["content"].startswith("Davide prefers espresso"),
        )
        check(
            checks,
            "memory_search_does_not_leak_bob",
            lambda: all(row["user_identifier"] == "alice" for row in alice_search),
        )

        incident_memory = payload(
            await client.call_tool(
                "memory_store_message",
                {
                    "user_identifier": "alice",
                    "session_id": "ops",
                    "role": "assistant",
                    "content": (
                        "Incident INC-7781 affects C:\\ops\\delta\\router.yml "
                        "and reports error E42-ALPHA."
                    ),
                    "source": "e2e-hybrid",
                    "tags": ["incident", "hybrid"],
                },
            )
        )
        incident_hits = payload(
            await client.call_tool(
                "memory_search",
                {
                    "user_identifier": "alice",
                    "query": "INC-7781 E42-ALPHA router.yml",
                    "limit": 3,
                    "explain": True,
                },
            )
        )
        incident_details = incident_hits[0]["score_details"]
        check(
            checks,
            "memory_search_hybrid_exact_code_match_explains_lexical_score",
            lambda: (
                incident_hits[0]["id"] == incident_memory["id"]
                and incident_details["lexical_score"] > 0.0
                and incident_details["final_score"] >= incident_details["semantic_score"]
            ),
        )

        context = payload(
            await client.call_tool(
                "memory_get_context",
                {
                    "user_identifier": "alice",
                    "query": "what drink during memory review",
                    "limit": 3,
                },
            )
        )
        check(
            checks,
            "memory_get_context_returns_prompt_ready_context",
            lambda: "espresso" in context["context"].lower() and bool(context["items"]),
        )

        duplicate_payload = {
            "user_identifier": "alice",
            "session_id": "lifecycle",
            "role": "user",
            "content": "Lifecycle marker: Alice likes deterministic duplicate-safe memory writes.",
            "source": "e2e",
            "tags": ["lifecycle", "idempotent"],
            "metadata": {"source_test": "lifecycle"},
        }
        duplicate_first = payload(await client.call_tool("memory_store_message", duplicate_payload))
        duplicate_second = payload(
            await client.call_tool("memory_store_message", duplicate_payload)
        )
        lifecycle_list = payload(
            await client.call_tool(
                "memory_list",
                {
                    "user_identifier": "alice",
                    "session_id": "lifecycle",
                    "tags": ["idempotent"],
                    "limit": 5,
                },
            )
        )
        check(
            checks,
            "memory_store_message_is_idempotent_and_memory_list_filters_metadata",
            lambda: (
                duplicate_first["id"] == duplicate_second["id"]
                and len(lifecycle_list) == 1
                and lifecycle_list[0]["source"] == "e2e"
                and "idempotent" in lifecycle_list[0]["tags"]
            ),
        )

        fetched = payload(
            await client.call_tool(
                "memory_get",
                {"user_identifier": "alice", "memory_id": duplicate_first["id"]},
            )
        )
        updated = payload(
            await client.call_tool(
                "memory_update",
                {
                    "user_identifier": "alice",
                    "memory_id": duplicate_first["id"],
                    "content": "Lifecycle marker: Alice likes corrected memory updates.",
                    "source": "e2e-update",
                    "tags": ["lifecycle", "updated"],
                    "metadata": {"source_test": "updated"},
                },
            )
        )
        check(
            checks,
            "memory_get_and_update_return_structured_metadata",
            lambda: (
                fetched["id"] == duplicate_first["id"]
                and updated["content"].endswith("corrected memory updates.")
                and updated["created_at"] == fetched["created_at"]
                and updated["updated_at"] >= fetched["updated_at"]
                and updated["source"] == "e2e-update"
                and updated["metadata"]["source_test"] == "updated"
            ),
        )

        delete_result = payload(
            await client.call_tool(
                "memory_delete",
                {"user_identifier": "alice", "memory_id": duplicate_first["id"]},
            )
        )
        deleted_get = payload(
            await client.call_tool(
                "memory_get",
                {"user_identifier": "alice", "memory_id": duplicate_first["id"]},
            )
        )
        deleted_search = payload(
            await client.call_tool(
                "memory_search",
                {
                    "user_identifier": "alice",
                    "query": "deterministic duplicate-safe memory writes",
                    "limit": 3,
                },
            )
        )
        check(
            checks,
            "memory_delete_hides_memory_from_get_and_search",
            lambda: (
                delete_result["deleted"] is True
                and deleted_get is None
                and all(row["id"] != duplicate_first["id"] for row in deleted_search)
            ),
        )

        document_text = (
            "Emergency stop reset requires the blue key and a safety guard interlock check "
            "before power is restored to the conveyor line. Only certified operators may "
            "perform the reset, and the guard interlock status must read green on the panel.\n"
            "After the reset completes, verify that all guard interlock lights are illuminated "
            "and steady before restarting the conveyor motor. If any interlock light flickers, "
            "stop immediately and file a fault ticket with the maintenance supervisor on shift.\n"
            "Monthly maintenance records include oil inspection, belt tension measurement, and "
            "a signed checklist logged in the plant register. Keep completed log sheets for at "
            "least twelve months to satisfy the annual safety audit requirements."
        )
        doc = payload(
            await client.call_tool(
                "document_ingest_text",
                {
                    "user_identifier": "alice",
                    "document_id": "doc-machine-safety",
                    "title": "Machine Safety Manual",
                    "text": document_text,
                },
            )
        )
        check(
            checks,
            "document_ingest_text_writes_chunks",
            lambda: doc["document_id"] == "doc-machine-safety" and doc["chunk_count"] == 3,
        )

        doc_hits = payload(
            await client.call_tool(
                "document_search",
                {
                    "user_identifier": "alice",
                    "query": "reset safety guard interlock",
                    "limit": 3,
                },
            )
        )
        check(
            checks,
            "document_search_retrieves_exact_top1_with_citation_and_neighbor_context",
            lambda: (
                doc_hits[0]["chunk_id"] == _chunk_id("alice", "doc-machine-safety", 1)
                and doc_hits[0]["locator"] == "chunk=1"
                and doc_hits[0]["context"][0]["chunk_id"]
                == _chunk_id("alice", "doc-machine-safety", 2)
            ),
        )

        hybrid_doc = payload(
            await client.call_tool(
                "document_ingest_text",
                {
                    "user_identifier": "alice",
                    "document_id": "doc-incident-runbook",
                    "title": "Incident Runbook",
                    "text": (
                        "Runbook RBK-4412 maps incident INC-7781 to the affected configuration "
                        "file C:\\ops\\delta\\router.yml and the reported error E42-ALPHA. "
                        "Operators should snapshot the current router.yml before applying any "
                        "hotfix or rollback to the gateway.\n"
                        "Escalation requires paging the on-call NOC bridge and capturing a full "
                        "postmortem timeline within the first hour of the incident. Attach packet "
                        "captures and the relevant service logs so the review board can "
                        "reconstruct the failure sequence."
                    ),
                },
            )
        )
        hybrid_doc_hits = payload(
            await client.call_tool(
                "document_search",
                {
                    "user_identifier": "alice",
                    "document_id": "doc-incident-runbook",
                    "query": "INC-7781 E42-ALPHA router.yml",
                    "limit": 3,
                    "explain": True,
                },
            )
        )
        hybrid_doc_details = hybrid_doc_hits[0]["score_details"]
        check(
            checks,
            "document_search_hybrid_exact_code_match_explains_lexical_score",
            lambda: (
                hybrid_doc["chunk_count"] == 2
                and hybrid_doc_hits[0]["chunk_id"] == _chunk_id("alice", "doc-incident-runbook", 1)
                and hybrid_doc_details["lexical_score"] > 0.0
                and hybrid_doc_details["final_score"] >= hybrid_doc_details["semantic_score"]
            ),
        )

        duplicate_doc = payload(
            await client.call_tool(
                "document_ingest_text",
                {
                    "user_identifier": "alice",
                    "document_id": "doc-machine-safety",
                    "title": "Machine Safety Manual",
                    "text": document_text,
                    "source": "e2e",
                    "tags": ["manual", "idempotent"],
                    "metadata": {"revision": "1"},
                },
            )
        )
        repeated_doc = payload(
            await client.call_tool(
                "document_ingest_text",
                {
                    "user_identifier": "alice",
                    "document_id": "doc-machine-safety",
                    "title": "Machine Safety Manual",
                    "text": document_text,
                    "source": "e2e",
                    "tags": ["manual", "idempotent"],
                    "metadata": {"revision": "1"},
                },
            )
        )
        check(
            checks,
            "document_ingest_text_is_idempotent_for_same_payload",
            lambda: (
                duplicate_doc["document_id"] == repeated_doc["document_id"]
                and duplicate_doc["chunk_count"] == repeated_doc["chunk_count"] == 3
                and duplicate_doc["created_at"] == repeated_doc["created_at"]
                and repeated_doc["source"] == "e2e"
                and "idempotent" in repeated_doc["tags"]
            ),
        )

        reindexed_doc = payload(
            await client.call_tool(
                "document_reindex_text",
                {
                    "user_identifier": "alice",
                    "document_id": "doc-machine-safety",
                    "title": "Machine Safety Manual v2",
                    "text": (
                        "Reindexed procedure now uses a green reset token and a verified lockout "
                        "sequence before any energy source is restored to the machine. The "
                        "operator scans the green token at the panel and confirms the lockout "
                        "tags remain in place on every isolation point.\n"
                        "The previous blue key wording is obsolete after the recent safety "
                        "retrofit and must be struck from all printed copies of the manual. "
                        "Update the training deck and the laminated line-side card so crews stop "
                        "referencing the retired blue key entirely."
                    ),
                    "source": "e2e-reindex",
                    "tags": ["manual", "reindexed"],
                    "metadata": {"revision": "2"},
                },
            )
        )
        reindexed_hits = payload(
            await client.call_tool(
                "document_search",
                {
                    "user_identifier": "alice",
                    "document_id": "doc-machine-safety",
                    "query": "green reset token lockout",
                    "limit": 3,
                },
            )
        )
        stale_hits = payload(
            await client.call_tool(
                "document_search",
                {
                    "user_identifier": "alice",
                    "document_id": "doc-machine-safety",
                    "query": "monthly maintenance records oil inspection",
                    "limit": 3,
                },
            )
        )
        check(
            checks,
            "document_reindex_text_replaces_old_chunks_and_metadata",
            lambda: (
                reindexed_doc["chunk_count"] == 2
                and reindexed_doc["source"] == "e2e-reindex"
                and reindexed_doc["metadata"]["revision"] == "2"
                and reindexed_hits[0]["chunk_id"] == _chunk_id("alice", "doc-machine-safety", 1)
                and all("Monthly maintenance records" not in row["text"] for row in stale_hits)
            ),
        )

        payload(
            await client.call_tool(
                "document_ingest_text",
                {
                    "user_identifier": "alice",
                    "document_id": "doc-delete-me",
                    "title": "Temporary Delete Manual",
                    "text": "Temporary document contains a crimson disposal marker for deletion testing.",
                },
            )
        )
        deleted_doc = payload(
            await client.call_tool(
                "document_delete",
                {"user_identifier": "alice", "document_id": "doc-delete-me"},
            )
        )
        deleted_doc_hits = payload(
            await client.call_tool(
                "document_search",
                {
                    "user_identifier": "alice",
                    "document_id": "doc-delete-me",
                    "query": "crimson disposal marker",
                    "limit": 3,
                },
            )
        )
        check(
            checks,
            "document_delete_hides_document_from_search",
            lambda: deleted_doc["deleted"] is True and deleted_doc_hits == [],
        )

        sample = load_sample("progressive_search", index=0)
        question = sample["questions"][0]
        answer = sample["answers"][0]
        marker = answer_marker(answer)
        memoryarena_message = (
            f"MemoryArena progressive_search id={sample['id']} subtask=0\n"
            f"question: {question}\n"
            f"answer_json: {json.dumps(answer, sort_keys=True)}"
        )
        payload(
            await client.call_tool(
                "memory_store_message",
                {
                    "user_identifier": "memoryarena",
                    "session_id": "memoryarena-progressive-search",
                    "role": "assistant",
                    "content": memoryarena_message,
                },
            )
        )
        arena_hits = payload(
            await client.call_tool(
                "memory_search",
                {
                    "user_identifier": "memoryarena",
                    "query": f"MemoryArena progressive_search subtask 0 {question}",
                    "limit": 1,
                },
            )
        )
        check(
            checks,
            "memoryarena_bucket_sample_retrieves_answer_context",
            lambda: (
                marker in arena_hits[0]["content"]
                and "Chetro983/memoryarena-bucket" in sample["_source_url"]
            ),
        )
