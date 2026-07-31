# ABOUTME: Tests that browse routes taking a project/path param accept the
# ABOUTME: volume-relative studios/<slug>/... currency the Studio Library emits.
import asyncio
import importlib
import json
import sys
import types
from types import SimpleNamespace

import pytest

from conftest import inline_cell, make_xlsx, sheet_of_rows


class _Routes:
    def get(self, path):
        def deco(fn):
            return fn
        return deco
    post = get


def _order_xlsx() -> bytes:
    header = "".join(
        inline_cell(f"{col}1", text)
        for col, text in zip("ABCDEFG", ["Feature", "Event Name", "Asset Name",
                                         "ID", "Asset Category", "Canvas", "Prompt"])
    )
    row2 = "".join(
        inline_cell(f"{col}2", text)
        for col, text in zip("ABCDEFG", ["Mini 1", "Ghostly Goodies", "Bat Croissants",
                                         "1", "Food - 3 stages", "128x128", "spooky bread"])
    )
    return make_xlsx(sheet_of_rows(header, row2))


@pytest.fixture()
def volume(tmp_path):
    """A studio-assets Volume with one project folder the Studio Library node
    would emit as studios/imperia/bakery."""
    project = tmp_path / "studios" / "imperia" / "bakery"
    (project / "orders").mkdir(parents=True)
    (project / "orders" / "Bakery October Art.xlsx").write_bytes(_order_xlsx())
    (project / "templates").mkdir()
    (project / "refs").mkdir()
    (project / "refs" / "hero.png").write_bytes(b"x")
    return tmp_path


@pytest.fixture()
def routes_mod(monkeypatch, volume):
    captured = {}

    def json_response(body, status=200):
        captured.clear()
        captured.update(body=body, status=status)
        return SimpleNamespace(body=body, status=status)

    server = SimpleNamespace(instance=SimpleNamespace(routes=_Routes()))
    monkeypatch.setitem(sys.modules, "server", SimpleNamespace(PromptServer=server))
    fake_web = types.ModuleType("aiohttp.web")
    fake_web.json_response = json_response
    fake_web.FileResponse = lambda *a, **k: None
    fake_aiohttp = types.ModuleType("aiohttp")
    fake_aiohttp.web = fake_web
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)
    monkeypatch.setitem(sys.modules, "aiohttp.web", fake_web)
    from pipeline import routes as mod
    importlib.reload(mod)
    monkeypatch.setattr(mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(volume))
    mod._captured = captured
    return mod


def _req(**query):
    return SimpleNamespace(query=query)


class _Body:
    """A POST request whose json() resolves to the given dict."""

    def __init__(self, body):
        self._body = body

    async def json(self):
        return self._body


def test_list_orders_accepts_volume_relative_project(routes_mod):
    asyncio.run(routes_mod.list_orders(_req(project="studios/imperia/bakery")))
    months = routes_mod._captured["body"]["months"]
    assert [m["label"] for m in months] == ["October"]


def test_list_orders_absolute_and_bogus_still_behave(routes_mod, volume):
    asyncio.run(routes_mod.list_orders(
        _req(project=str(volume / "studios" / "imperia" / "bakery"))))
    assert [m["label"] for m in routes_mod._captured["body"]["months"]] == ["October"]
    asyncio.run(routes_mod.list_orders(_req(project="studios/imperia/nope")))
    assert routes_mod._captured["body"] == {"months": []}


def test_parse_order_accepts_volume_relative_project(routes_mod):
    asyncio.run(routes_mod.parse_order(
        _req(project="studios/imperia/bakery", month="October")))
    body = routes_mod._captured["body"]
    assert routes_mod._captured["status"] == 200
    assert [e["eventName"] for e in body["events"]] == ["Ghostly Goodies"]


def test_list_assets_accepts_volume_relative_dir(routes_mod, volume):
    asyncio.run(routes_mod.list_assets(_req(dir="studios/imperia/bakery/refs")))
    body = routes_mod._captured["body"]
    assert routes_mod._captured["status"] == 200
    assert body["root"] == str((volume / "studios" / "imperia" / "bakery" / "refs").resolve())
    assert [i["rel"] for i in body["images"]] == ["hero.png"]


def test_pack_template_list_accepts_volume_relative_project(routes_mod, volume):
    """The reference pool of a volume-relative project resolves to its absolute
    <project>/templates/reference — the universal, month-free pool."""
    asyncio.run(routes_mod.pack_template_list(
        _req(project="studios/imperia/bakery", kind="reference")))
    body = routes_mod._captured["body"]
    project = (volume / "studios" / "imperia" / "bakery").resolve()
    assert body["dir"] == str(project / "templates" / "reference")
    assert str(project / "templates" / "reference") in body["dirs"]


def test_pack_template_list_order_kind_browses_the_month(routes_mod, volume):
    """Order templates live beside the month's order — inside that month's
    client-refs folder, not in the project-level pool."""
    project = (volume / "studios" / "imperia" / "bakery").resolve()
    (project / "orders" / "Bakery-October").mkdir()
    asyncio.run(routes_mod.pack_template_list(
        _req(project="studios/imperia/bakery", kind="order", month="October")))
    body = routes_mod._captured["body"]
    assert body["dir"] == str(project / "orders" / "Bakery-October" / "templates")


def test_pack_template_delete_reaches_a_pre_split_template(routes_mod, volume):
    """A template saved before the split sits in the flat <project>/templates
    but lists with an inferred kind — the delete must still find it, or its row
    can never be removed from the browser."""
    project = (volume / "studios" / "imperia" / "bakery").resolve()
    flat = project / "templates" / "old-food"
    flat.mkdir(parents=True)
    (flat / "template.json").write_text(json.dumps(
        {"name": "old-food", "sheets": [],
         "order": {"month": "October", "feature": "Mini 1"}}))
    asyncio.run(routes_mod.pack_template_delete(_Body(
        {"project": "studios/imperia/bakery", "name": "order/old-food",
         "kind": "order", "month": "October"})))
    assert routes_mod._captured["body"] == {"ok": True, "removed": True}
    assert not flat.exists()


def test_pack_template_delete_still_spares_the_other_pool(routes_mod, volume):
    project = (volume / "studios" / "imperia" / "bakery").resolve()
    for kind, path in (("order", project / "orders" / "Bakery-October"
                        / "templates" / "food"),
                       ("reference", project / "templates" / "reference"
                        / "food")):
        path.mkdir(parents=True)
        (path / "template.json").write_text(json.dumps(
            {"name": "food", "sheets": [], "kind": kind, "order": {}}))
    asyncio.run(routes_mod.pack_template_delete(_Body(
        {"project": "studios/imperia/bakery", "name": "order/food",
         "kind": "order", "month": "October"})))
    assert routes_mod._captured["body"]["removed"] is True
    assert (project / "templates" / "reference" / "food").is_dir()


def test_pack_template_list_order_kind_without_refs_folder(routes_mod, volume):
    """No client-refs folder for the month → still month-scoped, under the
    project's templates/orders/<month>, never the reference pool."""
    project = (volume / "studios" / "imperia" / "bakery").resolve()
    asyncio.run(routes_mod.pack_template_list(
        _req(project="studios/imperia/bakery", kind="order", month="October")))
    body = routes_mod._captured["body"]
    assert body["dir"] == str(project / "templates" / "orders" / "october")
