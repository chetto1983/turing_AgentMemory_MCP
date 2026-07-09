from turing_agentmemory_mcp.models import DocumentHit, MemoryItem


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
