from __future__ import annotations

import json
import os
import sys
import threading
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class SpanEvent:
    timestamp: str
    name: str
    duration_ms: float
    success: bool
    attributes: dict[str, object] = field(default_factory=dict)
    error_type: str = ""
    error_message: str = ""

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        if not self.error_type:
            value.pop("error_type", None)
        if not self.error_message:
            value.pop("error_message", None)
        return value


class SpanRecorder(Protocol):
    def span(self, name: str, attributes: dict[str, object] | None = None) -> Any:
        ...


class NoopSpanRecorder:
    def span(self, name: str, attributes: dict[str, object] | None = None) -> Any:
        return nullcontext()


class RuntimeSignals:
    """Content-free readiness and degradation state for health cadence."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stages: dict[str, dict[str, object]] = {}
        self._projections: dict[str, dict[str, object]] = {}
        self._degraded_channels: Counter[str] = Counter()

    def configure_stage(
        self,
        name: str,
        *,
        ready: bool,
        identity: dict[str, object] | None = None,
    ) -> None:
        stage: dict[str, object] = {"ready": bool(ready)}
        if identity:
            stage["identity"] = _clean_attributes(identity)
        with self._lock:
            self._stages[name] = stage

    def record_degraded_channels(self, channels: list[str] | tuple[str, ...]) -> None:
        with self._lock:
            self._degraded_channels.update(str(channel) for channel in channels if channel)

    def record_projection(
        self,
        name: str,
        *,
        success: bool,
        item_count: int = 0,
        error_type: str = "",
    ) -> None:
        value: dict[str, object] = {
            "status": "ready" if success else "degraded",
            "item_count": max(0, int(item_count)),
            "updated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        if error_type:
            value["error_type"] = error_type
        with self._lock:
            self._projections[name] = value

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "stages": {name: dict(value) for name, value in sorted(self._stages.items())},
                "projections": {
                    name: dict(value) for name, value in sorted(self._projections.items())
                },
                "degraded_channel_counts": dict(sorted(self._degraded_channels.items())),
            }


class InMemorySpanRecorder:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []
        self._lock = threading.Lock()

    @contextmanager
    def span(self, name: str, attributes: dict[str, object] | None = None) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        except Exception as exc:
            self._record(
                name=name,
                started=started,
                success=False,
                attributes=attributes,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise
        else:
            self._record(name=name, started=started, success=True, attributes=attributes)

    def metrics(self) -> dict[str, dict[str, object]]:
        with self._lock:
            grouped: dict[str, list[dict[str, object]]] = {}
            for event in self.events:
                grouped.setdefault(str(event["name"]), []).append(event)
        return {name: _metrics_for_events(events) for name, events in grouped.items()}

    def _record(
        self,
        *,
        name: str,
        started: float,
        success: bool,
        attributes: dict[str, object] | None,
        error_type: str = "",
        error_message: str = "",
    ) -> None:
        event = _event_dict(
            name=name,
            started=started,
            success=success,
            attributes=attributes,
            error_type=error_type,
            error_message=error_message,
        )
        with self._lock:
            self.events.append(event)


class JsonlSpanRecorder:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    @contextmanager
    def span(self, name: str, attributes: dict[str, object] | None = None) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        except Exception as exc:
            self._write(
                name=name,
                started=started,
                success=False,
                attributes=attributes,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise
        else:
            self._write(name=name, started=started, success=True, attributes=attributes)

    def _write(
        self,
        *,
        name: str,
        started: float,
        success: bool,
        attributes: dict[str, object] | None,
        error_type: str = "",
        error_message: str = "",
    ) -> None:
        event = _event_dict(
            name=name,
            started=started,
            success=success,
            attributes=attributes,
            error_type=error_type,
            error_message=error_message,
        )
        line = json.dumps(event, ensure_ascii=True, sort_keys=True, default=str)
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.write("\n")


class StderrJsonSpanRecorder:
    @contextmanager
    def span(self, name: str, attributes: dict[str, object] | None = None) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        except Exception as exc:
            self._write(
                name=name,
                started=started,
                success=False,
                attributes=attributes,
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
            raise
        else:
            self._write(name=name, started=started, success=True, attributes=attributes)

    def _write(
        self,
        *,
        name: str,
        started: float,
        success: bool,
        attributes: dict[str, object] | None,
        error_type: str = "",
        error_message: str = "",
    ) -> None:
        print(
            json.dumps(
                _event_dict(
                    name=name,
                    started=started,
                    success=success,
                    attributes=attributes,
                    error_type=error_type,
                    error_message=error_message,
                ),
                ensure_ascii=True,
                sort_keys=True,
                default=str,
            ),
            file=sys.stderr,
            flush=True,
        )


def span_recorder_from_env() -> SpanRecorder:
    path = os.environ.get("AGENTMEMORY_OBSERVABILITY_JSONL", "").strip()
    if path:
        return JsonlSpanRecorder(path)
    enabled = os.environ.get("AGENTMEMORY_OBSERVABILITY_STDERR", "").strip().lower()
    if enabled in {"1", "true", "yes", "on"}:
        return StderrJsonSpanRecorder()
    return NoopSpanRecorder()


def _event_dict(
    *,
    name: str,
    started: float,
    success: bool,
    attributes: dict[str, object] | None,
    error_type: str = "",
    error_message: str = "",
) -> dict[str, object]:
    event = SpanEvent(
        timestamp=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        name=name,
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
        success=success,
        attributes=_clean_attributes(attributes),
        error_type=error_type,
        error_message=error_message[:500],
    ).to_dict()
    return event


def _metrics_for_events(events: list[dict[str, object]]) -> dict[str, object]:
    durations = sorted(float(event.get("duration_ms") or 0.0) for event in events)
    success_count = sum(1 for event in events if bool(event.get("success")))
    count = len(events)
    return {
        "count": count,
        "success_rate": success_count / count if count else 0.0,
        "p50_ms": _percentile(durations, 0.50),
        "p95_ms": _percentile(durations, 0.95),
        "p99_ms": _percentile(durations, 0.99),
    }


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, round((len(values) - 1) * percentile)))
    return values[index]


def _clean_attributes(attributes: dict[str, object] | None) -> dict[str, object]:
    clean: dict[str, object] = {}
    for key, value in (attributes or {}).items():
        normalized_key = str(key).strip().lower()
        if normalized_key in {"content", "query", "text", "document", "documents"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            clean[str(key)] = value
        elif isinstance(value, (list, tuple)):
            clean[str(key)] = [str(item) for item in value[:20]]
        else:
            clean[str(key)] = str(value)
    return clean
