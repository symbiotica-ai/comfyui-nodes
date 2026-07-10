# ABOUTME: Tests for load_order (filesystem xlsx + refs folder) and the
# ABOUTME: event-spec / overview output shapes ported from hub order-read.ts.
import json

import pytest
from conftest import inline_cell, make_xlsx, sheet_of_rows

from pipeline.order_loader import (
    event_spec,
    load_order,
    order_overview,
    spec_wire_json,
)


def _order_xlsx() -> bytes:
    header = "".join(
        inline_cell(f"{col}1", text)
        for col, text in zip("ABCDEFG", ["Feature", "Event Name", "Asset Name",
                                         "ID", "Asset Category", "Canvas", "Prompt"])
    )
    row2 = "".join(
        inline_cell(f"{col}2", text)
        for col, text in zip("ABCDEFG", ["Mini 1", "Ghostly Goodies", "Bat Croissants",
                                         "1", "Food - 3 stages", "128x128", "spooky bread"])
    )
    row3 = "".join(
        inline_cell(f"{col}3", text)
        for col, text in zip("ABCDEFG", ["Mini 1", "", "Ghost Cake",
                                         "2", "Decoration", "256x256", "a cake"])
    )
    return make_xlsx(sheet_of_rows(header, row2, row3))


@pytest.fixture
def order_dir(tmp_path):
    order = tmp_path / "Order.xlsx"
    order.write_bytes(_order_xlsx())
    refs = tmp_path / "refs"
    refs.mkdir()
    (refs / "BatCroissants.png").write_bytes(b"x")
    (refs / "BatCroissants_2.png").write_bytes(b"x")
    (refs / ".DS_Store").write_bytes(b"x")
    return order, refs


def test_load_order_parses_and_counts_refs(order_dir):
    order, refs = order_dir
    loaded = load_order(str(order), str(refs))
    assert loaded["refFileCount"] == 2  # dotfiles excluded
    assert len(loaded["events"]) == 1
    assets = loaded["events"][0]["assets"]
    assert assets[0]["refFiles"] == ["BatCroissants.png", "BatCroissants_2.png"]
    assert assets[1]["refFiles"] == []


def test_load_order_without_refs_path(order_dir):
    order, _ = order_dir
    loaded = load_order(str(order), "")
    assert loaded["refFileCount"] == 0


def test_load_order_unreadable_paths(tmp_path, order_dir):
    order, _ = order_dir
    with pytest.raises(ValueError, match="order file not readable"):
        load_order(str(tmp_path / "nope.xlsx"), "")
    with pytest.raises(ValueError, match="references folder not readable"):
        load_order(str(order), str(tmp_path / "norefs"))


def test_event_spec_selected_feature(order_dir):
    order, refs = order_dir
    events = load_order(str(order), str(refs))["events"]
    spec = event_spec(events, "Mini 1")
    assert spec["feature"] == "Mini 1"
    assert spec["eventName"] == "Ghostly Goodies"
    assert [t["template"] for t in spec["templates"]] == [
        "mini-1-food-3-stages-128x128", "mini-1-decoration-256x256"]
    # Full asset dicts survive (builder needs them).
    assert spec["templates"][0]["assets"][0]["assetName"] == "Bat Croissants"


def test_event_spec_unknown_feature_lists_available(order_dir):
    order, refs = order_dir
    events = load_order(str(order), str(refs))["events"]
    with pytest.raises(ValueError, match=r'"QE 9" is not in the parsed order \(have: Mini 1\)'):
        event_spec(events, "QE 9")


def test_spec_wire_json_trims_asset_keys(order_dir):
    order, refs = order_dir
    spec = event_spec(load_order(str(order), str(refs))["events"], "Mini 1")
    wire = json.loads(spec_wire_json(spec))
    asset = wire["templates"][0]["assets"][0]
    assert set(asset) == {"name", "id", "canvas", "plot", "rotation", "prompt", "refFiles"}
    assert asset["name"] == "Bat Croissants"


def test_order_overview_counts(order_dir):
    order, refs = order_dir
    events = load_order(str(order), str(refs))["events"]
    ov = order_overview(events)
    assert ov["events"] == [{"feature": "Mini 1", "eventName": "Ghostly Goodies",
                             "assetCount": 2, "named": 2, "refMatched": 1}]
