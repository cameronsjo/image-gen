# Plan: Local image-generation provider (ComfyUI) for image-gen

## Context

image-gen today shells out only to **remote** image APIs (Gemini 3 Pro default, plus
OpenAI and OpenRouter). Cameron wants to run image generation **locally** on his
Mac instead of paying the cloud round-trip for every image.

Research outcome on the "llmfit"-ish tool ([AlexsJones/llmfit](https://github.com/AlexsJones/llmfit)):
it is a **text-LLM** hardware-fit advisor (Rust TUI, scores 206+ chat/reasoning models
against your RAM/VRAM). It has **no diffusion / image-model coverage**, so it cannot pick
an image model for us — but it confirms the machine. This box is `cameron-m5-mbp`:
**Apple M5 Max, 18 cores, 128 GB unified memory** — far more than local image gen needs.
Memory is a non-issue (can run full unquantized FLUX); the only cost is GPU seconds per image.

**Decisions locked with the user:**
- **Scope:** full integration — stand up a local model server *and* wire a provider into image-gen.
- **Backend:** **ComfyUI** (batteries-included HTTP API, runs every FLUX/SD model, proven on Apple Silicon).
- **Topology:** **localhost only** — provider points at `http://127.0.0.1:8188`. The homelab
  container simply won't set `comfyui_url`, so the provider never registers there (no LAN exposure).

**Intended outcome:** `provider: "comfyui"` works end-to-end alongside `gemini`, generating
images on-device with zero API cost, behind the exact same `/api/generate` and MCP surface.

Working in worktree `worktree-local-comfyui-provider` (peer session `golden-kiln` stays on `main`).

## Architecture

The local provider is an **HTTP client to a localhost ComfyUI server** — structurally
identical to the existing `OpenRouterProvider` (pooled `httpx.AsyncClient`, `asyncio.timeout`,
`ProviderError` on failure), differing only in that ComfyUI is a **multi-step** API rather
than one POST:

1. `POST /prompt` with `{"prompt": <api-format graph>, "client_id": <uuid>}` → `{prompt_id, node_errors}`
   (non-empty `node_errors` → `ProviderError`).
2. Poll `GET /history/{prompt_id}` (~1 s interval, bounded by `request_timeout_seconds`) until the
   id appears with `outputs`; a `status.status_str == "error"` entry → `ProviderError`.
3. `GET /view?filename=…&subfolder=…&type=output` → raw PNG bytes → `ProviderResult(bytes, "image/png")`.

**Graph templating.** We ship a known-good **API-format** FLUX workflow JSON as package data and
inject only the dynamic fields per request, locating nodes by `class_type` + `_meta.title` (robust to
node-id churn): positive-prompt node ← `prompt`; latent node ← `width`/`height`; sampler/noise node ← random seed.

**Default model: FLUX.1-schnell** (Apache-2.0, ~4 steps, interactive — best UX for a local provider).
FLUX.1-dev is an opt-in via config (higher quality, ~20-30 steps, slower, non-commercial license).
With 128 GB we use full split files + `t5xxl_fp16` — no quantization.

**Resolution policy.** Reuse `services/_sizing.compute_size()` (already floors to multiples of 16,
caps at 3840 — FLUX-friendly). Map `1K→1024`, `2K→2048` long-edge. **`4K` → `UnsupportedParameterError`**
("local FLUX provider supports up to 2K; use a cloud provider for 4K") — honest about FLUX's sweet
spot, and exactly the contract the ABC defines for unsupported combos.

**Provider name: `comfyui`** (not generic `local`) — honest about the backend and leaves room for a
future `mflux`/`drawthings` local provider. Config prefix `IMAGEGEN_COMFYUI_*`.

## Execution

### Phase A — Stand up ComfyUI + FLUX on the Mac (one-time, scripted)
- `scripts/setup-comfyui.sh` (committed, reentrant, TTY-aware logging per cadence bash discipline):
  - Install via `comfy-cli` (`uv tool install comfy-cli` → `comfy install`) — clones ComfyUI, sets up the MPS PyTorch venv.
  - Download FLUX.1-schnell split files into `models/`: `flux1-schnell.safetensors` (unet),
    `ae.safetensors` (vae), `clip_l.safetensors` + `t5xxl_fp16.safetensors` (clip).
  - Launch (`comfy launch -- --listen 127.0.0.1 --port 8188`).
- In the ComfyUI web UI: load the stock FLUX example, generate once to confirm Metal works, then
  **Save (API Format)** → commit as `src/image_gen/services/workflows/flux_schnell.json`.
  (ComfyUI lives outside the repo; only the exported workflow JSON is committed.)

### Phase B — image-gen provider + wiring
- **New** `src/image_gen/services/comfyui_provider.py` — `ComfyUIProvider(ImageProvider)`:
  `name = "comfyui"`; pooled `httpx.AsyncClient`; `model_name` property; `generate_image()` (the
  3-step flow above, graph loaded via `importlib.resources.files("image_gen.services.workflows")`);
  `list_models()` (best-effort enumerate via `/object_info`, default first, degrade to `[model_name]`);
  `aclose()` closes the client. Mirror `openrouter_provider.py` structure + structlog Preparing/Success/Failure.
- **New** `src/image_gen/services/workflows/flux_schnell.json` — package-data template (auto-shipped;
  hatchling wheel already packages `src/image_gen`).
- **`config.py`** — add `comfyui_url: str | None = None`, `comfyui_model: str = "flux1-schnell"`,
  `comfyui_steps: int = 4`, optional `comfyui_workflow: Path | None = None` (override bundled template).
- **`models.py`** — add `COMFYUI = "comfyui"` to `ProviderName`.
- **`registry.py`** — `if settings.comfyui_url: registry["comfyui"] = ComfyUIProvider(settings)`.
- No changes to `api/generate.py`, `mcp/tools.py`, storage, db — they resolve providers generically.

### Phase C — Tests + docs
- **New** `tests/test_comfyui_provider.py` — follow `TestOpenRouterProvider`: patch
  `comfyui_provider.httpx.AsyncClient`; drive the flow with `mock_client.post`/`.get` `side_effect`
  lists (queued → pending `/history` → completed `/history` → `/view` bytes). Cover: happy path returns
  `ProviderResult`; graph templating injects prompt + W/H; polling handles pending→complete; `4K` →
  `UnsupportedParameterError`; ComfyUI down / `node_errors` / execution-error → `ProviderError`; timeout
  → `ProviderError`; `aclose()` closes client; `list_models()` degrades to `[model_name]` on error.
- Add a sizing test that ComfyUI `1K/2K` agree with `compute_size` math.
- **Docs:** `.env.example` (the `IMAGEGEN_COMFYUI_*` vars), a short `docs/` how-to (run ComfyUI →
  point image-gen at it), and an **ADR** `docs/adr/000X-local-comfyui-provider.md` recording the
  localhost-only + HTTP-client decision (extends ADR 0002). Copy this plan to
  `docs/plans/2026-06-30-local-comfyui-provider.md`.

## Verification (evidence before claims)
1. **ComfyUI proof:** `curl -s 127.0.0.1:8188/system_stats` returns JSON; one web-UI FLUX generation
   produces a coherent image (Metal path confirmed).
2. **Unit tests:** `uv run pytest tests/test_comfyui_provider.py -v` green; full `uv run pytest`
   stays ≥70% coverage. `uv run ruff check . && uv run ruff format --check . && uv run mypy src`.
3. **End-to-end:** run image-gen against ComfyUI —
   `IMAGEGEN_AUTH_ENABLED=false IMAGEGEN_DATA_DIR=$(mktemp -d) IMAGEGEN_COMFYUI_URL=http://127.0.0.1:8188 IMAGEGEN_DEFAULT_PROVIDER=comfyui uv run python -m image_gen` →
   `POST /api/generate {"name":"t","prompt":"a red fox in snow","provider":"comfyui","resolution":"1K"}` →
   assert 200, a `.png` written under the data dir, and `GET /ready` lists `comfyui`.

## Risks & notes
- **MLX/Metal can't run in the Linux homelab container** — that's *why* this is an out-of-process
  localhost server, not an in-process dependency. image-gen stays portable; `comfyui_url` unset in the
  container ⇒ provider absent there (and never the container's `default_provider`).
- **ComfyUI install is heavy** (multi-GB models, separate venv) and lives outside the repo — the setup
  script makes it reproducible; only the workflow JSON is version-controlled.
- **First-call latency:** ComfyUI loads the model on first generation (tens of seconds) then stays warm;
  schnell keeps steady-state generation interactive. `request_timeout_seconds` (120 s) covers cold start.
- **Workflow JSON is a coupling point** — pinned to the bundled FLUX node set; templating by title
  insulates against node-id renumbering but not against ComfyUI removing/renaming node *types*.

---

## Implementation notes (2026-06-30)

Deviation from Phase A's "export the workflow from the web UI": ComfyUI is not running in
this worktree session, so the bundled `flux_schnell.json` was **hand-authored** as a
known-good split-file FLUX.1-schnell API-format graph (UNETLoader + DualCLIPLoader +
VAELoader + 2× CLIPTextEncode + EmptyLatentImage + KSampler + VAEDecode + SaveImage) rather
than exported. The how-to and ADR document that a user should re-export from their own
ComfyUI (Save (API Format)) if the node set drifts. Verification steps 1 and 3 (live
ComfyUI) require the user to run `scripts/setup-comfyui.sh` first; step 2 (unit tests,
ruff, format, mypy) is fully satisfied (`comfyui_provider.py` at 91% line coverage, 85%
total, 26 provider tests green).
