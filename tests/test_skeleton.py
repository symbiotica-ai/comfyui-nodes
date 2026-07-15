# ABOUTME: Tests for the Template Editor's layout skeleton — the framing-free
# ABOUTME: facts an LLM turns into the edit prompt.
from pipeline.skeleton import build_skeleton, element_block


def region(rid, name, desc, x, y, w, h, z=0):
    return {"id": rid, "name": name, "desc": desc,
            "x": x, "y": y, "w": w, "h": h, "zIndex": z}


def test_element_block_carries_name_placement_ref_and_brief():
    r = region("r1", "Ghost Bakery Queue", "a queue of ghosts", 0, 0.25, 1, 0.5)
    block = element_block(1, r, 2)
    assert 'Element 1: "Ghost Bakery Queue"' in block
    assert "box_2d = [250, 0, 750, 1000]" in block
    assert "reference: image 2" in block
    assert "client brief: a queue of ghosts" in block


def test_element_block_omits_missing_parts():
    block = element_block(1, region("r1", "", "", 0, 0, 0.5, 0.5), None)
    assert block == "Element 1\n  placement: at the top-left · box_2d = [0, 0, 500, 500]"


def test_build_skeleton_orders_back_to_front_and_numbers_elements():
    regions = [region("front", "Front", "f", 0, 0, 0.2, 0.2, z=5),
               region("back", "Back", "b", 0.5, 0.5, 0.2, 0.2, z=1)]
    out = build_skeleton(regions, 1024, 1024, {"back": 2, "front": 3})
    assert out.index('Element 1: "Back"') < out.index('Element 2: "Front"')
    assert "reference: image 2" in out and "reference: image 3" in out


def test_build_skeleton_states_sheet_size_and_element_count():
    out = build_skeleton([region("r1", "One", "d", 0, 0, 1, 1)], 2048, 1024)
    assert "Sheet: 2048 x 1024 px." in out
    assert "1 element, listed back to front." in out


def test_build_skeleton_pluralizes_and_skips_ref_line_without_refs():
    regions = [region("a", "A", "d", 0, 0, 0.5, 0.5),
               region("b", "B", "d", 0.5, 0, 0.5, 0.5)]
    out = build_skeleton(regions, 1024, 1024)
    assert "2 elements, listed back to front." in out
    assert "reference: image" not in out
    assert "Image 1 is the sheet" not in out


def test_build_skeleton_carries_no_framing_words():
    # The whole point: the LLM's system prompt owns the brief. Any goal or
    # style word here would compete with it.
    out = build_skeleton([region("r1", "One", "a red crate", 0, 0, 1, 1)],
                         1024, 1024, {"r1": 2}).lower()
    for word in ["reproduce", "redraw", "style", "faithful", "edit the",
                 "do not", "keep everything"]:
        assert word not in out, f"skeleton must not frame the task: {word!r}"
