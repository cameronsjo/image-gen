# How-to: Generate images locally with ComfyUI

image-gen can generate images **on-device** via a local [ComfyUI](https://github.com/comfyanonymous/ComfyUI)
server instead of a paid cloud API. The `comfyui` provider is an HTTP client to a
ComfyUI running on `127.0.0.1:8188`; it costs GPU seconds, not API dollars, and runs
the full unquantized FLUX.1-schnell on Apple Silicon (128 GB unified memory makes
memory a non-issue).

This is **localhost only**. The provider registers only when `IMAGEGEN_COMFYUI_URL`
is set, so the Linux homelab container — which cannot run Metal/MPS — simply never
sees it. See [ADR 0004](adr/0004-local-comfyui-provider.md) for the rationale.

## 1. Stand up ComfyUI + FLUX (one time)

Run the setup script in a separate terminal. It installs `comfy-cli`, installs
ComfyUI (its own MPS PyTorch venv), and downloads the FLUX.1-schnell split files
(~33 GB total). It is reentrant — re-run it after a partial download and it skips
what is already present.

```bash
bash scripts/setup-comfyui.sh            # install + download, prints the launch command
bash scripts/setup-comfyui.sh --launch   # also launch ComfyUI on 127.0.0.1:8188
```

| File | Model dir | Source |
|------|-----------|--------|
| `flux1-schnell.safetensors` | `models/diffusion_models/` | FLUX.1-schnell (Apache-2.0) |
| `ae.safetensors` | `models/vae/` | FLUX.1-schnell |
| `clip_l.safetensors` | `models/clip/` | flux_text_encoders |
| `t5xxl_fp16.safetensors` | `models/clip/` | flux_text_encoders |

FLUX.1-schnell is Apache-2.0 and ungated — no Hugging Face token required.

### Confirm Metal works and export the workflow

With ComfyUI launched, open `http://127.0.0.1:8188`, load the stock FLUX example,
and generate once to confirm the Metal path produces a coherent image. The first
generation loads the model (tens of seconds); after that it stays warm and schnell
generation is interactive (~4 steps).

image-gen ships a known-good API-format workflow at
`src/image_gen/services/workflows/flux_schnell.json`, so you do **not** need to
export anything to get started. If your ComfyUI node set drifts (a node type is
renamed or removed), re-export from the web UI — **Save (API Format)** — and either
replace the bundled file or point `IMAGEGEN_COMFYUI_WORKFLOW` at your export.

## 2. Point image-gen at it

Set the URL (and optionally make it the default provider):

```bash
export IMAGEGEN_COMFYUI_URL=http://127.0.0.1:8188
export IMAGEGEN_DEFAULT_PROVIDER=comfyui   # optional
```

Or in `.env` (see `.env.example` for all `IMAGEGEN_COMFYUI_*` knobs):

```ini
IMAGEGEN_COMFYUI_URL=http://127.0.0.1:8188
IMAGEGEN_COMFYUI_MODEL=flux1-schnell
IMAGEGEN_COMFYUI_STEPS=4
```

## 3. Generate

The `comfyui` provider works behind the exact same `/api/generate` and MCP surface
as the cloud providers:

```bash
curl -s -X POST http://127.0.0.1:8000/api/generate \
  -H 'Content-Type: application/json' \
  -d '{"name":"fox","prompt":"a red fox in snow","provider":"comfyui","resolution":"1K"}'
```

`GET /ready` lists `comfyui` among the configured providers once the URL is set.

## Resolution support

| Tier | Result |
|------|--------|
| `1K` | 1024 long edge |
| `2K` | 2048 long edge |
| `4K` | **rejected** (`UnsupportedParameterError`) — local FLUX's sweet spot is ≤ 2K; use a cloud provider for 4K |

Aspect ratios use the same shared sizing as the cloud providers (floored to
multiples of 16, FLUX-friendly).

## Troubleshooting

- **`/ready` doesn't list `comfyui`** — `IMAGEGEN_COMFYUI_URL` is unset, or the
  default provider's prerequisites are missing and startup failed fast.
- **`ProviderError: ComfyUI HTTP error: ... Connection refused`** — ComfyUI isn't
  running. Launch it (`bash scripts/setup-comfyui.sh --launch`).
- **`ProviderError: ComfyUI rejected the workflow graph`** — the bundled workflow
  references a model filename or node type your ComfyUI doesn't have. Re-export an
  API-format workflow from your ComfyUI and point `IMAGEGEN_COMFYUI_WORKFLOW` at it.
- **First request is slow** — ComfyUI loads the model on the first generation (tens
  of seconds), then stays warm. The 120 s `request_timeout_seconds` covers cold start.
