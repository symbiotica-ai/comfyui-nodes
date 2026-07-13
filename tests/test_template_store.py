# ABOUTME: Tests for the template editor's save/list helpers in routes.py —
# ABOUTME: slugged filenames, sidecar merging, and tolerant listing.
import importlib
import json
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


def test_write_template_slugs_name_and_writes_pair(tmp_path, monkeypatch):
    routes = _load_routes(monkeypatch)
    out = tmp_path / "templates"
    rel = routes.write_template(str(out), "Mini 08!", b"\x89PNGdata",
                                {"size": {"w": 4, "h": 2}})
    assert rel == "templates/mini-08.png"
    assert (out / "mini-08.png").read_bytes() == b"\x89PNGdata"
    sidecar = json.loads((out / "mini-08.json").read_text())
    assert sidecar["name"] == "mini-08"


def test_write_template_sidecar_merges_fields(tmp_path, monkeypatch):
    routes = _load_routes(monkeypatch)
    rel = routes.write_template(
        str(tmp_path), "hero",
        b"png",
        {"size": {"w": 8, "h": 8}, "spriteCount": 2,
         "regions": [{"id": "r1"}, {"id": "r2"}],
         "settings": {"background": "#808080"},
         "scenePrompt": "moody forest"})
    assert rel == "templates/hero.png"
    sidecar = json.loads((tmp_path / "hero.json").read_text())
    assert sidecar == {
        "name": "hero",
        "size": {"w": 8, "h": 8},
        "spriteCount": 2,
        "regions": [{"id": "r1"}, {"id": "r2"}],
        "settings": {"background": "#808080"},
        "scenePrompt": "moody forest",
    }


def test_write_template_unsluggable_name_falls_back(tmp_path, monkeypatch):
    routes = _load_routes(monkeypatch)
    rel = routes.write_template(str(tmp_path), "!!!", b"png", {})
    assert rel == "templates/template.png"


def test_list_templates_sorted_and_skips_corrupt(tmp_path, monkeypatch):
    routes = _load_routes(monkeypatch)
    routes.write_template(str(tmp_path), "zeta", b"png", {"spriteCount": 1})
    routes.write_template(str(tmp_path), "alpha", b"png", {"spriteCount": 3})
    (tmp_path / "broken.json").write_text("{not json")

    got = routes.list_templates(str(tmp_path))
    assert [t["name"] for t in got] == ["alpha", "zeta"]
    assert got[0]["file"] == "templates/alpha.png"
    assert got[1]["file"] == "templates/zeta.png"
    assert got[0]["spriteCount"] == 3


def test_list_templates_missing_dir(tmp_path, monkeypatch):
    routes = _load_routes(monkeypatch)
    assert routes.list_templates(str(tmp_path / "nope")) == []
    assert routes.list_templates(None) == []
