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


def test_only_25_offers_the_editing_switch_comfyui_gives_only_25(node_module):
    assert "video_editing" in widgets(node_module, "Seedance 2.5")
    assert "video_editing" not in widgets(node_module, "Seedance 2.0")


def test_every_model_offers_reference_clips(node_module):
    """Through fal a reference clip rides like any other reference, so all four
    models carry the slots. On the Cloudflare catalog fall back none of them
    can, which is said at render time rather than by hiding sockets that exist
    everywhere else."""
    for label in ("Seedance 2.5", "Seedance 2.0", "Seedance 2.0 Fast",
                  "Seedance 2.0 Mini"):
        assert "videos" in widgets(node_module, label), label


def test_every_model_offers_reference_audio(node_module):
    """fal gives the whole 2.0 family three audio slots, where the Cloudflare
    catalog gives Mini one and the other two none."""
    for label in ("Seedance 2.5", "Seedance 2.0", "Seedance 2.0 Fast",
                  "Seedance 2.0 Mini"):
        assert "audios" in widgets(node_module, label), label


def test_each_model_offers_exactly_the_reference_slots_it_accepts(node_module):
    """Autogrow names the slots up front, so a slot list longer than the model
    takes is a socket the user can wire and the call cannot carry."""
    from pipeline import fal_seedance as fal
    for label, limits in fal.LIMITS.items():
        slots = widgets(node_module, label)
        assert len(slots["images"].template.names) == limits.max_images, label
        assert len(slots["videos"].template.names) == limits.max_videos, label
        assert len(slots["audios"].template.names) == limits.max_audios, label


def test_the_seed_and_watermark_sit_outside_the_model_combo(node_module):
    """They mean the same thing on every model, and ComfyUI's own node keeps
    them at the top level too."""
    schema = node_module.SymbioticaSeedanceReference.define_schema()
    top = {getattr(i, "id", None) for i in schema.inputs}
    assert {"model", "seed", "watermark"} <= top


def test_the_node_hands_back_a_video(node_module):
    schema = node_module.SymbioticaSeedanceReference.define_schema()
    assert len(schema.outputs) == 1


def default_of(node_module, label, name):
    return getattr(widgets(node_module, label)[name], "default", None)


def test_25_starts_where_comfyuis_own_node_starts_it(node_module):
    assert default_of(node_module, "Seedance 2.5", "resolution") == "720p"
    assert default_of(node_module, "Seedance 2.5", "duration") == 5


def test_the_20_family_starts_at_the_cheapest_resolution_it_offers(node_module):
    """ComfyUI's node gives the 2.0 options no resolution default, so they open
    on the first entry — 480p. Opening on 720p instead would make every
    freshly dropped node cost more than the one it copies."""
    for label in ("Seedance 2.0", "Seedance 2.0 Fast", "Seedance 2.0 Mini"):
        assert default_of(node_module, label, "resolution") == "480p", label


def test_the_20_family_starts_at_the_duration_comfyui_starts_it(node_module):
    for label in ("Seedance 2.0", "Seedance 2.0 Fast", "Seedance 2.0 Mini"):
        assert default_of(node_module, label, "duration") == 7, label


def widget_values(node_module, label):
    """The values a freshly dropped node would hand `execute` for this model.

    Read off the schema rather than written out, because a fixture written by
    hand drifts from the widgets and then proves the request builder works
    against inputs the node never sends."""
    values = {"model": label}
    for name, widget in widgets(node_module, label).items():
        default = getattr(widget, "default", None)
        if default is not None:
            values[name] = default
    return values


@pytest.mark.parametrize("label", ["Seedance 2.5", "Seedance 2.0",
                                   "Seedance 2.0 Fast", "Seedance 2.0 Mini"])
def test_each_arm_can_build_a_request_from_what_the_node_actually_sends(
        node_module, label):
    """Both request builders, against the widgets as the schema defines them.

    The catalog builder read `output_format` unconditionally for 2.5 while the
    node had no such widget, so the flagship model raised KeyError before any
    call — and every existing test passed, because they hand-added the key the
    node never sends."""
    from pipeline import seedance_video as catalog
    from pipeline import fal_seedance as fal
    values = dict(widget_values(node_module, label), prompt="a cat")
    catalog_body = catalog.build_request(label, values, 7, False, ["i"], [])
    assert catalog_body["input"]["prompt"] == "a cat"
    fal_values = dict(values, duration=str(values["duration"]))
    if fal_values["ratio"] == "adaptive":
        fal_values["ratio"] = "auto"
    assert fal.build_request(fal_values, ["i"], [], [])["prompt"] == "a cat"


def test_a_status_poll_answering_202_is_not_read_as_a_failure(node_module):
    """fal answers a status read with 202 while the job is still running. Read
    as a failure the node dies on its first poll of every render that does not
    finish instantly — which is every render."""
    assert node_module._is_ok(202)
    assert node_module._is_ok(200)
    assert not node_module._is_ok(400)
    assert not node_module._is_ok(500)
