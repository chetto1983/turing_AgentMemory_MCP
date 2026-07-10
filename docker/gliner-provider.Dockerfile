# syntax=docker/dockerfile:1.7
FROM python:3.12-slim@sha256:423ed6ab25b1921a477529254bfeeabf5855151dc2c3141699a1bfc852199fbf

ENV HOME=/models \
    HF_HOME=/models/huggingface \
    XDG_CACHE_HOME=/models/.cache \
    PYTHONPATH=/app/src \
    PYTHONPYCACHEPREFIX=/tmp/pycache

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /models --shell /usr/sbin/nologin app \
    && mkdir -p /app/src /models /tmp /run \
    && chown -R app:app /app /models /tmp /run

RUN --mount=type=cache,target=/root/.cache/pip \
    HOME=/root XDG_CACHE_HOME=/root/.cache \
    pip install --root-user-action=ignore "fast_gliner==0.2.1"

COPY src/ /app/src/
RUN chown -R app:app /app/src

USER app

EXPOSE 8080
ENTRYPOINT ["python", "-m", "turing_agentmemory_mcp.gliner_provider"]
