# ABOUTME: Import-and-register guard for the eight nodes that lived only on the
# ABOUTME: Modal volume until 2026-08-04 and had never been committed.

# Why this file exists: `__init__.py` discovers nodes by importing every
# non-underscore module under py/ and swallowing any failure into a printed
# traceback. A module that stops importing therefore removes its nodes from the
# menu silently. These eight arrived without a single test, so an import guard is
# the floor: if one of them breaks, the suite says so instead of the node quietly
# vanishing from a running ComfyUI.

import importlib
import sys
import types

import pytest

# module name -> the keys it must contribute to NODE_CLASS_MAPPINGS
RESCUED = {
    "camera_shake": ["CameraShake"],
    "film_grain": ["FilmGrain"],
    "focus_pull": ["FocusPull"],
    "chromatic_aberration": ["ChromaticAberration"],
    "text_file": ["LoadTextFile"],
    "text_list": ["LoadTextList"],
    "product_gallery_scrape": ["NSProductGalleryScrape"],
    "product_image_sort": ["NSProductImageSort"],
}


@pytest.fixture()
def pack(monkeypatch, tmp_path):
    """The pack as a package (relative imports need one) plus the two ambient
    modules ComfyUI supplies at import time."""
    fp = types.ModuleType("folder_paths")
    out = tmp_path / "output"
    out.mkdir()
    inp = tmp_path / "input"
    inp.mkdir()
    fp.get_output_directory = lambda: str(out)
    fp.get_input_directory = lambda: str(inp)
    fp.get_temp_directory = lambda: str(tmp_path)
    monkeypatch.setitem(sys.modules, "folder_paths", fp)

    pkg = types.ModuleType("symbiotica")
    pkg.__path__ = ["py"]
    monkeypatch.setitem(sys.modules, "symbiotica", pkg)

    def load(module_name):
        sys.modules.pop(f"symbiotica.{module_name}", None)
        return importlib.import_module(f"symbiotica.{module_name}")

    return load


@pytest.mark.parametrize("module_name,keys", sorted(RESCUED.items()))
def test_module_imports_and_registers_its_nodes(pack, module_name, keys):
    mod = pack(module_name)
    assert hasattr(mod, "NODE_CLASS_MAPPINGS"), (
        f"{module_name} registers nothing, so __init__ would import it for nothing")
    for key in keys:
        assert key in mod.NODE_CLASS_MAPPINGS, f"{module_name} lost {key}"
        assert key in mod.NODE_DISPLAY_NAME_MAPPINGS, f"{key} has no menu label"


def test_rescued_keys_do_not_collide_with_each_other(pack):
    seen = {}
    for module_name in sorted(RESCUED):
        mod = pack(module_name)
        for key in mod.NODE_CLASS_MAPPINGS:
            assert key not in seen, (
                f"{key} registered by both {seen[key]} and {module_name}; "
                "__init__ merges the dicts, so one silently wins")
            seen[key] = module_name
