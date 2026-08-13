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
    bucket_for,
    bucket_of,
    canvas_spec_of,
    canvas_tiles,
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


def test_nan_status_is_none():
    grid = _grid(HEADER, _row("Crate", "", "Chest", status="nan"))
    assert extract_order_rows(grid)[0]["status"] is None


def test_inf_status_is_none():
    grid = _grid(HEADER, _row("Crate", "", "Chest", status="inf"))
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


# --- the bucket: one category drawn two ways ---------------------------------

class TestWhichSubKindARowIs:
    """A `Food - 3 stages` row is a chopping board for a cake and an empty cup
    on a saucer for a tea. The client's own Prep) line already says which, so
    the bucket is read rather than guessed off the asset name — which would
    have caught "Skull Tea" and missed "Fox Cocoa Float"."""

    def test_a_prep_line_with_a_board_is_not_a_drink(self):
        assert bucket_of(
            "Prep) Rolled croissant dough and chocolate wings lay on a wooden "
            "chopping board.\nReady) Three croissants.") == ""

    def test_an_empty_cup_on_a_saucer_is_a_drink(self):
        assert bucket_of(
            "Prep) A white teacup with gold trim sits empty on a matching "
            "saucer.\nReady) Three white teacups.") == "Drinks"

    def test_a_board_beats_a_cup_on_it(self):
        # Food preps name bowls and cups on the board all the time; a drink
        # prep never has a board at all.
        assert bucket_of(
            "Prep) Ingredients on a chopping board alongside a cup of icing "
            "and a bowl of dough.") == ""

    def test_a_row_with_no_stages_at_all_has_no_prep_line_to_read(self):
        """`Midnight Cathedral Oven` is an Appliance whose door carries "red
        and purple stained glass inserts". Reading the whole prompt as its prep
        line called it a drink, and the Drinks bucket then hid its canvas — so
        a 128x256 appliance asked for the wrong grid."""
        assert bucket_of(
            "A square-shaped oven with a flat top. The front door is arched, "
            "with red and purple stained glass inserts.") == ""

    def test_a_row_that_says_neither_keeps_the_plain_category(self):
        assert bucket_of("Prep) Dough rolled out flat on a surface.") == ""
        assert bucket_of("") == ""

    def test_the_prep_line_is_found_without_newlines(self):
        # A sheet cell is one string whose newlines survive inconsistently.
        assert bucket_of(
            "Prep) An empty mug. Ready) Three mugs on a tray.") == "Drinks"

    def test_a_ready_line_does_not_decide(self):
        # Only PREP separates them: a food row's Ready can name a teacup too.
        assert bucket_of(
            "Prep) Ingredients on a chopping board.\n"
            "Ready) A cake beside a teacup on a saucer.") == ""

    def test_every_row_carries_its_bucket(self):
        grid = [["Feature", "Asset Name", "Asset Category", "Prompt"],
                ["Mini 1", "Bat Brew", "Food - 3 stages",
                 "Prep) A vintage teacup, empty inside."],
                ["Mini 1", "Spookies", "Food - 3 stages",
                 "Prep) Dough on a chopping board."]]
        rows = extract_order_rows(grid)
        assert [r["bucket"] for r in rows] == ["Drinks", ""]


class TestTheCanvasInTiles:
    """assetkit names a grid by the tiles its canvas covers — `Appliance 1x1`
    is a short room corner and `Appliance 1x2` is the same floor under a wall
    twice as high."""

    def test_a_canvas_is_counted_in_128px_tiles(self):
        assert canvas_tiles("128x128") == "1x1"
        assert canvas_tiles("128x256") == "1x2"
        assert canvas_tiles("512x512") == "4x4"

    def test_the_sheets_own_plot_column_is_a_different_number(self):
        """The trap: October marks BOTH a 128x128 and a 128x256 Appliance as
        plot `1x1`, and three different plots on one 256x256 Decoration canvas.
        Reading `plot` would put two different grids under one name."""
        grid = [["Feature", "Asset Name", "Asset Category", "Canvas", "Plot"],
                ["Mini 1", "Squat Oven", "Appliance", "128x128", "1x1"],
                ["Mini 1", "Tall Oven", "Appliance", "128x256", "1x1"]]
        rows = extract_order_rows(grid)
        assert [r["plot"] for r in rows] == ["1x1", "1x1"]
        assert [canvas_tiles(r["canvas"]) for r in rows] == ["1x1", "1x2"]

    def test_a_canvas_that_is_not_whole_tiles_has_no_grid_of_its_own(self):
        assert canvas_tiles("200x200") == ""      # Crate Icon
        assert canvas_tiles("128x129") == ""      # a Wallpaper typo
        assert canvas_tiles("") == ""


class TestTheBucketOneWireCarries:
    def test_the_prep_line_wins_over_the_canvas(self):
        """A drink is a drink whatever size it is drawn at."""
        assert bucket_for({"canvas": "128x128",
                           "prompt": "Prep) An empty teacup."}) == "Drinks"

    def test_a_row_with_nothing_in_its_prep_line_falls_back_to_the_canvas(self):
        assert bucket_for({"canvas": "128x256",
                           "prompt": "Prep) Dough on a board."}) == "1x2"

    def test_a_bucket_already_on_the_row_is_kept(self):
        assert bucket_for({"bucket": "Drinks", "canvas": "512x512"}) == "Drinks"

    def test_a_row_with_neither_has_no_bucket(self):
        assert bucket_for({"canvas": "200x200", "prompt": ""}) == ""
        assert bucket_for({}) == ""
