# KOSIS MCP — FastMCP (Python)
FROM python:3.12-slim

RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

USER app

ENV PORT=3000
EXPOSE 3000

CMD ["kosis-mcp", "--http", "--host", "0.0.0.0", "--port", "3000"]
