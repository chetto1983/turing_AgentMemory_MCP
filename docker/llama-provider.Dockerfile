# syntax=docker/dockerfile:1.7
FROM ghcr.io/ggml-org/llama.cpp:server-cuda@sha256:502fde462776339020cec39425525e9ce78f17cd9f7b14123f55f5197b1da00a

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
