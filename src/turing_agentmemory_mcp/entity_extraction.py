from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_METADATA_KEY = "entity_extraction"
LEGACY_METADATA_KEYS = ("entity_detection",)
DEFAULT_GLINER_MODEL = "gliner-community/gliner_small-v2.5"
DEFAULT_GLINER_LABELS = [
    "person",
    "organization",
    "location",
    "product",
    "project",
    "technology",
    "programming language",
    "library",
    "framework",
    "file path",
    "error code",
    "feature",
    "task",
    "decision",
    "preference",
    "event",
    "date",
    "metric",
    "version",
]


@dataclass(frozen=True)
class ProcessedText:
    text: str
    metadata: dict[str, object]


class EntityProcessor(Protocol):
    def process(self, text: str) -> ProcessedText:
        ...


class NoopEntityProcessor:
    metadata_keys: tuple[str, ...] = ()

    def process(self, text: str) -> ProcessedText:
        return ProcessedText(text=text, metadata={})


@dataclass
class GLiNEREntityProcessor:
    model: Any
    model_name: str
    labels: list[str]
    backend: str
    threshold: float = 0.5
    redact: bool = False
    metadata_key: str = DEFAULT_METADATA_KEY

    @property
    def metadata_keys(self) -> tuple[str, ...]:
        return (self.metadata_key, *LEGACY_METADATA_KEYS)

    @classmethod
    def from_env(cls) -> GLiNEREntityProcessor:
        model_name = os.environ.get("GLINER_MODEL", DEFAULT_GLINER_MODEL).strip() or DEFAULT_GLINER_MODEL
        backend = (os.environ.get("GLINER_BACKEND", "auto").strip() or "auto").lower()
        if backend == "auto":
            model_key = model_name.lower()
            if "onnx" in model_key:
                backend = "gliner2_onnx"
            elif "gliner2" in model_key:
                backend = "gliner2"
            else:
                backend = "gliner"
        labels = _split_csv(os.environ.get("GLINER_LABELS")) or list(DEFAULT_GLINER_LABELS)
        threshold = float(os.environ.get("GLINER_THRESHOLD", "0.5"))
        redact = _env_bool("GLINER_REDACT")
        metadata_key = os.environ.get("GLINER_METADATA_KEY", DEFAULT_METADATA_KEY).strip()
        if not metadata_key:
            metadata_key = DEFAULT_METADATA_KEY
        model = _load_model(backend=backend, model_name=model_name)
        return cls(
            model=model,
            model_name=model_name,
            labels=labels,
            backend=backend,
            threshold=threshold,
            redact=redact,
            metadata_key=metadata_key,
        )

    def process(self, text: str) -> ProcessedText:
        if not text.strip():
            return ProcessedText(text=text, metadata={})
        return _processed_text_from_entities(
            self._predict(text),
            source_text=text,
            backend=self.backend,
            model_name=self.model_name,
            labels=self.labels,
            threshold=self.threshold,
            redact=self.redact,
            metadata_key=self.metadata_key,
        )

    def _predict(self, text: str) -> Any:
        if self.backend == "gliner2_onnx":
            return list(self.model.extract_entities(text, self.labels, threshold=self.threshold))
        if self.backend == "gliner2":
            return self.model.extract_entities(
                text,
                self.labels,
                threshold=self.threshold,
                include_confidence=True,
                include_spans=True,
            )
        return list(self.model.predict_entities(text, self.labels, threshold=self.threshold))


@dataclass(frozen=True)
class HTTPGLiNEREntityProcessor:
    base_url: str
    model_name: str
    labels: list[str]
    threshold: float = 0.5
    redact: bool = False
    metadata_key: str = DEFAULT_METADATA_KEY
    timeout_s: float = 30.0
    backend: str = "gliner2_http"

    @property
    def metadata_keys(self) -> tuple[str, ...]:
        return (self.metadata_key, *LEGACY_METADATA_KEYS)

    @classmethod
    def from_env(cls) -> HTTPGLiNEREntityProcessor:
        model_name = os.environ.get("GLINER_MODEL", DEFAULT_GLINER_MODEL).strip() or DEFAULT_GLINER_MODEL
        labels = _split_csv(os.environ.get("GLINER_LABELS")) or list(DEFAULT_GLINER_LABELS)
        threshold = float(os.environ.get("GLINER_THRESHOLD", "0.5"))
        redact = _env_bool("GLINER_REDACT")
        metadata_key = os.environ.get("GLINER_METADATA_KEY", DEFAULT_METADATA_KEY).strip()
        base_url = os.environ.get("GLINER_BASE_URL", "http://agentmemory-gliner:8080").strip()
        timeout_s = float(os.environ.get("GLINER_TIMEOUT_SECONDS", "30"))
        if not metadata_key:
            metadata_key = DEFAULT_METADATA_KEY
        if not base_url:
            raise ValueError("GLINER_BASE_URL must be non-empty")
        if not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("GLINER_TIMEOUT_SECONDS must be a positive finite number")
        return cls(
            base_url=base_url.rstrip("/"),
            model_name=model_name,
            labels=labels,
            threshold=threshold,
            redact=redact,
            metadata_key=metadata_key,
            timeout_s=timeout_s,
        )

    def process(self, text: str) -> ProcessedText:
        return self.process_many([text])[0]

    def process_many(self, texts: list[str]) -> list[ProcessedText]:
        if not texts:
            return []
        active_indices = [index for index, text in enumerate(texts) if text.strip()]
        processed = [ProcessedText(text=text, metadata={}) for text in texts]
        if not active_indices:
            return processed
        active_texts = [texts[index] for index in active_indices]
        payload = {
            "texts": active_texts,
            "labels": self.labels,
            "threshold": self.threshold,
            "include_confidence": True,
            "include_spans": True,
        }
        request = Request(
            self.base_url + "/extract",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                decoded = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"GLiNER provider HTTP {exc.code} at {self.base_url}") from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise RuntimeError(f"GLiNER provider unavailable at {self.base_url}") from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"GLiNER provider returned invalid JSON at {self.base_url}") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError(f"GLiNER provider returned invalid JSON at {self.base_url}")
        results = decoded.get("results")
        if not isinstance(results, list):
            raise RuntimeError(f"GLiNER provider returned invalid results at {self.base_url}")
        if len(results) != len(active_texts):
            raise RuntimeError(
                f"GLiNER provider returned {len(results)} results for {len(active_texts)} texts at {self.base_url}"
            )
        provider_model = decoded.get("model")
        if provider_model != self.model_name:
            raise RuntimeError(f"GLiNER provider model mismatch at {self.base_url}")
        for index, raw_entities in zip(active_indices, results, strict=True):
            processed[index] = _processed_text_from_entities(
                raw_entities,
                source_text=texts[index],
                backend=self.backend,
                model_name=self.model_name,
                labels=self.labels,
                threshold=self.threshold,
                redact=self.redact,
                metadata_key=self.metadata_key,
            )
        return processed


def entity_processor_from_env() -> EntityProcessor:
    if not _env_bool("GLINER_ENABLED"):
        return NoopEntityProcessor()
    backend = (os.environ.get("GLINER_BACKEND", "auto").strip() or "auto").lower()
    if backend == "gliner2_http":
        return HTTPGLiNEREntityProcessor.from_env()
    return GLiNEREntityProcessor.from_env()


def entity_metadata_search_text(metadata: dict[str, object]) -> str:
    terms: list[str] = []
    for key in (DEFAULT_METADATA_KEY, *LEGACY_METADATA_KEYS):
        payload = metadata.get(key)
        if not isinstance(payload, dict):
            continue
        for label in payload.get("labels") or []:
            if isinstance(label, str) and label.strip():
                terms.append(label)
        for entity in payload.get("entities") or []:
            if not isinstance(entity, dict):
                continue
            label = entity.get("label")
            text = entity.get("text")
            if isinstance(label, str) and label.strip():
                terms.append(label)
            if isinstance(text, str) and text.strip():
                terms.append(text)
    return " ".join(terms)


def _load_model(*, backend: str, model_name: str) -> Any:
    if backend == "gliner2_onnx":
        try:
            from gliner2_onnx import GLiNER2ONNXRuntime
        except ImportError as exc:
            raise RuntimeError(
                "GLINER_ENABLED is set with GLINER_BACKEND=gliner2_onnx, "
                "but gliner2-onnx is not installed. Install with the 'gliner' optional extra."
            ) from exc
        kwargs: dict[str, object] = {}
        precision = os.environ.get("GLINER_PRECISION", "").strip()
        providers = _split_csv(os.environ.get("GLINER_PROVIDERS"))
        if precision:
            kwargs["precision"] = precision
        if providers:
            kwargs["providers"] = providers
        return GLiNER2ONNXRuntime.from_pretrained(model_name, **kwargs)
    if backend == "gliner":
        try:
            from gliner import GLiNER
        except ImportError as exc:
            raise RuntimeError(
                "GLINER_ENABLED is set with GLINER_BACKEND=gliner, "
                "but gliner is not installed. Install with the 'gliner' optional extra."
            ) from exc
        return GLiNER.from_pretrained(model_name)
    if backend == "gliner2":
        try:
            from gliner2 import GLiNER2
        except ImportError as exc:
            raise RuntimeError(
                "GLINER_ENABLED is set with GLINER_BACKEND=gliner2, "
                "but gliner2 is not installed. Install with the 'gliner' optional extra."
            ) from exc
        return GLiNER2.from_pretrained(model_name)
    raise ValueError("GLINER_BACKEND must be one of: auto, gliner, gliner2, gliner2_onnx")


def _processed_text_from_entities(
    raw_entities: Any,
    *,
    source_text: str,
    backend: str,
    model_name: str,
    labels: list[str],
    threshold: float,
    redact: bool,
    metadata_key: str,
) -> ProcessedText:
    entities = _normalize_entities(
        raw_entities,
        source_text=source_text,
        include_text=not redact,
    )
    if not entities:
        return ProcessedText(text=source_text, metadata={})
    return ProcessedText(
        text=_redact_text(source_text, entities) if redact else source_text,
        metadata={
            metadata_key: {
                "backend": backend,
                "model": model_name,
                "labels": labels,
                "threshold": threshold,
                "redacted": redact,
                "entity_count": len(entities),
                "entities": entities,
            }
        },
    )


def _normalize_entities(
    raw_entities: Any,
    *,
    source_text: str,
    include_text: bool,
) -> list[dict[str, object]]:
    entities: list[dict[str, object]] = []
    search_offsets: dict[tuple[str, str], int] = {}
    for raw in _flatten_entities(raw_entities):
        label = str(_entity_field(raw, "label", "entity", "type") or "").strip()
        text = str(_entity_field(raw, "text", "span") or "")
        start = _optional_int(_entity_field(raw, "start", "start_char", "start_idx"))
        end = _optional_int(_entity_field(raw, "end", "end_char", "end_idx"))
        has_start = _entity_field_present(raw, "start", "start_char", "start_idx")
        has_end = _entity_field_present(raw, "end", "end_char", "end_idx")
        if has_start or has_end:
            if start is None or end is None:
                continue
            if text and (start < 0 or end > len(source_text) or source_text[start:end] != text):
                continue
        else:
            if not text:
                continue
            key = (label, text)
            found_at = source_text.find(text, search_offsets.get(key, 0))
            if found_at < 0:
                continue
            start = found_at
            end = found_at + len(text)
            search_offsets[key] = end
        if not label or start < 0 or end <= start or end > len(source_text):
            continue
        entity: dict[str, object] = {
            "label": label,
            "start": start,
            "end": end,
        }
        score = _optional_float(_entity_field(raw, "score", "confidence"))
        if score is not None:
            entity["score"] = score
        if include_text:
            entity["text"] = text or source_text[start:end]
        entities.append(entity)
    entities.sort(key=lambda item: (int(item["start"]), int(item["end"]), str(item["label"])))
    return entities


def _flatten_entities(raw: Any) -> list[Any]:
    if isinstance(raw, (list, tuple)):
        return list(raw)
    if not isinstance(raw, dict):
        return []
    grouped = raw.get("entities")
    if not isinstance(grouped, dict):
        return []
    flattened: list[Any] = []
    for label, values in grouped.items():
        if not isinstance(label, str) or not isinstance(values, (list, tuple)):
            continue
        for value in values:
            if isinstance(value, dict):
                entity = dict(value)
                entity["label"] = label
                flattened.append(entity)
            elif isinstance(value, str):
                flattened.append({"label": label, "text": value})
    return flattened


def _entity_field(entity: Any, *names: str) -> object | None:
    if isinstance(entity, dict):
        for name in names:
            if name in entity:
                return entity[name]
        return None
    for name in names:
        if hasattr(entity, name):
            return getattr(entity, name)
    return None


def _entity_field_present(entity: Any, *names: str) -> bool:
    if isinstance(entity, dict):
        return any(name in entity for name in names)
    return any(hasattr(entity, name) for name in names)


def _redact_text(text: str, entities: list[dict[str, object]]) -> str:
    redacted = text
    next_start = len(text) + 1
    for entity in sorted(entities, key=lambda item: int(item["start"]), reverse=True):
        start = int(entity["start"])
        end = int(entity["end"])
        if end > next_start:
            continue
        token = _redaction_token(str(entity["label"]))
        redacted = redacted[:start] + token + redacted[end:]
        next_start = start
    return redacted


def _redaction_token(label: str) -> str:
    token = []
    for char in label.upper().replace(" ", "_").replace("-", "_"):
        if char.isalnum() or char == "_":
            token.append(char)
    return "[" + ("".join(token).strip("_") or "ENTITY") + "]"


def _split_csv(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _env_bool(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _optional_int(value: object | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: object | None) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None
