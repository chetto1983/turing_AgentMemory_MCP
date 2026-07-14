"""Small result-shaping and scoring helpers shared by every E2E scenario
check. Split out of `e2e_score_scenarios.py` purely to keep that module
under the 600-LOC cap (04-09) -- `payload`/`check` are re-exported from
`e2e_score_scenarios.py` unchanged for backward compatibility with any
existing import of them from there.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any


def payload(result: Any) -> Any:
    if hasattr(result, "structured_content") and result.structured_content is not None:
        value = result.structured_content
        if isinstance(value, dict) and set(value) == {"result"}:
            return value["result"]
        return value
    if hasattr(result, "data") and result.data is not None:
        return result.data
    if hasattr(result, "content"):
        text = "".join(getattr(item, "text", "") for item in result.content)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    return result


def check(checks: list[dict[str, Any]], name: str, fn: Callable[[], Any]) -> None:
    started = time.perf_counter()
    try:
        detail = fn()
        checks.append(
            {
                "name": name,
                "ok": bool(detail),
                "points": 1.0,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "detail": detail,
            }
        )
    except Exception as exc:
        checks.append(
            {
                "name": name,
                "ok": False,
                "points": 1.0,
                "elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                "error": {"type": type(exc).__name__, "message": str(exc)[:1000]},
            }
        )
