# ABOUTME: Tests that the remaining path-taking routes refuse a target outside every
# ABOUTME: declared root instead of reading or enumerating it.
import importlib
import sys
import types

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


class TestListAssets:
    def test_a_directory_outside_every_root_is_refused(self, tmp_path, monkeypatch):
        routes = _load_routes(monkeypatch)
        monkeypatch.setattr(routes, "declared_roots", lambda: [])
        stray = tmp_path / "somebody-elses-tree"
        stray.mkdir()
        (stray / "a.png").write_bytes(b"x")

        res = _run(routes.list_assets(_Req(dir=str(stray))))
        assert res["status"] == 403, "scanned a directory outside every declared root"

    def test_a_directory_inside_a_root_is_scanned(self, tmp_path, monkeypatch):
        routes = _load_routes(monkeypatch)
        trusted = tmp_path / "trusted"
        (trusted / "refs").mkdir(parents=True)
        (trusted / "refs" / "a.png").write_bytes(b"x")
        monkeypatch.setattr(routes, "declared_roots", lambda: [str(trusted)])

        res = _run(routes.list_assets(_Req(dir=str(trusted / "refs"))))
        assert res["status"] == 200


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
