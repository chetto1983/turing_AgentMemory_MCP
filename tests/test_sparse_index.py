from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from turing_agentmemory_mcp.sparse_index import (
    SPARSE_SCHEMA_VERSION,
    SparseDocument,
    SparseIndex,
    SparseIndexUnavailable,
    SparseMutation,
    SparseSchemaMismatch,
    compile_fts_query,
)


def document(
    source_id: str,
    content: str,
    *,
    user_identifier: str = "alice",
    kind: str = "episode",
    expires_at: str = "",
) -> SparseDocument:
    return SparseDocument(
        doc_key=f"{user_identifier}:{kind}:{source_id}",
        user_identifier=user_identifier,
        source_id=source_id,
        kind=kind,
        content=content,
        source="locomo",
        session_id="session-1",
        created_at="2026-07-10T10:00:00Z",
        expires_at=expires_at,
    )


def test_initialize_uses_versioned_fts5_wal_database(tmp_path: Path) -> None:
    path = tmp_path / "agent-memory-fts.sqlite3"
    index = SparseIndex(path)

    index.initialize()

    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert connection.execute(
            "SELECT value FROM sparse_meta WHERE key = 'schema_version'"
        ).fetchone()[0] == str(SPARSE_SCHEMA_VERSION)
        definition = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'sparse_fts'"
        ).fetchone()[0]
    assert "fts5" in definition.lower()
    assert "unicode61" in definition.lower()


def test_search_is_tenant_scoped_kind_filtered_and_expiry_aware(tmp_path: Path) -> None:
    index = SparseIndex(tmp_path / "fts.sqlite3")
    index.initialize()
    index.upsert_many(
        [
            document("m1", "Alice prefers alpine hiking"),
            document("m2", "Alice prefers city walking", kind="fact"),
            document("m3", "Alice prefers alpine hiking", user_identifier="bob"),
            document("m4", "Alice prefers alpine hiking", expires_at="2026-01-01T00:00:00Z"),
        ]
    )

    hits = index.search(
        user_identifier="alice",
        query="alpine hiking",
        kinds=["episode"],
        limit=20,
        now="2026-07-10T12:00:00Z",
    )

    assert [hit.source_id for hit in hits] == ["m1"]
    assert all(hit.user_identifier == "alice" for hit in hits)


def test_phrase_and_exact_identifier_queries_are_literal_and_safe(tmp_path: Path) -> None:
    index = SparseIndex(tmp_path / "fts.sqlite3")
    index.initialize()
    index.upsert_many(
        [
            document("conv-26", "project aurora launch notes"),
            document("conv-30", "project launch notes for aurora"),
        ]
    )

    phrase_hits = index.search(user_identifier="alice", query='"project aurora"', limit=10)
    identifier_hits = index.search(user_identifier="alice", query="conv-26", limit=10)
    hostile_hits = index.search(user_identifier="alice", query='" OR * NOT (', limit=10)

    assert [hit.source_id for hit in phrase_hits] == ["conv-26"]
    assert identifier_hits[0].source_id == "conv-26"
    assert hostile_hits == []
    assert compile_fts_query('alpha OR beta"') == (
        '(content : "alpha" OR source_id : "alpha") OR '
        '(content : "OR" OR source_id : "OR") OR '
        '(content : "beta" OR source_id : "beta")'
    )


def test_bm25_orders_more_relevant_document_first_deterministically(tmp_path: Path) -> None:
    index = SparseIndex(tmp_path / "fts.sqlite3")
    index.initialize()
    index.upsert_many(
        [
            document("m2", "hiking was mentioned once"),
            document("m1", "hiking hiking hiking alpine hiking"),
        ]
    )

    hits = index.search(user_identifier="alice", query="hiking", limit=10)

    assert [hit.source_id for hit in hits] == ["m1", "m2"]
    assert hits[0].rank < hits[1].rank


def test_upsert_and_delete_are_idempotent(tmp_path: Path) -> None:
    index = SparseIndex(tmp_path / "fts.sqlite3")
    index.initialize()
    original = document("m1", "old project name")
    replacement = document("m1", "new project name")

    index.upsert_many([original, original])
    index.upsert_many([replacement])

    assert index.search(user_identifier="alice", query="old", limit=10) == []
    assert [hit.content for hit in index.search(user_identifier="alice", query="new", limit=10)] == [
        "new project name"
    ]
    index.delete_many([replacement.doc_key, replacement.doc_key])
    assert index.search(user_identifier="alice", query="new", limit=10) == []


def test_committed_outbox_replays_after_process_restart(tmp_path: Path) -> None:
    path = tmp_path / "fts.sqlite3"
    first = SparseIndex(path)
    first.initialize()
    batch_id = first.prepare([SparseMutation.upsert(document("m1", "durable hiking memory"))])
    first.commit_batch(batch_id)

    restarted = SparseIndex(path)
    restarted.initialize()
    assert restarted.search(user_identifier="alice", query="hiking", limit=10) == []

    assert restarted.replay() == 1

    assert [hit.source_id for hit in restarted.search(user_identifier="alice", query="hiking", limit=10)] == [
        "m1"
    ]
    assert restarted.replay() == 0
    assert restarted.status()["pending_count"] == 0


def test_prepared_outbox_is_not_searchable_or_replayable(tmp_path: Path) -> None:
    index = SparseIndex(tmp_path / "fts.sqlite3")
    index.initialize()
    index.prepare([SparseMutation.upsert(document("m1", "not graph committed"))])

    assert index.replay() == 0
    assert index.search(user_identifier="alice", query="committed", limit=10) == []
    assert index.status()["prepared_count"] == 1
    assert index.status()["repair_required"] is True


def test_schema_mismatch_requires_explicit_rebuild(tmp_path: Path) -> None:
    path = tmp_path / "fts.sqlite3"
    index = SparseIndex(path)
    index.initialize()
    index.upsert_many([document("old", "stale projection")])
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE sparse_meta SET value = '0' WHERE key = 'schema_version'"
        )

    with pytest.raises(SparseSchemaMismatch):
        SparseIndex(path).initialize()

    rebuilt = SparseIndex(path)
    rebuilt.rebuild([document("new", "rebuilt projection")])

    assert rebuilt.search(user_identifier="alice", query="stale", limit=10) == []
    assert [hit.source_id for hit in rebuilt.search(user_identifier="alice", query="rebuilt", limit=10)] == [
        "new"
    ]


def test_unavailable_index_raises_explicit_error(tmp_path: Path) -> None:
    invalid_path = tmp_path / "directory.sqlite3"
    invalid_path.mkdir()

    with pytest.raises(SparseIndexUnavailable):
        SparseIndex(invalid_path).initialize()


@pytest.mark.parametrize("limit", [0, -1, 201, True])
def test_search_rejects_unbounded_limits(tmp_path: Path, limit: object) -> None:
    index = SparseIndex(tmp_path / "fts.sqlite3")
    index.initialize()

    with pytest.raises(ValueError):
        index.search(user_identifier="alice", query="memory", limit=limit)  # type: ignore[arg-type]
