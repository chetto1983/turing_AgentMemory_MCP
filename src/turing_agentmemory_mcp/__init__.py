__all__ = ["TuringAgentMemory"]

from turing_agentmemory_mcp.warning_filters import suppress_fastmcp_authlib_warning

suppress_fastmcp_authlib_warning()


def __getattr__(name: str):
    if name == "TuringAgentMemory":
        from turing_agentmemory_mcp.store import TuringAgentMemory

        return TuringAgentMemory
    raise AttributeError(name)
