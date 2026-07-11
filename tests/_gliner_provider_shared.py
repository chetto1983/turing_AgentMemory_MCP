"""Shared payload builders for the test_gliner_provider* split (not collected as tests)."""

from __future__ import annotations

from turing_agentmemory_mcp.memory_extraction import MEMORY_EXTRACTION_SCHEMA_VERSION


def extract_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "texts": ["first source text", "second source text"],
        "labels": ["project", "person"],
        "threshold": 0.42,
        "include_confidence": True,
        "include_spans": True,
    }
    payload.update(overrides)
    return payload


def memory_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "texts": ["Caroline joined the LGBTQ support group on 7 May 2023."],
        "threshold": 0.5,
        "schema_version": MEMORY_EXTRACTION_SCHEMA_VERSION,
    }
    payload.update(overrides)
    return payload


def memory_result() -> dict[str, object]:
    return {
        "entities": [
            {"text": "Caroline", "label": "person", "score": 0.99, "start": 0, "end": 8}
        ],
        "relations": [],
        "classifications": {
            "memory_kind": [{"label": "episodic_event", "score": 0.88}]
        },
    }
