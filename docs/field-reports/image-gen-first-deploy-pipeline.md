# image-gen First Deploy Pipeline -- Field Report

**Date:** 2026-02-22
**Type:** pipeline + discovery
**Project:** image-gen

## Goal

Get the image-gen service from "code on main" to "running container on Unraid, routable via Traefik, with Authelia auth" -- the full pipeline: Release Please PR, GHCR Docker image, Bosun reconciliation, and live healthchecks.

## Pipeline Overview

```
git push (fix: commit)
  -> Release Please creates PR (v0.1.x)
  -> Merge PR
  -> release-please job creates tag + GitHub Release
  -> docker-publish job (same workflow, needs: release-please)
     -> docker/build-push-action -> GHCR
     -> actions/attest-build-provenance -> SLSA attestation
  -> docker pull on Unraid
  -> bosun trigger -> reconcile -> compose up
  -> Traefik routes imagegen.sjo.lol -> container:8000
  -> Authelia forward-auth protects all endpoints
```

Three release cycles were needed to get a working image: v0.1.1, v0.1.2, v0.1.3.

## What Went Wrong

### v0.1.1: Hatchling needs README.md in Docker context

**Error:** `OSError: Readme file does not exist: README.md`

Hatchling reads `readme = "README.md"` from pyproject.toml during wheel build. The Dockerfile only copied `pyproject.toml` and `uv.lock` into the builder stage. Hatchling couldn't find README.md when `uv sync` triggered the build.

**Fix:** `COPY pyproject.toml uv.lock README.md ./`

**Lesson:** Any file referenced in pyproject.toml metadata must be present during `uv sync`. Check `readme`, `license`, and `include` fields.

### v0.1.2: uv editable install breaks multi-stage Docker

**Error:** `No module named image_gen` (container crash loop)

This was the most interesting bug. `uv sync` installs the project package as an editable install, creating a `.pth` file (`_image_gen.pth`) in `site-packages/` that contains the path `/app/src/image_gen`. In the builder stage, this path exists. But the runtime stage only copied `.venv` -- not `src/`. The `.pth` file pointed to a directory that didn't exist.

**Evidence:**

```
$ ls .venv/lib/python3.*/site-packages/ | grep image
_image_gen.pth              # <- points to /app/src/image_gen
image_gen-0.1.0.dist-info   # <- metadata only, no actual code
```

**Fix:** Added `COPY --from=builder /app/src /app/src` to the runtime stage.

**Alternative:** Could use `uv pip install --no-editable .` instead of `uv sync` to create a non-editable install that copies the package into site-packages. But copying src/ is simpler and keeps the Dockerfile consistent.

**Lesson:** `uv sync` always creates editable installs for the project package. In multi-stage Docker builds, you must copy the source tree to the runtime stage alongside the venv.

### v0.1.3: Host directories don't exist on Unraid

**Error:** `sqlite3.OperationalError: unable to open database file`

The compose volume mounts (`/mnt/user/appdata/image-gen:/app/appdata`) assume the host directories exist. First deploy -- they didn't. Docker creates mount-point directories as root, but aiosqlite can't create the DB file if the parent directory doesn't exist or has wrong permissions.

**Fix:**

```bash
mkdir -p /mnt/user/appdata/image-gen /mnt/user/data/image-gen/images
chown -R 1000:1000 /mnt/user/appdata/image-gen /mnt/user/data/image-gen
docker restart image-gen
```

**Lesson:** Bosun manifests should ideally create host directories before compose up. For now, first deploys of new services need manual directory creation. Could add an init container or a pre-start script.

## Bosun Operational Discovery

### Socket Path Mismatch

`bosun trigger` defaults to `/var/run/bosun.sock`, but the container configures `BOSUN_SOCKET_PATH=/tmp/bosun.sock`. Must specify:

```bash
docker exec bosun bosun trigger --socket /tmp/bosun.sock
```

Use `--force` to skip the "already deployed this commit" short-circuit.

### Reconciliation Lock

Running `bosun reconcile` manually inside the container fails with "lock already held" because the daemon holds the lock. Always trigger via socket, never run reconcile directly when the daemon is running.

### Compose File Layout

Bosun groups services by the `group` field in manifests and renders them into separate compose files:

```
/mnt/user/appdata/compose/
  ai.yml        # group: AI (image-gen, llm-council, agentgateway, etc.)
  apps.yml      # group: Apps
  arr.yml       # group: Media
  core.yml      # group: Core
  ...
```

To operate on a single service: `docker compose -f /mnt/user/appdata/compose/ai.yml up -d image-gen`

### Provisioning vs Reconciliation

- `bosun provision <service> --dry-run` (from `/app/repo`) shows the rendered compose/traefik/gatus output
- `bosun reconcile` or `bosun trigger` runs the full GitOps loop: git pull, decrypt secrets, render templates, deploy, compose up
- The daemon runs an initial reconciliation on startup, then polls on `BOSUN_POLL_INTERVAL` (default 1h)

### Environment Variables

Bosun uses `BOSUN_` prefixed env vars internally but the reconcile command expects unprefixed names (`REPO_URL`, `REPO_BRANCH`, `SECRETS_FILES`). The daemon maps these automatically, but manual `docker exec bosun bosun reconcile` requires manual mapping:

```bash
docker exec bosun sh -c 'REPO_URL=$BOSUN_REPO_URL REPO_BRANCH=$BOSUN_REPO_BRANCH SECRETS_FILES=$BOSUN_SECRETS_FILE bosun reconcile'
```

## GitHub Actions: Permissions Gotcha

Release Please needs write permissions to create PRs. The repo's `default_workflow_permissions` was `read` (GitHub default for new repos). Fix:

```bash
gh api repos/{owner}/{repo}/actions/permissions/workflow \
  -X PUT \
  -f default_workflow_permissions=write \
  -F can_approve_pull_request_reviews=true
```

## Gotchas

- **Beads pre-commit hook**: image-gen has beads initialized but no SQLite DB. The hook tries to flush and fails. Workaround: `--no-verify` or `bd init` or set `no-db: true` in `.beads/config.yaml`
- **docker-publish is not a separate workflow**: It's a job within `release-please.yml` with `needs: release-please`. Both share a single run ID. Don't look for a separate workflow run.
- **Watchtower won't help on first deploy**: Watchtower monitors running containers for image updates. If the container was never started, you need to pull manually and compose up.

## Key Takeaways

- `uv sync` in Docker multi-stage builds requires copying `src/` to the runtime stage because it creates editable installs via `.pth` files
- First deploy of any new service on Unraid needs manual host directory creation (`mkdir -p` + `chown 1000:1000`)
- Bosun trigger command: `docker exec bosun bosun trigger --socket /tmp/bosun.sock --force`
- Always test Docker builds locally (`docker build && docker run`) before pushing -- catches module import issues before burning a release cycle
- Three release cycles to get a working image is too many -- a local smoke test of `python -m image_gen` inside the built container would have caught both issues
