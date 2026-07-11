from __future__ import annotations

import re
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from .sparse_index import SparseDocument, SparseIndex

_SAFE_TIMESTAMP = re.compile(r"^[A-Za-z0-9_.-]+$")


class CommunityRebuilder(Protocol):
    def rebuild_communities(self, *, user_identifier: str) -> dict[str, object]: ...


def repair_vector_index(
    turing_home: str | Path,
    *,
    timestamp: str | None = None,
    apply: bool = False,
) -> dict[str, object]:
    """Quarantine a corrupt TuringDB vector directory and create a fresh one."""
    home = Path(turing_home).expanduser().resolve()
    stamp = _repair_timestamp(timestamp)
    vector_dir = home / "vector"
    quarantine_dir = home / f"vector.corrupt-{stamp}"
    result = {
        "operation": "vector_index_repair",
        "turing_home": str(home),
        "vector_dir": str(vector_dir),
        "quarantine_dir": str(quarantine_dir),
        "applied": False,
        "actions": [
            "move vector directory to quarantine",
            "create fresh empty vector directory",
            "restart the MCP/TuringDB stack so bootstrap recreates vector indexes",
        ],
        "notes": [
            "Graph/data files are not modified.",
            "Run a document or memory reindex after repair if vector rows need to be rebuilt.",
        ],
    }

    if not vector_dir.exists():
        return {
            **result,
            "status": "skipped",
            "notes": [*result["notes"], "Vector directory does not exist."],
        }
    if not vector_dir.is_dir():
        raise NotADirectoryError(str(vector_dir))
    if quarantine_dir.exists():
        raise FileExistsError(str(quarantine_dir))
    if not apply:
        return {**result, "status": "would_repair"}

    home.mkdir(parents=True, exist_ok=True)
    shutil.move(str(vector_dir), str(quarantine_dir))
    vector_dir.mkdir(parents=True, exist_ok=False)
    return {**result, "status": "repaired", "applied": True}


def repair_sparse_projection(
    path: str | Path,
    documents: Sequence[SparseDocument],
    *,
    apply: bool = False,
) -> dict[str, object]:
    """Replace the recoverable FTS projection from canonical graph documents."""
    resolved = Path(path).expanduser().resolve()
    result = {
        "operation": "sparse_projection_repair",
        "path": str(resolved),
        "canonical_document_count": len(documents),
        "applied": False,
        "notes": [
            "TuringDB graph records are not modified.",
            "The sparse projection and its outbox are replaced atomically.",
        ],
    }
    if not apply:
        return {**result, "status": "would_rebuild"}
    index = SparseIndex(resolved)
    index.rebuild(documents)
    return {
        **result,
        "status": "rebuilt",
        "applied": True,
        "projection": index.status(),
    }


def repair_community_projection(
    store: CommunityRebuilder,
    *,
    user_identifier: str,
    apply: bool = False,
) -> dict[str, object]:
    """Rebuild derived community graph, sparse, and vector projections."""
    if not isinstance(user_identifier, str) or not user_identifier.strip():
        raise ValueError("user_identifier must be non-empty")
    result = {
        "operation": "community_projection_repair",
        "user_identifier": user_identifier,
        "applied": False,
        "notes": [
            "Memory, entity, fact, and mention records are not modified.",
            "Community nodes and their sparse/vector projections are derived and replaceable.",
        ],
    }
    if not apply:
        return {**result, "status": "would_rebuild"}
    projection = store.rebuild_communities(user_identifier=user_identifier)
    return {
        **result,
        "status": "rebuilt",
        "applied": True,
        "projection": projection,
    }


def _repair_timestamp(timestamp: str | None) -> str:
    value = timestamp or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if not _SAFE_TIMESTAMP.fullmatch(value):
        raise ValueError("timestamp may contain only letters, numbers, dots, dashes, or underscores")
    return value
