from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PINNED_PYTHON_RE = re.compile(r"^FROM python:3\.14-slim@sha256:[a-f0-9]{64}$", re.MULTILINE)
PINNED_LLAMA_RE = re.compile(
    r"^FROM ghcr\.io/ggml-org/llama\.cpp:server-cuda@sha256:[a-f0-9]{64}$",
    re.MULTILINE,
)
PINNED_GLINER_PYTHON_RE = re.compile(
    r"^FROM python:3\.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf$",
    re.MULTILINE,
)
GRANITE_FILENAME = "granite-embedding-311M-multilingual-r2-Q4_K_M.gguf"
GRANITE_REVISION = "4413a1d4c63ed0aeda030202ad982a613a91f9ea"
GRANITE_SHA256 = "58d27f63e69ccf7abce27bf6b35bb0edebc3a1c05ad4a3165acaba1cdca107c0"
GRANITE_URL = (
    "https://huggingface.co/mykor/granite-embedding-311m-multilingual-r2-GGUF/"
    f"resolve/{GRANITE_REVISION}/{GRANITE_FILENAME}?download=true"
)
QWEN_FILENAME = "Qwen3-Reranker-0.6B-q8_0.gguf"
QWEN_REVISION = "041387f8ed7ead711b9496b153b682c5b2f5d158"
QWEN_SHA256 = "8b5337e5baadf83fdd6f7a865dde4b3627fc53a1c8e56cc2f83260dfdd089c49"
QWEN_URL = (
    "https://huggingface.co/Mungert/Qwen3-Reranker-0.6B-GGUF/"
    f"resolve/{QWEN_REVISION}/{QWEN_FILENAME}?download=true"
)
GEMMA_FILENAME = "embeddinggemma-300M-Q8_0.gguf"
GEMMA_REVISION = "6661a6504c30d8304af13455cb4a5d4f5bc6011f"
GEMMA_SHA256 = "a0f7b4e13c397a6e1b32c2de75b1f65a14c92ec524d5f674d94a4290a1c4969b"
GEMMA_URL = (
    "https://huggingface.co/unsloth/embeddinggemma-300m-GGUF/"
    f"resolve/{GEMMA_REVISION}/{GEMMA_FILENAME}?download=true"
)

def test_runtime_dockerfiles_pin_base_image_and_run_as_non_root() -> None:
    app = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    turingdb = (ROOT / "docker" / "turingdb.Dockerfile").read_text(encoding="utf-8")
    llama = (ROOT / "docker" / "llama-provider.Dockerfile").read_text(encoding="utf-8")
    gliner = (ROOT / "docker" / "gliner-provider.Dockerfile").read_text(encoding="utf-8")

    for dockerfile in (app, turingdb):
        assert PINNED_PYTHON_RE.search(dockerfile)
        assert "10001" in dockerfile
        assert "USER app" in dockerfile
    assert PINNED_LLAMA_RE.search(llama)
    assert "10001" in llama
    assert "USER app" in llama
    assert PINNED_GLINER_PYTHON_RE.search(gliner)
    assert "HOME=/root XDG_CACHE_HOME=/root/.cache" in gliner
    assert '"fast_gliner==0.2.1"' in gliner
    assert "download.pytorch.org" not in gliner
    assert "gliner2[local]" not in gliner
    assert "10001" in gliner
    assert "USER app" in gliner


def test_dockerfiles_use_pip_cache_mounts() -> None:
    app = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    turingdb = (ROOT / "docker" / "turingdb.Dockerfile").read_text(encoding="utf-8")

    assert app.count("--mount=type=cache,target=/root/.cache/pip") >= 2
    assert "--mount=type=cache,target=/root/.cache/pip" in turingdb
    assert "--no-cache-dir" not in app
    assert "--no-cache-dir" not in turingdb


def test_compose_declares_runtime_hardening_controls() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    for name in ("turingdb", "turing-agentmemory-mcp"):
        service = services[name]
        assert service["restart"] == "unless-stopped"
        assert "healthcheck" in service
        assert service["security_opt"] == ["no-new-privileges:true"]
        limits = service["deploy"]["resources"]["limits"]
        assert limits["cpus"]
        assert limits["memory"]

    app = services["turing-agentmemory-mcp"]
    assert app["read_only"] is True
    assert {"/tmp", "/run"} <= set(app["tmpfs"])


def test_compose_routes_mcp_to_gpu_gguf_sidecars() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    embed = services["agentmemory-embed"]
    rerank = services["agentmemory-rerank"]
    for service in (embed, rerank):
        assert service["image"] == "turing-agentmemory-llama-provider:local"
        assert service["gpus"] == "all"
        assert service["read_only"] is True
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert "agentmemory-llama-cache:/models" in service["volumes"]
        assert "healthcheck" in service
        assert "--device" in service["command"]
        assert "CUDA0" in service["command"]
        assert "--gpu-layers" in service["command"]
        assert "all" in service["command"]

    assert embed["command"][:2] == ["--model", f"/models/pinned/{GRANITE_FILENAME}"]
    assert "--hf-repo" not in embed["command"]
    assert "--hf-file" not in embed["command"]
    assert "--ubatch-size" in embed["command"]
    assert "4096" in embed["command"]
    assert rerank["command"][:2] == ["--model", f"/models/pinned/{QWEN_FILENAME}"]
    assert "--hf-repo" not in rerank["command"]
    assert "--hf-file" not in rerank["command"]
    assert "--embedding" in rerank["command"]
    assert "--parallel" in rerank["command"]
    assert "--no-cache-prompt" in rerank["command"]

    app = services["turing-agentmemory-mcp"]
    app_env = set(app["environment"])
    assert app["depends_on"]["agentmemory-embed"]["condition"] == "service_healthy"
    assert app["depends_on"]["agentmemory-rerank"]["condition"] == "service_healthy"
    assert "EMBED_BASE_URL=http://agentmemory-embed:8080" in app_env
    assert "EMBED_MODEL=mykor/granite-embedding-311m-multilingual-r2-GGUF:Q4_K_M" in app_env
    assert "EMBED_BATCH_SIZE=128" in app_env
    assert "RERANK_BASE_URL=http://agentmemory-rerank:8080" in app_env
    assert "RERANK_MODEL=Qwen3-Reranker-0.6B-q8_0.gguf" in app_env
    assert "RERANK_PROVIDER_MIN_SCORE=${RERANK_PROVIDER_MIN_SCORE:-0}" in app_env
    assert "RERANK_CANDIDATE_LIMIT=${RERANK_CANDIDATE_LIMIT:-50}" in app_env
    assert "RERANK_BLEND=${RERANK_BLEND:-0}" in app_env
    assert not any("host.docker.internal" in value for value in app_env)


def test_compose_declares_profile_gated_embeddinggemma_gpu_candidate() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    init = services["agentmemory-gemma-model-init"]
    candidate = services["agentmemory-embed-gemma"]

    assert init["profiles"] == ["embeddinggemma-eval"]
    assert candidate["profiles"] == ["embeddinggemma-eval"]
    assert candidate["image"] == "turing-agentmemory-llama-provider:local"
    assert candidate["gpus"] == "all"
    assert candidate["command"][:2] == ["--model", f"/models/pinned/{GEMMA_FILENAME}"]
    assert "--embedding" in candidate["command"]
    assert "--device" in candidate["command"]
    assert "CUDA0" in candidate["command"]
    assert candidate["read_only"] is True
    assert candidate["security_opt"] == ["no-new-privileges:true"]
    assert "agentmemory-llama-cache:/models" in candidate["volumes"]
    assert candidate["depends_on"]["agentmemory-gemma-model-init"]["condition"] == "service_completed_successfully"

    script = init["command"][0]
    assert GEMMA_URL in script
    assert f"/models/pinned/{GEMMA_FILENAME}" in script
    assert GEMMA_SHA256 in script


def test_compose_routes_mcp_to_cached_fast_gliner_sidecar() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]
    gliner = services["agentmemory-gliner"]

    assert "gpus" not in gliner
    assert "ports" not in gliner
    assert gliner["read_only"] is True
    assert gliner["user"] == "10001:10001"
    assert gliner["restart"] == "unless-stopped"
    assert gliner["security_opt"] == ["no-new-privileges:true"]
    assert {"/tmp", "/run"} <= set(gliner["tmpfs"])
    assert gliner["expose"] == ["8080"]
    assert "agentmemory-gliner-cache:/models" in gliner["volumes"]
    gliner_env = set(gliner["environment"])
    assert "GLINER_MODEL=lion-ai/gliner2-base-v1-onnx" in gliner_env
    assert "GLINER_MODEL_REVISION=5551729ccc76b30395bc9600f2348ec52a87cead" in gliner_env
    assert "GLINER_DEVICE=cpu" in gliner_env
    assert "GLINER_BATCH_SIZE=1" in gliner_env
    assert gliner["healthcheck"]["retries"] >= 80
    assert "urlopen('http://127.0.0.1:8080/health'" in gliner["healthcheck"]["test"][1]
    assert "agentmemory-gliner-cache" in compose["volumes"]

    app = services["turing-agentmemory-mcp"]
    app_env = set(app["environment"])
    assert app["depends_on"]["agentmemory-gliner"]["condition"] == "service_healthy"
    assert "GLINER_ENABLED=1" in app_env
    assert "GLINER_BACKEND=gliner2_http" in app_env
    assert "GLINER_MODEL=lion-ai/gliner2-base-v1-onnx" in app_env
    assert "GLINER_BASE_URL=http://agentmemory-gliner:8080" in app_env
    assert "GLINER_TIMEOUT_SECONDS=900" in app_env
    assert services["agentmemory-lab"]["ports"] == ["127.0.0.1:8096:8096"]


def test_compose_provisions_commit_pinned_models_with_exact_checksums() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert "agentmemory-model-init" in services
    script = services["agentmemory-model-init"]["command"][0]
    for url, revision, filename, sha256 in (
        (GRANITE_URL, GRANITE_REVISION, GRANITE_FILENAME, GRANITE_SHA256),
        (QWEN_URL, QWEN_REVISION, QWEN_FILENAME, QWEN_SHA256),
    ):
        assert url in script
        assert f"resolve/{revision}/{filename}" in script
        assert f"/models/pinned/{filename}" in script
        assert sha256 in script

    assert GEMMA_URL not in script

    assert "resolve/main/" not in script
    assert "mkdir -p /models/pinned" in script
    assert 'partial="$$final.partial"' in script
    cache_check = 'if [ -f "$$final" ] && printf'
    final_checksum = '"$$sha256" "$$final" | sha256sum -c -'
    assert cache_check in script
    assert final_checksum in script
    assert script.count("sha256sum -c -") >= 2
    normalized_script = re.sub(r"\\\s*", " ", script)
    normalized_script = re.sub(r"\s+", " ", normalized_script)
    download = (
        'curl -fL --retry 5 --retry-delay 2 --retry-all-errors '
        '--connect-timeout 30 --speed-limit 1024 --speed-time 120 '
        '--output "$$partial" "$$url"'
    )
    for flag in (
        "--retry 5",
        "--retry-delay 2",
        "--retry-all-errors",
        "--connect-timeout 30",
        "--speed-limit 1024",
        "--speed-time 120",
    ):
        assert flag in script
    partial_checksum = '"$$sha256" "$$partial" | sha256sum -c -'
    atomic_rename = 'mv "$$partial" "$$final"'
    assert download in normalized_script
    assert partial_checksum in script
    assert atomic_rename in script
    assert (
        normalized_script.index(cache_check)
        < normalized_script.index("return 0")
        < normalized_script.index(download)
    )
    assert (
        normalized_script.index(download)
        < normalized_script.index(partial_checksum)
        < normalized_script.index(atomic_rename)
    )


def test_compose_model_init_is_hardened_and_gates_both_sidecars() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert "agentmemory-model-init" in services
    init = services["agentmemory-model-init"]
    assert init["image"] == "turing-agentmemory-llama-provider:local"
    assert init["user"] == "10001:10001"
    assert init["restart"] == "no"
    assert init["read_only"] is True
    assert init["security_opt"] == ["no-new-privileges:true"]
    assert {"/tmp", "/run"} <= set(init["tmpfs"])
    assert "agentmemory-llama-cache:/models" in init["volumes"]
    assert "ports" not in init

    for name in ("agentmemory-embed", "agentmemory-rerank"):
        service = services[name]
        assert (
            service["depends_on"]["agentmemory-model-init"]["condition"]
            == "service_completed_successfully"
        )
        assert "agentmemory-llama-cache:/models" in service["volumes"]
        assert "ports" not in service

    gemma_init = services["agentmemory-gemma-model-init"]
    assert gemma_init["profiles"] == ["embeddinggemma-eval"]
    assert gemma_init["image"] == "turing-agentmemory-llama-provider:local"
    assert gemma_init["user"] == "10001:10001"
    assert gemma_init["restart"] == "no"
    assert gemma_init["read_only"] is True
    assert gemma_init["security_opt"] == ["no-new-privileges:true"]
    assert {"/tmp", "/run"} <= set(gemma_init["tmpfs"])
    assert "agentmemory-llama-cache:/models" in gemma_init["volumes"]
    assert "ports" not in gemma_init

    gemma = services["agentmemory-embed-gemma"]
    assert (
        gemma["depends_on"]["agentmemory-gemma-model-init"]["condition"]
        == "service_completed_successfully"
    )


def test_compose_allows_overrideable_rerank_provider_min_score() -> None:
    default_env = os.environ.copy()
    default_env.pop("RERANK_PROVIDER_MIN_SCORE", None)
    default = yaml.safe_load(
        subprocess.check_output(["docker", "compose", "config"], text=True, env=default_env)
    )
    override_env = os.environ.copy()
    override_env["RERANK_PROVIDER_MIN_SCORE"] = "0.25"
    overridden = yaml.safe_load(
        subprocess.check_output(
            ["docker", "compose", "config"], text=True, env=override_env
        )
    )

    def value(config: dict) -> str:
        environment = config["services"]["turing-agentmemory-mcp"]["environment"]
        if isinstance(environment, dict):
            return str(environment["RERANK_PROVIDER_MIN_SCORE"])
        return next(
            item.split("=", 1)[1]
            for item in environment
            if item.startswith("RERANK_PROVIDER_MIN_SCORE=")
        )

    assert value(default) == "0"
    assert value(overridden) == "0.25"


def test_compose_routes_non_root_runtime_caches_to_tmpfs() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    app_env = set(services["turing-agentmemory-mcp"]["environment"])
    assert "HOME=/tmp" in app_env
    assert "XDG_CACHE_HOME=/tmp/.cache" in app_env
    assert "PYTHONPYCACHEPREFIX=/tmp/pycache" in app_env

    e2e_env = services["e2e"]["environment"]
    assert e2e_env["RUFF_CACHE_DIR"] == "/tmp/ruff-cache"
    assert e2e_env["PYTHONPYCACHEPREFIX"] == "/tmp/pycache"


def test_e2e_writes_report_to_container_scratch_space() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    entrypoint = compose["services"]["e2e"]["entrypoint"]

    assert entrypoint[entrypoint.index("--out") + 1] == "/tmp/e2e-results.json"


def test_compose_gates_e2e_harness_behind_an_explicit_profile() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))

    assert compose["services"]["e2e"]["profiles"] == ["e2e"]


def test_compose_repairs_legacy_volume_ownership_before_turingdb_start() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    services = compose["services"]

    init = services["turingdb-volume-init"]
    assert init["user"] == "0:0"
    assert init["restart"] == "no"
    assert init["entrypoint"] == ["/bin/sh", "-c", "chown -R 10001:10001 /turing"]

    turingdb_deps = services["turingdb"]["depends_on"]
    assert turingdb_deps["turingdb-volume-init"]["condition"] == "service_completed_successfully"
    assert services["turingdb"]["user"] == "10001:10001"


def test_turingdb_startup_cleans_runtime_socket_and_allows_slow_vector_load() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    service = compose["services"]["turingdb"]
    command = service["command"][0]

    assert "rm -f /turing/turingdb.sock" in command
    assert "touch /tmp/.turing_history" in command
    assert "turingdb start -turing-dir /turing -i 0.0.0.0 -p 6666 -demon" in command
    assert "turingdb stop -turing-dir /turing" in command
    assert "trap shutdown TERM INT" in command
    assert "while :; do" in command
    assert "sleep 3600 &" in command
    assert "wait $!" in command
    assert "try_reach" not in command
    assert "stdin_open" not in service
    assert "exec turingdb start" not in command
    assert "-start-timeout" not in command
    assert "healthcheck" in service
    assert service["healthcheck"]["retries"] >= 80
    assert service["deploy"]["resources"]["limits"] == {
        "cpus": "4.0",
        "memory": "8g",
    }


def test_compose_serves_agentmemory_lab_frontend_on_local_port() -> None:
    compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))
    lab = compose["services"]["agentmemory-lab"]

    assert lab["image"] == "turing-agentmemory-mcp:local"
    assert lab["command"] == [
        "lab",
        "--host",
        "0.0.0.0",
        "--port",
        "8096",
        "--benchmark-dir",
        "/work/.benchmarks",
    ]
    assert lab["ports"] == ["127.0.0.1:8096:8096"]
    assert ".:/work:ro" in lab["volumes"]
    assert lab["read_only"] is True
    assert {"/tmp", "/run"} <= set(lab["tmpfs"])


def test_readme_documents_backup_restore_and_build_attestation() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "## Backup And Restore" in readme
    assert "docker run --rm -v turing-agentmemory-mcp_turing-data:/turing:ro" in readme
    assert "docker run --rm -v turing-agentmemory-mcp_turing-data:/turing" in readme
    assert "## Build Attestation" in readme
    assert "docker buildx build --provenance=true --sbom=true" in readme
