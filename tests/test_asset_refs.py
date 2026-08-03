# ABOUTME: Tests for a single asset's client references — lookup, order, and
# ABOUTME: saying plainly whether they line up with the packed sheet's cells.
import pytest

from pipeline.asset_refs import (asset_names, find_asset, pairing_note,
                                 reference_files)
from pipeline.sheet_cells import cell_boxes


def order(tmp_path, assets, refs_root=None, project_path=""):
    return {
        "assets": assets,
        "refsRoot": str(tmp_path if refs_root is None else refs_root),
        "project_path": project_path,
    }


def touch(tmp_path, *names):
    for n in names:
        (tmp_path / n).write_bytes(b"x")


SPOOKIES = {
    "assetName": "Spookies", "category": "Food - 3 stages",
    # Sorted exactly as the order sheet pairs them: "." sorts before "_", so the
    # base file leads and the stages follow.
    "refFiles": ["Spookies.png", "Spookies_1.png", "Spookies_2.png"],
}


def test_finds_an_asset_by_its_order_sheet_name():
    o = {"assets": [SPOOKIES]}
    assert find_asset(o, "Spookies")["category"] == "Food - 3 stages"
    assert find_asset(o, " Spookies ")["assetName"] == "Spookies"
    assert find_asset(o, "spookies") is None, "names are exact, not folded"
    assert find_asset(o, "") is None


def test_returns_the_references_in_the_orders_own_sequence(tmp_path):
    touch(tmp_path, *SPOOKIES["refFiles"])
    paths, names = reference_files(order(tmp_path, [SPOOKIES]), "Spookies")
    assert names == ["Spookies.png", "Spookies_1.png", "Spookies_2.png"]
    assert [p.startswith(str(tmp_path)) for p in paths] == [True] * 3


def test_an_unknown_asset_says_what_the_order_does_have(tmp_path):
    with pytest.raises(ValueError, match="Ghostly Jelly Cake"):
        reference_files(order(tmp_path, [SPOOKIES, {
            "assetName": "Ghostly Jelly Cake", "refFiles": []}]), "Spooky")


def test_an_asset_with_no_matched_references_says_so(tmp_path):
    with pytest.raises(ValueError, match="no reference images"):
        reference_files(order(tmp_path, [{"assetName": "Bare",
                                          "refFiles": []}]), "Bare")


def test_a_missing_file_is_named_not_silently_dropped(tmp_path):
    """Dropping it would shift every later index by one, so the reference that
    pairs with a cell would quietly become the wrong one."""
    touch(tmp_path, "Spookies.png", "Spookies_2.png")
    with pytest.raises(ValueError, match="Spookies_1.png"):
        reference_files(order(tmp_path, [SPOOKIES]), "Spookies")


def test_an_order_with_no_refs_folder_names_the_node_to_re_run(tmp_path):
    with pytest.raises(ValueError, match="Order Specs"):
        reference_files(order(tmp_path, [SPOOKIES], refs_root=""), "Spookies")


def test_asset_names_lists_only_named_assets():
    o = {"assets": [SPOOKIES, {"assetName": "  "}, {"assetName": "Chair"}]}
    assert asset_names(o) == ["Spookies", "Chair"]


def test_note_confirms_the_pairing_when_counts_match():
    cells = cell_boxes("food2row", 1024, 1024, 20)
    note = pairing_note({"assets": [SPOOKIES]}, "Spookies",
                        SPOOKIES["refFiles"], cells)
    assert "reference i is role i" in note
    assert "prep, ready, serving" in note


def test_note_warns_loudly_when_counts_disagree():
    cells = cell_boxes("pair", 1024, 1024, 20)
    note = pairing_note({"assets": [SPOOKIES]}, "Spookies",
                        SPOOKIES["refFiles"], cells)
    assert "do NOT line up" in note
    assert "3 references but 2 cells" in note


def test_note_says_when_the_type_has_no_rule_recorded():
    note = pairing_note({"assets": [SPOOKIES]}, "Spookies",
                        SPOOKIES["refFiles"], [])
    assert "no packing rule recorded" in note
