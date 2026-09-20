# ABOUTME: Tests that the remaining path-taking routes refuse a target outside every
# ABOUTME: declared root instead of reading or enumerating it.
import importlib
import sys
import types

from conftest import inline_cell, make_xlsx, sheet_of_rows


def _project(tmp_path):
    """A client project laid out the way the node reads one: an orders/ folder
    with a month's xlsx in it, and nothing declaring any of it."""
    orders = tmp_path / "imperia-bakery" / "orders"
    orders.mkdir(parents=True)
    columns = ["Feature", "Event Name", "Asset Name", "ID", "Asset Category",
               "Canvas", "Prompt"]
    row = ["Mini 1", "Ghostly Goodies", "Bat Croissants", "1",
           "Food - 3 stages", "128x128", "spooky bread"]
    (orders / "Bakery October Art.xlsx").write_bytes(make_xlsx(sheet_of_rows(
        "".join(inline_cell(f"{c}1", t) for c, t in zip("ABCDEFG", columns)),
        "".join(inline_cell(f"{c}2", t) for c, t in zip("ABCDEFG", row)))))
    return orders.parent


def _load_routes(monkeypatch):
    fake_server = types.ModuleType("server")

    class _Routes:
        def get(self, _path):
            def deco(fn):
                return fn
            return deco

        post = get

    fake_server.PromptServer = types.SimpleNamespace(
        instance=types.SimpleNamespace(routes=_Routes()))
    monkeypatch.setitem(sys.modules, "server", fake_server)
    monkeypatch.setitem(sys.modules, "aiohttp", types.ModuleType("aiohttp"))
    web = types.ModuleType("aiohttp.web")
    web.json_response = lambda body, status=200: {"body": body, "status": status}
    web.FileResponse = lambda *a, **k: None
    sys.modules["aiohttp"].web = web
    monkeypatch.setitem(sys.modules, "aiohttp.web", web)
    import pipeline.routes as routes
    importlib.reload(routes)
    return routes


class _Req:
    def __init__(self, **query):
        self.query = query


def _run(coro):
    import asyncio
    return asyncio.run(coro)


class TestParseOrder:
    def test_an_order_file_outside_every_root_is_refused(self, tmp_path, monkeypatch):
        # The handler read any absolute path and, for any zip container, parsed
        # and returned its contents.
        routes = _load_routes(monkeypatch)
        monkeypatch.setattr(routes, "declared_roots", lambda: [])
        secret = tmp_path / "secret.xlsx"
        secret.write_bytes(b"PK\x03\x04rest")

        res = _run(routes.parse_order(_Req(order_path=str(secret))))
        assert res["status"] == 403, "read an order file outside every declared root"

    def test_a_refs_dir_outside_every_root_is_refused(self, tmp_path, monkeypatch):
        routes = _load_routes(monkeypatch)
        trusted = tmp_path / "trusted"
        trusted.mkdir()
        order = trusted / "o.xlsx"
        order.write_bytes(b"PK\x03\x04rest")
        stray = tmp_path / "stray-refs"
        stray.mkdir()
        monkeypatch.setattr(routes, "declared_roots", lambda: [str(trusted)])

        res = _run(routes.parse_order(_Req(order_path=str(order),
                                           refs_path=str(stray))))
        assert res["status"] == 403, "accepted a refs dir outside every declared root"

    def test_a_project_nothing_declared_is_read_rather_than_refused(
            self, tmp_path, monkeypatch):
        """"the node should browse the files from the path i input regardless
        of whether i am on modal, local, etc" — the folder he typed IS the
        project. Queueing a node with it already registered it; the panel asks
        before the graph has ever run, and the 403 was cached as the final
        answer for the rest of the session."""
        routes = _load_routes(monkeypatch)
        project = _project(tmp_path)
        order = project / "orders" / "Bakery October Art.xlsx"
        assert routes.resolve_within(routes.declared_roots(), str(order),
                                     kind="file") is None

        res = _run(routes.parse_order(_Req(project=str(project))))
        assert res["status"] == 200, res["body"]
        assert [e["feature"] for e in res["body"]["events"]] == ["Mini 1"]

    def test_an_order_file_outside_the_named_project_is_still_refused(
            self, tmp_path, monkeypatch):
        """Naming a project is not naming the machine. What a request may touch
        is CONTAINMENT: every path is derived from that folder, and one the
        request names for itself is checked against it."""
        routes = _load_routes(monkeypatch)
        project = _project(tmp_path)
        secret = tmp_path / "secret.xlsx"
        secret.write_bytes(b"PK\x03\x04rest")

        res = _run(routes.parse_order(_Req(project=str(project),
                                           order_path=str(secret))))
        assert res["status"] == 403, "read an order file outside the project"
