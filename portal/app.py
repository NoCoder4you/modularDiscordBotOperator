"""FastAPI application factories for the local management boundary."""

from __future__ import annotations

from fastapi import FastAPI

from .management import ManagementApplication, ManagementDependencies, install_management_api
from .web import PortalDependencies, install_portal


def create_app(
    dependencies: ManagementDependencies | None = None,
    portal_dependencies: PortalDependencies | None = None,
) -> FastAPI:
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
    if portal_dependencies is not None:
        install_portal(application, portal_dependencies)
    return application


def create_portal_app(
    management_dependencies: ManagementDependencies,
    *,
    identities,
    sessions,
    secure_cookies: bool = True,
) -> FastAPI:
    """Compose both transports over one Stage 9 dependency set."""
    portal_dependencies = PortalDependencies(
        ManagementApplication(management_dependencies),
        identities,
        sessions,
        management_dependencies.authorizer,
        management_dependencies.audit_sink,
        secure_cookies,
        management_dependencies.resources,
        management_dependencies.backups,
    )
    return create_app(management_dependencies, portal_dependencies)


async def health() -> dict[str, str]:
    """Report only portal-process liveness, not bot readiness."""
    return {"status": "ok", "component": "portal"}


app = create_app()
