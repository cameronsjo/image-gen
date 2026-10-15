# Model-download integrity — issue #28

Cameron authorized tightening-only hardening via cos-imagegen2/go.md.

- [x] Pin immutable revisions and SHA-256 for all four model files.
- [x] Independently verify the hash-to-file mapping from pinned Hugging Face metadata.
- [x] Verify existing files before skipping; preserve mismatched existing files unchanged.
- [x] Verify fresh downloads before rename; use unique sibling temporary files and remove failures.
- [x] Support Linux sha256sum and macOS shasum; fail closed on hashing failure.
- [x] Exercise tiny local fixtures with stub curl/comfy; no models downloaded or installed.
- [x] Remove both verification sites in a disposable copied script: both corrupt-file tests fail.
- [x] Remove unique temporary downloads on normal exit and INT/TERM interruption.
- [x] Set verified newly installed model files to mode 0644 before atomic rename.
- [x] Exercise interrupted-download cleanup, signal exit status, and installed modes with tiny fixtures.
- [x] Final gates: 330 tests / 90.14% coverage, ruff lint/format, mypy, bash syntax, ShellCheck, uv build.
- [x] Original checksum implementation's independent code/security reviews completed without change-induced findings.
- [x] Fix-round independent code/security review completed without supported findings.
- [x] Codex independently reran 9 setup tests, syntax/ShellCheck and both new control-removal probes.

Hosting can require publisher access; this change does not acquire/manage credentials.
The pre-existing same-user destination-symlink race in mv is outside the checksum fix;
model directories are assumed operator-controlled. Reviewers did not count it as a regression.
Fix-round delivery/CI and the orchestrator's separate Opus review gate are recorded in report-fix1.md.
Release Please owns generated changelog entries. No merge or deployment is authorized.
