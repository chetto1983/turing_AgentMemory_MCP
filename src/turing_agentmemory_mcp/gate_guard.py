"""Phase-7 entry guard (ARC-09/D-09/D-10).

Phase 7 invokes `assert_gate_go` before performing the irreversible TuringDB
removal. It reads the committed `baseline/06-gate/gate-result.json` fresh on
every call (no caching — Tampering mitigation, T-06-02-01), validates the
D-09 schema shape, and refuses (raises) unless `verdict == "GO"`. A missing
file, malformed JSON, or a `NO_GO`/unknown verdict all fail closed. There is
no `pytest.skip` escape hatch anywhere in this contract: a missing artifact
is a hard failure, matching this repo's no-skip-as-green discipline and the
"corrupt schema is never auto-repaired" posture already established in
`tenant_registry.py`.
"""

from __future__ import annotations

import json
from pathlib import Path

_REQUIRED_FIELDS = frozenset(
    {
        "verdict",
        "tolerance",
        "provider_config",
        "corpus_verification",
        "metrics_diff",
        "baseline_bar",
        "e2e_diff",
        "latency",
        "runs",
    }
)
_VALID_VERDICTS = frozenset({"GO", "NO_GO"})


def validate_gate_result_schema(obj: object) -> None:
    """Assert `obj` is a dict carrying every D-09-mandated field with a
    recognized verdict. Raises ValueError naming the missing field or bad
    verdict; never repairs or defaults a malformed artifact."""
    if not isinstance(obj, dict):
        raise ValueError(f"gate-result.json must be a JSON object, got {type(obj).__name__}")
    missing = _REQUIRED_FIELDS - obj.keys()
    if missing:
        raise ValueError(f"gate-result.json is missing mandated D-09 field(s): {sorted(missing)}")
    verdict = obj["verdict"]
    if verdict not in _VALID_VERDICTS:
        raise ValueError(
            f"gate-result.json has an unrecognized verdict {verdict!r}; "
            f"expected one of {sorted(_VALID_VERDICTS)}"
        )


def load_verdict(path: Path) -> str:
    """Read `path` fresh (no caching), validate the D-09 schema, and return
    the verdict string. Raises on a missing file, unparseable JSON, or a
    schema/verdict violation — never returns a default."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise AssertionError(f"gate-result.json is missing or unreadable at {path}: {exc}") from exc
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"gate-result.json at {path} is not valid JSON: {exc}") from exc
    try:
        validate_gate_result_schema(obj)
    except ValueError as exc:
        raise AssertionError(str(exc)) from exc
    return obj["verdict"]


def assert_gate_go(path: Path) -> None:
    """Fail closed on the Phase-7 entry gate: read `path` fresh, validate the
    D-09 schema, and refuse (raise AssertionError) unless verdict == 'GO'.
    Never caches, never skips."""
    verdict = load_verdict(path)
    assert verdict == "GO", (
        f"Phase-7 entry blocked: gate-result.json at {path} has verdict={verdict!r}, "
        "not 'GO' -- the migration-correctness gate has not passed"
    )
