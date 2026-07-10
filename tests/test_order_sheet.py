# ABOUTME: Tests for the order-sheet xlsx parser — ported 1:1 from hub's
# ABOUTME: order-sheet.test.ts so both parsers keep identical behavior.
from conftest import inline_cell, make_xlsx, sheet_of_rows

from pipeline.order_sheet import parse_xlsx_grid


def test_reads_inline_string_cells_into_grid():
    xml = sheet_of_rows(
        inline_cell("A1", "Feature") + inline_cell("B1", "Asset Name"),
        inline_cell("A2", "Crate") + inline_cell("B2", "Pastel Chest"),
    )
    grid = parse_xlsx_grid(make_xlsx(xml))
    assert grid[0][0] == "Feature"
    assert grid[0][1] == "Asset Name"
    assert grid[1] == ["Crate", "Pastel Chest"]


def test_self_closing_empty_cells_do_not_swallow_next_cell():
    # A styled-but-empty cell (<c .../>) must not eat B1's body.
    xml = sheet_of_rows('<c r="A1" s="3"/>' + inline_cell("B1", "Kept"))
    grid = parse_xlsx_grid(make_xlsx(xml))
    assert grid[0][1] == "Kept"
    assert grid[0][0] == ""


def test_reads_shared_string_cells():
    sst = (
        '<sst><si><t>Feature</t></si>'
        "<si><t>Split </t><t>Run</t></si></sst>"
    )
    xml = sheet_of_rows('<c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c>')
    grid = parse_xlsx_grid(make_xlsx(xml, sst))
    assert grid[0] == ["Feature", "Split Run"]


def test_numeric_cells_normalize_trailing_zero():
    xml = sheet_of_rows('<c r="A1"><v>46301.0</v></c><c r="B1"><v>1.5</v></c>')
    grid = parse_xlsx_grid(make_xlsx(xml))
    assert grid[0] == ["46301", "1.5"]


def test_decodes_xml_entities_and_char_refs():
    xml = sheet_of_rows(inline_cell("A1", "Tom &amp; Jerry &#x41;"))
    grid = parse_xlsx_grid(make_xlsx(xml))
    assert grid[0][0] == "Tom & Jerry A"


from pipeline.order_sheet import (
    canvas_spec_of,
    compact_asset_name,
    extract_order_rows,
    group_order_events,
    match_ref_files,
    slugify,
    template_groups,
)


def _grid(*rows):
    return [list(r) for r in rows]


HEADER = ["Status", "Release", "Feature", "Event Name", "Asset Name", "ID",
          "Asset Category", "Canvas", "Plot", "Rotation", "Prompt", "Sets #"]


def _row(feature="", event="", name="", status="", category="", canvas="",
         prompt="", asset_id="", plot="", rotation="", release="", sets=""):
    return [status, release, feature, event, name, asset_id, category, canvas,
            plot, rotation, prompt, sets]


def test_detects_header_row_and_types_data_rows():
    grid = _grid(["junk"], HEADER, _row("QE 2", "Coven of Shadows", "Midnight Cat",
                                        "1", "Appliance", "128x128", "a cat", "241084"))
    rows = extract_order_rows(grid)
    assert len(rows) == 1
    r = rows[0]
    assert r["row"] == 3  # 1-based sheet row
    assert r["feature"] == "QE 2"
    assert r["eventName"] == "Coven of Shadows"
    assert r["assetName"] == "Midnight Cat"
    assert r["assetId"] == "241084"
    assert r["category"] == "Appliance"
    assert r["canvas"] == "128x128"
    assert r["prompt"] == "a cat"
    assert r["status"] == 1


def test_header_row_not_found_raises():
    import pytest
    with pytest.raises(ValueError, match="header row not found"):
        extract_order_rows(_grid(["a", "b"], ["c"]))


def test_first_duplicate_header_wins():
    grid = _grid(HEADER + ["Prompt"],  # artist copy column at the end
                 _row("Mini 1", "", "Thing", prompt="client prompt") + ["artist prompt"])
    assert extract_order_rows(grid)[0]["prompt"] == "client prompt"


def test_keeps_placeholder_rows_feature_only():
    grid = _grid(HEADER, _row("RR Crate"), _row())
    rows = extract_order_rows(grid)
    assert len(rows) == 1
    assert rows[0]["feature"] == "RR Crate"
    assert rows[0]["assetName"] == ""


def test_trims_whitespace_in_names():
    grid = _grid(HEADER, _row("Crate ", "", " Pastel Chest "))
    r = extract_order_rows(grid)[0]
    assert r["feature"] == "Crate"
    assert r["assetName"] == "Pastel Chest"


def test_empty_status_is_none():
    grid = _grid(HEADER, _row("Crate", "", "Chest"))
    assert extract_order_rows(grid)[0]["status"] is None


def test_compact_asset_name_removes_spaces_keeps_underscores():
    assert compact_asset_name("Bat Croissants") == "BatCroissants"
    assert compact_asset_name("Gargoyle_Handle x") == "Gargoyle_Handlex"


def test_match_ref_files_base_and_variants():
    files = ["BatCroissants.png", "BatCroissants_2.png", "BatCroissantsExtra.png",
             "batcroissants.png", "Other.png"]
    assert match_ref_files("Bat Croissants", files) == [
        "BatCroissants.png", "BatCroissants_2.png"]
    assert match_ref_files("Nope", files) == []
    assert match_ref_files("", files) == []


def test_group_order_events_first_appearance_order_and_event_name():
    rows = extract_order_rows(_grid(
        HEADER,
        _row("Crate", "", "Chest A"),
        _row("QE 2", "Coven of Shadows", "Cat"),
        _row("Crate", "Pastel Enchantment", "Chest B"),
    ))
    events = group_order_events(rows, ["Cat.png"])
    assert [e["feature"] for e in events] == ["Crate", "QE 2"]
    assert events[0]["eventName"] == "Pastel Enchantment"  # first non-empty wins
    assert events[1]["assets"][0]["refFiles"] == ["Cat.png"]
    assert events[0]["assets"][0]["refFiles"] == []


def test_group_empty_feature_bucket():
    rows = extract_order_rows(_grid(HEADER, _row("", "", "Orphan")))
    assert group_order_events(rows, [])[0]["feature"] == "(no feature)"


def test_template_groups_by_category_canvas_with_slug():
    rows = extract_order_rows(_grid(
        HEADER,
        _row("QE 2", "Coven", "Cat", category="Food - 3 stages", canvas="128x128"),
        _row("QE 2", "", "Dog", category="Food - 3 stages", canvas="128x128"),
        _row("QE 2", "", "Arch", category="Appliance", canvas="128x256"),
        _row("QE 2", "", ""),  # unnamed placeholder skipped
    ))
    groups = template_groups(group_order_events(rows, [])[0])
    assert [g["template"] for g in groups] == [
        "qe-2-food-3-stages-128x128", "qe-2-appliance-128x256"]
    assert len(groups[0]["assets"]) == 2


def test_slugify():
    assert slugify("QE 2-Appliance-128x128") == "qe-2-appliance-128x128"
    assert slugify("--Mini 1! Food--") == "mini-1-food"


def test_canvas_spec_of():
    assert canvas_spec_of("128x128") == {"w": 128, "h": 128}
    assert canvas_spec_of(" 200 X 100 ") == {"w": 200, "h": 100}
    assert canvas_spec_of("-") is None
    assert canvas_spec_of("") is None
