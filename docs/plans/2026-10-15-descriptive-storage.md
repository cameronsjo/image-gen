# Descriptive stored filenames — issue #22

Cameron authorized this tightening-only hardening pick via cos-imagegen2/go.md.

- [x] Reuse sanitized record.download_name for REST and MCP stored filenames.
- [x] Serve the persisted path after the existing ownership check and containment validation.
- [x] Preserve legacy ULID files and cwd-relative persisted paths without bulk renaming.
- [x] Refuse path components, symlink escapes, and collisions at the write boundary.
- [x] Exercise descriptive/legacy serving, Unicode names, traversal, symlinks and uniqueness.
- [x] Stage removal of containment in a disposable package copy: all three traversal tests failed.
- [x] Recheck the real package: 33 storage/download/isolation tests passed after the negative control.
- [x] Full local gates passed: lint, format, mypy, 321 tests / 90.14% coverage, uv build.

Independent code/security review and delivery are recorded in the run report.
The shared environment/cache is reused; no Docker image or model was built/downloaded.
Release Please owns generated changelog entries. No merge or deployment is authorized.
