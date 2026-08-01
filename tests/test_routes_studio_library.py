# ABOUTME: Tests for the /symbiotica/studio-library route — a capturing
# ABOUTME: json_response stub + asyncio.run assert real payloads and statuses.
import asyncio
import importlib
import sys
import types
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
    # Stub aiohttp so the suite runs without it installed (CI ships a minimal dep
    # set — aiohttp is a ComfyUI-runtime dep), mirroring test_routes_allowlist.py.
    # json_response is our capturing stub.
    fake_web = types.ModuleType("aiohttp.web")
    fake_web.json_response = json_response
    fake_aiohttp = types.ModuleType("aiohttp")
    fake_aiohttp.web = fake_web
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)
    monkeypatch.setitem(sys.modules, "aiohttp.web", fake_web)
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


def test_sync_spawn_failure_still_lists(routes_mod, monkeypatch, tmp_path):
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))

    async def _fake_exec(*a, **k):
        raise FileNotFoundError("no such file: sync")

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _fake_exec)
    asyncio.run(routes_mod.studio_library(_req(sync="1")))
    assert routes_mod._captured["status"] == 200
    assert "entries" in routes_mod._captured["body"]


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


def test_concurrent_browsers_share_one_volume_walk(routes_mod, monkeypatch, tmp_path):
    """`sync` on the mount is a walk that can take the whole timeout, and the
    browse control is a button anyone can hold down. Each press starting its own
    walk piles them onto the editor container; the hub runs the same mechanism
    one-at-a-time per mount for exactly this reason."""
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    state = {"spawned": 0, "release": None}

    class _Proc:
        async def wait(self):
            await state["release"].wait()
            return 0
        def kill(self):
            pass

    async def _fake_exec(*a, **k):
        state["spawned"] += 1
        return _Proc()

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _fake_exec)

    async def two_at_once():
        state["release"] = asyncio.Event()
        both = [asyncio.create_task(routes_mod.studio_library(_req(sync="1")))
                for _ in range(2)]
        for _ in range(10):  # let both reach the sync before either finishes
            await asyncio.sleep(0)
        state["release"].set()
        await asyncio.gather(*both)

    asyncio.run(two_at_once())
    assert state["spawned"] == 1
    assert routes_mod._captured["status"] == 200


def test_a_finished_walk_is_not_reused(routes_mod, monkeypatch, tmp_path):
    """Sharing an in-flight walk is safe because it is idempotent. Sharing a
    FINISHED one is not: a browse after someone else's upload has to get a walk
    that could see it."""
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

    async def one_after_the_other():
        await routes_mod.studio_library(_req(sync="1"))
        await routes_mod.studio_library(_req(sync="1"))

    asyncio.run(one_after_the_other())
    assert spawned["n"] == 2


def test_the_root_hides_model_folders_and_counts_them(routes_mod, monkeypatch, tmp_path):
    (tmp_path / "studios" / "ggs" / "loras").mkdir(parents=True)
    (tmp_path / "studios" / "ggs" / "refs").mkdir()
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    asyncio.run(routes_mod.studio_library(_req()))
    body = routes_mod._captured["body"]
    assert [e["name"] for e in body["entries"]] == ["refs"]
    assert body["hidden"] == 1


def test_models_flag_lists_the_model_folders(routes_mod, monkeypatch, tmp_path):
    (tmp_path / "studios" / "ggs" / "loras").mkdir(parents=True)
    (tmp_path / "studios" / "ggs" / "refs").mkdir()
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    asyncio.run(routes_mod.studio_library(_req(models="1")))
    body = routes_mod._captured["body"]
    assert [e["name"] for e in body["entries"]] == ["loras", "refs"]
    assert "hidden" not in body


def test_sync_timeout_says_so_in_the_payload(routes_mod, monkeypatch, tmp_path):
    """A killed sync leaves the mount as stale as it was, and the listing that
    follows is indistinguishable from a fresh one. Saying which it was is the
    difference between 'the folder is not there' and 'we could not go and look'."""
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))

    class _Proc:
        async def wait(self):
            return 0
        def kill(self):
            pass

    async def _fake_exec(*a, **k):
        return _Proc()

    async def _timeout(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(routes_mod.asyncio, "wait_for", _timeout)
    asyncio.run(routes_mod.studio_library(_req(sync="1")))
    assert routes_mod._captured["status"] == 200
    assert routes_mod._captured["body"]["sync"] == "timeout"
    assert "entries" in routes_mod._captured["body"]


def test_a_sync_that_exits_non_zero_says_so(routes_mod, monkeypatch, tmp_path):
    """`sync` reporting failure is not the same as `sync` never running, but the
    listing is identical either way, so the exit code has to be read."""
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))

    class _Proc:
        async def wait(self):
            return 1
        def kill(self):
            pass

    async def _fake_exec(*a, **k):
        return _Proc()

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _fake_exec)
    asyncio.run(routes_mod.studio_library(_req(sync="1")))
    assert routes_mod._captured["status"] == 200
    assert routes_mod._captured["body"]["sync"] == "failed"


def test_a_sync_that_never_started_says_so(routes_mod, monkeypatch, tmp_path):
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))

    async def _fake_exec(*a, **k):
        raise FileNotFoundError("no such file: sync")

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _fake_exec)
    asyncio.run(routes_mod.studio_library(_req(sync="1")))
    assert routes_mod._captured["body"]["sync"] == "failed"


def test_a_listing_that_asked_for_no_sync_carries_no_verdict(routes_mod, monkeypatch,
                                                             tmp_path):
    """`sync` present at all is the client's cue to distrust the listing, so a
    request that never asked for one must not carry the key at any value."""
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))
    asyncio.run(routes_mod.studio_library(_req()))
    assert "sync" not in routes_mod._captured["body"]


def test_a_refused_listing_reports_only_the_refusal(routes_mod, monkeypatch, tmp_path):
    """An escaping dir gets a 400 whose body is the error. Riding a sync verdict
    into it hands the client two things to read and a field its error path was
    never written to expect."""
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))

    class _Proc:
        async def wait(self):
            return 1
        def kill(self):
            pass

    async def _fake_exec(*a, **k):
        return _Proc()

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _fake_exec)
    asyncio.run(routes_mod.studio_library(_req(sync="1", dir="studios/ggs/../elsewhere")))
    assert routes_mod._captured["status"] == 400
    assert "error" in routes_mod._captured["body"]
    assert "sync" not in routes_mod._captured["body"]


def test_each_degraded_sync_records_why(routes_mod, monkeypatch, tmp_path, capfd):
    """The payload collapses a spawn failure and a non-zero exit into the same
    "failed", so the log is the only place the reason survives for whoever is
    working out why a studio looks out of date."""
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))

    class _Proc:
        def __init__(self, code):
            self._code = code
        async def wait(self):
            return self._code
        def kill(self):
            pass

    def _exec_returning(code):
        async def _fake(*a, **k):
            return _Proc(code)
        return _fake

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _exec_returning(3))
    asyncio.run(routes_mod.studio_library(_req(sync="1")))
    assert "exited 3" in capfd.readouterr().out

    async def _cannot_spawn(*a, **k):
        raise FileNotFoundError("no such file: sync")

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _cannot_spawn)
    asyncio.run(routes_mod.studio_library(_req(sync="1")))
    assert "could not start" in capfd.readouterr().out

    async def _timeout(coro, timeout):
        coro.close()
        raise asyncio.TimeoutError

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _exec_returning(0))
    monkeypatch.setattr(routes_mod.asyncio, "wait_for", _timeout)
    asyncio.run(routes_mod.studio_library(_req(sync="1")))
    out = capfd.readouterr().out
    assert "exceeded" in out and str(routes_mod.SYNC_TIMEOUT_S) in out


def test_a_clean_sync_leaves_the_payload_alone(routes_mod, monkeypatch, tmp_path):
    """`sync` present at all is the client's cue to distrust the listing, so a
    refresh that worked must not set it."""
    (tmp_path / "studios" / "ggs").mkdir(parents=True)
    monkeypatch.setenv("CANVAS_STUDIO", "ggs")
    monkeypatch.setattr(routes_mod.studio_library_mod, "STUDIO_ASSETS_DIR", str(tmp_path))

    class _Proc:
        async def wait(self):
            return 0
        def kill(self):
            pass

    async def _fake_exec(*a, **k):
        return _Proc()

    monkeypatch.setattr(routes_mod.asyncio, "create_subprocess_exec", _fake_exec)
    asyncio.run(routes_mod.studio_library(_req(sync="1")))
    assert "sync" not in routes_mod._captured["body"]
