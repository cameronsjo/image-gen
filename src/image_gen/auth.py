"""Dual authentication: forward-auth headers (REST) + JWT (MCP).

REST endpoints rely on Traefik's Authelia forward-auth middleware — user identity
arrives via headers. MCP endpoints validate JWTs directly against the Authelia
OIDC issuer. Both paths resolve to an AuthenticatedUser.

Auth bypass is available via IMAGEGEN_AUTH_ENABLED=false for local development.
"""

from dataclasses import dataclass

import structlog
from fastapi import HTTPException, Request

logger = structlog.get_logger()

# Headers set by Authelia forward-auth
HEADER_USER = "Remote-User"
HEADER_NAME = "Remote-Name"
HEADER_EMAIL = "Remote-Email"
HEADER_GROUPS = "Remote-Groups"


@dataclass(frozen=True)
class AuthenticatedUser:
    """Resolved user identity from either auth path."""

    user_id: str
    name: str
    email: str
    groups: list[str]


def _anonymous_user() -> AuthenticatedUser:
    """Default user when auth is disabled."""
    return AuthenticatedUser(
        user_id="anonymous",
        name="Anonymous",
        email="",
        groups=[],
    )


async def get_current_user(request: Request) -> AuthenticatedUser:
    """Extract the authenticated user from the request.

    Checks forward-auth headers first (set by Traefik/Authelia),
    falls back to anonymous when auth is disabled.
    """
    settings = request.app.state.settings

    if not settings.auth_enabled:
        user = _anonymous_user()
        request.state.user_id = user.user_id
        return user

    # Try forward-auth headers (REST path behind Traefik)
    user_id = request.headers.get(HEADER_USER)
    if user_id:
        groups_raw = request.headers.get(HEADER_GROUPS, "")
        user = AuthenticatedUser(
            user_id=user_id,
            name=request.headers.get(HEADER_NAME, user_id),
            email=request.headers.get(HEADER_EMAIL, ""),
            groups=[g.strip() for g in groups_raw.split(",") if g.strip()],
        )
        request.state.user_id = user.user_id
        logger.debug("User authenticated via forward-auth", user_id=user.user_id)
        return user

    logger.warning("No authentication credentials found")
    raise HTTPException(status_code=401, detail="Authentication required")
