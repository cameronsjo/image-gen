# MCP SDK upgrade for the 2026-07-28 protocol

Requested by Cameron in the 2026-10-14 sweep, via chief-of-staff addendum 1.

## Scope

Upgrade image-gen to FastMCP 4.1.0 and the official Python MCP SDK 2.3.0.
Use stateless Streamable HTTP, retain legacy-client compatibility and the SDK's
stdio transport, and preserve authenticated per-user image and quota behavior.
No merge, deployment, credentials, or paid generations are authorized.

## Delivery

- [x] Read the upstream stable release notes and protocol support statements.
- [x] Start from freshly fetched origin/main in an isolated worktree.
- [x] Merge the overlapping model-selection branch (PR #34) without rebasing.
- [x] Resolve SDK dependencies and apply required compatibility changes.
- [x] Verify modern stateless HTTP, legacy HTTP, and stdio tool enumeration.
- [x] Run the full test suite, lint, format, type checking, and package build.
- [x] Independently review the final change.
- [ ] Resolve the subjectless-JWT security policy with Cameron before publishing a PR.
- [ ] Open a ready PR after the policy is resolved; record CI results in report.md.

## Held security decision

The SDK's JWT verifier accepts otherwise valid tokens without a nonblank `sub`.
The current tool identity fallback then maps those authenticated requests to the
shared `anonymous` image and quota scope. Independent review identified this
as P1. This is not a deployable checkpoint despite the existing 247-test suite
passing: the adversarial subjectless-token probe is a separate failing gate.
Reproduce it with `uv run --locked python scripts/probe-mcp-subject.py`.

The brief reserves security-behavior changes for Cameron. Codex therefore holds
the upgrade PR and preserves the work as an explicitly broken checkpoint.

Proposed policy for approval: reject any authenticated JWT whose verified
subject is absent or whitespace, returning HTTP 401 before tool dispatch.
Retain anonymous access only for auth-disabled operation. Implement this at
the verifier boundary after its signature, issuer, audience, and expiry checks:

```python
token = await super().verify_token(raw_token)
if token is None or not token.subject or not token.subject.strip():
    return None
return token
```

Add modern and legacy rejection tests for missing and blank subjects, rerun the
full gates and real transport smoke, then re-engage the reviewer and publish.
If service tokens without subjects must be supported, Cameron must first choose
their ownership/quota identity; Codex will not invent a shared-user policy.

## Sources

- FastMCP stable release: https://github.com/PrefectHQ/fastmcp/releases/tag/v4.1.0
- FastMCP protocol support: https://github.com/PrefectHQ/fastmcp/releases/tag/v4.0.0
- Official Python SDK stable release: https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0
- Protocol specification release: https://blog.modelcontextprotocol.io/posts/2026-07-28/

The SDK PR includes PR #34's commit because the upgrade touches the MCP tools
and schema tests. PR #33's sizing refactor does not overlap the SDK upgrade.
