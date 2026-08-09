# ABOUTME: What the order nodes do when a stored payload names a month or an
# ABOUTME: event the project no longer holds — refuse, never render another one.
import importlib
import os
import sys
import types

import pytest
from conftest import inline_cell, make_xlsx, sheet_of_rows

sys.path.insert(0, os.path.dirname(__file__))
from comfy_api_stub import build_modules

COLUMNS = ["Feature", "Event Name", "Asset Name", "ID", "Asset Category",
           "Canvas", "Prompt"]


def _order_xlsx(feature: str, event_name: str, asset: str) -> bytes:
    """One order holding one event, so which order was read is visible from
    the events it yields."""
    rows = [COLUMNS,
            [feature, event_name, asset, "1", "Food - 3 stages", "128x128", "a bun"]]
    return make_xlsx(sheet_of_rows(*(
        "".join(inline_cell(f"{col}{n}", text)
                for col, text in zip("ABCDEFG", row))
        for n, row in enumerate(rows, start=1))))


@pytest.fixture
def project(tmp_path):
    """Two months, each with its own event — October first in calendar order."""
    orders = tmp_path / "orders"
    orders.mkdir()
    (orders / "Bakery October Art.xlsx").write_bytes(
        _order_xlsx("Mini 1", "Ghostly Goodies", "Bat Croissants"))
    (orders / "Bakery November Art.xlsx").write_bytes(
        _order_xlsx("Mini 2", "Winter Warmers", "Spiced Buns"))
    (tmp_path / "reference-assets").mkdir()
    return tmp_path


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
    # The UI push reads it; ComfyUI fills it in from the declared hidden.
    nodes.SymbioticaOrderRead.hidden = types.SimpleNamespace(unique_id="1")
    yield nodes
    sys.modules.pop("pipeline.nodes", None)


def _features(payload):
    return [e["feature"] for e in payload["events"]]


def test_order_read_refuses_a_month_the_project_no_longer_holds(nodes_mod, project):
    from pipeline.project_layout import MonthNotFound
    with pytest.raises(MonthNotFound):
        nodes_mod.SymbioticaOrderRead.execute(str(project), "december")


def test_order_read_takes_the_first_order_when_no_month_is_named(nodes_mod, project):
    out = nodes_mod.SymbioticaOrderRead.execute(str(project), "")
    assert _features(out.result[0]) == ["Mini 1"]


def test_order_read_reads_the_month_it_was_given(nodes_mod, project):
    out = nodes_mod.SymbioticaOrderRead.execute(str(project), "november")
    assert _features(out.result[0]) == ["Mini 2"]


def test_order_read_fingerprint_survives_a_stale_month(nodes_mod, project):
    """ComfyUI catches whatever fingerprint_inputs raises and treats the node as
    changed, so the refusal must land on execute — but the raise still has to be
    the same one, not an AttributeError from a half-built path."""
    from pipeline.project_layout import MonthNotFound
    with pytest.raises(MonthNotFound):
        nodes_mod.SymbioticaOrderRead.fingerprint_inputs(str(project), "december")


def test_order_specs_refuses_a_month_the_project_no_longer_holds(nodes_mod, project):
    from pipeline.project_layout import MonthNotFound
    with pytest.raises(MonthNotFound):
        nodes_mod.SymbioticaOrderSpecs.execute(str(project), "december", "")


def test_order_specs_reads_the_month_it_was_given(nodes_mod, project):
    out = nodes_mod.SymbioticaOrderSpecs.execute(str(project), "november", "")
    assert out.result[0]["feature"] == "Mini 2"


def test_template_editor_refuses_a_month_the_project_no_longer_holds(nodes_mod, project):
    from pipeline.project_layout import MonthNotFound
    with pytest.raises(MonthNotFound):
        nodes_mod.SymbioticaTemplateEditor._resolve_spec(
            None, None, str(project), "december", "")


def test_template_editor_refuses_an_event_the_order_does_not_hold(nodes_mod, project):
    """A saved workflow keeps the feature it was built with; the order it names
    can be re-issued without it. Building the order's first event instead spends
    a render on artwork nobody asked for."""
    with pytest.raises(ValueError) as e:
        nodes_mod.SymbioticaTemplateEditor._resolve_spec(
            None, None, str(project), "october", "Mini 9")
    assert "Mini 9" in str(e.value) and "Mini 1" in str(e.value)


def test_template_editor_builds_the_first_event_when_no_feature_is_named(
        nodes_mod, project):
    spec, assets_root = nodes_mod.SymbioticaTemplateEditor._resolve_spec(
        None, None, str(project), "october", "")
    assert spec["feature"] == "Mini 1"
    assert os.path.basename(assets_root) == "reference-assets"
