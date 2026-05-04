# ── build stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# ── runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

RUN adduser --system --no-create-home --uid 1001 app

WORKDIR /app

COPY --from=builder /build/.venv /app/.venv
COPY src/ ./src/

ENV PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api')" || exit 1

USER app

CMD ["uvicorn", "md_backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
