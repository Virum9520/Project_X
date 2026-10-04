"""Owner-assistant tool gateway (Phase 12). Placeholder service with health probe."""

from fastapi import FastAPI

app = FastAPI(title="Skill Garden MCP Gateway", version="0.1.0")


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "mcp-gateway"}
