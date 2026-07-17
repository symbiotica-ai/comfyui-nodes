# ABOUTME: Tests for project-folder resolution — one path + month -> order xlsx,
# ABOUTME: that month's client-refs folder, and the shared sprite catalog.
import os

import pytest

from pipeline.project_layout import (
    list_order_months,
    refs_folder_for,
    resolve_month,
)


@pytest.fixture
def project(tmp_path):
    """A project laid out like the real one: Orders/ with month xlsx + per-month
    refs folders, and reference-assets/ as the sprite catalog."""
    orders = tmp_path / "Orders"
    orders.mkdir()
    (orders / "Bakery October Art.xlsx").write_bytes(b"x")
    (orders / "Bakery November Art.xlsx").write_bytes(b"x")
    (orders / "Bakery-October").mkdir()
    (orders / "Bakery-November").mkdir()
    (orders / "~$Bakery October Art.xlsx").write_bytes(b"x")  # temp, ignored
    (tmp_path / "reference-assets").mkdir()
    return tmp_path


def test_list_months_calendar_order_with_labels(project):
    months = list_order_months(str(project))
    assert [m["label"] for m in months] == ["October", "November"]
    assert months[0]["file"] == "Bakery October Art.xlsx"


def test_list_months_ignores_temp_files(project):
    files = [m["file"] for m in list_order_months(str(project))]
    assert not any(f.startswith("~") for f in files)


def test_refs_folder_matches_by_month(project):
    orders = str(project / "Orders")
    got = refs_folder_for(orders, "Bakery October Art.xlsx")
    assert os.path.basename(got) == "Bakery-October"


def test_resolve_month_by_month_name(project):
    r = resolve_month(str(project), "october")
    assert os.path.basename(r["order_path"]) == "Bakery October Art.xlsx"
    assert os.path.basename(r["refs_path"]) == "Bakery-October"
    assert os.path.basename(r["assets_root"]) == "reference-assets"


def test_resolve_month_by_filename(project):
    r = resolve_month(str(project), "Bakery November Art.xlsx")
    assert os.path.basename(r["order_path"]) == "Bakery November Art.xlsx"
    assert os.path.basename(r["refs_path"]) == "Bakery-November"


def test_resolve_defaults_to_first_month_when_blank(project):
    r = resolve_month(str(project), "")
    assert os.path.basename(r["order_path"]) == "Bakery October Art.xlsx"


def test_resolve_empty_project_is_all_empty(tmp_path):
    r = resolve_month(str(tmp_path), "october")
    assert r == {"order_path": "", "refs_path": "", "assets_root": ""}


def test_refs_folder_falls_back_to_name_overlap(tmp_path):
    orders = tmp_path / "orders"
    orders.mkdir()
    (orders / "SpecialDrop.xlsx").write_bytes(b"x")
    (orders / "SpecialDrop").mkdir()
    got = refs_folder_for(str(orders), "SpecialDrop.xlsx")
    assert os.path.basename(got) == "SpecialDrop"
