# Phase 3: TuringDB Retrieval Baseline - Pattern Map

**Mapped:** 2026-07-13
**Files analyzed:** 8 (2 modified, ~5 new artifact files, 1 new test file)
**Analogs found:** 8 / 8

This is a snapshot phase: no new application behavior, only (1) a minimal
additive loader in existing scripts, (2) a committed artifact directory, and
(3) tests for the new loader. All analogs are existing sibling files in the
same two scripts, so conventions transfer almost verbatim.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scripts/real_document_benchmark_scoring.py` (add `load_frozen_questions`) | utility (scoring/validation helper) | transform | same file's `parse_generated_questions` (lines 190-198) + `file_digest` (141-148) | exact — same file, same role |
| `scripts/real_document_benchmark.py` (add `--frozen-questions` branch) | CLI / orchestration call-site | request-response (per-file loop branch) | same file's existing per-file loop (lines 460-507) and `parse_args` (73-95) | exact — same file |
| `tests/test_real_document_benchmark.py` (add 2 tests) | test | transform | same file's existing `test_parse_generated_questions_*` tests (lines 25-60) | exact |
| `baseline/03-turingdb/e2e-results.json` | artifact (raw JSON output) | batch | `e2e-results.json` schema emitted by `src/turing_agentmemory_mcp/e2e_score.py:134-142` | exact — this is literally that file's own output, copied verbatim |
| `baseline/03-turingdb/real-document-benchmark.json` | artifact (raw JSON output) | batch | `real_document_benchmark.py`'s own `artifact` dict (lines 432-451) | exact — copied verbatim from `--output` |
| `baseline/03-turingdb/frozen-questions.json` | artifact (derived JSON) | transform (extraction) | `artifact["documents"][*]["questions"]` (real_document_benchmark.py:490) | role-match — trivial re-keying extraction |
| `baseline/03-turingdb/corpus-manifest.json` | artifact (derived JSON) | transform (extraction) | `artifact["documents"][*]` fields `filename/suffix/bytes/sha256/conversion.page_count` (real_document_benchmark.py:475-488) | role-match — trivial field-subset extraction |
| `baseline/03-turingdb/BASELINE.md` | doc / manifest | transform (summarization) | `.planning/PROJECT.md` (markdown status-doc conventions: `##` sections, `✓`/`[ ]` checklists, prose + fenced blocks) | partial — closest committed human-readable manifest convention in repo |

## Pattern Assignments

### `scripts/real_document_benchmark_scoring.py` — add `load_frozen_questions`

**Analog:** same file, `parse_generated_questions` (lines 190-198) and `file_digest` (141-148).

**Module docstring / header convention** (lines 1-21, already present, do not duplicate):
```python
"""Deterministic scoring and evidence-grounding helpers for real_document_benchmark.py.

Split out per D-08/D-09 so the CLI/live-MCP runner in `real_document_benchmark.py`
stays under the 600-LOC cap. ...
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
```
`Path` and `json` are already imported — the new loader needs no new imports.

**Core transform pattern to copy** (validate-and-raise, mirrors `parse_generated_questions` lines 190-199 and `select_passages` lines 151-160 — raise `ValueError` with a descriptive message on any malformed input, never swallow):
```python
def parse_generated_questions(
    response: str,
    passages: list[dict[str, str]],
    *,
    expected_count: int,
) -> list[dict[str, str]]:
    payload = _json_object_from_text(response)
    rows = payload.get("questions")
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise ValueError(f"question model must return exactly {expected_count} questions")
```

**Exact new function** (per RESEARCH.md's already-designed signature — implement verbatim, it matches this file's existing style: `Path` param, `json.loads`, `ValueError` on any schema mismatch, dict return):
```python
def load_frozen_questions(path: Path) -> dict[str, list[dict[str, str]]]:
    """Load a previously-frozen per-file question set (D-08). Raises ValueError on
    schema mismatch so a corrupted/incompatible freeze fails loudly, not silently."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    by_file = payload.get("questions_by_document")
    if not isinstance(by_file, dict) or not by_file:
        raise ValueError("frozen-questions file has no questions_by_document mapping")
    for filename, rows in by_file.items():
        if not isinstance(rows, list) or not all(
            isinstance(row, dict) and {"source_id", "question", "answer", "evidence_quote"} <= row.keys()
            for row in rows
        ):
            raise ValueError(f"frozen questions for {filename} are malformed")
    return by_file
```
LOC cost: ~13 lines. File is 288/600 — ample headroom (final ~301 lines).

---

### `scripts/real_document_benchmark.py` — additive `--frozen-questions` branch

**Analog:** same file's own `parse_args` (73-95) and per-file loop (460-507).

**Import-block pattern to extend** (lines 30-55 — both `try`/`except ImportError` branches must add `load_frozen_questions` to the re-export tuple, keeping the two lists in lockstep as the file already does):
```python
try:
    from real_document_benchmark_scoring import (  # noqa: F401 - some re-exported for tests
        evidence_rank,
        file_digest,
        load_env_file,
        normalize_text,
        parse_generated_questions,
        safe_id,
        select_evidence,
        select_passages,
        summarize_results,
        utc_timestamp,
    )
except ImportError:  # running as `python scripts/real_document_benchmark.py` directly
    from scripts.real_document_benchmark_scoring import (  # noqa: F401 - some re-exported for tests
        evidence_rank,
        file_digest,
        load_env_file,
        normalize_text,
        parse_generated_questions,
        safe_id,
        select_evidence,
        select_passages,
        summarize_results,
        utc_timestamp,
    )
```
Add `load_frozen_questions` alphabetically to both import lists (2 lines added, matches existing sort order).

**Argparse pattern to extend** (lines 73-95 — one `parser.add_argument` per flag, `default=""` for optional string paths, matching `--output`/`--scope` style):
```python
    parser.add_argument("--output", default="")
    parser.add_argument("--scope", default="")
```
New flag: `parser.add_argument("--frozen-questions", default="")` (1 line).

**Core call-site branch to replace** (lines 460-473, the per-file loop — this is the exact, RESEARCH.md-verified minimal diff):
```python
# BEFORE (current, unconditional):
    for path in files:
        started = time.perf_counter()
        converted = await asyncio.to_thread(convert_document_to_markdown, path)
        passages = select_passages(
            converted.text,
            count=args.question_count,
            passage_chars=args.passage_chars,
        )
        questions, usage = await asyncio.to_thread(
            generator.generate,
            filename=path.name,
            passages=passages,
            count=args.question_count,
        )
```
```python
# AFTER (additive branch — build `frozen` once before the loop, e.g. right after
# `generator = QuestionGenerator(...)` at line 431):
    frozen = load_frozen_questions(Path(args.frozen_questions)) if args.frozen_questions else None
    ...
    for path in files:
        started = time.perf_counter()
        converted = await asyncio.to_thread(convert_document_to_markdown, path)
        if frozen is not None:
            questions = frozen[path.name]
            usage = {"frozen": True, "prompt_tokens": 0, "completion_tokens": 0, "attempt": 0}
        else:
            passages = select_passages(
                converted.text,
                count=args.question_count,
                passage_chars=args.passage_chars,
            )
            questions, usage = await asyncio.to_thread(
                generator.generate,
                filename=path.name,
                passages=passages,
                count=args.question_count,
            )
```
Net diff to this file: ~10-12 lines (2 import lines + 1 argparse line + ~8 loop lines). Verify with `bash scripts/check-file-size.sh` after editing (currently 582/600).

**Error handling convention already used at call boundaries** (`main()`, lines 570-578 — catches `ValueError`/`RuntimeError` from `run()`, prints a `BENCHMARK_FAILED` line, returns exit code 1; `load_frozen_questions`'s `ValueError` on a malformed freeze file will surface through this same existing handler with zero extra code):
```python
def main() -> int:
    args = parse_args()
    load_env_file(Path(args.env_file))
    try:
        asyncio.run(run(args))
    except (ValueError, RuntimeError) as exc:
        print(f"BENCHMARK_FAILED {exc}", flush=True)
        return 1
    return 0
```

---

### `tests/test_real_document_benchmark.py` — add 2 tests

**Analog:** same file's existing tests (lines 1-60), which import directly from `scripts.real_document_benchmark` (re-exported names) and use `json.dumps` to build fixtures inline (no separate fixture files).

**Import pattern to extend** (lines 1-14):
```python
from __future__ import annotations

import json

import pytest

from scripts.real_document_benchmark import (
    evidence_rank,
    normalize_text,
    parse_generated_questions,
    select_evidence,
    select_passages,
    summarize_results,
)
```
Add `load_frozen_questions` to this import tuple (it will be available via the re-export chain once added to `real_document_benchmark.py`'s import block above).

**Test pattern to copy** (lines 17-23 style — arrange inline JSON, act, assert on shape):
```python
def test_select_passages_returns_ten_grounded_samples_for_short_text() -> None:
    passages = select_passages("Alpha fact.\n\nBeta fact.", count=10, passage_chars=200)

    assert len(passages) == 10
    assert [item["source_id"] for item in passages] == [f"S{i}" for i in range(1, 11)]
    assert all(item["text"] for item in passages)
```
Write two new tests following this exact arrange/act/assert shape:
- `test_load_frozen_questions_round_trips` — write a valid `{"schema_version":1,"questions_by_document":{...}}` payload via `tmp_path`, load it, assert the returned dict matches; also assert a malformed payload (missing a required key) raises `ValueError` (mirrors `test_parse_generated_questions_rejects_paraphrased_answers`, lines 52+, which asserts `pytest.raises(ValueError)`).
- `test_frozen_questions_skip_generation` — monkeypatch `generator.generate` (or the `QuestionGenerator.generate` method) to raise if called, pass `--frozen-questions`, assert no exception (proves the branch actually bypasses generation, not just a schema check).

---

### `baseline/03-turingdb/*.json` artifacts — no new code, verbatim/extraction copies

**Analog:** the two scripts' own existing JSON serialization.

**`e2e-results.json` schema to copy verbatim** (`src/turing_agentmemory_mcp/e2e_score.py:134-142`):
```python
{
  "verdict": "VALIDATED_10_10" | "FAILED_SCORE_GATE",
  "score": <float, 0.0-10.0>,
  "score_gate": "10/10",
  "check_count": <int>,
  "turingdb_version": "<str>",
  "checks": [
    {"name": "...", "ok": True, "points": 1.0, "elapsed_ms": 12.3, "detail": ...},
    ...
  ],
  "cleanup": {"stopped": True, "returncode": 0}
}
```
Action: copy the file produced by `docker compose run --rm ... e2e --out /work/e2e-results.json` byte-for-byte into `baseline/03-turingdb/e2e-results.json`. No transform.

**`real-document-benchmark.json` to copy verbatim** — the `artifact` dict built in `real_document_benchmark.py:432-451` and written via `atomic_json_write` (lines 396-403, same file):
```python
    temporary...  # atomic write pattern already in file:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)
```
This is the exact JSON-serialization convention (`ensure_ascii=False, indent=2, sort_keys=True`, atomic write via temp file + `os.replace`) to reuse for `corpus-manifest.json` and `frozen-questions.json` if the executor writes them with a small ad hoc script rather than by hand.

**`corpus-manifest.json` — field-subset extraction, source fields already computed** (`real_document_benchmark.py:474-488`):
```python
        total_bytes, sha256 = file_digest(path)
        document = {
            "path": str(path),
            "filename": path.name,
            "title": path.stem,
            "suffix": path.suffix.lower(),
            "bytes": total_bytes,
            "sha256": sha256,
            "document_id": f"{safe_id(path.stem)}-{sha256[:12]}",
            "conversion": {
                "converter": converted.metadata.get("converter"),
                "chars": len(converted.text),
                "page_count": converted.metadata.get("page_count"),
                "seconds": time.perf_counter() - started,
            },
            ...
        }
```
Extract `{filename, suffix, bytes, sha256, conversion.page_count}` per document from the already-produced `real-document-benchmark.json`'s `documents[]` array — do not re-hash or re-walk the corpus. XLSX sheet counts are not present in this structure (`document_processing.py` MarkItDown path has no sheet-count field per RESEARCH.md Open Question 1) — document this as a known gap in `BASELINE.md` rather than hand-rolling an `openpyxl` extraction, unless the user confirms it's a hard requirement.

**`frozen-questions.json` — re-keying extraction**, per RESEARCH.md's designed schema (matches what `load_frozen_questions` above expects to consume in Phase 6):
```json
{
  "schema_version": 1,
  "source_benchmark_id": "real-documents-direct-mcp-<timestamp>",
  "questions_by_document": {
    "<filename>": [
      {"source_id": "S1", "question": "...", "answer": "...", "evidence_quote": "..."}
    ]
  }
}
```
Built by iterating `real-document-benchmark.json`'s `documents[]`, keying by `document["filename"]`, value = `document["questions"]` (already in the right per-question shape per `parse_generated_questions`'s output, real_document_benchmark_scoring.py:190-210ish).

---

### `baseline/03-turingdb/BASELINE.md` — human-readable manifest

**Analog:** `.planning/PROJECT.md` — closest committed markdown status/manifest document in the repo (no dedicated "artifact manifest" doc type exists yet, so this is a role-match, not exact).

**Structural convention to copy** (PROJECT.md lines 1-23, `.planning/PROJECT.md`):
```markdown
# Turing AgentMemory MCP — Stabilization Milestone

## What This Is

<prose paragraph>

## Core Value

<prose paragraph>

## Requirements

### Validated

<!-- comment explaining section provenance -->

- ✓ item — existing
```
Apply the same shape to `BASELINE.md`: `#` title, `##` sections per D-11 metadata group (Provider Config, Corpus Manifest, Frozen Questions, E2E Per-Check Results, Known Inflation Caveats, Reproduction Command), prose + fenced code blocks for exact commands, and an explicit checklist/table for D-07's per-check caveats (mirrors the `- ✓ item — existing` / `- [ ] item` checklist convention already used in PROJECT.md lines 30-60).

**Git-SHA capture pattern to copy** for the "snapshot SHA" field (`src/turing_agentmemory_mcp/benchmark.py:254-269`, already the established pattern per RESEARCH.md):
```python
def _git_commit() -> str:
    configured = os.environ.get("BENCHMARK_GIT_COMMIT") or os.environ.get("GIT_COMMIT")
    if configured:
        return configured
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return proc.stdout.strip()
    except Exception:
        return _git_head_commit()
```
For this phase, running `git rev-parse --short HEAD` directly at capture time (no need to import `benchmark.py`'s helper — this is a one-off manual/shell step, not new product code) and pasting the SHA into `BASELINE.md` is sufficient; do not add a dependency on `benchmark.py` for a markdown-authoring step.

## Shared Patterns

### JSON serialization convention
**Source:** `scripts/real_document_benchmark.py:396-403` (`atomic_json_write`)
**Apply to:** any hand-assembled artifact JSON (`corpus-manifest.json`, `frozen-questions.json`) if produced by script rather than by hand — use `json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)` and atomic write via temp-file + `os.replace`, matching the existing convention rather than inventing a new serialization style.

### Validate-and-raise-ValueError convention
**Source:** `scripts/real_document_benchmark_scoring.py` (`parse_generated_questions` lines 190-198, `select_passages` lines 151-159, `select_evidence` lines 125-137)
**Apply to:** `load_frozen_questions` — every existing helper in this file raises a descriptive `ValueError` on malformed input rather than returning partial/empty data; the new loader must follow the identical shape (already reflected in the Code Example above).

### CLI error-to-exit-code convention
**Source:** `scripts/real_document_benchmark.py:570-578` (`main()`)
**Apply to:** no new code needed — `load_frozen_questions`'s `ValueError` will propagate through the existing `try: asyncio.run(run(args)) except (ValueError, RuntimeError)` handler unchanged, printing `BENCHMARK_FAILED {exc}` and exiting 1.

### 600-LOC file-size discipline
**Source:** `scripts/check-file-size.sh:8,28-30` (no allowlist, `wc -l`-based, enforced by lefthook pre-commit)
**Apply to:** `real_document_benchmark.py` (currently 582/600) — keep the net diff to this file at or under ~15 lines; push all loader/validation logic into `real_document_benchmark_scoring.py` (currently 288/600, becomes ~301/600 after the new function). Re-run `bash scripts/check-file-size.sh` before committing.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `baseline/03-turingdb/BASELINE.md` | doc / manifest | transform (summarization) | No prior "artifact manifest" doc type exists in this repo; `.planning/PROJECT.md` is the closest structural analog (role-match only, not exact) — planner/executor has latitude on exact BASELINE.md section layout within D-11's mandatory-field constraints |
| XLSX sheet-count extraction (part of D-06's corpus manifest) | utility (transform) | transform | No existing code computes sheet counts anywhere in the repo (`document_processing.py`'s MarkItDown path doesn't expose it); RESEARCH.md flags this as Open Question 1 — confirm with user whether it's a hard requirement before hand-rolling an `openpyxl`-based one-off outside the LOC-constrained scripts |

## Metadata

**Analog search scope:** `scripts/real_document_benchmark.py`, `scripts/real_document_benchmark_scoring.py`, `src/turing_agentmemory_mcp/e2e_score.py`, `src/turing_agentmemory_mcp/e2e_score_scenarios.py`, `src/turing_agentmemory_mcp/benchmark.py`, `tests/test_real_document_benchmark.py`, `.planning/PROJECT.md`
**Files scanned:** 7 (all directly read; RESEARCH.md already contains verified line-accurate excerpts for most, cross-checked against source in this pass)
**Pattern extraction date:** 2026-07-13
