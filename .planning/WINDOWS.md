---
schema_version: 1
open_count: 1
waived_count: 0
fixed_count: 0
total_count: 1
last_updated: 2026-07-29T08:46:52.041Z
---

# Broken Windows Ledger

> Cross-phase defect register. `/gsd-ship` blocks while `open_count > 0`.
> Waive with `gsd-tools windows waive <id> "<reason>"` (reason required).
> Mark fixed with `gsd-tools windows fixed <id>`.

| id | phase | kind | file | line | description | status | reason | recorded_at | resolved_at |
|----|-------|------|------|------|-------------|--------|--------|-------------|-------------|
| 1 | 07.1 | deviation | tests/test_vector_id_absent.py | 21 | Adding store_documents_ingest.py intentionally adds two parametrized store-module invariant cases, so the green suite count rises from 856 to 858 instead of remaining identical. | open |  | 2026-07-29T08:46:52.041Z |  |

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
  }
]
````
