# ABOUTME: Regressions for the four defects the release preflight caught — an ordinary
# ABOUTME: project must work, an undeclared one must not be touched, and a pool is not a template.
import importlib
import os
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


def _template(base, name, kind=""):
    """A saved template folder as pack_library writes it: a dir plus its sidecar."""
    import json
    d = os.path.join(base, name)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "sheet.png"), "wb").close()
    with open(os.path.join(d, "template.json"), "w") as f:
        json.dump({"name": name, "kind": kind}, f)
    return d


class TestAnOrdinaryProjectWorks:
    """The release blocker: containment was checked against the project, but every
    root a graph execution registers is a SUBdirectory of it, so no real project
    could ever satisfy it and the Library silently listed nothing."""

    def test_a_project_whose_pool_was_registered_is_visible(self, tmp_path, monkeypatch):
        routes = _load_routes(monkeypatch)
        out = tmp_path / "output" / "templates"
        out.mkdir(parents=True)
        monkeypatch.setattr(routes, "_template_dir", lambda: str(out))
        project = tmp_path / "my-game"
        pool = project / "templates"
        pool.mkdir(parents=True)
        _template(str(pool), "my-template")
        # What a node execution actually registers: the pool, not the project.
        routes.register_root(str(pool))

        dirs = routes._pack_dirs(str(project), "", "")
        assert any(str(project) in d for d in dirs), (
            "an ordinary project's own pool is invisible to the Library")

    def test_the_operator_setting_admits_a_project(self, tmp_path, monkeypatch):
        # SYMBIOTICA_ASSET_ROOTS is the documented escape hatch; it must reach
        # these routes, not only the browse ones.
        routes = _load_routes(monkeypatch)
        monkeypatch.setattr(routes, "_template_dir", lambda: None)
        project = tmp_path / "my-game"
        (project / "templates").mkdir(parents=True)
        monkeypatch.setattr(routes, "_operator_roots", lambda: [str(project)])

        dirs = routes._pack_dirs(str(project), "", "")
        assert any(str(project) in d for d in dirs), (
            "SYMBIOTICA_ASSET_ROOTS does not admit a project for the pack routes")


class TestAnUndeclaredProjectIsUntouched:
    def test_its_pools_are_not_returned(self, tmp_path, monkeypatch):
        routes = _load_routes(monkeypatch)
        monkeypatch.setattr(routes, "_template_dir", lambda: None)
        monkeypatch.setattr(routes, "_operator_roots", lambda: [])
        stray = tmp_path / "somebody-elses-tree"
        _template(str(stray / "templates"), "theirs")

        dirs = routes._pack_dirs(str(stray), "", "")
        assert not any(str(stray) in d for d in dirs), "returned an undeclared project's pool"

    def test_the_list_route_does_not_enumerate_it(self, tmp_path, monkeypatch):
        # The route computed `dir` from the UNCONTAINED project, so save_dirs
        # walked the tree and echoed back a real folder name it found there.
        routes = _load_routes(monkeypatch)
        monkeypatch.setattr(routes, "_template_dir", lambda: None)
        monkeypatch.setattr(routes, "_operator_roots", lambda: [])
        stray = tmp_path / "somebody-elses-tree"
        (stray / "orders" / "Bakery-October").mkdir(parents=True)

        seen = []
        real_listdir = os.listdir
        monkeypatch.setattr(os, "listdir", lambda p: (seen.append(str(p)), real_listdir(p))[1])
        res = _run(routes.pack_template_list(_Req(project=str(stray))))

        assert not any(str(stray) in p for p in seen), (
            f"enumerated an undeclared tree: {[p for p in seen if str(stray) in p][:3]}")
        assert "Bakery-October" not in str(res["body"]), (
            "leaked a directory name discovered on disk")


class TestAPoolIsNotATemplate:
    def test_an_unqualified_name_cannot_delete_a_whole_pool(self, tmp_path):
        # pack_dirs returns the bare templates dir as a delete base, and the
        # pools live inside it — so "reference" as a name targeted the pool.
        from pipeline.pack_library import delete_pack_template_dirs
        base = tmp_path / "templates"
        _template(str(base / "reference"), "keep-me")

        delete_pack_template_dirs([str(base)], "reference")

        assert (base / "reference").is_dir(), "one request deleted an entire pool"

    def test_a_real_template_still_deletes(self, tmp_path):
        from pipeline.pack_library import delete_pack_template_dirs
        base = tmp_path / "templates"
        target = _template(str(base), "my-template")

        assert delete_pack_template_dirs([str(base)], "my-template") is True
        assert not os.path.isdir(target)
