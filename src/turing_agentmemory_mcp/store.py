"""Canonical TuringDB-backed memory/document store. See docs/architecture.md.

`TuringAgentMemory` is composed from `store_<concern>.py` sibling mixins (D-08/D-09,
phase 01 decomposition) behind this thin facade; the import path
`turing_agentmemory_mcp.store.TuringAgentMemory` is unchanged for all consumers.
"""

from __future__ import annotations

from turing_agentmemory_mcp.store_chunking import _ChunkingMixin
from turing_agentmemory_mcp.store_core import _StoreCore
from turing_agentmemory_mcp.store_documents import _DocumentMixin
from turing_agentmemory_mcp.store_evidence import _EvidenceMixin
from turing_agentmemory_mcp.store_memory_read import _MemoryReadMixin
from turing_agentmemory_mcp.store_memory_write import _MemoryWriteMixin
from turing_agentmemory_mcp.store_rebuild import _RebuildMixin
from turing_agentmemory_mcp.store_search import _SearchMixin
from turing_agentmemory_mcp.store_utils import _UtilsMixin

__all__ = ["TuringAgentMemory"]


class TuringAgentMemory(
    _MemoryWriteMixin,
    _MemoryReadMixin,
    _SearchMixin,
    _EvidenceMixin,
    _DocumentMixin,
    _ChunkingMixin,
    _RebuildMixin,
    _UtilsMixin,
    _StoreCore,
):
    """Unified memory/document store. See docs/architecture.md."""
