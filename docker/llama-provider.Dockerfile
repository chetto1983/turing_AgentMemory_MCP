# syntax=docker/dockerfile:1.7
FROM ghcr.io/ggml-org/llama.cpp:server-cuda@sha256:7b3d7834fc7307cb54f24f8869b67bfff276404c416452a48d11321bc36a81be

ENV HOME=/models \
    XDG_CACHE_HOME=/models/.cache \
    HF_HOME=/models/huggingface \
    LLAMA_CACHE=/models/llama.cpp \
    PYTHONPYCACHEPREFIX=/tmp/pycache

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /models --shell /usr/sbin/nologin app \
    && mkdir -p /models /tmp /run \
    && chown -R app:app /models /tmp /run

USER app
