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

    assert not routes.is_allowed(str(root / "a.png"))  # nothing registered yet
    routes.register_root(str(root))
    assert routes.is_allowed(str(root / "a.png"))
    assert not routes.is_allowed(str(outside))
    # Traversal out of the root is rejected on the resolved path.
    assert not routes.is_allowed(str(root / ".." / "secret.png"))
    # Non-image extensions rejected even under the root.
    (root / "b.txt").write_bytes(b"x")
    assert not routes.is_allowed(str(root / "b.txt"))
