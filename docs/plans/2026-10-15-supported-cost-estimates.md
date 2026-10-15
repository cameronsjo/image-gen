# Supported output-cost estimates — issue #24

Cameron explicitly authorized the supported-subset scope after the initial deferral:
only published model/size prices, output-only where that is all the source publishes,
source citations in code, and unknown for every other combination. Codex owns this branch.

Implementation choice: keep cost_usd as provider-reported charges and add a separate
nullable estimated_output_cost_usd field. Output-only list-price estimates are never
mixed into billed/reported history totals or presented as a total request cost.

- [x] Centralize exact published model/size lookups with source URLs; no scaling or alias guessing.
- [x] Populate the separate estimate for successful supported Gemini/OpenAI calls.
- [x] Persist/expose nullable estimates through REST/MCP and legacy-safe migration.
- [x] Label published-table output-only estimates explicitly in UI and MCP responses.
- [x] Verify supported values, unknown combinations, override models and API/database boundaries.
- [x] Complete independent review and the full local gates, then deliver a ready PR.

Delivery and final CI are recorded in the run report. No merge/deployment is authorized.

Codex verified 333 tests passing with 90.81% coverage, Ruff lint/format, mypy
and source/wheel builds. Independent code and agent-experience reviews found no
remaining supported defects after documentation corrections. Provider calls were mocked.

Separate pre-existing follow-up: Google lists the configured Gemini preview
default as shut down; migrating that default is outside this pricing change.
Source: https://ai.google.dev/gemini-api/docs/deprecations

## Fix round 1

- [x] Merge origin/main after #43; retain both README sections and descriptive-storage callers.
- [x] Verify full local gates on the combined artifact: 346 tests, 91.29% coverage, lint/format/types and build pass. Final push/CI evidence is in report-fix1.md.

## Fix round 2

- [x] Keep the approved supported subset; change PR relationship to Part of #24 with an exact coverage list.
- [x] Execute shipped showResult on REST metadata and assert rendered $0.134000, zero and unknown behavior.
- [x] Include estimated_output_cost_usd in the generation-completed log, preserving zero/null.

Final local checks, review and pushed-head CI are appended to report-fix1.md.

Fix-round 2 local gates passed: 349 tests, 91.29% coverage, lint/format/types,
and package builds. The wrong-rendered-value negative control failed as expected.
Codex reviewed this narrow log/test/documentation increment inline; no supported findings.

Subsequent main reconciliation resolves conflicts against e872b8d while keeping
both usage_json and estimated_output_cost_usd migrations, provider fields and
REST/MCP persistence. Combined metadata round-trip assertions cover both fields.
CHANGELOG.md remains byte-identical to main; final verification follows in report-fix1.md.

The reconciled artifact passed 366 tests with 91.37% coverage and all local
gates. Independent merge review found no behavioral/security defects; 36 cost/usage
tests passed independently. Resolved conflict files are staged as part of delivery.

## Standing-order reconciliation after #42

Merged main c45212c while retaining history totals and both usage/estimate fields.
Only README conflicted; main section order is retained and estimate documentation
follows Stored image names. CHANGELOG.md is byte-identical to main.
Full local gates passed: 370 tests, 91.60% coverage, lint/format/types/build.
Codex independently reviewed the resolution and passed 51 cost/history/image/usage
tests plus a shared-cache type check. Partial #24 scope remains unchanged.
