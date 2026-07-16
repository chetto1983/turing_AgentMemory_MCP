# Phase 6: Migration-Correctness Gate - Pattern Map

**Mapped:** 2026-07-16
**Files analyzed:** 6 (new) + 1 verification-only touch
**Analogs found:** 6 / 6

**IMPORTANT — no source-code fix task:** per RESEARCH.md's CRITICAL FINDING, `check()`
in `src/turing_agentmemory_mcp/e2e_score_check.py:33-55` already computes
`ok = bool(detail)`. D-05 is a verification + derivation task, not an edit. Do not
plan a diff against `e2e_score_check.py`.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scripts/gate_diff.py` (or `src/turing_agentmemory_mcp/gate_diff.py`) | service/script | batch/transform | `scripts/real_document_benchmark_scoring.py` (`_metrics`/`summarize_results`) | exact (same "read JSON, compute deterministic metrics" shape) |
| `scripts/derive_corrected_baseline.py` (D-05 derivation, optional standalone or inlined into gate_diff) | utility/transform | batch/transform | `src/turing_agentmemory_mcp/e2e_score_check.py` (`check()`) — read pattern, not edit target | role-match |
| `tests/test_gate_diff.py` | test | request-response (pure function) | `tests/test_real_document_benchmark.py` (scoring-helper unit tests) — verify existence/shape before use | role-match |
| `tests/test_gate_artifact_schema.py` | test | request-response | `tests/test_no_skip_as_green_guard.py` (pytester-isolated guard-shape test) | role-match |
| `tests/test_phase7_gate_guard.py` | test/guard | request-response, fail-closed | `tests/test_no_skip_as_green_guard.py` (exact template) | exact |
| `baseline/06-gate/GATE.md` | doc/config (committed artifact) | file-I/O | `baseline/03-turingdb/BASELINE.md` | exact |
| `baseline/06-gate/gate-result.json` | config/data (committed artifact) | file-I/O | `baseline/03-turingdb/e2e-results.json` + `baseline/04-arcadedb/e2e-results.json` (field-shape reference) | exact |
| corpus sha256 verification (D-11) — likely a function inside `gate_diff.py`, not a separate file | utility | file-I/O | `file_digest()` in `scripts/real_document_benchmark_scoring.py:142-149` | exact — reuse directly, don't re-hash |

## Pattern Assignments

### `scripts/gate_diff.py` (new script — diff/tolerance/verdict computation)

**Analog:** `scripts/real_document_benchmark_scoring.py` (325 LOC; `_metrics`/`summarize_results`) and `src/turing_agentmemory_mcp/e2e_score.py` (verdict/threshold + CLI shape)

**Imports pattern** (from `real_document_benchmark_scoring.py:1-22`):
```python
from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import unicodedata
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
```
Use plain stdlib (`json`, `hashlib`, `statistics`, `pathlib`) — this codebase's script tier
does not pull in extra deps for pure JSON post-processing.

**Core metric-aggregation pattern to imitate** (`real_document_benchmark_scoring.py:288-324`):
```python
def _metrics(rows: list[dict[str, Any]], cutoffs: tuple[int, ...]) -> dict[str, Any]:
    count = len(rows)
    ranks = [int(row.get("evidence_rank") or 0) for row in rows]
    return {
        "question_count": count,
        "search_error_count": sum(bool(row.get("error")) for row in rows),
        "mrr_at_20": (
            sum((1.0 / rank) if 0 < rank <= 20 else 0.0 for rank in ranks) / count if count else 0.0
        ),
        "recall_at_k": {
            str(cutoff): (sum(0 < rank <= cutoff for rank in ranks) / count if count else 0.0)
            for cutoff in cutoffs
        },
        ...
    }


def summarize_results(rows, *, cutoffs=DEFAULT_CUTOFFS) -> dict[str, Any]:
    by_document: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_document[str(row.get("document_id") or "unknown")].append(row)
    return {
        **_metrics(rows, cutoffs),
        "documents": {
            document_id: _metrics(document_rows, cutoffs)
            for document_id, document_rows in sorted(by_document.items())
        },
    }
```
`gate_diff.py` should NOT recompute MRR/recall from raw `results` rows — the committed
`real-document-benchmark.json`'s own `summary`/`summary.documents` fields already carry
this exact shape (produced by `summarize_results`); read those fields directly and diff
them per-document + aggregate (D-02), rather than re-deriving from `results`. Only use
`_metrics`/`summarize_results` directly if `gate_diff.py` needs to recompute a corrected
subset (e.g. the 7-doc "meaningful" slice) that isn't already summarized in the artifact.

**Verdict pattern to imitate** (`src/turing_agentmemory_mcp/e2e_score.py:161-180`):
```python
total = sum(item["points"] for item in checks)
earned = sum(item["points"] for item in checks if item["ok"])
score = round((earned / total) * 10.0, 3) if total else 0.0
result = {
    "verdict": "VALIDATED_10_10" if score >= 9.8 and len(checks) == 19 else "FAILED_SCORE_GATE",
    "score": score,
    ...
}
out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
return result
```
Mirror this exact shape for `gate_diff.py`'s own verdict: compute per-metric/per-check
pass-fail booleans, aggregate into a top-level `verdict: "GO" | "NO_GO"`, and
`json.dumps(..., indent=2, sort_keys=True)` to `baseline/06-gate/gate-result.json` —
consistent, diffable, deterministic serialization matching every other artifact in this
repo.

**CLI entrypoint pattern** (`src/turing_agentmemory_mcp/e2e_score.py:183-193`):
```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="e2e-results.json")
    args = parser.parse_args()
    result = run_e2e(Path(args.out))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["score"] >= 9.8 and result["check_count"] == 19 else 1


if __name__ == "__main__":
    raise SystemExit(main())
```
Same shape for `gate_diff.py`: `argparse`, deterministic exit code (0 = GO, 1 = NO_GO),
print the JSON to stdout as well as writing the file.

**Corpus sha256 verification (D-11) — reuse, do not reimplement:**
`scripts/real_document_benchmark_scoring.py:142-149`
```python
def file_digest(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
            total += len(chunk)
    return total, digest.hexdigest()
```
Import this directly (`from scripts.real_document_benchmark_scoring import file_digest` or
equivalent path) rather than hand-rolling a second hasher — it is the exact function that
originally generated `corpus-manifest.json`'s `sha256` field, so re-using it guarantees the
verification can't disagree with the manifest's own generation logic. Fail closed (raise/
exit non-zero) on any mismatch — matches CLAUDE.md invariant #7's "fail closed on missing
database" posture, applied here to "fail closed on corpus drift."

**Frozen-question loading (if `gate_diff.py` needs to re-validate the replay contract):**
`scripts/real_document_benchmark_scoring.py:152-160`
```python
def load_frozen_questions(path: Path) -> dict[str, list[dict[str, str]]]:
    """Load a previously-frozen per-file question set (D-08). Raises ValueError on
    schema mismatch so a corrupted/incompatible freeze fails loudly, not silently."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_file = payload.get("questions_by_document")
    if not isinstance(by_file, dict) or not by_file:
        raise ValueError("frozen-questions file has no questions_by_document mapping")
    required = {"source_id", "question", "answer", "evidence_quote"}
    ...
```
Reuse this loader; do not write a second one (Don't-Hand-Roll table in RESEARCH.md).

---

### D-05 derivation (verify-not-fix) — inline in `gate_diff.py` or a small helper

**Analog:** `src/turing_agentmemory_mcp/e2e_score_check.py:33-55` — READ ONLY, cite as evidence, do not edit.

**Derivation pattern** — apply the already-correct `ok = bool(detail)` semantics over the
existing `checks` array already committed in `baseline/03-turingdb/e2e-results.json`
(each row already has shape `{name, ok, points, elapsed_ms, detail}` or
`{name, ok:false, points, elapsed_ms, error:{type,message}}`):
```python
def corrected_checks(raw_checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    corrected = []
    for row in raw_checks:
        if "error" in row:
            corrected.append({**row, "ok": False})
        else:
            corrected.append({**row, "ok": bool(row.get("detail"))})
    return corrected
```
This is a pure transform over already-committed JSON — no live TuringDB re-run, no
`e2e_score.py` invocation (RESEARCH.md Pitfall 2: `run_e2e()` is hardcoded to
`ArcadeE2EBackend`, there is no TuringDB code path left). Record the `8120efd` /
`ab7abd0` git-ancestry evidence (already gathered in RESEARCH.md's CRITICAL FINDING) in
`GATE.md`'s D-05 section rather than re-deriving it.

---

### `tests/test_phase7_gate_guard.py` (Phase-7 entry guard, D-10)

**Analog:** `tests/test_no_skip_as_green_guard.py` (42 LOC) — full file read above, copy its shape almost verbatim.

**Fail-closed pattern to imitate** (this repo's only existing "guard that must fail
loudly, never skip" test):
```python
"""Proves the [X] guard actually fires. Uses pytest's own [mechanism] fixture so
the probe test never pollutes the real collected suite."""

from __future__ import annotations

from pathlib import Path

import pytest

def test_guard_fails_when_gate_result_missing(tmp_path: Path) -> None:
    missing = tmp_path / "gate-result.json"
    with pytest.raises(AssertionError):
        assert_gate_go(missing)  # or pytest.fail(...) directly, no skip marker

def test_guard_fails_when_verdict_is_no_go(tmp_path: Path) -> None:
    path = tmp_path / "gate-result.json"
    path.write_text('{"verdict": "NO_GO"}', encoding="utf-8")
    with pytest.raises(AssertionError):
        assert_gate_go(path)

def test_guard_passes_when_verdict_is_go(tmp_path: Path) -> None:
    path = tmp_path / "gate-result.json"
    path.write_text('{"verdict": "GO"}', encoding="utf-8")
    assert_gate_go(path)  # must not raise
```
Key discipline from the analog and RESEARCH.md Area 5: **no `pytest.skip()` escape
hatch** anywhere in the guard — a missing `gate-result.json` must be a hard failure
(`pytest.fail()`/`AssertionError`), not a skip, matching the repo's no-skip-as-green
discipline (`tests/conftest.py`'s `pytest_runtest_makereport` hookwrapper, exercised by
the very file this is modeled on). Read the JSON fresh every call, no caching (Security
Domain: "corrupted/tampered gate-result.json silently authorizing Phase-7 removal" —
Tampering mitigation).

---

### `baseline/06-gate/GATE.md` (human-readable artifact)

**Analog:** `baseline/03-turingdb/BASELINE.md` — read the first ~60 lines above for structure: `## What This Is`, `## Provider Configuration (D-XX)`, `## Corpus (D-XX)`, deviation callouts in bold, exact reproduction commands. Mirror this section structure for `GATE.md`:
- `## What This Is` (GO/NO-GO verdict + rationale, one paragraph)
- `## Provider Configuration` (same table shape: Role | Model | Dimensions | Endpoint)
- `## Metrics Diff` (per-metric, per-check, per-document — D-02/D-04)
- `## Deviations / Confounds` (GLiNER-scope nuance, latency-confound note — bold callouts like the analog's "Reranker swap (user-directed, mid-phase)")
- `## Reproduction Commands` (exact CLI invocations, matching the analog's precision about flag names — `--output` not `--out` for `real_document_benchmark.py`, per RESEARCH.md discrepancy #7)
- `## Verdict` (GO | NO_GO, one line, machine-cross-referenced to `gate-result.json`)

### `baseline/06-gate/gate-result.json` (machine artifact)

**Analog:** `baseline/03-turingdb/e2e-results.json` (top-level keys: `check_count, checks, cleanup, score, score_gate, turingdb_version, verdict`) and `baseline/04-arcadedb/e2e-results.json` (adds `backend`, `arcadedb_image`). Follow the same flat, `sort_keys=True`, `indent=2` JSON convention. D-09 mandates fields: per-metric diff, per-check diff, per-document diff, latency, tolerance params, run count, provider config, corpus sha-verification result, `verdict: GO | NO_GO`. Serialize with the same pattern as `e2e_score.py:179`:
```python
out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
```

---

## Shared Patterns

### Deterministic JSON artifact serialization
**Source:** `src/turing_agentmemory_mcp/e2e_score.py:179`, `scripts/real_document_benchmark.py` (writes to `.benchmarks/<id>.json`)
**Apply to:** `gate_diff.py`'s `gate-result.json` output
```python
out.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
```

### Fail-closed on drift/missing state (no silent fallback)
**Source:** `scripts/real_document_benchmark_scoring.py:152-160` (`load_frozen_questions` raises `ValueError` on schema mismatch); CLAUDE.md invariant #7 ("ready registry row with missing database fails closed")
**Apply to:** corpus sha256 verification (D-11), the Phase-7 guard (D-10) — never substitute, never silently pass on missing/malformed input.

### Committed artifact under gitignored directories — force-add
**Source:** `baseline/03-turingdb/` (Phase 3 D-09) — `.benchmarks/`/`e2e-results.json` are gitignored, but the copies under `baseline/<phase>/` are force-added.
**Apply to:** `baseline/06-gate/e2e-results.json`, `baseline/06-gate/real-document-benchmark.json`, and the corrected baseline-side recapture — use `git add -f`.

### Deterministic metric aggregation, not re-derivation with different weighting
**Source:** `scripts/real_document_benchmark_scoring.py:288-324` (`_metrics`/`summarize_results`)
**Apply to:** any part of `gate_diff.py` that touches per-document/aggregate MRR/recall — reuse the committed `summary` field or these exact functions; a re-derivation with different weighting would silently invalidate the comparison (Don't-Hand-Roll table, RESEARCH.md).

## No Analog Found

None — every file this phase creates has a strong, recent, in-repo analog. This is a
measurement/gate phase reusing existing comparison machinery (RESEARCH.md's core
finding), not new architectural surface.

## Metadata

**Analog search scope:** `scripts/`, `src/turing_agentmemory_mcp/e2e_score*.py`, `tests/test_no_skip_as_green_guard.py`, `tests/test_real_document_benchmark.py`, `baseline/03-turingdb/`, `baseline/04-arcadedb/`, `scripts/check-file-size.sh`
**Files scanned:** 6 read in full/targeted excerpt (e2e_score.py, e2e_score_check.py, test_no_skip_as_green_guard.py, real_document_benchmark_scoring.py ×2 ranges, check-file-size.sh, BASELINE.md head)
**Pattern extraction date:** 2026-07-16
