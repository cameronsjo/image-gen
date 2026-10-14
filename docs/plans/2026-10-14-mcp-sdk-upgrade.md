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
- [x] Resolve the subjectless-JWT security policy with Cameron before publishing a PR.
- [x] Open a ready PR after the policy is resolved; record final CI results in report-fix2.md.

## Approved security decision

The SDK's JWT verifier accepts otherwise valid tokens without a nonblank `sub`.
Independent review demonstrated that the tool identity fallback exposed the
shared `anonymous` image and quota scope. The pushed `wip: broken` checkpoint
is retained in history; it is not deployable.

Cameron approved fail-closed HTTP 401 rejection at the verifier boundary in
`brief-fix2.md`. Codex implemented this as a new commit, without rewriting the
pushed checkpoint. Valid identities remain unchanged; no service-token identity
or shared-user policy is invented.

Approved policy: reject any authenticated JWT whose verified
subject is absent or whitespace, returning HTTP 401 before tool dispatch.
Retain anonymous access only for auth-disabled operation. Implement this at
the verifier boundary after its signature, issuer, audience, and expiry checks:

```python
token = await super().verify_token(raw_token)
if token is None or not token.subject or not token.subject.strip():
    return None
return token
```

Modern and legacy rejection tests cover missing, empty, and whitespace-only
subjects. `uv run --locked python scripts/probe-mcp-subject.py` checks HTTP 401
and that seeded anonymous records are not exposed. Valid-user isolation and
auth-disabled operation are checked separately.

## Sources

- FastMCP stable release: https://github.com/PrefectHQ/fastmcp/releases/tag/v4.1.0
- FastMCP protocol support: https://github.com/PrefectHQ/fastmcp/releases/tag/v4.0.0
- Official Python SDK stable release: https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0
- Protocol specification release: https://blog.modelcontextprotocol.io/posts/2026-07-28/

The SDK PR includes PR #34's commit because the upgrade touches the MCP tools
and schema tests. PR #33's sizing refactor does not overlap the SDK upgrade.

## Delivery evidence

- Ready PR: https://github.com/cameronsjo/image-gen/pull/36 (left open).
- Fix commit: `9ba9981`, following the pushed `wip: broken` checkpoint and merges
  of current main (PR #33) and the overlapping PR #34 branch. No history rewritten.
- Final source checks: 261 tests, 89.76% coverage; lint, format, types, build,
  six rejection probes, and real modern/legacy HTTP and stdio smoke all passed.
- Independent read-only code/security review found no supported remaining
  defects; it independently reran the 20 transport tests and six rejection probes.
- Live issuer/JWKS access, paid-provider calls, merge, and deployment were not
  performed. Provider discovery and signing material are test-only.
- `CHANGELOG.md` matches main; release-please owns generated release entries.

## Round 3 approved security follow-ups

Cameron authorized these in `brief-fix3.md`; scope remains PR #36, without
merge/deployment or history rewriting.

- [x] Merge freshly fetched main after PR #34 merged, leaving an SDK-only diff.
- [x] Fail closed in tools when auth is enabled but verified identity is absent;
  retain anonymous access only with auth disabled and test both dispatch modes.
- [x] Require `exp` in authenticated JWTs, in addition to nonblank `sub`.
- [x] Enable strict MCP Host/Origin protection with loopback defaults and
  `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS` JSON-array allowlists for LAN/proxy
  access. Map the SDK's rejected-Host 421 to the requested 403 and document it.
- [x] Run subject rejection tests on `tools/call` as well as `tools/list` in CI.
- [ ] Complete final security review, quality gates, push and current-head CI;
  write `report-fix3.md` and stop.

The review finding that PR #36 bundled PR #34 is declined: merging current main
after #34 landed removes those feature changes from the net SDK diff.
