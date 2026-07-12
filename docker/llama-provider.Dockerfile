# syntax=docker/dockerfile:1.7
FROM ghcr.io/ggml-org/llama.cpp:server-cuda@sha256:8d1e8ddc42585632d7bd625c2285eba891ed2ed4428e9eda25ca71ce2f6cce27

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
