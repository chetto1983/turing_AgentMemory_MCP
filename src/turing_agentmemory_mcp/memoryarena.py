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
    local_path = os.environ.get("MEMORYARENA_JSONL")
    if local_path:
        return _load_from_file(Path(local_path), index=index, source=local_path)

    last_error: Exception | None = None
    timeout = float(os.environ.get("MEMORYARENA_TIMEOUT_SECONDS", "30"))
    for url in sample_urls(config):
        try:
            req = Request(url, headers={"User-Agent": "turing-agentmemory-mcp-e2e"})
            with urlopen(req, timeout=timeout) as resp:
                for row_index, line in enumerate(resp):
                    if row_index == index:
                        sample = json.loads(line.decode("utf-8"))
                        sample["_source_url"] = url
                        return sample
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"could not load MemoryArena {config}[{index}]: {last_error}")


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
    with path.open("r", encoding="utf-8") as handle:
        for row_index, line in enumerate(handle):
            if row_index == index:
                sample = json.loads(line)
                sample["_source_url"] = source
                return sample
    raise RuntimeError(f"MemoryArena local file has no row {index}: {path}")
