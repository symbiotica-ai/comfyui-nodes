# ABOUTME: Tests for the Auto Packer Template Library store — write/list/load/
# ABOUTME: delete of per-template folders + the template-as-defaults layering.
import json

from PIL import Image

from pipeline.pack_library import (
    collect_checked,
    delete_pack_template,
    delete_pack_template_dirs,
    kind_of_order,
    list_pack_templates,
    list_pack_templates_dirs,
    load_pack_template,
    load_pack_template_dirs,
    order_templates_dir,
    pack_dirs,
    qualified_name,
    reference_templates_dir,
    resolve_pack_inputs,
    save_dirs,
    split_qualified,
    templates_dir,
    write_pack_template,
)


def _img(color=(1, 2, 3)):
    return Image.new("RGB", (4, 4), color)


def _sidecar(**over):
    base = {"order": {"project_path": "/p", "month": "October",
                      "feature": "Mini 1", "assets": [{"assetName": "d1"}],
                      "refsRoot": "/p/refs"},
            "preset": {"model": "qwen-image", "tier": "1K"},
            "settings": {"scale": 2.0}, "category": "Decoration",
            "overrides": {"hidden": ["x"]}, "sheetNames": ["s0"]}
    base.update(over)
    return base


def test_templates_dir_under_project():
    assert templates_dir("/clients/imperia/bakery") == \
        "/clients/imperia/bakery/templates"
    assert templates_dir("") == ""
    assert templates_dir("  ") == ""


def test_write_creates_folder_sheets_and_sidecar(tmp_path):
    base = str(tmp_path / "templates")
    res = write_pack_template(base, "Mini 1 · Deco!", [_img(), _img()],
                              _sidecar())
    assert res["name"] == "mini-1-deco"
    assert res["sheetCount"] == 2
    sub = tmp_path / "templates" / "mini-1-deco"
    assert (sub / "sheet-000.png").is_file()
    assert (sub / "sheet-001.png").is_file()
    doc = json.loads((sub / "template.json").read_text())
    assert doc["name"] == "mini-1-deco"
    assert doc["sheets"] == ["sheet-000.png", "sheet-001.png"]
    assert doc["category"] == "Decoration"
    assert doc["order"]["feature"] == "Mini 1"
    assert "savedAt" in doc


def test_resave_clears_stale_sheets(tmp_path):
    base = str(tmp_path / "templates")
    write_pack_template(base, "t", [_img(), _img(), _img()], _sidecar())
    write_pack_template(base, "t", [_img()], _sidecar())  # fewer sheets now
    sub = tmp_path / "templates" / "t"
    pngs = sorted(p.name for p in sub.glob("sheet-*.png"))
    assert pngs == ["sheet-000.png"]  # sheet-001/002 removed


def test_load_injects_dir_and_sheetpaths(tmp_path):
    base = str(tmp_path / "templates")
    write_pack_template(base, "t", [_img(), _img()], _sidecar())
    doc = load_pack_template(base, "t")
    assert doc["name"] == "t"
    assert doc["dir"].endswith("/templates/t")
    assert len(doc["sheetPaths"]) == 2
    assert all(p.endswith(".png") for p in doc["sheetPaths"])
    # slug-normalised lookup works too
    assert load_pack_template(base, "T") is not None
    assert load_pack_template(base, "missing") is None
    assert load_pack_template(base, "") is None


def test_list_sorted_and_skips_non_templates(tmp_path):
    base = str(tmp_path / "templates")
    write_pack_template(base, "zeta", [_img()], _sidecar())
    write_pack_template(base, "alpha", [_img()], _sidecar())
    (tmp_path / "templates" / "loose.txt").write_text("junk")  # not a dir
    (tmp_path / "templates" / "empty").mkdir()  # dir, no template.json
    got = list_pack_templates(base)
    assert [t["name"] for t in got] == ["alpha", "zeta"]


def test_list_missing_dir_is_empty(tmp_path):
    assert list_pack_templates(str(tmp_path / "nope")) == []
    assert list_pack_templates("") == []


def test_delete_removes_folder(tmp_path):
    base = str(tmp_path / "templates")
    write_pack_template(base, "t", [_img()], _sidecar())
    assert delete_pack_template(base, "t") is True
    assert not (tmp_path / "templates" / "t").exists()
    assert delete_pack_template(base, "t") is False  # already gone


def test_name_cannot_escape_base(tmp_path):
    base = str(tmp_path / "templates")
    # "../evil" slugifies to "evil" (dots/slashes collapse) — stays inside.
    res = write_pack_template(base, "../evil", [_img()], _sidecar())
    assert res["name"] == "evil"
    assert (tmp_path / "templates" / "evil" / "template.json").is_file()
    assert not (tmp_path / "evil").exists()


# --- resolve_pack_inputs: template supplies defaults, node inputs win --------

TEMPLATE = {
    "order": {"assets": [{"assetName": "d1"}], "feature": "Mini 1",
              "refsRoot": "/r"},
    "preset": {"model": "qwen-image", "tier": "2K"},
    "settings": {"scale": 4.0},
    "category": "Decoration",
    "overrides": {"hidden": ["d2"]},
    "name": "mini-1",
}


def test_resolve_uses_template_when_node_unset():
    # category="" = unset → defers to the template's saved category.
    cfg = resolve_pack_inputs(order=None, preset=None, settings=None,
                              category="", overrides="{}",
                              template=TEMPLATE)
    assert cfg["order"]["feature"] == "Mini 1"
    assert cfg["preset"]["tier"] == "2K"
    assert cfg["settings"]["scale"] == 4.0
    assert cfg["category"] == "Decoration"
    assert json.loads(cfg["overrides"]) == {"hidden": ["d2"]}


def test_resolve_explicit_all_beats_template_category():
    # "All" is a deliberate pick (pack every type), NOT the unset sentinel — it
    # must win over a template whose saved category was narrower.
    cfg = resolve_pack_inputs(order=None, preset=None, settings=None,
                              category="All", overrides="{}",
                              template=TEMPLATE)
    assert cfg["category"] == "All"


def test_resolve_node_inputs_override_template():
    node_order = {"assets": [{"assetName": "x"}], "feature": "QE 2"}
    cfg = resolve_pack_inputs(
        order=node_order, preset={"model": "nano", "tier": "1K"},
        settings={"scale": 1.0}, category="Food",
        overrides='{"hidden":["y"]}', template=TEMPLATE)
    assert cfg["order"]["feature"] == "QE 2"      # wired order wins
    assert cfg["preset"]["model"] == "nano"        # wired preset wins
    assert cfg["settings"]["scale"] == 1.0         # wired settings win
    assert cfg["category"] == "Food"               # edited category wins
    assert json.loads(cfg["overrides"]) == {"hidden": ["y"]}


def test_resolve_no_template_no_order():
    cfg = resolve_pack_inputs(order=None, preset=None, settings=None,
                              category="All", overrides="{}", template=None)
    assert cfg["order"] is None
    assert cfg["preset"] == {}
    assert cfg["category"] == "All"
    assert cfg["overrides"] == "{}"


# --- multi-dir browse (project templates/ + output/templates fallback) -------

def test_list_dirs_merges_project_first(tmp_path):
    project = str(tmp_path / "project" / "templates")
    out = str(tmp_path / "output" / "templates")
    write_pack_template(project, "shared", [_img()],
                        _sidecar(category="ProjectWins"))
    write_pack_template(out, "shared", [_img()], _sidecar(category="Fallback"))
    write_pack_template(out, "only-fallback", [_img()], _sidecar())
    got = list_pack_templates_dirs([project, out])
    names = [t["name"] for t in got]
    assert names == ["only-fallback", "shared"]
    shared = next(t for t in got if t["name"] == "shared")
    assert shared["category"] == "ProjectWins"  # project dir shadows fallback


def test_load_dirs_falls_back_to_output(tmp_path):
    project = str(tmp_path / "project" / "templates")
    out = str(tmp_path / "output" / "templates")
    write_pack_template(out, "orphan", [_img()], _sidecar())
    # project dir has nothing → falls through to output/templates
    assert load_pack_template_dirs([project, out], "orphan") is not None
    assert load_pack_template_dirs([project, out], "missing") is None


def test_collect_checked_pairs_sheets_with_prompts(tmp_path):
    base = str(tmp_path / "templates")
    write_pack_template(base, "t", [_img(), _img()],
                        _sidecar(sheetPrompts=["p0", "p1"]))
    pairs = collect_checked([base], ["t"])
    assert [pr for _, pr in pairs] == ["p0", "p1"]
    assert all(path.endswith(".png") for path, _ in pairs)


def test_collect_checked_skips_unknown_and_missing_prompts(tmp_path):
    base = str(tmp_path / "templates")
    write_pack_template(base, "noprompts", [_img()], _sidecar())  # no sheetPrompts
    pairs = collect_checked([base], ["noprompts", "ghost"])   # ghost = unknown
    assert len(pairs) == 1
    assert pairs[0][1] == ""                                   # missing → ""


def test_collect_checked_multiple_templates_in_order(tmp_path):
    base = str(tmp_path / "templates")
    write_pack_template(base, "a", [_img()], _sidecar(sheetPrompts=["pa"]))
    write_pack_template(base, "b", [_img(), _img()],
                        _sidecar(sheetPrompts=["pb0", "pb1"]))
    pairs = collect_checked([base], ["a", "b"])
    assert [pr for _, pr in pairs] == ["pa", "pb0", "pb1"]


def test_delete_dirs_removes_from_all(tmp_path):
    project = str(tmp_path / "project" / "templates")
    out = str(tmp_path / "output" / "templates")
    write_pack_template(project, "dup", [_img()], _sidecar())
    write_pack_template(out, "dup", [_img()], _sidecar())
    assert delete_pack_template_dirs([project, out], "dup") is True
    assert list_pack_templates_dirs([project, out]) == []
    assert delete_pack_template_dirs([project, out], "dup") is False


# --- the order / reference split --------------------------------------------

def _project(tmp_path, month_refs="Bakery-October"):
    """A client project laid out the way the pipeline expects: orders/ with a
    month xlsx and (optionally) that month's client-refs folder."""
    project = tmp_path / "bakery"
    (project / "orders").mkdir(parents=True)
    (project / "orders" / "Bakery October Art.xlsx").write_bytes(b"x")
    if month_refs:
        (project / "orders" / month_refs).mkdir()
    (project / "reference-assets").mkdir()
    return project


def test_reference_pool_is_project_level_and_month_free(tmp_path):
    project = _project(tmp_path)
    assert reference_templates_dir(str(project)) == \
        str(project / "templates" / "reference")
    assert reference_templates_dir("") == ""


def test_order_pool_sits_beside_the_month_order(tmp_path):
    project = _project(tmp_path)
    assert order_templates_dir(str(project), "October") == \
        str(project / "orders" / "Bakery-October" / "templates")


def test_order_pool_falls_back_to_month_scoped_project_folder(tmp_path):
    """No client-refs folder for that month — still month-scoped, and still out
    of the universal reference pool."""
    project = _project(tmp_path, month_refs="")
    got = order_templates_dir(str(project), "October")
    assert got == str(project / "templates" / "orders" / "october")
    assert order_templates_dir("", "October") == ""


def test_kind_of_order_reads_source_then_infers():
    assert kind_of_order({"source": "reference"}) == "reference"
    assert kind_of_order({"source": "order"}) == "order"
    # Legacy payloads (no source): a month or the shared catalog root means it
    # came from an order; a library pick carries neither.
    assert kind_of_order({"month": "October"}) == "order"
    assert kind_of_order({"assetsRoot": "/p/reference-assets"}) == "order"
    assert kind_of_order({"refsRoot": "/p/reference-assets/Food"}) == "reference"
    assert kind_of_order(None) == "order"


def test_write_and_load_carry_the_kind(tmp_path):
    base = str(tmp_path / "templates" / "reference")
    write_pack_template(base, "blossom", [_img()],
                        _sidecar(kind="reference",
                                 order={"source": "reference", "month": ""}))
    doc = load_pack_template(base, "blossom")
    assert doc["kind"] == "reference"
    assert doc["key"] == "reference/blossom"


def test_legacy_template_gets_its_kind_inferred(tmp_path):
    base = str(tmp_path / "templates")
    write_pack_template(base, "legacy", [_img()], _sidecar())  # no kind key
    doc = load_pack_template(base, "legacy")
    assert doc["kind"] == "order"          # sidecar order has a month
    assert doc["key"] == "order/legacy"


def test_same_slug_in_both_pools_stays_two_rows(tmp_path):
    ref = str(tmp_path / "templates" / "reference")
    order = str(tmp_path / "orders" / "Bakery-October" / "templates")
    write_pack_template(ref, "food", [_img()],
                        _sidecar(kind="reference", category="RefPool"))
    write_pack_template(order, "food", [_img()],
                        _sidecar(kind="order", category="OrderPool"))
    got = list_pack_templates_dirs([order, ref])
    assert [(t["kind"], t["name"]) for t in got] == \
        [("order", "food"), ("reference", "food")]
    # …and a qualified id picks exactly one of them.
    assert load_pack_template_dirs([order, ref], "reference/food")["category"] \
        == "RefPool"
    assert load_pack_template_dirs([order, ref], "order/food")["category"] \
        == "OrderPool"
    # A bare slug still resolves (workflows saved before the split), first dir.
    assert load_pack_template_dirs([order, ref], "food")["category"] == "OrderPool"


def test_qualified_delete_spares_the_other_pool(tmp_path):
    ref = str(tmp_path / "templates" / "reference")
    order = str(tmp_path / "orders" / "Bakery-October" / "templates")
    write_pack_template(ref, "food", [_img()], _sidecar(kind="reference"))
    write_pack_template(order, "food", [_img()], _sidecar(kind="order"))
    assert delete_pack_template_dirs([order, ref], "order/food") is True
    left = list_pack_templates_dirs([order, ref])
    assert [(t["kind"], t["name"]) for t in left] == [("reference", "food")]


def test_collect_checked_takes_qualified_ids(tmp_path):
    ref = str(tmp_path / "templates" / "reference")
    order = str(tmp_path / "orders" / "Bakery-October" / "templates")
    write_pack_template(ref, "food", [_img()],
                        _sidecar(kind="reference", sheetPrompts=["style"]))
    write_pack_template(order, "food", [_img()],
                        _sidecar(kind="order", sheetPrompts=["design"]))
    pairs = collect_checked([order, ref], ["reference/food", "order/food"])
    assert [pr for _, pr in pairs] == ["style", "design"]


def test_split_and_qualify_round_trip():
    assert split_qualified("reference/food") == ("reference", "food")
    assert split_qualified("order/food") == ("order", "food")
    assert split_qualified("food") == ("", "food")
    # Not a kind prefix — the whole thing is the slug's business, not a pool.
    assert split_qualified("mini-1/food") == ("", "mini-1/food")
    assert split_qualified("") == ("", "")
    assert qualified_name("reference", "food") == "reference/food"
    assert qualified_name("", "food") == "food"


def test_pack_dirs_per_kind(tmp_path):
    project = _project(tmp_path)
    out = str(tmp_path / "output" / "templates")
    ref = pack_dirs(str(project), "reference", "October", out)
    assert ref == [str(project / "templates" / "reference"),
                   str(tmp_path / "output" / "templates" / "reference")]
    order = pack_dirs(str(project), "order", "October", out)
    assert order == [str(project / "orders" / "Bakery-October" / "templates"),
                     str(tmp_path / "output" / "templates" / "orders" / "october")]
    # "All" browses both pools AND the legacy flat ones.
    every = pack_dirs(str(project), "", "October", out)
    assert set(ref + order).issubset(set(every))
    assert str(project / "templates") in every
    assert out in every


def test_every_alias_of_a_month_is_one_folder(tmp_path):
    """"", the month name, and the xlsx filename all name the same order — so
    they must name the same template folder, or a save lands where no browse
    looks."""
    project = _project(tmp_path, month_refs="")   # fallback path, the risky one
    out = str(tmp_path / "output" / "templates")
    want = str(project / "templates" / "orders" / "october")
    for alias in ("", "October", "october", "Bakery October Art.xlsx"):
        assert order_templates_dir(str(project), alias) == want, alias
        assert pack_dirs(str(project), "order", alias, out)[0] == want, alias
        assert save_dirs(str(project), "order", alias, out)[0] == want, alias
    # …and the output fallback agrees, so a read-only project lands in one place.
    fallbacks = {save_dirs(str(project), "order", a, out)[1]
                 for a in ("", "October", "Bakery October Art.xlsx")}
    assert fallbacks == {str(tmp_path / "output" / "templates" / "orders"
                             / "october")}


def test_all_browses_every_month_not_just_the_asked_one(tmp_path):
    """The save follows the ORDER's month, the Library browses its own — so All
    has to cover every month or a November template is invisible in October."""
    project = _project(tmp_path, month_refs="Bakery-October")
    (project / "orders" / "Bakery November Art.xlsx").write_bytes(b"x")
    (project / "orders" / "Bakery-November").mkdir()
    out = str(tmp_path / "output" / "templates")
    write_pack_template(str(project / "orders" / "Bakery-November" / "templates"),
                        "nov-food", [_img()], _sidecar(kind="order"))
    every = pack_dirs(str(project), "", "October", out)
    assert [t["name"] for t in list_pack_templates_dirs(every)] == ["nov-food"]


def test_save_dirs_project_then_output_fallback(tmp_path):
    project = _project(tmp_path)
    out = str(tmp_path / "output" / "templates")
    assert save_dirs(str(project), "reference", "", out) == [
        str(project / "templates" / "reference"),
        str(tmp_path / "output" / "templates" / "reference")]
    # No project (Reference Browser outside a project tree) → output only.
    assert save_dirs("", "reference", "", out) == [
        str(tmp_path / "output" / "templates" / "reference")]
