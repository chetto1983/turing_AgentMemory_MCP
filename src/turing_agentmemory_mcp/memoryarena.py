from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

BUCKET_BASE = "https://huggingface.co/buckets/Chetro983/memoryarena-bucket/resolve"
DATASET_BASE = "https://huggingface.co/datasets/ZexueHe/memoryarena/resolve/main"


def sample_urls(config: str) -> list[str]:
    bucket_base = os.environ.get("MEMORYARENA_BUCKET_BASE", BUCKET_BASE).rstrip("/")
    dataset_base = os.environ.get("MEMORYARENA_DATASET_BASE", DATASET_BASE).rstrip("/")
    return [
        f"{bucket_base}/{config}/data.jsonl",
        f"{dataset_base}/{config}/data.jsonl",
    ]


def load_sample(config: str = "progressive_search", index: int = 0) -> dict[str, Any]:
    samples = load_samples(config=config, start_index=index, limit=1)
    if not samples:
        raise RuntimeError(f"could not load MemoryArena {config}[{index}]")
    return samples[0]


def load_samples(
    config: str = "progressive_search",
    *,
    start_index: int = 0,
    limit: int = 1,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    local_path = os.environ.get("MEMORYARENA_JSONL")
    if local_path:
        return _load_samples_from_file(Path(local_path), start_index=start_index, limit=limit, source=local_path)

    last_error: Exception | None = None
    timeout = float(os.environ.get("MEMORYARENA_TIMEOUT_SECONDS", "30"))
    for url in sample_urls(config):
        try:
            req = Request(url, headers={"User-Agent": "turing-agentmemory-mcp-e2e"})
            with urlopen(req, timeout=timeout) as resp:
                samples: list[dict[str, Any]] = []
                for row_index, line in enumerate(resp):
                    if row_index < start_index:
                        continue
                    if len(samples) >= limit:
                        break
                    sample = json.loads(line.decode("utf-8"))
                    sample["_source_url"] = url
                    samples.append(sample)
                if samples:
                    return samples
        except Exception as exc:
            last_error = exc
    raise RuntimeError(
        f"could not load MemoryArena {config}[{start_index}:{start_index + limit}]: {last_error}"
    )


def answer_marker(answer: Any) -> str:
    if isinstance(answer, dict):
        for key in ("target_asin", "name", "paper_name"):
            if answer.get(key):
                return str(answer[key])
        for value in answer.values():
            if isinstance(value, list) and value:
                return str(value[0])
            if isinstance(value, (str, int, float)):
                return str(value)
    if isinstance(answer, list) and answer:
        return answer_marker(answer[0])
    return str(answer)[:80]


def _load_from_file(path: Path, *, index: int, source: str) -> dict[str, Any]:
    samples = _load_samples_from_file(path, start_index=index, limit=1, source=source)
    if not samples:
        raise RuntimeError(f"MemoryArena local file has no row {index}: {path}")
    return samples[0]


def _load_samples_from_file(
    path: Path,
    *,
    start_index: int,
    limit: int,
    source: str,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for row_index, line in enumerate(handle):
            if row_index < start_index:
                continue
            if len(samples) >= limit:
                break
            sample = json.loads(line)
            sample["_source_url"] = source
            samples.append(sample)
    if not samples:
        raise RuntimeError(f"MemoryArena local file has no rows from {start_index}: {path}")
    return samples
