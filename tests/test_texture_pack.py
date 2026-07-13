# ABOUTME: Tests for the packing algorithms (shelf/grid/maxrects/by-folder) and
# ABOUTME: model-preset sheet sizing — ported behaviors from hub pack.ts.
from pipeline.model_presets import aspect_dims, preset_dims
from pipeline.texture_pack import PackSettings, effective_max, pack, sheet_size


def sprite(sid, w, h, path=None):
    return {"id": sid, "name": sid, "path": path or f"Cat/{sid}/{sid}.png",
            "width": w, "height": h}


def test_preset_dims_nano_banana_pro_2k_square():
    assert preset_dims({"model": "nano-banana-pro", "tier": "2K", "ar": "1:1"}) == \
        {"w": 2048, "h": 2048}


def test_aspect_dims_long_edge_and_round8():
    assert aspect_dims("16:9", "1K") == {"w": 1024, "h": 576}
    assert aspect_dims("9:16", "1K") == {"w": 576, "h": 1024}


def test_preset_dims_invalid_returns_none():
    assert preset_dims(None) is None
    assert preset_dims({"model": "nope", "tier": "1K", "ar": "1:1"}) is None
    assert preset_dims({"model": "imagen-4", "tier": "4K", "ar": "1:1"}) is None


def test_effective_max_prefers_preset():
    s = PackSettings(preset={"model": "nano-banana-pro", "tier": "1K", "ar": "1:1"},
                     max_width=99, max_height=99)
    assert effective_max(s) == {"w": 1024, "h": 1024}
    assert effective_max(PackSettings(max_width=99, max_height=77)) == {"w": 99, "h": 77}


def test_shelf_packs_tallest_first_rows():
    s = PackSettings(algorithm="shelf", preset=None, max_width=100, max_height=100)
    res = pack([sprite("a", 40, 10), sprite("b", 40, 30), sprite("c", 40, 20)], s)
    by_id = {p["id"]: p for p in res["placed"]}
    assert by_id["b"]["y"] == 0 and by_id["c"]["y"] == 0  # tallest two on shelf 1
    assert by_id["a"]["y"] == 30  # next shelf below the tallest
    assert res["overflow"] == []


def test_shelf_overflow_when_too_tall():
    s = PackSettings(algorithm="shelf", preset=None, max_width=50, max_height=25)
    res = pack([sprite("a", 40, 20), sprite("b", 40, 20)], s)
    assert res["overflow"] == ["b"]


def test_grid_centres_in_cells():
    s = PackSettings(algorithm="grid", preset=None, max_width=100, max_height=100,
                     grid_cell=50)
    res = pack([sprite("a", 30, 30), sprite("b", 30, 30), sprite("c", 30, 30)], s)
    by_id = {p["id"]: p for p in res["placed"]}
    assert (by_id["a"]["x"], by_id["a"]["y"]) == (10, 10)
    assert (by_id["b"]["x"], by_id["b"]["y"]) == (60, 10)
    assert (by_id["c"]["x"], by_id["c"]["y"]) == (10, 60)


def test_maxrects_places_all_when_they_fit():
    s = PackSettings(algorithm="maxrects", preset=None, max_width=100, max_height=100)
    res = pack([sprite("a", 50, 50), sprite("b", 50, 50), sprite("c", 50, 50),
                sprite("d", 50, 50)], s)
    assert res["overflow"] == []
    coords = {(p["x"], p["y"]) for p in res["placed"]}
    assert coords == {(0, 0), (50, 0), (0, 50), (50, 50)}


def test_distribute_by_folder_rows_spread_evenly():
    s = PackSettings(preset=None, max_width=100, max_height=100,
                     distribute_by_folder=True)
    res = pack([sprite("a", 20, 10, "Food/A/a.png"), sprite("b", 20, 10, "Food/A/b.png"),
                sprite("c", 20, 10, "Deco/C/c.png")], s)
    by_id = {p["id"]: p for p in res["placed"]}
    # Two folder rows (A, C) of height 10 → gap = (100-20)/3.
    gap = (100 - 20) / 3
    assert abs(by_id["a"]["y"] - gap) < 1e-6
    assert abs(by_id["c"]["y"] - (gap * 2 + 10)) < 1e-6
    # Row 1 (a+b, width 40) centred: x starts at 30.
    assert abs(by_id["a"]["x"] - 30) < 1e-6


def test_border_shifts_placements():
    s = PackSettings(algorithm="shelf", preset=None, max_width=100, max_height=100,
                     border=10)
    res = pack([sprite("a", 20, 20)], s)
    assert (res["placed"][0]["x"], res["placed"][0]["y"]) == (10, 10)


def test_padding_inflates_boxes():
    s = PackSettings(algorithm="shelf", preset=None, max_width=100, max_height=100,
                     padding=4)
    res = pack([sprite("a", 20, 20), sprite("b", 20, 20)], s)
    by_id = {p["id"]: p for p in res["placed"]}
    assert by_id["b"]["x"] - by_id["a"]["x"] == 24


def test_sheet_size_preset_locks_pow2_square_otherwise():
    preset = PackSettings(preset={"model": "nano-banana-pro", "tier": "1K", "ar": "1:1"})
    assert sheet_size(10, 10, preset) == {"w": 1024, "h": 1024}
    free = PackSettings(preset=None, force_square=True, power_of_two=True)
    assert sheet_size(300, 500, free) == {"w": 512, "h": 512}
