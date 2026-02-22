"""FastMCP server instance creation."""

from fastmcp import FastMCP
from fastmcp.server.auth import JWTVerifier, OAuthProvider

from image_gen.config import Settings


def create_mcp_server(settings: Settings) -> FastMCP:
    """Create a FastMCP server, optionally with JWT auth."""
    if settings.auth_enabled:
        jwks_uri = f"{settings.oidc_issuer}/jwks.json"
        token_verifier = JWTVerifier(
            jwks_uri=jwks_uri,
            issuer=settings.oidc_issuer,
            audience=settings.oidc_client_id,
        )
        auth = OAuthProvider(
            base_url=settings.oidc_issuer,
            issuer_url=settings.oidc_issuer,
        )
        # Override the token verifier on the auth provider
        auth.token_verifier = token_verifier

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
