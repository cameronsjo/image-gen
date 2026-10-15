"""Exercise the real setup shell with tiny pinned fixtures and no network."""

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts/setup-comfyui.sh"
ENTRY = re.compile(r'"(https://[^"|]+)\|([^"|]+)\|([^"|]+)\|([0-9a-f]{64})"')


def manifest():
    entries = ENTRY.findall(SCRIPT.read_text())
    assert len(entries) == 4
    return entries


def test_manifest_uses_immutable_revisions_and_sha256():
    for url, _, filename, digest in manifest():
        assert re.search(r"/resolve/[0-9a-f]{40}/", url)
        assert url.endswith("/" + filename)
        assert len(digest) == 64


@pytest.fixture
def setup(tmp_path):
    source = SCRIPT.read_text()
    entries = manifest()
    for _, _, filename, digest in entries:
        expected = hashlib.sha256(("fixture:" + filename).encode()).hexdigest()
        source = source.replace(digest, expected)
    script = tmp_path / "setup.sh"
    script.write_text(source)
    home = tmp_path / "Comfy workspace"
    home.mkdir()
    (home / "main.py").write_text("# Existing ComfyUI; do not install.\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    (binaries / "comfy").write_text("#!/bin/sh\nexit 0\n")
    (binaries / "comfy").chmod(0o755)
    curl = binaries / "curl"
    curl.write_text(
        "#!"
        + sys.executable
        + "\n"
        + r"""
import os
import sys
from pathlib import Path
args = sys.argv[1:]
output = Path(args[args.index('-o') + 1])
name = args[-1].rsplit('/', 1)[-1]
with Path(os.environ['TEST_DOWNLOAD_LOG']).open('a') as log:
    log.write(name + '\n')
mode = os.environ.get('TEST_DOWNLOAD_MODE', 'good')
output.write_bytes(('fixture:' + name).encode() if mode == 'good' else b'corrupted')
if mode == 'fail':
    sys.exit(22)
"""
    )
    curl.chmod(0o755)
    log = tmp_path / "downloads.log"
    env = dict(os.environ, COMFY_HOME=str(home), NO_COLOR="1", TEST_DOWNLOAD_LOG=str(log))
    env["PATH"] = str(binaries) + os.pathsep + os.environ["PATH"]

    def run(mode="good"):
        return subprocess.run(
            ["bash", str(script)],
            cwd=tmp_path,
            env={**env, "TEST_DOWNLOAD_MODE": mode},
            text=True,
            capture_output=True,
        )

    return run, home, log, entries, binaries


def assert_no_partial(home):
    assert not list(home.glob("models/*/*.partial*"))


def test_verified_downloads_and_existing_files(setup):
    run, home, log, entries, _ = setup
    result = run()
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert len(log.read_text().splitlines()) == 4
    for _, directory, filename, _ in entries:
        assert (home / "models" / directory / filename).read_bytes() == (
            "fixture:" + filename
        ).encode()
    log.write_text("")
    result = run()
    assert result.returncode == 0, result.stderr
    assert log.read_text() == ""
    assert_no_partial(home)


def test_corrupt_download_rejected_and_partial_removed(setup):
    run, home, _, entries, _ = setup
    result = run("corrupt")
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr
    _, directory, filename, _ = entries[0]
    assert not (home / "models" / directory / filename).exists()
    assert_no_partial(home)


def test_corrupt_existing_file_rejected_and_left_unchanged(setup):
    run, home, log, entries, _ = setup
    assert run().returncode == 0
    _, directory, filename, _ = entries[0]
    target = home / "models" / directory / filename
    target.write_bytes(b"corrupt-existing")
    log.write_text("")
    result = run()
    assert result.returncode != 0
    assert "existing model failed verification" in result.stderr
    assert target.read_bytes() == b"corrupt-existing"
    assert log.read_text() == ""


def test_download_failure_removes_partial(setup):
    run, home, _, _, _ = setup
    result = run("fail")
    assert result.returncode != 0
    assert "download failed" in result.stderr
    assert_no_partial(home)


def test_hashing_failure_does_not_install(setup):
    run, home, _, entries, binaries = setup
    for name in ("sha256sum", "shasum"):
        stub = binaries / name
        stub.write_text("#!/bin/sh\nexit 1\n")
        stub.chmod(0o755)
    result = run()
    assert result.returncode != 0
    _, directory, filename, _ = entries[0]
    assert not (home / "models" / directory / filename).exists()
    assert_no_partial(home)


def test_existing_non_file_is_not_treated_as_verified(setup):
    run, home, _, entries, _ = setup
    _, directory, filename, _ = entries[0]
    target = home / "models" / directory / filename
    target.mkdir(parents=True)
    result = run()
    assert result.returncode != 0
    assert "not a regular file" in result.stderr
    assert target.is_dir()
