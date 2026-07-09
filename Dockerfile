FROM python:3.14-slim@sha256:b877e50bd90de10af8d82c57a022fc2e0dc731c5320d762a27986facfc3355c1

WORKDIR /app

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app /turing /tmp /run

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY tests/ ./tests/

ARG PYPROJECT_EXTRAS=dev
RUN pip install --no-cache-dir --root-user-action=ignore -e ".[${PYPROJECT_EXTRAS}]" \
    && chown -R app:app /app /turing /tmp /run

USER app

EXPOSE 8080
ENTRYPOINT ["turing-agentmemory-mcp"]
CMD ["serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]
