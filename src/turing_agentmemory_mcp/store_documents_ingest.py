"""Document ingest write-path mixin for TuringAgentMemory.

Split out of store_documents.py (phase 07.1-02) to create 600-LOC headroom for
FIX-08's per-chunk extraction and GRAPH-04's fusion port. No instance state is
defined here; all helpers resolve via the TuringAgentMemory MRO.
"""

from __future__ import annotations

from turing_agentmemory_mcp.ids import stable_id
from turing_agentmemory_mcp.models import IngestedDocument
from turing_agentmemory_mcp.sparse_encoder import sparse_vector
from turing_agentmemory_mcp.store_documents_queries import (
    chunk_create_statement,
    chunk_hard_delete_statement,
    chunk_metadata_update_statement,
    document_create_statement,
    document_edge_statement,
    document_hard_delete_statement,
    document_update_statement,
    has_chunk_edge_statement,
    next_chunk_edge_statement,
)


class _DocumentsIngestMixin:
    def ingest_document_text(
        self,
        *,
        user_identifier: str,
        title: str,
        text: str,
        document_id: str | None = None,
        chunk_chars: int = 360,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> IngestedDocument:
        self._require_user(user_identifier)
        # user_identifier deliberately omitted -- _StoreCore._span sanitizes
        # centrally (ARC-07/D-07); this call site should not read as
        # exporting raw identity even though the choke point is the backstop.
        with self._span(
            "document.ingest_text",
            {
                "document_id": document_id or "",
                "source": source,
            },
        ):
            if not title.strip():
                raise ValueError("title is required")
            if not text.strip():
                raise ValueError("text is required")
            text, metadata = self._redact_for_storage(text, dict(metadata or {}))
            for key in getattr(self.entity_processor, "metadata_keys", ()):
                metadata.pop(str(key), None)
            document_id = document_id or stable_id("doc", user_identifier, title, text[:128])
            text_hash = self._document_text_hash(text)
            chunks = self._chunk_document_text(text, chunk_chars=chunk_chars)
            self._ensure_user(user_identifier)
            existing = self.get_document(user_identifier=user_identifier, document_id=document_id)
            if existing is not None:
                if existing.text_hash != text_hash or existing.chunk_chars != chunk_chars:
                    raise ValueError(
                        f"document {document_id} already exists with different text; use document_reindex_text"
                    )
                return self._update_document_metadata(
                    user_identifier=user_identifier,
                    document_id=document_id,
                    title=title,
                    source=source,
                    tags=tags,
                    metadata=metadata,
                    expires_at=expires_at,
                    preserve_updated_at=False,
                )
            item = self._create_document(
                user_identifier=user_identifier,
                document_id=document_id,
                title=title,
                text=text,
                chunks=chunks,
                chunk_chars=chunk_chars,
                text_hash=text_hash,
                source=source,
                tags=tags,
                metadata=metadata,
                expires_at=expires_at or "",
            )
            self._audit(
                operation="document.ingest_text",
                user_identifier=user_identifier,
                resource_type="document",
                resource_id=item.document_id,
            )
            return item

    def reindex_document_text(
        self,
        *,
        user_identifier: str,
        document_id: str,
        title: str,
        text: str,
        chunk_chars: int = 360,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> IngestedDocument:
        self._require_user(user_identifier)
        # user_identifier deliberately omitted -- see ingest_document_text's
        # comment above (ARC-07/D-07 central sanitizer is the backstop).
        with self._span(
            "document.reindex_text",
            {"document_id": document_id, "source": source},
        ):
            if not document_id.strip():
                raise ValueError("document_id is required")
            if not title.strip():
                raise ValueError("title is required")
            if not text.strip():
                raise ValueError("text is required")
            text, metadata = self._redact_for_storage(text, dict(metadata or {}))
            for key in getattr(self.entity_processor, "metadata_keys", ()):
                metadata.pop(str(key), None)
            existing = self.get_document(user_identifier=user_identifier, document_id=document_id)
            # HI-03: hard-delete (not the soft `delete_document()` a
            # user-facing delete uses -- a soft-deleted row still occupies
            # its slot in Document[id]'s UNIQUE index, so recreating the
            # SAME id right after would raise DuplicatedKeyException, Rule 1
            # bug, found live via the 04-09 E2E capture) is folded into the
            # SAME `_write_many` transaction as the recreate below, not a
            # separate prior commit -- live-confirmed against a real
            # ArcadeDB 26.7.1 container that an intra-transaction DELETE
            # followed by a same-id CREATE VERTEX on a UNIQUE-indexed
            # property succeeds (read-your-writes within one session). Two
            # separate transactions left a window where a concurrent reader
            # observed the document as fully absent, and a crash between
            # them left it permanently deleted with no recreate.
            extra_statements: list[tuple[str, dict[str, object]]] = []
            if existing is not None:
                extra_statements = [
                    document_hard_delete_statement(
                        document_id=document_id, user_identifier=user_identifier
                    ),
                    chunk_hard_delete_statement(
                        document_id=document_id, user_identifier=user_identifier
                    ),
                ]
            chunks = self._chunk_document_text(text, chunk_chars=chunk_chars)
            item = self._create_document(
                user_identifier=user_identifier,
                document_id=document_id,
                title=title,
                text=text,
                chunks=chunks,
                chunk_chars=chunk_chars,
                text_hash=self._document_text_hash(text),
                source=source,
                tags=tags,
                metadata=metadata,
                expires_at=expires_at
                if expires_at is not None
                else existing.expires_at
                if existing is not None
                else "",
                created_at=existing.created_at if existing is not None else None,
                extra_statements=extra_statements,
            )
            self._audit(
                operation="document.reindex_text",
                user_identifier=user_identifier,
                resource_type="document",
                resource_id=item.document_id,
            )
            return item

    def _create_document(
        self,
        *,
        user_identifier: str,
        document_id: str,
        title: str,
        text: str,
        chunks: list[str],
        chunk_chars: int,
        text_hash: str,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str = "",
        created_at: str | None = None,
        extra_statements: list[tuple[str, dict[str, object]]] | None = None,
    ) -> IngestedDocument:
        self._ensure_user(user_identifier)
        created_at = created_at or self._now_iso()
        updated_at = self._now_iso()
        clean_tags = self._clean_tags(tags)
        clean_metadata = dict(metadata or {})
        processed_chunks = self._process_texts_for_storage(
            [(chunk_text, dict(clean_metadata)) for chunk_text in chunks]
        )
        # PERF-01: one batched embedding round-trip for every chunk.
        vectors = self._embed_many([chunk_text for chunk_text, _ in processed_chunks])

        # HI-03: `extra_statements` (reindex_document_text's hard-delete of
        # the old Document/Chunk rows) runs FIRST in the SAME transaction as
        # the CREATE below -- not a separate prior commit.
        statements: list[tuple[str, dict[str, object]]] = list(extra_statements or [])
        statements += [
            document_create_statement(
                document_id=document_id,
                user_identifier=user_identifier,
                title=title,
                chunk_count=len(processed_chunks),
                chunk_chars=chunk_chars,
                text_hash=text_hash,
                source=source,
                tags_json=self._json_dumps(clean_tags),
                metadata_json=self._json_dumps(clean_metadata),
                created_at=created_at,
                updated_at=updated_at,
                expires_at=expires_at,
            ),
            document_edge_statement(user_identifier=user_identifier, document_id=document_id),
        ]
        previous_chunk_id = ""
        for idx, ((chunk_text, chunk_metadata), vector) in enumerate(
            zip(processed_chunks, vectors, strict=True),
            start=1,
        ):
            # ARC-08: stable_id() is the sole chunk identifier -- no legacy
            # synthetic-integer join property.
            chunk_id = stable_id("chunk", user_identifier, document_id, str(idx))
            locator = f"chunk={idx}"
            lexical_tokens, lexical_weights = sparse_vector(chunk_text)
            statements.append(
                chunk_create_statement(
                    chunk_id=chunk_id,
                    document_id=document_id,
                    user_identifier=user_identifier,
                    title=title,
                    ordinal=idx,
                    locator=locator,
                    source=source,
                    tags_json=self._json_dumps(clean_tags),
                    metadata_json=self._json_dumps(chunk_metadata),
                    created_at=created_at,
                    updated_at=updated_at,
                    expires_at=expires_at,
                    text=chunk_text,
                    embedding=vector,
                    lexical_tokens=lexical_tokens,
                    lexical_weights=lexical_weights,
                )
            )
            statements.append(
                has_chunk_edge_statement(
                    document_id=document_id,
                    chunk_id=chunk_id,
                    ordinal=idx,
                    user_identifier=user_identifier,
                )
            )
            if previous_chunk_id:
                statements.append(
                    next_chunk_edge_statement(
                        previous_chunk_id=previous_chunk_id,
                        chunk_id=chunk_id,
                        user_identifier=user_identifier,
                    )
                )
            previous_chunk_id = chunk_id

        # D-08: the whole document + every chunk + every edge is ONE managed
        # transaction under ArcadeDB's session-header read-your-writes model
        # -- no separate byte-budget batch splitter is needed.
        self._write_many(statements)
        return IngestedDocument(
            document_id=document_id,
            title=title,
            chunk_count=len(processed_chunks),
            user_identifier=user_identifier,
            created_at=created_at,
            updated_at=updated_at,
            expires_at=expires_at,
            source=source,
            tags=clean_tags,
            metadata=clean_metadata,
            text_hash=text_hash,
            chunk_chars=chunk_chars,
        )

    def _update_document_metadata(
        self,
        *,
        user_identifier: str,
        document_id: str,
        title: str,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
        preserve_updated_at: bool = False,
    ) -> IngestedDocument:
        existing = self.get_document(user_identifier=user_identifier, document_id=document_id)
        if existing is None:
            raise ValueError(f"document {document_id} not found")
        next_source = existing.source if source == "" else source
        next_tags = existing.tags if tags is None else self._clean_tags(tags)
        next_metadata = existing.metadata if metadata is None else dict(metadata)
        next_expires_at = existing.expires_at if expires_at is None else expires_at
        updated_at = existing.updated_at if preserve_updated_at else self._now_iso()
        self._write_many(
            [
                document_update_statement(
                    document_id=document_id,
                    user_identifier=user_identifier,
                    title=title,
                    source=next_source,
                    tags_json=self._json_dumps(next_tags),
                    metadata_json=self._json_dumps(next_metadata),
                    expires_at=next_expires_at,
                    updated_at=updated_at,
                ),
                chunk_metadata_update_statement(
                    document_id=document_id,
                    user_identifier=user_identifier,
                    title=title,
                    source=next_source,
                    tags_json=self._json_dumps(next_tags),
                    metadata_json=self._json_dumps(next_metadata),
                    expires_at=next_expires_at,
                    updated_at=updated_at,
                ),
            ]
        )
        return IngestedDocument(
            document_id=document_id,
            title=title,
            chunk_count=existing.chunk_count,
            user_identifier=user_identifier,
            created_at=existing.created_at,
            updated_at=updated_at,
            expires_at=next_expires_at,
            source=next_source,
            tags=next_tags,
            metadata=next_metadata,
            text_hash=existing.text_hash,
            chunk_chars=existing.chunk_chars,
        )
