FROM python:3.14-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
COPY scripts/ ./scripts/
COPY tests/ ./tests/

RUN pip install --no-cache-dir --root-user-action=ignore -e ".[dev]"

EXPOSE 8080
ENTRYPOINT ["turing-agentmemory-mcp"]
CMD ["serve", "--transport", "http", "--host", "0.0.0.0", "--port", "8080"]
