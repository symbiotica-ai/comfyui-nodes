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
