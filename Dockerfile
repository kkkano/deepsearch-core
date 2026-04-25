FROM python:3.11-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir uv

COPY pyproject.toml ./
COPY deepsearch_core/ ./deepsearch_core/

RUN uv pip install --system --no-cache-dir .

# ---------- Runtime ----------
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=builder /usr/local/bin/deepsearch* /usr/local/bin/

COPY deepsearch_core/ ./deepsearch_core/
COPY .env.example ./

EXPOSE 8000 8765

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["deepsearch-server"]
