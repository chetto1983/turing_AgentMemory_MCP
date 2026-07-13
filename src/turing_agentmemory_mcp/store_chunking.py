"""Document text chunking mixin for TuringAgentMemory.

Split out of store.py (D-08/D-09, phase 01-01). Pure text-splitting logic plus the
`Chunk`-graph context lookup; no other mixin depends on this module's internals beyond
the mixed-in methods resolved via the TuringAgentMemory MRO.

Ported to ArcadeDB (04-06, ARC-04/ARC-05): `_chunk_context` resolves `NEXT_CHUNK`
neighbors by `chunk_id` (`ids.stable_id()`) graph traversal via a bound-param
SQL `MATCH`-equivalent subquery (D-05, `store_documents_queries.py`) -- no
legacy synthetic-integer join parameter remains. `_document_from_row` reads ArcadeDB's own
bare (unqualified) row-key convention (`"id"`, `"chunk_count"`, ...), matching
`store_memory_read.py`'s 04-05 precedent, not the retired Cypher `RETURN d.id`
alias shape (`"d.id"`). `_active_chunk_rows`/`_document_chunk_batch_query` are
retired along with the old byte-budget batch splitter they served -- D-08's
single managed transaction has no submit-before-match batching to build for,
and `search_documents` (04-06) now sources its lexical candidates from the
native Lucene channel instead of a full active-chunk table scan.
"""

from __future__ import annotations

import re
from typing import Any

from turing_agentmemory_mcp.models import IngestedDocument
from turing_agentmemory_mcp.store_documents_queries import chunk_context_statement

_PAGE_MARKER_PATTERN = re.compile(r"<!-- page (\d+) -->")


class _ChunkingMixin:
    def _chunk_document_text(self, text: str, *, chunk_chars: int) -> list[str]:
        attributes: dict[str, object] = {
            "chunk_chars": chunk_chars,
            "text_chars": len(text),
            "chunk_count": 0,
        }
        with self._span("document.chunk", attributes):
            chunks = self._chunk_text(text, chunk_chars=chunk_chars)
            attributes["chunk_count"] = len(chunks)
            return chunks

    @classmethod
    def _chunk_text(cls, text: str, *, chunk_chars: int) -> list[str]:
        if chunk_chars < 1:
            raise ValueError("chunk_chars must be positive")
        page_markers = list(_PAGE_MARKER_PATTERN.finditer(text))
        if page_markers:
            chunks: list[str] = []
            for index, marker_match in enumerate(page_markers):
                body_end = (
                    page_markers[index + 1].start() if index + 1 < len(page_markers) else len(text)
                )
                marker = marker_match.group(0)
                body = text[marker_match.end() : body_end].strip()
                body_budget = max(1, chunk_chars - len(marker) - 2)
                chunks.extend(
                    f"{marker}\n\n{part}" for part in cls._pack_text(body, chunk_chars=body_budget)
                )
            return chunks
        return cls._pack_text(text, chunk_chars=chunk_chars)

    @staticmethod
    def _pack_text(text: str, *, chunk_chars: int) -> list[str]:
        paragraphs = [part.strip() for part in text.split("\n") if part.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs or [text.strip()]:
            while len(paragraph) > chunk_chars:
                split_at = paragraph.rfind(" ", 0, chunk_chars)
                if split_at < min(80, chunk_chars // 2):
                    split_at = chunk_chars
                part = paragraph[:split_at].strip()
                if current:
                    chunks.append(current)
                    current = ""
                if part:
                    chunks.append(part)
                paragraph = paragraph[split_at:].strip()
            if not paragraph:
                continue
            candidate = f"{current}\n\n{paragraph}" if current else paragraph
            if len(candidate) <= chunk_chars:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = paragraph
        if current:
            chunks.append(current)
        return chunks

    def _chunk_context(self, chunk_id: str) -> list[dict[str, object]]:
        if not chunk_id:
            return []
        statement, params = chunk_context_statement(chunk_id=chunk_id)
        rows = self._records(
            self._query(statement, operation="document.chunk_context", params=params)
        )
        return [
            {
                "chunk_id": row.get("chunk_id", ""),
                "locator": row.get("locator", ""),
                "text": row.get("text", ""),
            }
            for row in rows
        ]

    def _document_from_row(self, row: dict[str, Any]) -> IngestedDocument:
        tags = self._json_loads(row.get("tags_json"), [])
        metadata = self._json_loads(row.get("metadata_json"), {})
        created_at = str(row.get("created_at") or "")
        return IngestedDocument(
            document_id=str(row.get("id", "")),
            title=str(row.get("title", "")),
            chunk_count=self._int_value(row.get("chunk_count")),
            user_identifier=str(row.get("user_identifier", "")),
            created_at=created_at,
            updated_at=str(row.get("updated_at") or created_at),
            expires_at=str(row.get("expires_at") or ""),
            source=str(row.get("source", "")),
            tags=tags if isinstance(tags, list) else [],
            metadata=metadata if isinstance(metadata, dict) else {},
            text_hash=str(row.get("text_hash", "")),
            chunk_chars=self._int_value(row.get("chunk_chars")),
        )
