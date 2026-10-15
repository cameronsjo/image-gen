# Loaded-history costs — issue #25

Cameron authorized Phase 2 via cos-imagegen2/go.md. Codex owns this branch.

- [x] Display provider-reported per-generation costs in the history.
- [x] Display the total for the loaded history and label its limited scope.
- [x] Preserve unknown costs instead of treating them as zero.
- [x] Execute the shipped JavaScript against zero/null/missing/mixed costs and refresh cases.
- [x] Verify FastAPI serves the helper and HTML wiring.

Local gates passed: ruff lint/format, mypy, 310 pytest tests with 90.06% coverage,
and uv build. Browser verification was attempted through the available computer-use
surface, but no browser provider is available (browser inventory was empty).
No rendered-browser pass is claimed. Node behavioral tests executed, not skipped.
Issue #24 was deferred for an estimation-scope decision, so this branch aggregates
existing reported costs without introducing estimates. CHANGELOG.md remains owned by Release Please.
Delivery and independent review are tracked in the run report. No merge is authorized.
