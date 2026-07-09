from turing_agentmemory_mcp.models import DocumentHit, IngestedDocument, MemoryItem


def test_models_export_dicts() -> None:
    memory = MemoryItem(
        id="m1",
        user_identifier="alice",
        kind="message",
        content="hello",
        score=1.0,
    )
    hit = DocumentHit(
        chunk_id="c1",
        document_id="d1",
        title="Doc",
        locator="chunk=1",
        text="hello",
        score=1.0,
    )
    assert memory.to_dict()["user_identifier"] == "alice"
    assert hit.to_dict()["locator"] == "chunk=1"


def test_score_details_are_omitted_unless_present() -> None:
    memory = MemoryItem(
        id="m1",
        user_identifier="alice",
        kind="message",
        content="hello",
        score=1.0,
    )

    assert "score_details" not in memory.to_dict()


def test_score_details_are_exported_when_present() -> None:
    memory = MemoryItem(
        id="m1",
        user_identifier="alice",
        kind="message",
        content="hello",
        score=0.9,
        score_details={"semantic_score": 0.8, "final_score": 0.9},
    )

    assert memory.to_dict()["score_details"] == {"semantic_score": 0.8, "final_score": 0.9}


def test_memory_metadata_fields_export_as_structured_values() -> None:
    memory = MemoryItem(
        id="m1",
        user_identifier="alice",
        kind="message",
        content="hello",
        score=1.0,
        created_at="2026-07-09T12:00:00Z",
        updated_at="2026-07-09T12:01:00Z",
        source="chat",
        tags=["preference", "coffee"],
        metadata={"confidence": 0.9},
    )

    exported = memory.to_dict()
    assert exported["created_at"] == "2026-07-09T12:00:00Z"
    assert exported["updated_at"] == "2026-07-09T12:01:00Z"
    assert exported["source"] == "chat"
    assert exported["tags"] == ["preference", "coffee"]
    assert exported["metadata"] == {"confidence": 0.9}


def test_ingested_document_metadata_fields_export_as_structured_values() -> None:
    document = IngestedDocument(
        document_id="doc-1",
        title="Runbook",
        chunk_count=3,
        user_identifier="alice",
        created_at="2026-07-09T12:00:00Z",
        updated_at="2026-07-09T12:01:00Z",
        source="upload",
        tags=["runbook", "safety"],
        metadata={"revision": "A"},
    )

    exported = document.to_dict()
    assert exported["created_at"] == "2026-07-09T12:00:00Z"
    assert exported["updated_at"] == "2026-07-09T12:01:00Z"
    assert exported["source"] == "upload"
    assert exported["tags"] == ["runbook", "safety"]
    assert exported["metadata"] == {"revision": "A"}
