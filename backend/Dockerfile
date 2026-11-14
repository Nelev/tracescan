# The TraceScan backend: the FastAPI app, and the image the `migrate` service runs Alembic from.
# Built by docker-compose.yml (`docker compose --profile app up -d --build` at the repo root).
# The trace server (trace_store.mcp_server) needs no image of its own: the app starts it as a
# subprocess with its own Python (sys.executable), so it runs inside this container.

FROM ghcr.io/astral-sh/uv:0.12.22 AS uv

FROM python:3.13.18-slim AS build
COPY --from=uv /uv /usr/local/bin/uv
# The image's own Python, compiled bytecode, and files copied out of uv's cache (it is a mount).
ENV UV_PYTHON_DOWNLOADS=0 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
WORKDIR /app
# Dependencies first, in their own layer: a code change does not reinstall them.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    uv sync --frozen --no-dev --no-install-project

FROM python:3.13.18-slim AS runtime
ARG APP_UID=1000
RUN groupadd --gid "${APP_UID}" app \
    && useradd --uid "${APP_UID}" --gid app --create-home app \
    && mkdir -p /app/out /cache/fastembed \
    && chown app:app /app/out /cache/fastembed
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY --chown=app:app . .
# The venv first on the PATH, so `python`, `uvicorn` and `alembic` are its own, and so is the
# sys.executable the trace server is started with. The embedding model is cached in a volume.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    FASTEMBED_CACHE_PATH=/cache/fastembed
USER app
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
