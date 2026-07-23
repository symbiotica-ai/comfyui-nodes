# ABOUTME: Tests for the /symbiotica/studio-library route — a capturing
# ABOUTME: json_response stub + asyncio.run assert real payloads and statuses.
import asyncio
import importlib
import sys
from types import SimpleNamespace

import pytest


class _Routes:
    def get(self, path):
        def deco(fn):
            return fn
        return deco
    post = get


def _touch(path, data=b"x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture()
def routes_mod(monkeypatch):
    captured = {}

    def json_response(body, status=200):
        captured.clear()
        captured.update(body=body, status=status)
        return SimpleNamespace(body=body, status=status)

    server = SimpleNamespace(instance=SimpleNamespace(routes=_Routes()))
    monkeypatch.setitem(sys.modules, "server", SimpleNamespace(PromptServer=server))
    from aiohttp import web
    monkeypatch.setattr(web, "json_response", json_response)
    from pipeline import routes as mod
    importlib.reload(mod)
    mod._captured = captured  # expose for assertions
    return mod


def _req(**query):
    return SimpleNamespace(query=query)


def test_no_canvas_studio_returns_503(routes_mod, monkeypatch, tmp_path):
    monkeypatch.delenv("CANVAS_STUDIO", raising=False)
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    asyncio.run(routes_mod.studio_library(_req()))
    assert routes_mod._captured["status"] == 503
    assert "error" in routes_mod._captured["body"]


def test_real_tree_returns_entries(routes_mod, monkeypatch, tmp_path):
    _touch(tmp_path / "studios" / "ggs" / "references" / "hero.png", b"1234")
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    asyncio.run(routes_mod.studio_library(_req(dir="studios/ggs/references")))
    assert routes_mod._captured["status"] == 200
    names = [e["name"] for e in routes_mod._captured["body"]["entries"]]
    assert "hero.png" in names


def test_escaping_dir_returns_400(routes_mod, monkeypatch, tmp_path):
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    asyncio.run(routes_mod.studio_library(_req(dir="studios/ggs/../imperia")))
    assert routes_mod._captured["status"] == 400


def test_sync_flag_spawns_and_still_lists(routes_mod, monkeypatch, tmp_path):
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    spawned = {"n": 0}

    class _Proc:
        async def wait(self):
            return 0
        def kill(self):
            pass

    async def _fake_exec(*a, **k):
        spawned["n"] += 1
        return _Proc()

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _fake_exec)
    asyncio.run(routes_mod.studio_library(_req(sync="1")))
    assert spawned["n"] == 1
    assert routes_mod._captured["status"] == 200


def test_no_sync_flag_does_not_spawn(routes_mod, monkeypatch, tmp_path):
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    spawned = {"n": 0}

    async def _fake_exec(*a, **k):
        spawned["n"] += 1
        raise AssertionError("should not spawn")

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _fake_exec)
    asyncio.run(routes_mod.studio_library(_req()))
    assert spawned["n"] == 0


def test_sync_timeout_still_lists_and_kills(routes_mod, monkeypatch, tmp_path):
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    killed = {"v": False}

    class _Proc:
        async def wait(self):
            return 0
        def kill(self):
            killed["v"] = True

    async def _fake_exec(*a, **k):
        return _Proc()

    async def _timeout(coro, timeout):
        coro.close()  # real wait_for cancels the inner awaitable on timeout
        raise asyncio.TimeoutError

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(routes_mod.asyncio, "wait_for", _timeout)
    asyncio.run(routes_mod.studio_library(_req(sync="1")))
    assert killed["v"] is True
    assert routes_mod._captured["status"] == 200
