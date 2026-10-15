# History reported costs — issue #25

Cameron authorized Phase 2 via cos-imagegen2/go.md. Codex owns this branch.

- [x] Display provider-reported per-generation costs in the history.
- [x] Display separate server aggregates for all time and the current UTC day.
- [x] Preserve completed unknown costs instead of treating them as zero, and count non-completed statuses separately.
- [x] Execute the shipped JavaScript against zero/null/missing/mixed costs, explicit statuses, and aggregate formatting cases.
- [x] Verify FastAPI serves the helper and HTML wiring.

Initial branch gates passed: ruff lint/format, mypy, 310 pytest tests with 90.06% coverage,
and uv build. Fix-round gates pass with ruff lint/format, mypy, 325 pytest tests at 90.41% coverage,
and uv build. Browser verification was attempted through the available computer-use
surface, but no browser provider is available (browser inventory was empty).
No rendered-browser pass is claimed. Node behavioral tests executed, not skipped.
Issue #24's approved estimate field remains separate from these reported-cost totals,
so this branch aggregates existing reported costs without introducing estimates. CHANGELOG.md remains owned by Release Please.
Delivery and independent review are tracked in report-fix1.md. No merge is authorized.

Fix-round correction: the UI now reads an authenticated server aggregate with explicit all-time and current-UTC-day scopes, rather than treating the most recent loaded rows as a total. Pending, generating, and failed rows are excluded from cost sums, labeled by status in each row, and counted separately in each aggregate.

Fix-round independent review confirmed ownership/status/UTC boundaries. Codex addressed
the supported finite-sum overflow edge by retaining an explicitly unknown total when
the sum cannot be represented, with a repository and API regression test.
The UI labels today as UTC. Final gate results and CI are in report-fix1.md.
