# FastMCP ASGI Integration — Fixing the /mcp 307 Redirect — Field Report

**Date:** 2026-03-23
**Type:** investigation
**Project:** image-gen

## Goal

Diagnose why the agentgateway's MCP session to `http://image-gen:8000/mcp` was failing with a 307 Temporary Redirect, and fix the server so MCP transport works end-to-end through the gateway.

## Root Cause

Two independent bugs, both rooted in incomplete ASGI sub-application integration:

**Bug 1: Starlette mount trailing-slash redirect.** When FastAPI mounts a sub-application via `app.mount("/mcp", mcp_app)`, Starlette's `Mount` class returns a 307 redirect for requests to `/mcp` (no trailing slash), pointing them to `/mcp/`. Most MCP clients — including the agentgateway — send `POST /mcp` and do not follow redirects on POST requests (per HTTP spec, clients should not automatically redirect POST without user confirmation). The MCP endpoint was reachable at `/mcp/` but not at `/mcp`.

**Bug 2: FastMCP lifespan not composed.** `app.mount()` only forwards HTTP requests to the sub-application — it does **not** run the sub-app's ASGI lifespan. FastMCP's `StreamableHTTPSessionManager` initializes its `anyio` task group inside a lifespan context manager (`session_manager.run()`). Without it, every request to the MCP endpoint — even at the correct path — raises `RuntimeError: Task group is not initialized`.

These bugs were independent but masked each other: the 307 redirect prevented requests from reaching the handler, so the lifespan error was never observed until the redirect was fixed.

## Gotchas

**`BaseHTTPMiddleware` breaks SSE streaming.** The obvious fix for the trailing-slash redirect is `@app.middleware("http")`, but this uses Starlette's `BaseHTTPMiddleware`, which buffers the entire response body before sending. MCP uses Server-Sent Events (SSE) for streaming responses — buffering defeats the purpose. The fix must use a raw ASGI middleware class that passes `scope`/`receive`/`send` through without touching the response.

**`app.mount()` is request-only, not lifecycle.** This is a Starlette fundamental that's easy to miss. The mounted sub-app's lifespan never runs unless you explicitly compose it into the parent's lifespan. FastMCP's error message is helpful — it names the fix — but you have to reach the handler first (past the 307) to see it.

**Scope mutation requires a copy.** When rewriting `scope["path"]` in ASGI middleware, you should shallow-copy the scope dict (`scope = dict(scope, path="/mcp/")`) rather than mutating in-place. The scope dict is shared across middleware layers, and in-place mutation can cause subtle bugs in other middleware that inspects the original path.

## Recommendations

**For any FastMCP + FastAPI integration:**

1. Always compose lifespans explicitly:

   ```python
   mcp_starlette = mcp.http_app(path="/")
   app.state.mcp_app = mcp_starlette
   app.mount("/mcp", mcp_starlette)

   # In the FastAPI lifespan:
   async with mcp_app.lifespan(mcp_app):
       # ... rest of app initialization ...
       yield
   ```

2. Add a raw ASGI middleware for the trailing-slash rewrite:

   ```python
   class MCPSlashRewrite:
       def __init__(self, app: ASGIApp) -> None:
           self.app = app

       async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
           if scope["type"] == "http" and scope["path"] == "/mcp":
               scope = dict(scope, path="/mcp/")
           await self.app(scope, receive, send)

   app.add_middleware(MCPSlashRewrite)
   ```

3. Never use `BaseHTTPMiddleware` on paths that serve SSE or streaming responses.

**For agentgateway config:** The target URL `http://image-gen:8000/mcp` (without trailing slash) is the canonical form and now works correctly. No gateway config change needed.

## Key Takeaways

- `app.mount()` in Starlette/FastAPI is **request forwarding only** — it does not compose ASGI lifespans. Any mounted sub-app with initialization logic needs explicit lifespan composition.
- Starlette's 307 trailing-slash redirect on mount points is a known behavior that breaks HTTP clients that don't auto-redirect POST requests. A raw ASGI middleware rewrite is the clean fix.
- When debugging "MCP endpoint returns 307," check the `Location` header — it tells you the canonical path. The real endpoint was always there, just behind a redirect.
- Two bugs can mask each other: fix the first (redirect) and you may discover the second (lifespan). Test one layer at a time.
- Raw ASGI middleware is the right tool for path rewriting on streaming endpoints — `BaseHTTPMiddleware` buffers responses and breaks SSE.
