# ABOUTME: Tests the Seedance video node's registration and schema — it must
# ABOUTME: load without ComfyUI present and offer only what each model accepts.
import importlib.util
import os
import sys
import types

import pytest

import comfy_api_stub

PY_DIR = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "py")


@pytest.fixture
def node_module(monkeypatch):
    """py/seedance_video.py loaded as the package member it is at run time.

    The pack's loader imports every py/*.py inside a try/except that only
    prints the traceback, so a wrapper that will not import loses its node
    while the pack still loads clean."""
    comfy_pkg, comfy_latest = comfy_api_stub.build_modules()
    monkeypatch.setitem(sys.modules, "comfy_api", comfy_pkg)
    monkeypatch.setitem(sys.modules, "comfy_api.latest", comfy_latest)
    pkg = types.ModuleType("symbiotica_seedance_under_test")
    pkg.__path__ = [PY_DIR]
    monkeypatch.setitem(sys.modules, "symbiotica_seedance_under_test", pkg)
    spec = importlib.util.spec_from_file_location(
        "symbiotica_seedance_under_test.seedance_video",
        os.path.join(PY_DIR, "seedance_video.py"))
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    return mod


def test_the_node_is_registered_under_the_house_prefix(node_module):
    assert "SymbioticaSeedanceReference" in node_module.NODE_CLASS_MAPPINGS


def test_the_display_name_tells_it_apart_from_comfyuis_own_bytedance_nodes(node_module):
    """Stock ComfyUI ships a Seedance reference-to-video node that sits in the
    same search results and bills a ComfyUI account instead of the studio. A
    name that does not say whose it is picks itself by accident."""
    shown = node_module.NODE_DISPLAY_NAME_MAPPINGS["SymbioticaSeedanceReference"]
    assert shown == "Seedance Reference to Video (Symbiotica)"


def options(node_module):
    """The model combo's options, keyed by the label the canvas shows."""
    schema = node_module.SymbioticaSeedanceReference.define_schema()
    combo = [i for i in schema.inputs if getattr(i, "id", None) == "model"][0]
    return {option.label: option for option in combo.options}


def widgets(node_module, label):
    """One model option's own inputs, keyed by name."""
    return {getattr(i, "id", None): i for i in options(node_module)[label].inputs}


def test_every_model_the_catalog_serves_is_offered(node_module):
    assert list(options(node_module)) == [
        "Seedance 2.5", "Seedance 2.0", "Seedance 2.0 Fast",
        "Seedance 2.0 Mini"]


def test_only_25_offers_the_widgets_only_25_has(node_module):
    """output_format does not exist on the 2.0 family at all — offered there,
    it is a widget whose every render is refused."""
    assert "output_format" in widgets(node_module, "Seedance 2.5")
    assert "output_format" not in widgets(node_module, "Seedance 2.0")


def test_no_model_offers_a_reference_video_slot(node_module):
    """ByteDance takes a reference video only as a web URL, and this node sends
    its references inline. A VIDEO socket here would be one a user can wire and
    every render then refuses."""
    for label in ("Seedance 2.5", "Seedance 2.0", "Seedance 2.0 Fast",
                  "Seedance 2.0 Mini"):
        assert "videos" not in widgets(node_module, label), label


def test_an_audio_slot_is_offered_only_where_one_can_be_sent(node_module):
    assert "audios" in widgets(node_module, "Seedance 2.5")
    assert "audios" in widgets(node_module, "Seedance 2.0 Mini")
    assert "audios" not in widgets(node_module, "Seedance 2.0 Fast")


def test_each_model_offers_exactly_the_reference_slots_it_accepts(node_module):
    """Autogrow names the slots up front, so a slot list longer than the model
    takes is a socket the user can wire and the call cannot carry."""
    from pipeline import seedance_video as core
    for label, limits in core.LIMITS.items():
        slots = widgets(node_module, label)
        assert len(slots["images"].template.names) == limits.max_images, label


def test_the_seed_and_watermark_sit_outside_the_model_combo(node_module):
    """They mean the same thing on every model, and ComfyUI's own node keeps
    them at the top level too."""
    schema = node_module.SymbioticaSeedanceReference.define_schema()
    top = {getattr(i, "id", None) for i in schema.inputs}
    assert {"model", "seed", "watermark"} <= top


def test_the_node_hands_back_a_video(node_module):
    schema = node_module.SymbioticaSeedanceReference.define_schema()
    assert len(schema.outputs) == 1
