# ABOUTME: Tests for the local-image route's path allowlist — only image files
# ABOUTME: under explicitly registered roots may be served.
import importlib
import os
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


def test_allowlist(tmp_path, monkeypatch):
    routes = _load_routes(monkeypatch)
    root = tmp_path / "refs"
    root.mkdir()
    (root / "a.png").write_bytes(b"x")
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"x")

    assert routes.is_allowed(str(root / "a.png")) is None  # nothing registered yet
    routes.register_root(str(root))
    # Allowed paths come back as the RESOLVED realpath the handler must serve.
    assert routes.is_allowed(str(root / "a.png")) == os.path.realpath(
        str(root / "a.png"))
    assert routes.is_allowed(str(outside)) is None
    # Traversal out of the root is rejected on the resolved path.
    assert routes.is_allowed(str(root / ".." / "secret.png")) is None
    # Non-image extensions rejected even under the root.
    (root / "b.txt").write_bytes(b"x")
    assert routes.is_allowed(str(root / "b.txt")) is None


def test_prefix_collision_sibling_root_rejected(tmp_path, monkeypatch):
    routes = _load_routes(monkeypatch)
    root = tmp_path / "refs"
    root.mkdir()
    evil = tmp_path / "refs-evil"
    evil.mkdir()
    (evil / "x.png").write_bytes(b"x")

    routes.register_root(str(root))
    assert routes.is_allowed(str(evil / "x.png")) is None


def test_symlink_escape_rejected(tmp_path, monkeypatch):
    routes = _load_routes(monkeypatch)
    root = tmp_path / "refs"
    root.mkdir()
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"x")
    link = root / "link.png"
    os.symlink(str(outside), str(link))

    routes.register_root(str(root))
    # The symlink lives under the root but resolves outside it.
    assert routes.is_allowed(str(link)) is None


def test_null_byte_denied_without_exception(tmp_path, monkeypatch):
    routes = _load_routes(monkeypatch)
    root = tmp_path / "refs"
    root.mkdir()
    routes.register_root(str(root))

    assert routes.is_allowed(str(root) + "/a\x00.png") is None


def test_list_subdirs(tmp_path, monkeypatch):
    routes = _load_routes(monkeypatch)
    (tmp_path / "Beta").mkdir()
    (tmp_path / "alpha").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "file.txt").write_bytes(b"x")
    info = routes.list_subdirs(str(tmp_path))
    assert info["path"] == str(tmp_path.resolve())
    assert info["dirs"] == ["alpha", "Beta"]  # case-insensitive sort, no dotdirs
    assert info["parent"] == str(tmp_path.resolve().parent)


def test_list_subdirs_bad_paths(tmp_path, monkeypatch):
    routes = _load_routes(monkeypatch)
    assert routes.list_subdirs(str(tmp_path / "nope")) is None
    f = tmp_path / "f.txt"
    f.write_bytes(b"x")
    assert routes.list_subdirs(str(f)) is None
    assert routes.list_subdirs("bad\x00path") is None


def test_list_subdirs_default_is_home(monkeypatch):
    routes = _load_routes(monkeypatch)
    import os
    info = routes.list_subdirs("")
    assert info is not None
    assert info["path"] == os.path.realpath(os.path.expanduser("~"))
