"""Minimal unauthenticated liveness endpoint; management routes are deferred."""

from fastapi import FastAPI

app = FastAPI(title="modularDiscordBotOperator", version="0.1.0")


@app.get("/health", tags=["platform"])
async def health() -> dict[str, str]:
    """Report only portal-process liveness, not bot readiness."""
    return {"status": "ok", "component": "portal"}
