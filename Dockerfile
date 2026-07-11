# syntax=docker/dockerfile:1.7
FROM python:3.14-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1

WORKDIR /app

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app /turing /tmp /run

COPY pyproject.toml ./

ARG PYPROJECT_EXTRAS=dev
RUN --mount=type=cache,target=/root/.cache/pip \
    python - <<'PY'
import os
import subprocess
import sys
import tomllib

with open("pyproject.toml", "rb") as fh:
    project = tomllib.load(fh)["project"]

requirements = list(project["dependencies"])
optional = project.get("optional-dependencies", {})
for extra in os.environ.get("PYPROJECT_EXTRAS", "").split(","):
    extra = extra.strip()
    if extra:
        requirements.extend(optional.get(extra, []))

subprocess.check_call(
    [sys.executable, "-m", "pip", "install", "--root-user-action=ignore", *requirements]
)
PY

COPY README.md LICENSE ./
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY tests/ ./tests/

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --root-user-action=ignore --no-deps -e . \
    && chown -R app:app /app /turing /tmp /run

USER app

EXPOSE 8080
ENTRYPOINT ["turing-agentmemory-mcp"]
CMD ["serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]
