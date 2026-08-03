# ABOUTME: The layout hash — what has to invalidate a cached set of cell boxes,
# ABOUTME: since none of the files deciding them are wired into any node.
import json

from pipeline.sheet_cells import layout_fingerprint


def _project(tmp_path, layouts=None, padding=20, overrides=None):
    (tmp_path / "_sources").mkdir(exist_ok=True)
    (tmp_path / "_sources" / "config.json").write_text(json.dumps(
        {"layouts": layouts or {"Food - 3 stages": "food2row"}, "swapped": {}}))
    (tmp_path / "assetkit-project.json").write_text(json.dumps(
        {"settings": {"width": 1024, "height": 1024, "padding": padding}}))
    for cat, cells in (overrides or {}).items():
        d = tmp_path / "dataset" / cat
        d.mkdir(parents=True, exist_ok=True)
        (d / "_layout.json").write_text(json.dumps({"cells": cells}))
    return str(tmp_path)


def test_a_re_ruled_type_changes_the_hash(tmp_path):
    """The case the whole hash exists for: the packing rule changes, every
    wired value stays identical, and a cached box set would keep cutting on the
    old grid."""
    before = layout_fingerprint(_project(tmp_path))
    after = layout_fingerprint(
        _project(tmp_path, layouts={"Food - 3 stages": "grid2x2"}))
    assert before != after


def test_changed_sheet_settings_change_the_hash(tmp_path):
    before = layout_fingerprint(_project(tmp_path, padding=20))
    assert before != layout_fingerprint(_project(tmp_path, padding=40))


def test_adding_a_recorded_layout_changes_the_hash(tmp_path):
    """Absent has to hash differently from present, or dropping in a
    _layout.json would not take effect until something else invalidated."""
    before = layout_fingerprint(_project(tmp_path))
    after = layout_fingerprint(_project(tmp_path, overrides={
        "Food - 3 stages": [{"role": "prep", "x": 0, "y": 0, "w": 8, "h": 8}]}))
    assert before != after


def test_editing_a_recorded_layout_changes_the_hash(tmp_path):
    cells = [{"role": "prep", "x": 0, "y": 0, "w": 8, "h": 8}]
    before = layout_fingerprint(
        _project(tmp_path, overrides={"Food - 3 stages": cells}))
    moved = [{"role": "prep", "x": 4, "y": 0, "w": 8, "h": 8}]
    after = layout_fingerprint(
        _project(tmp_path, overrides={"Food - 3 stages": moved}))
    assert before != after


def test_the_same_project_hashes_the_same_twice(tmp_path):
    """Content, not mtime — a rewrite with identical bytes must not invalidate,
    or every queue press would re-run the lane."""
    p = _project(tmp_path)
    first = layout_fingerprint(p)
    (tmp_path / "assetkit-project.json").write_text(
        (tmp_path / "assetkit-project.json").read_text())
    assert layout_fingerprint(p) == first


def test_no_project_and_a_missing_project_never_raise(tmp_path):
    # Feeds a change-check: a raise there becomes NaN and re-bills every
    # descendant on each queue press.
    assert isinstance(layout_fingerprint(""), str)
    assert isinstance(layout_fingerprint(str(tmp_path / "nope")), str)
