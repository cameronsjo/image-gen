# ComfyUI image response limit — issue #27

Cameron authorized tightening-only hardening via cos-imagegen2/go.md.

- [x] Add a positive configurable 64 MiB default; document its environment setting.
- [x] Stream image bytes with bounded chunks; reject declared and actual oversized responses.
- [x] Request identity encoding and reject unexpected compression before decoding.
- [x] Preserve normal, exact-limit, HTTP-error and timeout behavior; close streams on failure.
- [x] Restore status/filename logs on every ComfyUI view rejection without logging response bodies.
- [x] Prove actual byte enforcement: guard removal in a disposable copy causes 3 failures.
- [x] Run real-package ComfyUI checks after the negative control: 54 tests passed.
- [x] Full gates: ruff lint/format, mypy, 322 tests / 90.16% coverage, uv build.
- [x] Independent code/security reviews found no supported defects; add the advised example setting.

Settings parsed IMAGEGEN_COMFYUI_MAX_IMAGE_BYTES=2048 successfully in a direct consuming-tool probe.
No live server or model download was required. Delivery is tracked in report.md.
Release Please owns generated changelog entries. No merge/deployment is authorized.

## Fix round 1

- [x] Merge origin/main at 615b109 before the logging fix.
- [x] Restore structured status/filename errors on HTTP, encoding, declared-size and actual-size rejection.
- [x] Full local gates: 337 tests, 90.28% coverage, lint/format/types and build pass.
- [x] Codex independently reran both ComfyUI suites: 56 tests pass.

Independent fix review and final pushed-head/CI evidence are tracked in report-fix1.md.

## Standing-order reconciliation after #42

Resolved README against main c45212c while retaining ComfyUI limits, history costs,
usage metadata and storage documentation. CHANGELOG.md remains unchanged from main.
Final checks and delivery are appended to report-fix1.md.

Reconciled local gates passed: 358 tests, 90.62% coverage, lint/format/types.
Codex reviewed the README-only conflict inline; response-limit source is unchanged.
