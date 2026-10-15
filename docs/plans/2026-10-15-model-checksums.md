# Model-download integrity — issue #28

Cameron authorized tightening-only hardening via cos-imagegen2/go.md.

- [x] Pin immutable revisions and SHA-256 for all four model files.
- [x] Independently verify the hash-to-file mapping from pinned Hugging Face metadata.
- [x] Verify existing files before skipping; preserve mismatched existing files unchanged.
- [x] Verify fresh downloads before rename; use unique sibling temporary files and remove failures.
- [x] Support Linux sha256sum and macOS shasum; fail closed on hashing failure.
- [x] Exercise tiny local fixtures with stub curl/comfy; no models downloaded or installed.
- [x] Remove both verification sites in a disposable copied script: both corrupt-file tests fail.
- [x] Final gates: 315 tests / 90.06% coverage, ruff lint/format, mypy, bash syntax, ShellCheck, uv build.
- [x] Independent code/security reviews completed without change-induced findings.

Hosting can require publisher access; this change does not acquire/manage credentials.
The pre-existing same-user destination-symlink race in mv is outside the checksum fix;
model directories are assumed operator-controlled. Reviewers did not count it as a regression.
Delivery and the orchestrator's separate Opus review gate are recorded in report.md.
Release Please owns generated changelog entries. No merge or deployment is authorized.
