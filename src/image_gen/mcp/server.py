"""FastMCP server instance creation."""

from fastmcp import FastMCP
from fastmcp.server.auth import AccessToken, JWTVerifier

from image_gen.config import Settings


class SubjectJWTVerifier(JWTVerifier):
    """Require an authenticated ownership identity before tool dispatch."""

    async def verify_token(self, token: str) -> AccessToken | None:
        verified = await super().verify_token(token)
        if verified is None or not verified.subject or not verified.subject.strip():
            return None
        return verified


def create_mcp_server(settings: Settings) -> FastMCP:
    """Create a FastMCP server, optionally with JWT auth."""
    if settings.auth_enabled:
        jwks_uri = f"{settings.oidc_issuer}/jwks.json"
        auth = SubjectJWTVerifier(
            jwks_uri=jwks_uri,
            issuer=settings.oidc_issuer,
            audience=settings.oidc_client_id,
        )
        mcp = FastMCP(
            "image-gen",
            auth=auth,
        )
    else:
        mcp = FastMCP("image-gen")

    # Import tools to register them on the server
    from image_gen.mcp import tools as _tools

    _tools.register(mcp)

    return mcp
