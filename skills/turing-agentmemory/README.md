# Turing AgentMemory Skill

Production guidance for agents and applications using the Turing AgentMemory MCP server.
It covers direct MCP recall, deliberate persistence, tenant isolation, cited document
retrieval, correction, deletion, retention, degraded operation, and projection recovery.

## Install

Install the `skills/turing-agentmemory` directory with any Agent Skills compatible client,
or configure the client to load skills from this repository. The runtime MCP server remains
a separate dependency and must be registered with the client.

## Example Requests

- "Add durable user memory to this agent through Turing AgentMemory MCP."
- "Recall the customer's previous decision without crossing tenant boundaries."
- "Store this preference, but never persist the API token in the same message."
- "Diagnose degraded memory retrieval and validate the repaired projection."
- "Retrieve policy documents with citations and combine them with personal context."

## Contents

```text
turing-agentmemory/
|-- SKILL.md
|-- README.md
|-- evals/evals.json
`-- references/
    |-- architecture.md
    |-- integration-patterns.md
    |-- mcp-tools.md
    `-- operations.md
```

This standalone skill is distributed under the included MIT `LICENSE`.
