# ABOUTME: Tests for the Auto Packer Template Library store — write/list/load/
# ABOUTME: delete of per-template folders + the template-as-defaults layering.
import json

from PIL import Image

from pipeline.pack_library import (
    collect_checked,
    delete_pack_template,
    delete_pack_template_dirs,
    list_pack_templates,
    list_pack_templates_dirs,
    load_pack_template,
    load_pack_template_dirs,
    resolve_pack_inputs,
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
