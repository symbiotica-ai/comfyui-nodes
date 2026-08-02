# ABOUTME: One item per asset grouped by type, and the seeded per-type draw of
# ABOUTME: a style reference from <project>/dataset/<Type>/.
import pytest
from PIL import Image

from pipeline.order_assets import (MissingDatasetsError, assets_by_category,
                                   list_dataset_images,
                                   pick_reference_per_category)


def _asset(name, category, prompt="brief", refs=("a.png", "b.png")):
    return {"assetName": name, "category": category, "prompt": prompt,
            "canvas": "128x128", "refFiles": list(refs)}


MINI_1 = {"feature": "Mini 1", "assets": [
    _asset("Phantom Freezer Cart", "Decoration", refs=("p.png",)),
    _asset("Ghost Bakery Queue", "Decoration"),
    _asset("Witch Cat Tea Parlor", "Decoration"),
    _asset("Spookies", "Food - 3 stages"),
    _asset("Spooky Stack Popsicle", "Food - 3 stages"),
    _asset("Ghostly Jelly Cake", "Food - 3 stages"),
]}


def test_one_item_per_asset_not_per_reference():
    # The packer splits a rotation-2 decoration per reference image; this must
    # not — one asset is one render, whatever its reference count.
    out = assets_by_category(MINI_1)
    assert len(out) == 6
    assert [a["assetName"] for a in out] == [
        "Phantom Freezer Cart", "Ghost Bakery Queue", "Witch Cat Tea Parlor",
        "Spookies", "Spooky Stack Popsicle", "Ghostly Jelly Cake"]


def test_grouped_by_type_in_first_appearance_order():
    order = {"assets": [_asset("Cake", "Food - 3 stages"),
                        _asset("Bench", "Decoration"),
                        _asset("Pie", "Food - 3 stages")]}
    # Food appears first, so food leads — and its two assets stay adjacent.
    assert [a["category"] for a in assets_by_category(order)] == [
        "Food - 3 stages", "Food - 3 stages", "Decoration"]
    assert [a["assetName"] for a in assets_by_category(order)][:2] == ["Cake", "Pie"]


def test_client_brief_rides_along():
    order = {"assets": [_asset("Cake", "Food - 3 stages", prompt="a spooky cake")]}
    assert assets_by_category(order)[0]["prompt"] == "a spooky cake"


def test_nameless_padding_rows_are_dropped():
    order = {"assets": [_asset("", "Decoration"), _asset("Bench", "Decoration")]}
    assert [a["assetName"] for a in assets_by_category(order)] == ["Bench"]


def test_no_order_is_empty_not_an_error():
    assert assets_by_category(None) == []
    assert assets_by_category({}) == []


def _dataset(tmp_path, **cats):
    proj = tmp_path / "bakery"
    for cat, names in cats.items():
        d = proj / "dataset" / cat
        d.mkdir(parents=True)
        for n in names:
            Image.new("RGB", (8, 8)).save(d / n)
    return proj


def test_every_asset_of_a_type_shares_one_reference(tmp_path):
    proj = _dataset(tmp_path, **{"Decoration": ["d1.png", "d2.png", "d3.png"],
                                 "Food - 3 stages": ["f1.png", "f2.png"]})
    cats = ["Decoration"] * 3 + ["Food - 3 stages"] * 3
    paths, names = pick_reference_per_category(proj, cats, seed=7)
    assert len(paths) == 6
    assert len(set(paths[:3])) == 1, "all decorations must share one reference"
    assert len(set(paths[3:])) == 1, "all food must share one reference"
    assert paths[0] != paths[3], "different types draw independently"
    assert names[0].endswith(".png")


def test_the_same_seed_draws_the_same_references(tmp_path):
    proj = _dataset(tmp_path, **{"Decoration": [f"d{i}.png" for i in range(10)]})
    a, _ = pick_reference_per_category(proj, ["Decoration"], seed=3)
    b, _ = pick_reference_per_category(proj, ["Decoration"], seed=3)
    assert a == b


def test_a_different_seed_can_draw_a_different_reference(tmp_path):
    proj = _dataset(tmp_path, **{"Decoration": [f"d{i}.png" for i in range(20)]})
    drawn = {pick_reference_per_category(proj, ["Decoration"], seed=s)[0][0]
             for s in range(12)}
    assert len(drawn) > 1, "the seed must actually move the draw"


def test_adding_a_type_does_not_reshuffle_the_others(tmp_path):
    # The draw is keyed per (seed, category) for this: adding food to an order
    # must not change which decoration reference was already approved.
    proj = _dataset(tmp_path, **{"Decoration": [f"d{i}.png" for i in range(8)],
                                 "Food - 3 stages": [f"f{i}.png" for i in range(8)]})
    before, _ = pick_reference_per_category(proj, ["Decoration"], seed=5)
    after, _ = pick_reference_per_category(
        proj, ["Decoration", "Food - 3 stages"], seed=5)
    assert after[0] == before[0]


def test_missing_type_folders_are_named_together(tmp_path):
    proj = _dataset(tmp_path, **{"Decoration": ["d1.png"]})
    with pytest.raises(MissingDatasetsError) as e:
        pick_reference_per_category(
            proj, ["Decoration", "Signage", "Wallpaper"], seed=1)
    assert "Signage" in str(e.value) and "Wallpaper" in str(e.value)
    assert "dataset" in str(e.value)


def test_an_empty_folder_counts_as_missing(tmp_path):
    proj = _dataset(tmp_path, **{"Decoration": []})
    with pytest.raises(MissingDatasetsError):
        pick_reference_per_category(proj, ["Decoration"], seed=1)


def test_non_images_are_ignored(tmp_path):
    proj = _dataset(tmp_path, **{"Decoration": ["d1.png"]})
    (proj / "dataset" / "Decoration" / "_caption-prompt.txt").write_text("x")
    (proj / "dataset" / "Decoration" / "notes.md").write_text("x")
    assert list_dataset_images(proj / "dataset" / "Decoration") == ["d1.png"]
