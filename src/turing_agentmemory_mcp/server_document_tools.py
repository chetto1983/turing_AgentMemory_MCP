"""Document-upload and document-retrieval MCP tool registrations for the FastMCP app."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastmcp import FastMCP

from turing_agentmemory_mcp.document_job_manager import DocumentIngestManager
from turing_agentmemory_mcp.file_upload import DocumentUploadStore
from turing_agentmemory_mcp.store import TuringAgentMemory


def register_document_tools(
    app: FastMCP,
    memory: TuringAgentMemory,
    uploads: DocumentUploadStore,
    document_manager: Callable[[], DocumentIngestManager],
    tool_span: Callable[[str], Any],
) -> None:
    """Register every `document_*` MCP tool on `app`."""

    @app.tool()
    def document_upload_begin(
        filename: str,
        total_bytes: int,
        sha256: str,
        title: str,
        user_identifier: str = "default",
        document_id: str | None = None,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, object]:
        """Start a tenant-scoped file upload for server-side document conversion."""
        with tool_span("document_upload_begin"):
            return uploads.begin(
                user_identifier=user_identifier,
                filename=filename,
                total_bytes=total_bytes,
                sha256=sha256,
                attributes={
                    "title": title,
                    "document_id": document_id,
                    "source": source,
                    "tags": list(tags or []),
                    "metadata": dict(metadata or {}),
                    "expires_at": expires_at,
                },
            )

    @app.tool()
    def document_upload_chunk(
        upload_id: str,
        sequence: int,
        content_base64: str,
        user_identifier: str = "default",
    ) -> dict[str, object]:
        """Append one ordered base64 chunk to a tenant-scoped document upload."""
        with tool_span("document_upload_chunk"):
            return uploads.append_base64(
                upload_id,
                user_identifier=user_identifier,
                sequence=sequence,
                content_base64=content_base64,
            )

    @app.tool()
    def document_upload_commit(
        upload_id: str,
        user_identifier: str = "default",
    ) -> dict[str, Any]:
        """Verify and durably enqueue an uploaded file for background ingestion."""
        with tool_span("document_upload_commit"):
            try:
                uploaded = uploads.complete(upload_id, user_identifier=user_identifier)
                attributes = uploaded.attributes
                return (
                    document_manager()
                    .enqueue_file(
                        uploaded.path,
                        user_identifier=user_identifier,
                        title=str(attributes["title"]),
                        document_id=attributes.get("document_id"),
                        source=str(attributes.get("source") or ""),
                        tags=list(attributes.get("tags") or []),
                        metadata=dict(attributes.get("metadata") or {}),
                        expires_at=attributes.get("expires_at"),
                        transport="mcp-chunk-upload",
                        expected_sha256=uploaded.sha256,
                        expected_bytes=uploaded.total_bytes,
                    )
                    .to_dict()
                )
            finally:
                uploads.discard(upload_id, user_identifier=user_identifier)

    @app.tool()
    def document_upload_abort(
        upload_id: str,
        user_identifier: str = "default",
    ) -> dict[str, object]:
        """Discard a tenant-scoped upload without converting or ingesting it."""
        with tool_span("document_upload_abort"):
            return {
                "upload_id": upload_id,
                "aborted": uploads.discard(upload_id, user_identifier=user_identifier),
            }

    @app.tool()
    def document_ingest_text(
        title: str,
        text: str,
        user_identifier: str = "default",
        document_id: str | None = None,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Ingest text as a cited document graph with chunk vectors."""
        with tool_span("document_ingest_text"):
            return memory.ingest_document_text(
                user_identifier=user_identifier,
                title=title,
                text=text,
                document_id=document_id,
                source=source,
                tags=tags,
                metadata=metadata,
                expires_at=expires_at,
            ).to_dict()

    @app.tool()
    def document_ingest_file(
        title: str,
        path: str,
        user_identifier: str = "default",
        document_id: str | None = None,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Durably enqueue a server-local file for background conversion and ingestion."""
        with tool_span("document_ingest_file"):
            return (
                document_manager()
                .enqueue_file(
                    path,
                    user_identifier=user_identifier,
                    title=title,
                    document_id=document_id,
                    source=source,
                    tags=tags,
                    metadata=metadata,
                    expires_at=expires_at,
                )
                .to_dict()
            )

    @app.tool()
    def document_ingest_status(
        job_id: str,
        user_identifier: str = "default",
    ) -> dict[str, object]:
        """Return tenant-scoped state and progress for a document ingestion job."""
        with tool_span("document_ingest_status"):
            job = document_manager().get(job_id, user_identifier=user_identifier)
            if job is None:
                raise ValueError("document ingestion job is unknown")
            return job.to_dict()

    @app.tool()
    def document_ingest_cancel(
        job_id: str,
        user_identifier: str = "default",
    ) -> dict[str, object]:
        """Cancel a queued job or request cooperative cancellation of a running job."""
        with tool_span("document_ingest_cancel"):
            return (
                document_manager()
                .cancel(
                    job_id,
                    user_identifier=user_identifier,
                )
                .to_dict()
            )

    @app.tool()
    def document_ingest_retry(
        job_id: str,
        user_identifier: str = "default",
    ) -> dict[str, object]:
        """Requeue a failed document ingestion job using its durable staged file."""
        with tool_span("document_ingest_retry"):
            return (
                document_manager()
                .retry(
                    job_id,
                    user_identifier=user_identifier,
                )
                .to_dict()
            )

    @app.tool()
    def document_reindex_text(
        document_id: str,
        title: str,
        text: str,
        user_identifier: str = "default",
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Replace one scoped document's chunks and vectors with fresh text."""
        with tool_span("document_reindex_text"):
            return memory.reindex_document_text(
                user_identifier=user_identifier,
                document_id=document_id,
                title=title,
                text=text,
                source=source,
                tags=tags,
                metadata=metadata,
                expires_at=expires_at,
            ).to_dict()

    @app.tool()
    def document_delete(
        document_id: str,
        user_identifier: str = "default",
    ) -> dict[str, object]:
        """Soft-delete one scoped document so its chunks are hidden from retrieval."""
        with tool_span("document_delete"):
            return memory.delete_document(user_identifier=user_identifier, document_id=document_id)

    @app.tool()
    def document_search(
        query: str,
        user_identifier: str = "default",
        limit: int = 5,
        document_id: str = "",
        source: str = "",
        tags: list[str] | None = None,
        created_after: str = "",
        created_before: str = "",
        updated_after: str = "",
        updated_before: str = "",
        threshold: float = 0.0,
        explain: bool = False,
    ) -> list[dict[str, Any]]:
        """Search scoped document chunks and return cited context with optional metadata filters."""
        with tool_span("document_search"):
            return [
                item.to_dict()
                for item in memory.search_documents(
                    user_identifier=user_identifier,
                    query=query,
                    limit=limit,
                    document_id=document_id,
                    source=source,
                    tags=tags,
                    created_after=created_after,
                    created_before=created_before,
                    updated_after=updated_after,
                    updated_before=updated_before,
                    threshold=threshold,
                    explain=explain,
                )
            ]
