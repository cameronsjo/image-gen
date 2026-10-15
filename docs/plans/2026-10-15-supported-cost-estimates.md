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
