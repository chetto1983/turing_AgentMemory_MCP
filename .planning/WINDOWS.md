---
schema_version: 1
open_count: 5
waived_count: 0
fixed_count: 0
total_count: 5
last_updated: 2026-07-29T10:42:34.379Z
---

# Broken Windows Ledger

> Cross-phase defect register. `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 07.1 | deviation | tests/test_vector_id_absent.py | 21 | Adding store_documents_ingest.py intentionally adds two parametrized store-module invariant cases, so the green suite count rises from 856 to 858 instead of remaining identical. | open |  | 2026-07-29T08:46:52.041Z |  |
| 2 | 07.1 | deviation | tests/test_temporal_graph.py |  | Preserved established internal-space canonicalization while testing D-02 type drift on one canonical surface | open |  | 2026-07-29T09:09:07.748Z |  |
| 3 | 07.1 | deviation | tests/test_store_arcadedb_retrieval.py |  | Aligned direct entity-expansion fixture with the new name-only stored stable ID | open |  | 2026-07-29T09:09:08.284Z |  |
| 4 | 07.1 | deviation | .planning/phases/07.1-document-graph-rag-and-gliner-gpu/07.1-05-PLAN.md |  | Plan 05 changed from CUDA delivery to validated CPU baseline after explicit user override; PERF-04 remains pending. | open |  | 2026-07-29T10:29:00.174Z |  |
| 5 | 07.1 | stub | src/turing_agentmemory_mcp/gliner_provider_extraction.py | 124 | batch_extract_memory still discards batch_size because its relation and classification APIs need separate concurrency analysis | open |  | 2026-07-29T10:42:34.379Z |  |

````json
[
  {
    "id": 1,
    "kind": "deviation",
    "phase": "07.1",
    "file": "tests/test_vector_id_absent.py",
    "line": 21,
    "description": "Adding store_documents_ingest.py intentionally adds two parametrized store-module invariant cases, so the green suite count rises from 856 to 858 instead of remaining identical.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-07-29T08:46:52.041Z",
    "resolved_at": null
  },
  {
    "id": 2,
    "kind": "deviation",
    "phase": "07.1",
    "file": "tests/test_temporal_graph.py",
    "line": null,
    "description": "Preserved established internal-space canonicalization while testing D-02 type drift on one canonical surface",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-07-29T09:09:07.748Z",
    "resolved_at": null
  },
  {
    "id": 3,
    "kind": "deviation",
    "phase": "07.1",
    "file": "tests/test_store_arcadedb_retrieval.py",
    "line": null,
    "description": "Aligned direct entity-expansion fixture with the new name-only stored stable ID",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-07-29T09:09:08.284Z",
    "resolved_at": null
  },
  {
    "id": 4,
    "kind": "deviation",
    "phase": "07.1",
    "file": ".planning/phases/07.1-document-graph-rag-and-gliner-gpu/07.1-05-PLAN.md",
    "line": null,
    "description": "Plan 05 changed from CUDA delivery to validated CPU baseline after explicit user override; PERF-04 remains pending.",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-07-29T10:29:00.174Z",
    "resolved_at": null
  },
  {
    "id": 5,
    "kind": "stub",
    "phase": "07.1",
    "file": "src/turing_agentmemory_mcp/gliner_provider_extraction.py",
    "line": 124,
    "description": "batch_extract_memory still discards batch_size because its relation and classification APIs need separate concurrency analysis",
    "status": "open",
    "reason": "",
    "recorded_at": "2026-07-29T10:42:34.379Z",
    "resolved_at": null
  }
]
````
