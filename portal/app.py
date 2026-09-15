"""FastAPI application factories for the local management boundary."""

from __future__ import annotations

from fastapi import FastAPI

from .management import ManagementDependencies, install_management_api


def create_app(dependencies: ManagementDependencies | None = None) -> FastAPI:
    """Create the portal application.

    Management routes are installed only when explicit, authenticated dependencies are
    supplied.  This keeps importing the development liveness application fail-closed.
    """
    application = FastAPI(title="modularDiscordBotOperator", version="0.2.0")

    @application.get("/health", tags=["platform"])
    async def liveness() -> dict[str, str]:
        return await health()

    if dependencies is not None:
        install_management_api(application, dependencies)
    return application


async def health() -> dict[str, str]:
    """Report only portal-process liveness, not bot readiness."""
    return {"status": "ok", "component": "portal"}


app = create_app()
