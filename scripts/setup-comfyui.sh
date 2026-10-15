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
#      verified file already present — safe to re-run after a partial download).
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
# FLUX.1-schnell is Apache-2.0; hosting access can require publisher approval.
# This script does not manage credentials. Pre-provision gated files if needed.
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

# ── Model manifest: "url|relative_dir|filename|sha256" ─────────────────────────────
# FLUX.1-schnell diffusion model + autoencoder (Apache-2.0) and the
# shared FLUX text encoders (clip_l + t5xxl_fp16 — full precision, no quant).
MODELS=(
  "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/741f7c3ce8b383c54771c7003378a50191e9efe9/flux1-schnell.safetensors|diffusion_models|flux1-schnell.safetensors|9403429e0052277ac2a87ad800adece5481eecefd9ed334e1f348723621d2a0a"
  "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/741f7c3ce8b383c54771c7003378a50191e9efe9/ae.safetensors|vae|ae.safetensors|afc8e28272cd15db3919bacdb6918ce9c1ed22e96cb12c4d5ed0fba823529e38"
  "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/6af2a98e3f615bdfa612fbd85da93d1ed5f69ef5/clip_l.safetensors|clip|clip_l.safetensors|660c6f5b1abae9dc498ac2d21e1347d2abdb0cf6c0c0c8576cd796491d9a6cdd"
  "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/6af2a98e3f615bdfa612fbd85da93d1ed5f69ef5/t5xxl_fp16.safetensors|clip|t5xxl_fp16.safetensors|6e480b09fae049a72d2a8c5fbccb8d3e92febeb233bbe9dfe7256958a9167635"
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

verify_checksum() {
  local file="$1" expected="$2" hash_output actual
  [[ "$expected" =~ ^[0-9a-f]{64}$ ]] || { log_err "invalid pinned checksum"; return 1; }
  if command -v sha256sum >/dev/null 2>&1; then
    hash_output="$(command sha256sum -- "$file")" || return 1
  elif command -v shasum >/dev/null 2>&1; then
    hash_output="$(command shasum -a 256 -- "$file")" || return 1
  else
    log_err "SHA-256 verification requires sha256sum or shasum"
    return 1
  fi
  actual="${hash_output%% *}"
  if [ "$actual" != "$expected" ]; then
    log_err "checksum mismatch for ${file##*/}"
    return 1
  fi
}

download_models() {
  command -v curl >/dev/null 2>&1 || die "curl not found"
  local entry url reldir fname expected dest dir download_tmp
  for entry in "${MODELS[@]}"; do
    url="${entry%%|*}"; entry="${entry#*|}"
    reldir="${entry%%|*}"; entry="${entry#*|}"
    fname="${entry%%|*}"; expected="${entry##*|}"
    dir="$COMFY_HOME/models/$reldir"
    dest="$dir/$fname"
    if [ -e "$dest" ] || [ -L "$dest" ]; then
      [ -f "$dest" ] || die "model path is not a regular file: $dest"
      verify_checksum "$dest" "$expected" || die "existing model failed verification: $fname (left unchanged)"
      log_skip "$reldir/$fname already downloaded and verified"
      continue
    fi
    mkdir -p "$dir"
    # A unique sibling prevents following an old predictable .partial symlink.
    download_tmp="$(mktemp "$dest.partial.XXXXXX")" || die "cannot create model download temporary file"
    log_step "downloading $fname → models/$reldir (large — may take a while)"
    if command curl -fL --retry 3 --retry-delay 5 -o "$download_tmp" "$url" >&2; then
      if ! verify_checksum "$download_tmp" "$expected"; then
        rm -f -- "$download_tmp"
        die "downloaded model failed checksum verification: $fname"
      fi
      if ! mv "$download_tmp" "$dest"; then
        rm -f -- "$download_tmp"
        die "cannot install verified model: $fname"
      fi
      log_ok "$reldir/$fname (SHA-256 verified)"
    else
      rm -f -- "$download_tmp"
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
