# ABOUTME: Tests that browse routes taking a project/path param accept the
# ABOUTME: volume-relative studios/<slug>/... currency the Studio Library emits.
import asyncio
import importlib
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
    asyncio.run(routes_mod.pack_template_list(_req(project="studios/imperia/bakery")))
    body = routes_mod._captured["body"]
    assert body["dir"] == str(
        (volume / "studios" / "imperia" / "bakery" / "templates").resolve())
