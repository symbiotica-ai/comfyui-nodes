# ABOUTME: Node-face tests for Client Examples — several client briefs as ONE
# ABOUTME: string, so an LLM downstream runs once and sees every example.
import importlib
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from comfy_api_stub import build_modules


@pytest.fixture()
def nodes_mod(monkeypatch, tmp_path):
    pkg, latest = build_modules()
    monkeypatch.setitem(sys.modules, "comfy_api", pkg)
    monkeypatch.setitem(sys.modules, "comfy_api.latest", latest)
    fp = types.ModuleType("folder_paths")
    out = tmp_path / "output"
    out.mkdir()
    fp.get_output_directory = lambda: str(out)
    monkeypatch.setitem(sys.modules, "folder_paths", fp)
    sys.modules.pop("pipeline.nodes", None)
    import pipeline.nodes as nodes
    importlib.reload(nodes)
    yield nodes
    sys.modules.pop("pipeline.nodes", None)


def order(*assets, feature="Mini 4 — Dark Bloom"):
    return {"feature": feature, "project_path": "/p", "assets": list(assets)}


def asset(name, category="Food - 3 stages", prompt="Prep) a\nReady) b"):
    return {"assetName": name, "category": category, "prompt": prompt}


def run(nodes, *args, **kwargs):
    out = nodes.SymbioticaClientExamples.execute(*args, **kwargs)
    return out.result if hasattr(out, "result") else out


def test_every_brief_of_the_type_in_one_string(nodes_mod):
    text, count = run(nodes_mod, order(
        asset("Skull Rose Cupcake", prompt="Prep) crumbs\nReady) cupcake"),
        asset("Bone Rose Cake", prompt="Prep) batter\nReady) cake"),
        asset("Vintage Plum Oven", category="Appliance", prompt="an oven"),
    ), category="Food - 3 stages")
    assert count == 2
    assert "Skull Rose Cupcake" in text and "Bone Rose Cake" in text
    # The other type stays out — this is the example set for ONE block.
    assert "Vintage Plum Oven" not in text
    # Numbered, and the briefs are verbatim.
    assert "1. Skull Rose Cupcake" in text and "2. Bone Rose Cake" in text
    assert "Prep) batter\nReady) cake" in text


def test_header_names_the_type_and_the_count(nodes_mod):
    text, _ = run(nodes_mod, order(asset("A"), asset("B")),
                  category="Food - 3 stages")
    assert text.startswith("CLIENT EXAMPLES — all 2 'Food - 3 stages' assets")
    assert "Mini 4 — Dark Bloom" in text


def test_limit_says_it_truncated(nodes_mod):
    text, count = run(nodes_mod,
                      order(asset("A"), asset("B"), asset("C")),
                      category="Food - 3 stages", limit=2)
    assert count == 2
    assert "the first 2 of 3" in text
    # The dropped asset is absent from the ENTRIES. Looking for "C" in the
    # header instead can never pass — the header starts "CLIENT EXAMPLES".
    entries = [block.split("\n")[0] for block in text.split("\n\n")[1:]]
    assert entries == ["1. A", "2. B"]


def test_all_types_labels_each_asset_with_its_type(nodes_mod):
    text, count = run(nodes_mod, order(
        asset("Skull Rose Cupcake"),
        asset("Vintage Plum Oven", category="Appliance", prompt="an oven"),
    ))
    assert count == 2
    assert "1. Skull Rose Cupcake — Food - 3 stages" in text
    assert "2. Vintage Plum Oven — Appliance" in text


def test_assets_without_a_brief_are_dropped(nodes_mod):
    text, count = run(nodes_mod, order(
        asset("Has one", prompt="Prep) a"),
        asset("Blank", prompt="   "),
    ), category="Food - 3 stages")
    assert count == 1
    assert "Blank" not in text


def test_no_brief_at_all_raises_and_names_what_has_one(nodes_mod):
    with pytest.raises(ValueError) as exc:
        run(nodes_mod, order(
            asset("Silent", prompt=""),
            asset("Vintage Plum Oven", category="Appliance", prompt="an oven"),
        ), category="Food - 3 stages")
    assert "Appliance" in str(exc.value)


def test_a_missing_order_says_what_to_wire(nodes_mod):
    with pytest.raises(ValueError) as exc:
        run(nodes_mod, None, category="Food - 3 stages")
    assert "Order Specs" in str(exc.value)
