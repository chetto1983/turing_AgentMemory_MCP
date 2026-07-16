"""Deterministic ARC-09 migration-correctness gate diff engine.

D-05 note: `check()` in `src/turing_agentmemory_mcp/e2e_score_check.py` already
computes `ok = bool(detail)` as of commit `8120efd`, an ancestor of the
baseline capture commit `ab7abd0`. The four false-passing rows recorded in
`baseline/03-turingdb/e2e-results.json` (`detail: false`, `ok: true`) reflect
whatever ran at capture time, not current HEAD; `corrected_checks()` below is
a pure DERIVATION applied to any raw `checks` array -- it is not a source fix
(D-05 is verify+derive, not an edit; see 06-01-PLAN.md's "RESEARCH CRITICAL
FINDING contingency").
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    from real_document_benchmark_scoring import file_digest
except ImportError:  # running as `python scripts/gate_diff.py` directly
    from scripts.real_document_benchmark_scoring import file_digest

STUB_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0"}


def corrected_checks(raw_checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-derive each check row's `ok` as `ok = False if error else bool(detail)`.

    Pure transform over already-captured JSON; does not re-run any check.
    """
    corrected: list[dict[str, Any]] = []
    for row in raw_checks:
        new_row = dict(row)
        new_row["ok"] = False if "error" in row else bool(row.get("detail"))
        corrected.append(new_row)
    return corrected


def verify_corpus(corpus_root: Path, manifest_path: Path) -> dict[str, Any]:
    """Re-hash every file under `corpus_root` against `manifest_path` (D-11).

    Fails closed: any missing file or sha256 drift is reported as a mismatch
    and `ok` is False. Never silently passes on a partial/renamed/tampered corpus.
    """
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    mismatches: list[dict[str, str]] = []
    for entry in manifest.get("documents", []):
        filename = entry["filename"]
        candidate = Path(corpus_root) / filename
        if not candidate.is_file():
            mismatches.append({"filename": filename, "reason": "missing"})
            continue
        _, digest = file_digest(candidate)
        if digest != entry.get("sha256"):
            mismatches.append({"filename": filename, "reason": "sha256_mismatch"})
    return {"ok": not mismatches, "mismatches": mismatches}


def _provider_host(url: Any) -> str | None:
    if not url or not isinstance(url, str):
        return None
    return urlparse(url).hostname


def is_stub_provider(e2e_json: dict[str, Any]) -> bool:
    """True when the capture's embed/rerank endpoints are localhost stubs (D-07).

    A stub-provider capture can never authorize a GO verdict -- see
    `compute_verdict` (Task 2).
    """
    checks = e2e_json.get("checks") or []
    if not checks:
        return True
    detail = checks[0].get("detail")
    if not isinstance(detail, dict):
        return True
    embed_host = _provider_host(detail.get("embedding_base_url"))
    rerank_host = _provider_host(detail.get("rerank_base_url"))
    return embed_host in STUB_HOSTS or rerank_host in STUB_HOSTS
