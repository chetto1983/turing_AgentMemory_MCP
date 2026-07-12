"""Optional full utcp-agent chat over a local llama.cpp Gemma endpoint (D-03/D-08a).

Spike-only, optional-color evidence-gathering tool for
`.planning/phases/02-utcp-spike/02-FINDINGS.md` (Phase 2: UTCP Spike). NEVER merged as
native-UTCP-serving code (SC#3) -- lives only under scripts/spike/.

Per CONTEXT.md D-08, the deterministic core SC#1 evidence is the LLM-free round-trip in
`scripts/spike/utcp_roundtrip.py`. This script is OPTIONAL COLOR: it drives the real
`utcp-agent` consumer (github.com/universal-tool-calling-protocol/utcp-agent) through a full
LangGraph chat loop, backed by a LOCAL llama.cpp server hosting the Gemma GGUF
(`unsloth/gemma-4-12B-it-qat-GGUF`, file `gemma-4-12B-it-qat-UD-Q4_K_XL.gguf`) -- no cloud
account, no real API key. Per D-08a this sidecar is served via the repo's EXISTING
`docker/llama-provider.Dockerfile` (`ghcr.io/ggml-org/llama.cpp:server-cuda`) as a THROWAWAY
one-off `docker run` invocation; it is never added as a compose.yaml service (SC#3):

    docker run --rm --gpus all -p 127.0.0.1:8199:8080 \\
        -v llama-cache:/models/llama.cpp -v hf-cache:/models/huggingface \\
        $(docker build -q -f docker/llama-provider.Dockerfile .) \\
        --hf-repo unsloth/gemma-4-12B-it-qat-GGUF \\
        --hf-file gemma-4-12B-it-qat-UD-Q4_K_XL.gguf --host 0.0.0.0 --port 8080

Per D-08a, this is GPU-mandatory like the embed/rerank sidecars. If no GPU is present, or the
llama.cpp endpoint above is unreachable, this script RECORDS "full-agent chat NOT exercised (no
GPU / endpoint unavailable)" and exits 0 -- it never silently skips (the recorded non-exercise
IS the required behavior for FINDINGS.md, per CONTEXT.md D-08a).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PATH = ROOT / "compose.yaml"
SERVER_NAME = "turing-agentmemory-mcp"
DEFAULT_LLAMA_BASE_URL = "http://127.0.0.1:8199/v1"
NOT_EXERCISED_MESSAGE = "full-agent chat NOT exercised (no GPU / endpoint unavailable)"


def _gpu_available() -> bool:
    try:
        result = subprocess.run(["nvidia-smi"], capture_output=True, timeout=5, check=False)
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _llama_endpoint_reachable(base_url: str, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"{base_url}/models", timeout=timeout):  # noqa: S310
            return True
    except (urllib.error.URLError, OSError, TimeoutError):
        return False


def _mcp_stdio_call_template() -> dict[str, object]:
    """Same corrected docker compose run --rm -T ... stdio argv as utcp_roundtrip.py.

    Built as a plain literal here (no cross-plan import needed) -- the mcpServers dict is
    identical to Task 1's hand-corrected McpCallTemplate config.
    """
    return {
        "name": SERVER_NAME,
        "call_template_type": "mcp",
        "config": {
            "mcpServers": {
                SERVER_NAME: {
                    "command": "docker.exe",
                    "args": [
                        "compose",
                        "-f",
                        str(COMPOSE_PATH),
                        "run",
                        "--rm",
                        "-T",
                        SERVER_NAME,
                        "serve",
                        "--transport",
                        "stdio",
                    ],
                }
            }
        },
    }


async def _run_chat(base_url: str) -> int:
    from langchain_openai import ChatOpenAI
    from utcp_agent import UtcpAgent

    llm = ChatOpenAI(
        model="local-gemma",
        base_url=base_url,
        api_key="not-needed",  # dummy -- local llama.cpp server does not check it
        temperature=0.1,
    )
    utcp_config = {"manual_call_templates": [_mcp_stdio_call_template()]}

    print("=== full utcp-agent chat over local llama.cpp Gemma (D-03/D-08a, optional color) ===")
    try:
        agent = await UtcpAgent.create(llm=llm, utcp_config=utcp_config)
        response = await agent.chat(
            "Store the note 'UTCP spike ran successfully' and then search for it."
        )
    except Exception as exc:  # noqa: BLE001 -- an observed failure IS evidence, never swallow it
        print(f"full-agent chat FAILED (observed): {exc!r}")
        return 1

    print(f"Agent transcript: {response}")
    print("=== full-agent chat evidence captured successfully ===")
    return 0


def _probe(llama_base_url: str) -> tuple[bool, bool]:
    gpu = _gpu_available()
    endpoint = _llama_endpoint_reachable(llama_base_url)
    print(f"GPU (nvidia-smi) available: {gpu}")
    print(f"llama.cpp endpoint reachable ({llama_base_url}): {endpoint}")
    return gpu, endpoint


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Run only the GPU/endpoint availability probe (automated gate). Always exits 0.",
    )
    parser.add_argument(
        "--llama-base-url",
        default=DEFAULT_LLAMA_BASE_URL,
        help=f"OpenAI-compatible base_url of the local llama.cpp Gemma sidecar (default: {DEFAULT_LLAMA_BASE_URL}).",
    )
    args = parser.parse_args(argv)

    gpu, endpoint = _probe(args.llama_base_url)

    if not endpoint:
        print(NOT_EXERCISED_MESSAGE)
        return 0

    print("GPU/endpoint available")
    if args.check:
        return 0

    import asyncio

    return asyncio.run(_run_chat(args.llama_base_url))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
