__all__ = ["TuringAgentMemory"]


def __getattr__(name: str):
    if name == "TuringAgentMemory":
        from turing_agentmemory_mcp.store import TuringAgentMemory

        return TuringAgentMemory
    raise AttributeError(name)
