#!/usr/bin/env bash
#
# setup-comfyui.sh — stand up a local ComfyUI + FLUX.1-schnell server for image-gen.
#
# One-time, reentrant setup of the *out-of-process* image backend that the image-gen
# `comfyui` provider points at (default http://127.0.0.1:8188). ComfyUI lives OUTSIDE
# this repo (multi-GB models, its own MPS PyTorch venv); only the exported workflow
# JSON is version-controlled. This script makes the standup reproducible.
#
# It will:
#   1. Install comfy-cli (via `uv tool install`) if absent.
#   2. Install ComfyUI (clones the repo + sets up the Apple-Silicon/MPS venv) if absent.
#   3. Download the FLUX.1-schnell split files into the right model dirs (skips any
#      file already present — safe to re-run after a partial download).
#   4. Print the launch command, or launch immediately with `--launch`.
#
# Usage:
#   bash scripts/setup-comfyui.sh            # install + download, then print launch cmd
#   bash scripts/setup-comfyui.sh --launch   # also launch ComfyUI on 127.0.0.1:8188
#
# Env overrides:
#   COMFY_HOME   ComfyUI workspace dir (default: $HOME/comfy/ComfyUI)
#   COMFY_PORT   Port to launch on      (default: 8188)
#
# FLUX.1-schnell is Apache-2.0 and ungated — no Hugging Face token required.
# Honors NO_COLOR. Diagnostics go to stderr; the final verdict to stdout.

set -euo pipefail

COMFY_HOME="${COMFY_HOME:-$HOME/comfy/ComfyUI}"
COMFY_PORT="${COMFY_PORT:-8188}"
LAUNCH=0
[ "${1:-}" = "--launch" ] && LAUNCH=1

# ── Logging (TTY-aware, NO_COLOR-respecting) ────────────────────────────────
if [ -t 2 ] && [ -z "${NO_COLOR:-}" ]; then
  C_BLUE=$'\033[34m'; C_GREEN=$'\033[32m'; C_RED=$'\033[31m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
  C_BLUE=''; C_GREEN=''; C_RED=''; C_DIM=''; C_RST=''
fi
log_step() { printf '%s\n' "${C_BLUE}▸ Preparing:${C_RST} $*" >&2; }
log_ok()   { printf '%s\n' "${C_GREEN}✓ Successfully:${C_RST} $*" >&2; }
log_skip() { printf '%s\n' "${C_DIM}• Skipping:${C_RST} $*" >&2; }
log_err()  { printf '%s\n' "${C_RED}✗ Failed:${C_RST} $*" >&2; }
die()      { log_err "$*"; exit 1; }

# ── Model manifest: "url|relative_dir|filename" ─────────────────────────────
# FLUX.1-schnell diffusion model + autoencoder (Apache-2.0, ungated) and the
# shared FLUX text encoders (clip_l + t5xxl_fp16 — full precision, no quant).
MODELS=(
  "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/flux1-schnell.safetensors|diffusion_models|flux1-schnell.safetensors"
  "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/ae.safetensors|vae|ae.safetensors"
  "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors|clip|clip_l.safetensors"
  "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors|clip|t5xxl_fp16.safetensors"
)

ensure_comfy_cli() {
  if command -v comfy >/dev/null 2>&1; then
    log_skip "comfy-cli already installed ($(command -v comfy))"
    return
  fi
  command -v uv >/dev/null 2>&1 || die "uv not found — install uv first (https://docs.astral.sh/uv/)"
  log_step "installing comfy-cli via uv tool"
  uv tool install comfy-cli >&2 || die "uv tool install comfy-cli failed"
  command -v comfy >/dev/null 2>&1 || die "comfy not on PATH after install — check 'uv tool' shims"
  log_ok "comfy-cli installed"
}

ensure_comfyui() {
  if [ -d "$COMFY_HOME" ] && [ -f "$COMFY_HOME/main.py" ]; then
    log_skip "ComfyUI already present at $COMFY_HOME"
    return
  fi
  log_step "installing ComfyUI into $COMFY_HOME (clones repo + sets up MPS venv)"
  # --skip-prompt accepts defaults; comfy-cli auto-detects Apple Silicon (MPS).
  comfy --skip-prompt --workspace "$COMFY_HOME" install >&2 \
    || die "comfy install failed — re-run, or see https://github.com/Comfy-Org/comfy-cli"
  [ -f "$COMFY_HOME/main.py" ] || die "ComfyUI not found at $COMFY_HOME after install"
  log_ok "ComfyUI installed"
}

download_models() {
  command -v curl >/dev/null 2>&1 || die "curl not found"
  local entry url reldir fname dest dir
  for entry in "${MODELS[@]}"; do
    url="${entry%%|*}"; entry="${entry#*|}"
    reldir="${entry%%|*}"; fname="${entry##*|}"
    dir="$COMFY_HOME/models/$reldir"
    dest="$dir/$fname"
    if [ -f "$dest" ]; then
      log_skip "$reldir/$fname already downloaded"
      continue
    fi
    mkdir -p "$dir"
    log_step "downloading $fname → models/$reldir (large — may take a while)"
    # Download to a temp file so an interrupted run never leaves a truncated model
    # that the skip-check would treat as complete.
    if curl -fL --retry 3 --retry-delay 5 -o "$dest.partial" "$url" >&2; then
      mv "$dest.partial" "$dest"
      log_ok "$reldir/$fname"
    else
      rm -f "$dest.partial"
      die "download failed for $url"
    fi
  done
}

main() {
  ensure_comfy_cli
  ensure_comfyui
  download_models

  log_ok "ComfyUI + FLUX.1-schnell ready at $COMFY_HOME"
  printf '%s\n' "${C_DIM}Next: export the API-format workflow from the ComfyUI web UI once" >&2
  printf '%s\n' "(load the FLUX example → generate once to confirm Metal → Save (API Format))" >&2
  printf '%s\n' "and commit it to src/image_gen/services/workflows/flux_schnell.json if it drifts.${C_RST}" >&2

  local launch_cmd="comfy --workspace \"$COMFY_HOME\" launch -- --listen 127.0.0.1 --port $COMFY_PORT"
  if [ "$LAUNCH" -eq 1 ]; then
    log_step "launching ComfyUI on 127.0.0.1:$COMFY_PORT (Ctrl-C to stop)"
    eval "$launch_cmd"
  else
    # Final verdict line on stdout — paste-back friendly.
    printf 'SETUP OK — launch with:\n  %s\n' "$launch_cmd"
  fi
}

main "$@"
