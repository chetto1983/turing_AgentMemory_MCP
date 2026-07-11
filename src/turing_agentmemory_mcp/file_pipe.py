from __future__ import annotations

import base64
import hashlib
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastmcp import Client, FastMCP
from fastmcp.server import create_proxy


def _tool_payload(result: Any) -> Any:
    structured = getattr(result, "structured_content", None)
    if structured is not None:
        if isinstance(structured, dict) and set(structured) == {"result"}:
            return structured["result"]
        return structured
    data = getattr(result, "data", None)
    if data is not None:
        return data
    text = "".join(getattr(item, "text", "") for item in getattr(result, "content", []))
    return json.loads(text)


def _resolve_allowed_file(path: str, allowed_roots: Sequence[Path]) -> Path:
    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError(f"{source} is not a file")
    for root in allowed_roots:
        try:
            source.relative_to(root)
        except ValueError:
            continue
        return source
    raise ValueError("path is outside AGENTMEMORY_FILE_PIPE_ROOTS allowlisted directories")


def _hash_file(path: Path, chunk_bytes: int) -> tuple[int, str]:
    digest = hashlib.sha256()
    total_bytes = 0
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_bytes):
            digest.update(chunk)
            total_bytes += len(chunk)
    return total_bytes, digest.hexdigest()


def create_file_pipe_proxy(
    remote: Any,
    *,
    allowed_roots: Sequence[str | Path],
    chunk_bytes: int = 512 << 10,
    timeout: float = 1800.0,
) -> FastMCP:
    if chunk_bytes < 1:
        raise ValueError("chunk_bytes must be positive")
    roots = [Path(root).expanduser().resolve(strict=True) for root in allowed_roots]
    if not roots:
        raise ValueError("at least one file-pipe allowlisted root is required")
    proxy = create_proxy(remote, name="turing-agentmemory-file-pipe")

    @proxy.tool(name="document_ingest_file")
    async def document_ingest_file(
        title: str,
        path: str,
        user_identifier: str = "default",
        document_id: str | None = None,
        source: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        """Stream an allowlisted local file to the MCP for conversion and ingestion."""
        local_file = _resolve_allowed_file(path, roots)
        total_bytes, sha256 = _hash_file(local_file, chunk_bytes)
        upload_id: str | None = None

        async with Client(remote, timeout=timeout) as client:
            started = _tool_payload(
                await client.call_tool(
                    "document_upload_begin",
                    {
                        "filename": local_file.name,
                        "total_bytes": total_bytes,
                        "sha256": sha256,
                        "title": title,
                        "user_identifier": user_identifier,
                        "document_id": document_id,
                        "source": source,
                        "tags": list(tags or []),
                        "metadata": dict(metadata or {}),
                        "expires_at": expires_at,
                    },
                )
            )
            upload_id = str(started["upload_id"])
            remote_chunk_bytes = int(started.get("chunk_bytes") or chunk_bytes)
            transfer_chunk_bytes = min(chunk_bytes, remote_chunk_bytes)
            try:
                with local_file.open("rb") as handle:
                    sequence = 0
                    while chunk := handle.read(transfer_chunk_bytes):
                        await client.call_tool(
                            "document_upload_chunk",
                            {
                                "upload_id": upload_id,
                                "sequence": sequence,
                                "content_base64": base64.b64encode(chunk).decode("ascii"),
                                "user_identifier": user_identifier,
                            },
                        )
                        sequence += 1
                committed = await client.call_tool(
                    "document_upload_commit",
                    {"upload_id": upload_id, "user_identifier": user_identifier},
                )
                return _tool_payload(committed)
            except BaseException:
                try:
                    await client.call_tool(
                        "document_upload_abort",
                        {"upload_id": upload_id, "user_identifier": user_identifier},
                    )
                except BaseException:
                    pass
                raise

    return proxy


def file_pipe_roots_from_env() -> list[Path]:
    raw = os.environ.get("AGENTMEMORY_FILE_PIPE_ROOTS", "")
    roots = [Path(value.strip()) for value in raw.split(os.pathsep) if value.strip()]
    if not roots:
        raise ValueError("AGENTMEMORY_FILE_PIPE_ROOTS must contain an allowlisted directory")
    return roots


def main() -> None:
    remote = os.environ.get("AGENTMEMORY_REMOTE_MCP_URL", "http://127.0.0.1:8095/mcp/")
    proxy = create_file_pipe_proxy(
        remote,
        allowed_roots=file_pipe_roots_from_env(),
        chunk_bytes=int(os.environ.get("AGENTMEMORY_FILE_PIPE_CHUNK_BYTES", str(512 << 10))),
        timeout=float(os.environ.get("AGENTMEMORY_FILE_PIPE_TIMEOUT_SECONDS", "1800")),
    )
    proxy.run(transport="stdio")


if __name__ == "__main__":
    main()
