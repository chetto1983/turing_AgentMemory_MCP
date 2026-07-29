"""Deterministic multi-hop retrieval measurements built on the canonical text normalizer."""

from __future__ import annotations

try:
    from real_document_benchmark_scoring import normalize_text
except ImportError:
    from scripts.real_document_benchmark_scoring import normalize_text

__all__ = ["normalize_text"]
