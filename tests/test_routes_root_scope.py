# ABOUTME: Tests that only a declared root becomes servable — a request cannot put
# ABOUTME: its own folder on the allowlist, and an operator can declare extra roots.
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
    web.json_response = lambda *a, **k: None
    web.FileResponse = lambda *a, **k: None
    sys.modules["aiohttp"].web = web
    monkeypatch.setitem(sys.modules, "aiohttp.web", web)
    import pipeline.routes as routes
    importlib.reload(routes)
    return routes


def _image(d, name="a.png"):
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_bytes(b"x")
    return f


class TestARequestCannotTrustItsOwnFolder:
    def test_an_undeclared_folder_does_not_become_servable(self, tmp_path, monkeypatch):
        # This is the escalation the audit found: browsing a folder was what put
        # it on the allowlist, so one request made any image under it readable.
        routes = _load_routes(monkeypatch)
        monkeypatch.setattr(routes, "declared_roots", lambda: [])
        stray = tmp_path / "somebody-elses-tree"
        img = _image(stray)

        assert routes.register_root_within(str(stray)) is False
        assert routes.is_allowed(str(img)) is None

    def test_a_folder_inside_a_declared_root_still_becomes_servable(self, tmp_path, monkeypatch):
        # Browse-before-run must keep working for legitimate assets.
        routes = _load_routes(monkeypatch)
        trusted = tmp_path / "trusted"
        trusted.mkdir()
        monkeypatch.setattr(routes, "declared_roots", lambda: [str(trusted)])
        sub = trusted / "project" / "refs"
        img = _image(sub)

        assert routes.register_root_within(str(sub)) is True
        assert routes.is_allowed(str(img)) == str(img.resolve())


class TestOperatorDeclaredRoots:
    def test_an_operator_root_from_settings_is_trusted(self, tmp_path, monkeypatch):
        routes = _load_routes(monkeypatch)
        mine = tmp_path / "my-game-art"
        img = _image(mine)
        monkeypatch.setattr(routes, "_operator_roots", lambda: [str(mine)])
        monkeypatch.setattr(routes, "_template_dir", lambda: None)
        monkeypatch.setattr(routes.studio_library_mod, "STUDIO_ASSETS_DIR", "")

        assert routes.register_root_within(str(mine)) is True
        assert routes.is_allowed(str(img)) == str(img.resolve())

    def test_a_folder_outside_every_operator_root_is_refused(self, tmp_path, monkeypatch):
        routes = _load_routes(monkeypatch)
        mine = tmp_path / "my-game-art"
        mine.mkdir()
        elsewhere = tmp_path / "elsewhere"
        _image(elsewhere)
        monkeypatch.setattr(routes, "_operator_roots", lambda: [str(mine)])
        monkeypatch.setattr(routes, "_template_dir", lambda: None)
        monkeypatch.setattr(routes.studio_library_mod, "STUDIO_ASSETS_DIR", "")

        assert routes.register_root_within(str(elsewhere)) is False


class TestParseRoots:
    def test_separators_and_blanks(self):
        from pipeline.paths import parse_roots
        assert parse_roots("/a\n/b, /c ; /d") == ["/a", "/b", "/c", "/d"]
        assert parse_roots("  ") == []
        assert parse_roots(None) == []

    def test_relative_entries_are_dropped(self):
        from pipeline.paths import parse_roots
        assert parse_roots("/abs, relative/path") == ["/abs"]


class TestGraphExecutionStillRegisters:
    def test_a_node_execution_root_is_unconditional(self, tmp_path, monkeypatch):
        # A path the user typed into the graph and ran is intent, not a request —
        # register_root keeps its meaning so nodes are unaffected.
        routes = _load_routes(monkeypatch)
        monkeypatch.setattr(routes, "declared_roots", lambda: [])
        d = tmp_path / "typed-into-the-graph"
        img = _image(d)
        routes.register_root(str(d))
        assert routes.is_allowed(str(img)) == str(img.resolve())
