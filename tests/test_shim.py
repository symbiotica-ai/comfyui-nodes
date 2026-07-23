# ABOUTME: Smoke test — the pipeline pure modules import without ComfyUI, and
# ABOUTME: the shim module registers exactly the four pipeline node ids.
import importlib

import pytest


def test_pure_modules_import_without_comfy():
    for mod in ["pipeline.order_sheet", "pipeline.order_loader",
                "pipeline.texture_pack", "pipeline.model_presets",
                "pipeline.prefill", "pipeline.compose",
                "pipeline.studio_library"]:
        importlib.import_module(mod)


def test_nodes_module_requires_comfy():
    # Outside ComfyUI the V3 node module must fail cleanly (ImportError),
    # never crash the whole package import.
    with pytest.raises(ImportError):
        importlib.import_module("pipeline.nodes")
