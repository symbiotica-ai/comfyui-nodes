# ABOUTME: Node-face tests for the order/reference template split — where the
# ABOUTME: Auto Packer's save lands, and which pool the Template Library reads.
import importlib
import json
import os
import sys
import types

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
from comfy_api_stub import build_modules


@pytest.fixture()
def nodes_mod(monkeypatch, tmp_path):
    """pipeline.nodes with ComfyUI stubbed out, and output/ pointed at tmp."""
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


@pytest.fixture()
def project(tmp_path):
    """A client project the way the pipeline expects it: an order xlsx and that
    month's client-refs folder."""
    p = tmp_path / "bakery"
    (p / "orders").mkdir(parents=True)
    (p / "orders" / "Bakery October Art.xlsx").write_bytes(b"x")
    (p / "orders" / "Bakery-October").mkdir()
    (p / "reference-assets").mkdir()
    return p


def _packed(n=1):
    return [{"image": Image.new("RGB", (4, 4)), "name": f"sheet-{i}",
             "prompts": f"p{i}"} for i in range(n)]


def _save(nodes, order, name="food"):
    nodes.SymbioticaAutoPacker._save_template(
        name, order, {"model": "qwen-image"}, {"padding": 0}, "All", {},
        _packed())


def test_reference_pack_saves_to_the_universal_pool(nodes_mod, project):
    _save(nodes_mod, {"project_path": str(project), "month": "",
                      "source": "reference", "feature": "Food",
                      "assets": [], "refsRoot": str(project / "reference-assets"),
                      "assetsRoot": ""})
    doc = project / "templates" / "reference" / "food" / "template.json"
    assert doc.is_file(), "a Reference Browser pack must land in templates/reference"
    assert json.loads(doc.read_text())["kind"] == "reference"
    # …and never under a month.
    assert not (project / "orders" / "Bakery-October" / "templates").exists()


def test_order_pack_saves_beside_the_month_order(nodes_mod, project):
    _save(nodes_mod, {"project_path": str(project), "month": "October",
                      "source": "order", "feature": "Mini 1", "assets": [],
                      "refsRoot": str(project / "orders" / "Bakery-October"),
                      "assetsRoot": str(project / "reference-assets")})
    doc = (project / "orders" / "Bakery-October" / "templates" / "food"
           / "template.json")
    assert doc.is_file(), "an order pack must land beside that month's order"
    saved = json.loads(doc.read_text())
    assert saved["kind"] == "order"
    assert saved["month"] == "October"
    assert saved["order"]["source"] == "order"
    assert not (project / "templates" / "reference").exists()


def test_legacy_order_without_source_still_files_as_order(nodes_mod, project):
    """A frozen order inside a pre-split template carries no `source` — the
    month (or the catalog root) is what says it came from an order."""
    _save(nodes_mod, {"project_path": str(project), "month": "October",
                      "feature": "Mini 1", "assets": [], "refsRoot": "",
                      "assetsRoot": str(project / "reference-assets")})
    assert (project / "orders" / "Bakery-October" / "templates" / "food").is_dir()


def test_unwritable_project_falls_back_into_the_same_pool(nodes_mod, tmp_path):
    """A read-only project (a Modal Volume) must not lose the sheets — and the
    fallback keeps the pool, so the Library's filter still finds them."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")           # a FILE where the project folder should be
    _save(nodes_mod, {"project_path": str(blocker / "bakery"), "month": "",
                      "source": "reference", "feature": "Food", "assets": [],
                      "refsRoot": "", "assetsRoot": ""})
    doc = (tmp_path / "output" / "templates" / "reference" / "food"
           / "template.json")
    assert doc.is_file(), "the fallback must keep the reference pool"


def test_library_reads_only_the_pool_it_is_set_to(nodes_mod, project):
    ref_order = {"project_path": str(project), "month": "", "source": "reference",
                 "feature": "Food", "assets": [{"assetName": "cake"}],
                 "refsRoot": "", "assetsRoot": ""}
    order_order = {"project_path": str(project), "month": "October",
                   "source": "order", "feature": "Mini 1",
                   "assets": [{"assetName": "oven"}], "refsRoot": "",
                   "assetsRoot": str(project / "reference-assets")}
    _save(nodes_mod, ref_order)        # same slug in both pools, on purpose
    _save(nodes_mod, order_order)

    Lib = nodes_mod.SymbioticaTemplateLibrary
    ref_dirs = Lib._dirs(str(project), "Reference", "October")
    order_dirs = Lib._dirs(str(project), "Order", "October")
    assert str(project / "templates" / "reference") in ref_dirs
    assert str(project / "orders" / "Bakery-October" / "templates") in order_dirs
    assert str(project / "templates" / "reference") not in order_dirs
    assert str(project / "orders" / "Bakery-October" / "templates") not in ref_dirs

    from pipeline.pack_library import list_pack_templates_dirs
    assert [t["kind"] for t in list_pack_templates_dirs(ref_dirs)] == ["reference"]
    assert [t["kind"] for t in list_pack_templates_dirs(order_dirs)] == ["order"]
    # All sees both rows (and the legacy flat pool).
    every = list_pack_templates_dirs(Lib._dirs(str(project), "All", "October"))
    assert sorted(t["kind"] for t in every) == ["order", "reference"]


def test_library_bundle_carries_the_pool(nodes_mod, project):
    _save(nodes_mod, {"project_path": str(project), "month": "", "source":
                      "reference", "feature": "Food",
                      "assets": [{"assetName": "cake"}], "refsRoot": "",
                      "assetsRoot": ""})
    out = nodes_mod.SymbioticaTemplateLibrary.execute(
        project_path=str(project), kind="Reference", month="",
        selected="reference/food", checked="[]")
    bundle = out.args[0]
    assert bundle["kind"] == "reference"
    assert bundle["order"]["source"] == "reference"
    assert bundle["name"] == "food"


def test_library_schema_exposes_kind_and_month(nodes_mod):
    schema = nodes_mod.SymbioticaTemplateLibrary.define_schema()
    names = [i.id if hasattr(i, "id") else i.name for i in schema.inputs]
    assert "kind" in names and "month" in names
