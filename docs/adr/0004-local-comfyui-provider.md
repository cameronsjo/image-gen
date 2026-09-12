# ADR 0004: Local ComfyUI Provider

**Date:** 2026-06-30
**Status:** Accepted
**Extends:** ADR 0002 (Provider Abstraction)

## Context

image-gen generates only through **remote** image APIs (Gemini 3 Pro default, plus
OpenAI and OpenRouter). Every image is a paid cloud round-trip. The development
machine (`cameron-m5-mbp`: Apple M5 Max, 18 cores, 128 GB unified memory) can run
image diffusion locally with memory to spare — full unquantized FLUX fits easily, so
the only cost is GPU seconds per image, not API dollars.

The catch: local image generation on Apple Silicon needs Metal/MPS, which **cannot**
run in the Linux homelab container where image-gen is deployed. A local backend must
therefore be out-of-process, optional, and absent in environments that can't host it
— without compromising image-gen's portability.

## Decision

Add a fourth provider, **`comfyui`**, implemented as an **HTTP client to a localhost
[ComfyUI](https://github.com/comfyanonymous/ComfyUI) server** (default
`http://127.0.0.1:8188`). It satisfies the existing `ImageProvider` ABC (ADR 0002)
and is interchangeable per request via `GenerationRequest.provider`.

Structurally it mirrors `OpenRouterProvider` — a pooled `httpx.AsyncClient`, an
`asyncio.timeout` backstop, `ProviderError` on failure, `aclose()` on shutdown —
differing only in that ComfyUI is a **multi-step** API rather than one POST:

1. `POST /prompt` with `{"prompt": <api-format graph>, "client_id": <uuid>}` →
   `{prompt_id, node_errors}`. Non-empty `node_errors` → `ProviderError`.
2. Poll `GET /history/{prompt_id}` (~1 s interval, bounded by
   `request_timeout_seconds`) until the id appears with `outputs`. A
   `status.status_str == "error"` entry → `ProviderError`.
3. `GET /view?filename=…&subfolder=…&type=output` → raw PNG bytes →
   `ProviderResult(bytes, "image/png")`.

Key choices:

1. **Localhost only — register on a URL, not an API key.** The provider registers
   only when `IMAGEGEN_COMFYUI_URL` is set:
   `if settings.comfyui_url: registry["comfyui"] = ComfyUIProvider(settings)`. The
   homelab container leaves it unset, so the provider is absent there (and can never
   be that environment's `default_provider`). No LAN exposure: the URL points at
   `127.0.0.1`.

2. **Graph templating by `class_type` + `_meta.title`.** A known-good **API-format**
   FLUX workflow ships as package data
   (`src/image_gen/services/workflows/flux_schnell.json`). Per request we load a
   fresh copy and inject only the dynamic fields — prompt (positive `CLIPTextEncode`),
   width/height (`EmptyLatentImage`), seed + steps (`KSampler`) — locating nodes by
   class type and title rather than node id, so re-exporting from a newer ComfyUI
   (which renumbers ids) does not break templating. An override path
   (`IMAGEGEN_COMFYUI_WORKFLOW`) swaps the bundled template for a user export.

3. **Default model FLUX.1-schnell, full precision.** Apache-2.0, ~4 steps,
   interactive — the best UX for a local provider. With 128 GB we run the full split
   files (`flux1-schnell` + `ae` + `clip_l` + `t5xxl_fp16`) — no quantization.
   FLUX.1-dev (higher quality, ~20–30 steps, non-commercial) is an opt-in via config.

4. **`4K` → `UnsupportedParameterError`.** Local FLUX's sweet spot is ≤ 2K; `1K`/`2K`
   reuse the shared `_sizing.compute_size()` math (floored to multiples of 16). `4K`
   raises the same way the ABC defines for any unsupported combo — honest rather than
   degrading silently.

5. **Provider name `comfyui`, config prefix `IMAGEGEN_COMFYUI_*`.** Honest about the
   backend (not a generic `local`), leaving room for a future `mflux`/`drawthings`
   local provider.

ComfyUI itself lives **outside** the repo (multi-GB models, its own MPS venv). A
committed, reentrant `scripts/setup-comfyui.sh` makes the standup reproducible; only
the exported workflow JSON is version-controlled.

## Consequences

**Positive:**

- On-device generation at zero API cost, behind the exact same `/api/generate` and
  MCP surface — no changes to `api/generate.py`, `mcp/tools.py`, storage, or db.
- image-gen stays portable: the container deploys unchanged and never references the
  local backend.
- New `IMAGEGEN_COMFYUI_*` settings; `ProviderName` gains `COMFYUI`.

**Trade-offs:**

- **Workflow JSON is a coupling point.** It is pinned to the bundled FLUX node set.
  Templating by title insulates against node-id renumbering but not against ComfyUI
  removing or renaming node *types*. Mitigation: the override config and a clear
  `ProviderError` when an expected node is missing.
- **First-call latency.** ComfyUI loads the model on the first generation (tens of
  seconds) then stays warm; `request_timeout_seconds` (120 s) covers cold start.
- **Heavy, out-of-repo install.** Multi-GB models and a separate venv; the setup
  script makes it reproducible but it is not a `uv sync` dependency.

## Rejected Alternatives

- **In-process MLX/diffusers dependency** — would not run in the Linux container and
  would bloat the image; an out-of-process server keeps image-gen portable.
- **Generic `local` provider name** — hides which backend is in use and forecloses a
  second local provider. `comfyui` names the actual server.
- **LAN exposure (bind ComfyUI to `0.0.0.0`, point the container at the Mac)** —
  adds an unauthenticated image server on the network for no requirement; localhost
  keeps the surface minimal.
- **Silently down-scaling `4K` to `2K`** — the ABC contract is to raise for
  unsupported combos; degrading silently would mislead callers about what they got.

## Param Mapping

| Canonical | ComfyUI (FLUX.1-schnell) |
|-----------|--------------------------|
| 1K | `EmptyLatentImage` long edge 1024 |
| 2K | `EmptyLatentImage` long edge 2048 |
| 4K | `UnsupportedParameterError` |
| aspect_ratio | `WxH` via shared `compute_size` (÷16, long edge = base) |
| prompt | positive `CLIPTextEncode.text` |
| steps | `KSampler.steps` (`IMAGEGEN_COMFYUI_STEPS`, default 4) |
| seed | `KSampler.seed` (random per request) |
