# ABOUTME: Tests for project-folder resolution — one path + month -> order xlsx,
# ABOUTME: that month's client-refs folder, and the shared sprite catalog.
import os

import pytest

from pipeline.project_layout import (
    MonthNotFound,
    list_order_months,
    refs_folder_for,
    require_month,
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
    assert r == {"order_path": "", "refs_path": "", "assets_root": "",
                 "month": ""}


def test_resolve_reports_one_canonical_month_per_order(project):
    """Every alias of a month resolves to the same canonical name — what the
    order template pool keys its folder off."""
    names = {resolve_month(str(project), alias)["month"]
             for alias in ("", "october", "October", "Bakery October Art.xlsx")}
    assert names == {"october"}


def test_require_month_refuses_an_order_the_project_does_not_hold(project):
    """A named month that matches nothing is a stale request, not a blank one —
    resolve_month answers it with October, which renders the wrong sheet and
    reports success."""
    with pytest.raises(MonthNotFound) as e:
        require_month(str(project), "december")
    assert "december" in str(e.value)
    assert "October" in str(e.value) and "November" in str(e.value)


def test_require_month_blank_still_takes_the_first_order(project):
    """"" means "whichever this project has" — the fallback IS the answer."""
    r = require_month(str(project), "")
    assert os.path.basename(r["order_path"]) == "Bakery October Art.xlsx"


@pytest.mark.parametrize("alias", ["october", "October", "OCTOBER",
                                  "Bakery October Art.xlsx", " october "])
def test_require_month_accepts_every_alias_resolve_month_does(project, alias):
    """Admitting fewer aliases than resolve_month matches on would refuse a
    correct resolution."""
    assert require_month(str(project), alias)["month"] == "october"


def test_require_month_accepts_a_monthless_order_by_its_label(tmp_path):
    """An order whose filename carries no month is labelled by its stem, and
    that label is the only name a caller can ask for it by."""
    orders = tmp_path / "orders"
    orders.mkdir()
    (orders / "SpecialDrop.xlsx").write_bytes(b"x")
    r = require_month(str(tmp_path), "SpecialDrop")
    assert os.path.basename(r["order_path"]) == "SpecialDrop.xlsx"


def test_require_month_leaves_an_orderless_project_to_its_own_error(tmp_path):
    """Nothing was substituted — there was nothing to substitute. The caller's
    "no order file" message is the useful one here, so don't pre-empt it."""
    assert require_month(str(tmp_path), "december") == {
        "order_path": "", "refs_path": "", "assets_root": "", "month": ""}


def test_refs_folder_falls_back_to_name_overlap(tmp_path):
    orders = tmp_path / "orders"
    orders.mkdir()
    (orders / "SpecialDrop.xlsx").write_bytes(b"x")
    (orders / "SpecialDrop").mkdir()
    got = refs_folder_for(str(orders), "SpecialDrop.xlsx")
    assert os.path.basename(got) == "SpecialDrop"
