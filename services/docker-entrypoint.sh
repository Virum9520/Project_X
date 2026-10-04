#!/bin/sh
# Starts the process for $SERVICE (baked in at build time, see services/Dockerfile).
# HOST defaults to 0.0.0.0; set HOST=:: to also listen on IPv6 (Railway private networking).
# Arguments, if any, replace the default command, e.g. `docker run sg-api alembic upgrade head`.
set -eu

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

case "${SERVICE}" in
  sg_api)
    exec uvicorn sg_api.main:app --host "${HOST:-0.0.0.0}" --port "${PORT}" \
      --proxy-headers --forwarded-allow-ips '*' --no-server-header
    ;;
  sg_mcp_gateway)
    exec uvicorn sg_mcp_gateway.main:app --host "${HOST:-0.0.0.0}" --port "${PORT}" \
      --proxy-headers --forwarded-allow-ips '*' --no-server-header
    ;;
  sg_worker)
    exec python -m sg_worker.main
    ;;
  *)
    echo "docker-entrypoint: unknown SERVICE '${SERVICE}'" >&2
    exit 64
    ;;
esac
