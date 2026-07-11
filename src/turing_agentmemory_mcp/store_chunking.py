"""Document text chunking mixin for TuringAgentMemory.

Split out of store.py (D-08/D-09, phase 01-01). Pure text-splitting logic plus the
`Chunk`-graph context lookup; no other mixin depends on this module's internals beyond
the mixed-in methods resolved via the TuringAgentMemory MRO.
"""

from __future__ import annotations

import re
from typing import Any

from turing_agentmemory_mcp.ids import quote
from turing_agentmemory_mcp.models import IngestedDocument

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

    def _chunk_context(self, vector: int) -> list[dict[str, object]]:
        if vector <= 0:
            return []
        try:
            rows = self._records(
                self._query(
                    "MATCH (c:Chunk)-[:NEXT_CHUNK]->(n:Chunk) "
                    f'WHERE c.vector_id = {vector} AND c.status = "active" AND n.status = "active" '
                    "RETURN n.chunk_id, n.locator, n.text",
                    operation="document.chunk_context",
                )
            )
        except Exception as exc:
            if "Unknown edge type: NEXT_CHUNK" not in str(exc):
                raise
            return []
        return [
            {
                "chunk_id": row.get("n.chunk_id", ""),
                "locator": row.get("n.locator", ""),
                "text": row.get("n.text", ""),
            }
            for row in rows
        ]

    def _active_chunk_rows(
        self, user_identifier: str, *, document_id: str = ""
    ) -> list[dict[str, Any]]:
        document_filter = ""
        if document_id:
            document_filter = f' AND c.document_id = "{quote(document_id)}"'
        try:
            return self._records(
                self._query(
                    f'MATCH (c:Chunk) WHERE c.user_identifier = "{quote(user_identifier)}" '
                    f'AND c.status = "active"{document_filter} '
                    "RETURN c.chunk_id, c.document_id, c.title, c.locator, c.text, c.vector_id, "
                    "c.created_at, c.updated_at, c.expires_at, c.source, c.tags_json, c.metadata_json",
                    operation="document.active_chunk_rows",
                )
            )
        except Exception as exc:
            if "Unknown label: Chunk" not in str(exc):
                raise
            return []

    def _document_from_row(self, row: dict[str, Any]) -> IngestedDocument:
        tags = self._json_loads(row.get("d.tags_json"), [])
        metadata = self._json_loads(row.get("d.metadata_json"), {})
        created_at = str(row.get("d.created_at") or "")
        return IngestedDocument(
            document_id=str(row.get("d.id", "")),
            title=str(row.get("d.title", "")),
            chunk_count=self._int_value(row.get("d.chunk_count")),
            user_identifier=str(row.get("d.user_identifier", "")),
            created_at=created_at,
            updated_at=str(row.get("d.updated_at") or created_at),
            expires_at=str(row.get("d.expires_at") or ""),
            source=str(row.get("d.source", "")),
            tags=tags if isinstance(tags, list) else [],
            metadata=metadata if isinstance(metadata, dict) else {},
            text_hash=str(row.get("d.text_hash", "")),
            chunk_chars=self._int_value(row.get("d.chunk_chars")),
        )

    @staticmethod
    def _document_chunk_batch_query(
        *,
        user_identifier: str,
        document_id: str,
        doc_var: str,
        units: list[Any],
    ) -> str:
        first = units[0]
        matches = [f"({doc_var}:Document)"]
        predicates = [
            f'{doc_var}.id = "{quote(document_id)}"',
            f'{doc_var}.user_identifier = "{quote(user_identifier)}"',
        ]
        if first.previous_var:
            matches.append(f"({first.previous_var}:Chunk)")
            predicates.extend(
                [
                    f'{first.previous_var}.chunk_id = "{quote(first.previous_chunk_id)}"',
                    f'{first.previous_var}.user_identifier = "{quote(user_identifier)}"',
                ]
            )
        literals: list[str] = []
        for unit in units:
            literals.extend((unit.node, unit.has_chunk_edge))
            if unit.next_chunk_edge:
                literals.append(unit.next_chunk_edge)
        return (
            "MATCH "
            + ", ".join(matches)
            + " WHERE "
            + " AND ".join(predicates)
            + " CREATE "
            + ", ".join(literals)
        )
