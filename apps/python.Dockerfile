# One Python image for the Campaign API, the worker, and the fakes and the MCP servers; the chart picks
# the process with `python -m <package>`. Build from the repo root:
#   docker build -f apps/python.Dockerfile .
# Base images are pinned by index digest (docs/pinned-versions.md).
FROM python:3.13-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641
COPY --from=ghcr.io/astral-sh/uv:0.12.0@sha256:606e70c71c852d03f611b1e56a195d08648507018a7057fab82c4974c4eae105 /uv /usr/local/bin/uv

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first, from the lockfile only, so a source change reuses this layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# The source roots of pyproject.toml's pythonpath. Owned by the app user, so Tilt's live
# update can sync a saved file into the running container.
COPY --chown=10001:10001 apps/engine /app/apps/engine
COPY --chown=10001:10001 apps/api /app/apps/api
COPY --chown=10001:10001 apps/worker /app/apps/worker
COPY --chown=10001:10001 services /app/services
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/apps/engine:/app/apps/api:/app/apps/worker:/app/services/fakes:/app/services/render:/app/services/mcp
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "campaign_api"]
