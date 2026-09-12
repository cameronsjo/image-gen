"""Bundled ComfyUI workflow templates (API format).

These JSON files are package data, loaded at runtime via
:func:`importlib.resources.files`.  Each is a known-good ComfyUI *API-format*
graph (a flat ``{node_id: {class_type, inputs, _meta}}`` mapping, as produced by
the ComfyUI web UI's **Save (API Format)** action).  The
:class:`~image_gen.services.comfyui_provider.ComfyUIProvider` injects the dynamic
fields (prompt, width/height, seed, steps) per request by locating nodes via
``class_type`` + ``_meta.title`` rather than by node id, so the template survives
node-id renumbering when re-exported from a newer ComfyUI.
"""
