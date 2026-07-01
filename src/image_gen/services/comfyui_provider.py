"""Local ComfyUI image-generation provider.

Unlike the cloud providers, this one talks to a **ComfyUI** server running on the
same machine (default ``http://127.0.0.1:8188``), so generation costs GPU seconds
rather than API dollars.  It is registered only when ``IMAGEGEN_COMFYUI_URL`` is
set, so the Linux homelab container — which cannot run Metal/MPS — simply never
sees it (see ADR 0004).

ComfyUI is a **multi-step** HTTP API rather than a single POST, so ``generate_image``
orchestrates three calls:

1. ``POST /prompt`` with ``{"prompt": <api-format graph>, "client_id": <uuid>}`` →
   ``{"prompt_id": ..., "node_errors": {...}}``.  A non-empty ``node_errors`` means
   the graph was rejected → :class:`~image_gen.exceptions.ProviderError`.
2. Poll ``GET /history/{prompt_id}`` (~1 s interval, bounded by
   ``request_timeout_seconds``) until the id appears with ``outputs``.  A
   ``status.status_str == "error"`` entry → :class:`ProviderError`.
3. ``GET /view?filename=…&subfolder=…&type=output`` → raw PNG bytes →
   ``ProviderResult(bytes, "image/png")``.

The workflow graph is shipped as package data (``workflows/flux_schnell.json``) in
ComfyUI *API format*.  Per request we load a fresh copy and inject the dynamic
fields — prompt, width/height, seed, steps — locating nodes by ``class_type`` +
``_meta.title`` so re-exporting the workflow from a newer ComfyUI (which renumbers
node ids) does not break templating.

Default model is **FLUX.1-schnell** (Apache-2.0, ~4 steps, interactive).  With
128 GB of unified memory we run the full split files (``t5xxl_fp16``) — no
quantization.  ``4K`` is rejected with :class:`UnsupportedParameterError`: local
FLUX's sweet spot is <= 2K, and the ABC contract is to raise for unsupported combos.
"""

import asyncio
import json
import random
import uuid
from importlib import resources
from typing import Any

import httpx
import structlog

from image_gen.config import Settings
from image_gen.exceptions import ProviderError, UnsupportedParameterError
from image_gen.services._sizing import compute_size
from image_gen.services.provider import ImageProvider, ProviderResult

logger = structlog.get_logger()

# Canonical resolution → long-edge pixel target.  4K is intentionally absent:
# local FLUX is happiest <= 2K, so we raise UnsupportedParameterError rather than
# pretend.  compute_size() floors to multiples of 16 (FLUX-friendly).
_RESOLUTION_BASE: dict[str, int] = {
    "1K": 1024,
    "2K": 2048,
}

# Seconds between /history polls while a generation is in flight.  Patched to ~0
# in tests so the polling loop runs without real sleeps.
_POLL_INTERVAL_SECONDS = 1.0

# Node-location markers for graph templating.  We anchor on class_type and
# disambiguate the two CLIPTextEncode nodes by a substring of their _meta.title.
_POSITIVE_TITLE_MARKER = "positive"
_BUNDLED_WORKFLOW = "flux_schnell.json"


def _compute_dimensions(aspect_ratio: str, resolution: str) -> tuple[int, int]:
    """Return ``(width, height)`` integers for the latent node.

    Reuses the shared :func:`compute_size` math (long edge = base, floored to a
    multiple of 16) and parses its ``WxH`` string back into integers.

    Raises:
        UnsupportedParameterError: For ``4K`` (above local FLUX's sweet spot), an
            otherwise-unknown resolution, or an unknown aspect ratio.
    """
    if resolution == "4K":
        msg = "local FLUX provider supports up to 2K; use a cloud provider for 4K"
        raise UnsupportedParameterError(msg)
    if resolution not in _RESOLUTION_BASE:
        msg = f"ComfyUI provider does not recognise resolution {resolution!r}"
        raise UnsupportedParameterError(msg)
    size = compute_size(aspect_ratio, _RESOLUTION_BASE[resolution], "ComfyUI")
    width, height = (int(part) for part in size.split("x"))
    return width, height


def _node_detail(class_type: str, title_marker: str | None) -> str:
    """Render a human-readable node identifier for error messages."""
    return f"{class_type!r}" + (f" titled ~{title_marker!r}" if title_marker else "")


def _find_node(
    graph: dict[str, Any], class_type: str, title_marker: str | None = None
) -> dict[str, Any]:
    """Return the first node of *class_type* (optionally matching *title_marker*).

    Locating by class_type + _meta.title is robust to node-id renumbering when the
    workflow is re-exported from a newer ComfyUI.

    Raises:
        ProviderError: If no matching node exists — a template-coupling failure the
            operator must fix (the bundled graph drifted from the running ComfyUI).
    """
    for node in graph.values():
        if node.get("class_type") != class_type:
            continue
        if title_marker is not None:
            title = node.get("_meta", {}).get("title", "")
            if title_marker.lower() not in title.lower():
                continue
        # Callers inject into node["inputs"]; a matched-but-malformed node (no
        # inputs map) is a template defect — surface it as an actionable
        # ProviderError rather than a raw KeyError downstream.
        if not isinstance(node.get("inputs"), dict):
            detail = _node_detail(class_type, title_marker)
            msg = f"ComfyUI workflow node {detail} has no 'inputs' map"
            raise ProviderError(msg)
        return node
    msg = f"ComfyUI workflow template is missing a {_node_detail(class_type, title_marker)} node"
    raise ProviderError(msg)


class ComfyUIProvider(ImageProvider):
    """Generates images via a local ComfyUI server (default FLUX.1-schnell)."""

    name = "comfyui"

    def __init__(self, settings: Settings) -> None:
        # comfyui_url is only ever set when the provider should exist (registry
        # guards on it), so it is non-None by construction here.
        self._base_url = str(settings.comfyui_url).rstrip("/")
        self._model = settings.comfyui_model
        self._steps = settings.comfyui_steps
        self._timeout = settings.request_timeout_seconds
        # A stable client_id ties our /prompt submissions to one ComfyUI session.
        self._client_id = str(uuid.uuid4())
        # Load the workflow template once (bundled package data unless overridden)
        # and re-parse per request so injected fields never bleed between calls.
        if settings.comfyui_workflow is not None:
            self._workflow_json = settings.comfyui_workflow.read_text(encoding="utf-8")
        else:
            self._workflow_json = (
                resources.files("image_gen.services.workflows")
                .joinpath(_BUNDLED_WORKFLOW)
                .read_text(encoding="utf-8")
            )
        # Pool one client for the provider's lifetime; closed via aclose() on shutdown.
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout))

    @property
    def model_name(self) -> str:
        return self._model

    def _build_graph(self, prompt: str, width: int, height: int) -> dict[str, Any]:
        """Return a fresh API-format graph with the dynamic fields injected.

        Malformed template input — invalid JSON or a non-object top level (e.g. an
        operator pointing ``comfyui_workflow`` at a UI-format export) — surfaces as
        :class:`ProviderError`, matching the ABC contract, rather than a raw
        ``JSONDecodeError``/``AttributeError`` from the generic catch-all.
        """
        try:
            graph = json.loads(self._workflow_json)
        except json.JSONDecodeError as e:
            logger.error("ComfyUI workflow template is not valid JSON", error=str(e))
            raise ProviderError(f"ComfyUI workflow template is not valid JSON: {e}") from e
        if not isinstance(graph, dict):
            msg = "ComfyUI workflow template must be an API-format JSON object of nodes"
            raise ProviderError(msg)

        try:
            positive = _find_node(graph, "CLIPTextEncode", _POSITIVE_TITLE_MARKER)
            positive["inputs"]["text"] = prompt

            latent = _find_node(graph, "EmptyLatentImage")
            latent["inputs"]["width"] = width
            latent["inputs"]["height"] = height

            sampler = _find_node(graph, "KSampler")
            sampler["inputs"]["seed"] = random.getrandbits(63)
            sampler["inputs"]["steps"] = self._steps
        except ProviderError as e:
            logger.error(
                "Failed to inject workflow parameters",
                error=str(e),
                width=width,
                height=height,
            )
            raise

        return graph

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        resolution: str = "2K",
    ) -> ProviderResult:
        """Generate an image on the local ComfyUI server.

        Wraps the full submit → poll → fetch flow in :func:`asyncio.timeout` so a
        hung server (or a never-completing job) surfaces as a timeout rather than
        blocking forever.  ``request_timeout_seconds`` (120 s default) is generous
        enough to cover ComfyUI's first-call model load.
        """
        width, height = _compute_dimensions(aspect_ratio, resolution)
        graph = self._build_graph(prompt, width, height)

        logger.info(
            "Submitting ComfyUI workflow",
            model=self._model,
            width=width,
            height=height,
            steps=self._steps,
        )

        try:
            async with asyncio.timeout(self._timeout):
                prompt_id = await self._submit(graph)
                image_ref = await self._await_output(prompt_id)
                image_data = await self._fetch_image(image_ref)
        except (TimeoutError, httpx.TimeoutException) as e:
            msg = f"ComfyUI request timed out after {self._timeout}s"
            raise ProviderError(msg) from e
        except ProviderError:
            # Already a domain error (node_errors, exec failure, missing node) — pass
            # through unwrapped rather than let the catch-all below double-wrap it.
            raise
        except Exception as e:
            logger.error("ComfyUI HTTP error", error=str(e))
            raise ProviderError(f"ComfyUI HTTP error: {e}") from e

        logger.info("ComfyUI image generated successfully", model=self._model)
        return ProviderResult(image_data=image_data, mime_type="image/png")

    async def _submit(self, graph: dict[str, Any]) -> str:
        """POST the graph to ``/prompt``; return the queued ``prompt_id``."""
        resp = await self._client.post(
            f"{self._base_url}/prompt",
            json={"prompt": graph, "client_id": self._client_id},
        )
        if resp.status_code >= 400:
            body_preview = resp.text[:200]
            msg = f"ComfyUI /prompt returned HTTP {resp.status_code}: {body_preview}"
            logger.error("ComfyUI submit error", status=resp.status_code, body=body_preview)
            raise ProviderError(msg)

        data = resp.json()
        node_errors = data.get("node_errors")
        if node_errors:
            msg = f"ComfyUI rejected the workflow graph: {node_errors}"
            logger.error("ComfyUI node errors", node_errors=node_errors)
            raise ProviderError(msg)

        prompt_id = data.get("prompt_id")
        if not prompt_id:
            msg = "ComfyUI /prompt response contained no prompt_id"
            logger.error("Failed to extract prompt_id from response")
            raise ProviderError(msg)

        logger.debug("ComfyUI prompt submitted", prompt_id=prompt_id)
        return str(prompt_id)

    async def _await_output(self, prompt_id: str) -> dict[str, str]:
        """Poll ``/history/{prompt_id}`` until the job finishes; return image ref.

        Returns a ``{filename, subfolder, type}`` mapping for the first output image.
        Raises :class:`ProviderError` on an execution error or a completed-but-empty
        result.  The surrounding :func:`asyncio.timeout` bounds the loop.
        """
        logger.debug("Polling for ComfyUI execution result", prompt_id=prompt_id)
        while True:
            resp = await self._client.get(f"{self._base_url}/history/{prompt_id}")
            if resp.status_code >= 400:
                msg = f"ComfyUI /history returned HTTP {resp.status_code}"
                logger.error(
                    "ComfyUI history poll error", prompt_id=prompt_id, status=resp.status_code
                )
                raise ProviderError(msg)

            entry = resp.json().get(prompt_id)
            if entry is not None:
                status_str = entry.get("status", {}).get("status_str")
                if status_str == "error":
                    messages = entry.get("status", {}).get("messages", [])
                    msg = f"ComfyUI execution failed: {messages}"
                    logger.error("ComfyUI execution error", prompt_id=prompt_id, messages=messages)
                    raise ProviderError(msg)
                if entry.get("outputs"):
                    logger.debug("ComfyUI execution completed", prompt_id=prompt_id)
                    return _extract_image_ref(entry["outputs"])

            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    async def _fetch_image(self, image_ref: dict[str, str]) -> bytes:
        """GET ``/view`` for *image_ref* and return the raw image bytes."""
        logger.debug("Fetching image from ComfyUI", filename=image_ref.get("filename"))
        params = {
            "filename": image_ref["filename"],
            "subfolder": image_ref.get("subfolder", ""),
            "type": image_ref.get("type", "output"),
        }
        resp = await self._client.get(f"{self._base_url}/view", params=params)
        if resp.status_code >= 400:
            msg = f"ComfyUI /view returned HTTP {resp.status_code}"
            logger.error(
                "ComfyUI fetch error", status=resp.status_code, filename=image_ref.get("filename")
            )
            raise ProviderError(msg)

        logger.debug("Image successfully fetched from ComfyUI", size_bytes=len(resp.content))
        return resp.content

    async def list_models(self) -> list[str]:
        """Best-effort enumeration of available diffusion models (default first).

        Reads ``/object_info`` and pulls the ``UNETLoader`` ``unet_name`` choice list.
        Any failure (server down, shape change) degrades to ``[model_name]`` rather
        than raising — this is an informational helper, not a generation path.
        """
        try:
            resp = await self._client.get(f"{self._base_url}/object_info")
            if resp.status_code >= 400:
                msg = f"ComfyUI /object_info returned HTTP {resp.status_code}"
                raise ProviderError(msg)
            choices = resp.json()["UNETLoader"]["input"]["required"]["unet_name"][0]
            models = [str(m) for m in choices]
        except Exception as e:
            logger.debug("ComfyUI list_models degraded to default", error=str(e))
            return [self._model]

        # Surface the configured default first (stable partition: False sorts before True).
        return sorted(models, key=lambda m: m != self._model) or [self._model]

    async def aclose(self) -> None:
        """Close the pooled HTTP client."""
        await self._client.aclose()


def _extract_image_ref(outputs: dict[str, Any]) -> dict[str, str]:
    """Return the first ``{filename, subfolder, type}`` image ref from *outputs*.

    Raises:
        ProviderError: If the completed job produced no image (e.g. the workflow
            has no SaveImage node).
    """
    for node_output in outputs.values():
        images = node_output.get("images")
        # Require a filename so _fetch_image can index it safely; an image entry
        # without one is not a fetchable output.
        if images and images[0].get("filename"):
            return images[0]
    msg = "ComfyUI completed but produced no output image"
    logger.error("Failed to extract image reference from ComfyUI output")
    raise ProviderError(msg)
