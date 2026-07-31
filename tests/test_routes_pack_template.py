# ABOUTME: Tests that pack-template deletion stays inside a declared root and that
# ABOUTME: a volume-relative project resolves the same way it does for the list route.
import importlib
import sys
import types


def _load_routes(monkeypatch):
    """Import routes.py with a stubbed `server` module (no ComfyUI needed)."""
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


def _template_tree(project):
    """A saved template folder as delete_pack_template would find it."""
    d = project / "templates" / "my-template"
    d.mkdir(parents=True)
    (d / "sheet.png").write_bytes(b"x")
    return d


class TestDeletionStaysInsideARoot:
    def test_a_project_outside_every_root_is_not_deleted(self, tmp_path, monkeypatch):
        # The name is slugified and realpath-guarded, so traversal via the NAME
        # is already closed — the parent directory is what was unguarded.
        routes = _load_routes(monkeypatch)
        monkeypatch.setattr(routes, "_template_dir", lambda: None)
        victim_project = tmp_path / "somebody-elses-tree"
        victim = _template_tree(victim_project)

        routes.delete_pack_template_dirs(
            routes._pack_dirs(str(victim_project)), "My Template")

        assert victim.exists(), "deleted a template under an unregistered project"

    def test_a_registered_project_still_deletes(self, tmp_path, monkeypatch):
        # A project a graph execution registered is a legitimate target: the
        # canvas must keep being able to delete its own saved templates.
        routes = _load_routes(monkeypatch)
        monkeypatch.setattr(routes, "_template_dir", lambda: None)
        project = tmp_path / "my-project"
        target = _template_tree(project)
        routes.register_root(str(project))

        routes.delete_pack_template_dirs(
            routes._pack_dirs(str(project)), "My Template")

        assert not target.exists(), "a registered project's template was not deleted"


class TestVolumeRelativeProject:
    def test_delete_expands_a_studios_project_like_list_does(self, tmp_path, monkeypatch):
        # pack-template-list expands studios/<slug> but delete did not, so a
        # studio-filed template resolved against the process CWD and could never
        # be removed. Both routes must resolve a project the same way.
        routes = _load_routes(monkeypatch)
        monkeypatch.setattr(routes, "_template_dir", lambda: None)
        volume = tmp_path / "studio-assets"
        project = volume / "studios" / "acme" / "proj"
        target = _template_tree(project)
        monkeypatch.setattr(routes.studio_library_mod, "STUDIO_ASSETS_DIR", str(volume))
        routes.register_root(str(project))

        routes.pack_dirs_for_project("studios/acme/proj")
        routes.delete_pack_template_dirs(
            routes.pack_dirs_for_project("studios/acme/proj"), "My Template")

        assert not target.exists(), "a volume-relative project was not resolved"
