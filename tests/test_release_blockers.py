# ABOUTME: Regressions for the path-trust defects the release preflight caught —
# ABOUTME: only a real project vouches, and a vouched one is fully usable.
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


class TestTheNodeVouchesForItsProject:
    """The route side can only trust a project an execution named, so the node
    must actually name it — otherwise its own thumbnails stop loading."""

    def test_executing_with_a_project_registers_it(self, tmp_path, monkeypatch):
        sys.path.insert(0, os.path.dirname(__file__))
        from comfy_api_stub import build_modules
        pkg, latest = build_modules()
        monkeypatch.setitem(sys.modules, "comfy_api", pkg)
        monkeypatch.setitem(sys.modules, "comfy_api.latest", latest)
        monkeypatch.setitem(sys.modules, "folder_paths",
                            types.ModuleType("folder_paths"))
        sys.modules.pop("pipeline.nodes", None)
        import pipeline.nodes as nodes
        importlib.reload(nodes)
        seen = []
        monkeypatch.setattr(nodes, "_register_project", lambda p: seen.append(p))
        monkeypatch.setattr(nodes, "_register_refs_root", lambda p: None)
        project = tmp_path / "my-game"
        (project / "orders").mkdir(parents=True)
        try:
            nodes.build_event_order(str(project), "October", "")
        except Exception:
            pass  # reading the order needs a real .xlsx; the vouch is the point
        assert str(project) in seen, "an execution did not vouch for its project"
        sys.modules.pop("pipeline.nodes", None)


class TestAVouchedProjectIsFullyUsable:
    """Vouching for a project is no use if the folders under it cannot be
    served — the browse registration gates on the same root set."""

    def test_its_thumbnails_can_be_served(self, tmp_path, monkeypatch):
        routes = _load_routes(monkeypatch)
        monkeypatch.setattr(routes, "_template_dir", lambda: None)
        monkeypatch.setattr(routes, "_operator_roots", lambda: [])
        project = tmp_path / "my-game"
        refs = project / "reference-assets" / "October"
        refs.mkdir(parents=True)
        routes.register_project(str(project))

        assert routes.register_root_within(str(refs)) is True, (
            "a vouched project's own references folder is not servable")


class TestAnAncestorIsNotAProject:
    """A declared root can be shallow (ComfyUI's own output dir). Trusting any
    ancestor of a root would hand the home directory, or /, to the browse."""

    def test_naming_an_ancestor_of_a_declared_root_is_refused(self, tmp_path,
                                                              monkeypatch):
        routes = _load_routes(monkeypatch)
        home = tmp_path / "someone"
        comfy_out = home / "ComfyUI" / "output"
        comfy_out.mkdir(parents=True)
        (home / "private-work").mkdir()
        monkeypatch.setattr(routes, "_template_dir", lambda: None)
        monkeypatch.setattr(routes, "_operator_roots", lambda: [])
        monkeypatch.setattr(routes, "declared_roots", lambda: [str(comfy_out)])

        assert routes.register_root_within(str(home / "private-work")) is False, (
            "reached a sibling tree by naming an ancestor of a declared root")


class TestTheOperatorSettingIsReal:
    """The escape hatch is the only way a project outside ComfyUI's own folders
    becomes usable, so the code path that reads it must actually work."""

    def test_the_env_var_is_read(self, tmp_path, monkeypatch):
        routes = _load_routes(monkeypatch)
        a, b = tmp_path / "art", tmp_path / "more art"
        a.mkdir(), b.mkdir()
        monkeypatch.setenv(routes.ASSET_ROOTS_ENV, f"{a}, {b}")
        got = routes._operator_roots()
        assert str(a) in got and str(b) in got

    def test_a_project_named_by_the_env_var_is_admitted(self, tmp_path,
                                                        monkeypatch):
        routes = _load_routes(monkeypatch)
        monkeypatch.setattr(routes, "_template_dir", lambda: None)
        project = tmp_path / "my-game"
        (project / "reference-assets").mkdir(parents=True)
        monkeypatch.setenv(routes.ASSET_ROOTS_ENV, str(project))
        assert routes.register_root_within(
            str(project / "reference-assets")) is True


class TestOnlyARealProjectRegisters:
    """os.path.realpath("") is the process CWD, so an empty project widget — the
    default, and the case that raises — silently trusted ComfyUI's own working
    directory."""

    def test_an_empty_project_registers_nothing(self, monkeypatch):
        routes = _load_routes(monkeypatch)
        routes.register_project("")
        assert os.path.realpath(os.getcwd()) not in routes._projects, (
            "an empty project string trusted the working directory")

    def test_a_relative_project_registers_nothing(self, monkeypatch):
        routes = _load_routes(monkeypatch)
        routes.register_project("some/relative/path")
        assert not routes._projects, "a relative path was resolved against the CWD"

    def test_a_real_project_still_registers(self, tmp_path, monkeypatch):
        routes = _load_routes(monkeypatch)
        routes.register_project(str(tmp_path))
        assert os.path.realpath(str(tmp_path)) in routes._projects
