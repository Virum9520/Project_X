# Shared image for the Python services. Build from the repo root:
#   docker build -f services/Dockerfile --build-arg SERVICE=sg_api -t sg-api .
#
# SERVICE picks the workspace package to install and the process to run
# (see services/docker-entrypoint.sh). On Railway, set SERVICE as a service
# variable: Railway passes variables declared with ARG into the build.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never PYTHONUNBUFFERED=1
WORKDIR /app

ARG SERVICE=sg_api
ENV SERVICE=${SERVICE}

# Third-party dependencies first, so source edits don't invalidate this layer.
# Every uv workspace member needs a line here (CI's docker job fails otherwise).
COPY pyproject.toml uv.lock .python-version ./
COPY services/core/pyproject.toml services/core/
COPY services/api/pyproject.toml services/api/
COPY services/worker/pyproject.toml services/worker/
COPY services/mcp_gateway/pyproject.toml services/mcp_gateway/
COPY services/agentops/pyproject.toml services/agentops/
RUN uv sync --frozen --no-dev --package "${SERVICE}" --no-install-workspace

COPY alembic.ini ./
COPY services ./services
RUN uv sync --frozen --no-dev --package "${SERVICE}" \
    && useradd --system --uid 10001 --no-create-home app

ENV PATH="/app/.venv/bin:$PATH" PORT=8000
USER app
EXPOSE 8000
ENTRYPOINT ["/app/services/docker-entrypoint.sh"]
