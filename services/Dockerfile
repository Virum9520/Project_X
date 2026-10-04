# Shared image for Python services. Build from repo root:
#   docker build -f services/Dockerfile --build-arg SERVICE=sg_api -t sg-api .
FROM python:3.12-slim AS base
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
WORKDIR /app

ARG SERVICE=sg_api
COPY pyproject.toml uv.lock .python-version ./
COPY services ./services
RUN uv sync --frozen --no-dev --package ${SERVICE}

ENV PATH="/app/.venv/bin:$PATH" PORT=8000
EXPOSE 8000
# Railway/ECS override the command per service; default runs the API.
CMD ["sh", "-c", "uvicorn sg_api.main:app --host 0.0.0.0 --port ${PORT}"]
