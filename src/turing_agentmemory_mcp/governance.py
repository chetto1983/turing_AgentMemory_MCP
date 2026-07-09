from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

SECRET_PATTERNS = (
    ("secret", re.compile(r"\bsk-[a-zA-Z0-9][a-zA-Z0-9_-]{8,}\b")),
    ("api_key", re.compile(r"(?i)\b(api[_-]?key|token|secret)\s*[:=]\s*['\"]?([a-z0-9][a-z0-9._-]{8,})")),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
)
SENSITIVE_AUDIT_KEYS = {"content", "text", "query", "embedding", "vector", "documents"}


@dataclass(frozen=True)
class RedactedText:
    text: str
    metadata: dict[str, object] = field(default_factory=dict)


class Redactor(Protocol):
    def redact(self, text: str) -> RedactedText:
        ...


class NoopRedactor:
    def redact(self, text: str) -> RedactedText:
        return RedactedText(text=text, metadata={})


class PatternRedactor:
    def redact(self, text: str) -> RedactedText:
        labels: list[str] = []
        redacted = text
        match_count = 0
        for label, pattern in SECRET_PATTERNS:
            redacted, count = pattern.subn(_token(label), redacted)
            if count:
                labels.append(label)
                match_count += count
        if not match_count:
            return RedactedText(text=text, metadata={})
        return RedactedText(
            text=redacted,
            metadata={
                "redaction": {
                    "redacted": True,
                    "match_count": match_count,
                    "labels": labels,
                }
            },
        )


class AuditSink(Protocol):
    def record(self, event: dict[str, object]) -> None:
        ...


class NoopAuditSink:
    def record(self, event: dict[str, object]) -> None:
        return


class JsonlAuditSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def record(self, event: dict[str, object]) -> None:
        clean = audit_event(event)
        line = json.dumps(clean, ensure_ascii=True, sort_keys=True, default=str)
        with self._lock, self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.write("\n")


def redactor_from_env() -> Redactor:
    enabled = os.environ.get("AGENTMEMORY_REDACTION_ENABLED", "").strip().lower()
    if enabled in {"1", "true", "yes", "on"}:
        return PatternRedactor()
    return NoopRedactor()


def audit_sink_from_env() -> AuditSink:
    path = os.environ.get("AGENTMEMORY_AUDIT_JSONL", "").strip()
    if path:
        return JsonlAuditSink(path)
    return NoopAuditSink()


def audit_event(event: dict[str, object]) -> dict[str, object]:
    clean = {
        str(key): _clean_value(value)
        for key, value in event.items()
        if str(key).lower() not in SENSITIVE_AUDIT_KEYS
    }
    clean.setdefault("timestamp", datetime.now(UTC).isoformat().replace("+00:00", "Z"))
    clean.setdefault("success", True)
    return clean


def _clean_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_clean_value(item) for item in value[:20]]
    if isinstance(value, dict):
        return {
            str(key): _clean_value(item)
            for key, item in value.items()
            if str(key).lower() not in SENSITIVE_AUDIT_KEYS
        }
    return str(value)


def _token(label: str) -> str:
    return "[" + label.upper().replace("_", "-") + "]"
