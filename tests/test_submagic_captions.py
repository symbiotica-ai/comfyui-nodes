# ABOUTME: Tests that every Submagic HTTP call is bounded by a finite timeout and
# ABOUTME: that the poll loop notices ComfyUI's Cancel instead of sleeping through it.
import sys
import types

import pytest


@pytest.fixture
def submagic(monkeypatch):
    """The node module with ComfyUI's folder_paths stubbed — the pack's tests
    never import the real ComfyUI runtime."""
    fp = types.ModuleType("folder_paths")
    fp.get_output_directory = lambda: "/tmp"
    monkeypatch.setitem(sys.modules, "folder_paths", fp)
    import importlib
    mod = importlib.import_module("submagic_captions")
    return importlib.reload(mod)


class _Resp:
    def __init__(self, status=200, payload=None, content=b""):
        self.status_code = status
        self._payload = payload or {}
        self.text = ""
        self.content = content

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=8192):
        yield self.content


class TestEveryCallIsBounded:
    """requests defaults to no timeout at all: a hung Submagic connection would
    block the node forever, holding its worker until the sandbox itself dies."""

    def test_upload_is_bounded(self, submagic, monkeypatch, tmp_path):
        seen = {}
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"x")

        def fake_post(url, headers=None, files=None, data=None, timeout=None, **kw):
            seen["timeout"] = timeout
            return _Resp(201, {"id": "proj-1"})

        monkeypatch.setattr(submagic.requests, "post", fake_post)
        submagic.NSSubmagicCaptions()._upload("k", str(video), "en", "Sara", False, False)
        assert seen["timeout"], "upload request has no timeout"

    def test_poll_is_bounded(self, submagic, monkeypatch):
        seen = {}

        def fake_get(url, headers=None, timeout=None, **kw):
            seen["timeout"] = timeout
            return _Resp(200, {"status": "done", "transcriptionStatus": "COMPLETED"})

        monkeypatch.setattr(submagic.requests, "get", fake_get)
        submagic.NSSubmagicCaptions()._poll("k", "p", "transcriptionStatus", "COMPLETED")
        assert seen["timeout"], "poll request has no timeout"

    def test_export_is_bounded(self, submagic, monkeypatch):
        seen = {}

        def fake_post(url, headers=None, json=None, timeout=None, **kw):
            seen["timeout"] = timeout
            return _Resp(200)

        monkeypatch.setattr(submagic.requests, "post", fake_post)
        submagic.NSSubmagicCaptions()._export("k", "p")
        assert seen["timeout"], "export request has no timeout"

    def test_download_is_bounded(self, submagic, monkeypatch, tmp_path):
        seen = {}

        def fake_get(url, stream=False, timeout=None, **kw):
            seen["timeout"] = timeout
            return _Resp(200, content=b"video")

        monkeypatch.setattr(submagic.requests, "get", fake_get)
        submagic.NSSubmagicCaptions()._download("http://x/v.mp4", str(tmp_path / "out.mp4"))
        assert seen["timeout"], "download request has no timeout"


class TestCancelReachesThePollLoop:
    def test_cancel_before_the_first_poll_asks_the_api_nothing(self, submagic, monkeypatch):
        polls = {"n": 0}

        def fake_get(url, headers=None, timeout=None, **kw):
            polls["n"] += 1
            return _Resp(200, {"status": "processing", "transcriptionStatus": "PENDING"})

        monkeypatch.setattr(submagic.requests, "get", fake_get)
        monkeypatch.setattr(submagic, "_resolve_interrupt_checker", lambda: (lambda: True))

        with pytest.raises(submagic.SubmagicInterrupted):
            submagic.NSSubmagicCaptions()._poll("k", "p", "transcriptionStatus", "COMPLETED")
        assert polls["n"] == 0, f"polled a cancelled job ({polls['n']} times)"

    def test_cancel_during_the_wait_does_not_sleep_through(self, submagic, monkeypatch):
        # Pressing Cancel between polls must land inside the wait, not five
        # seconds later — the whole point of slicing the sleep.
        polls = {"n": 0}
        cancelled = {"yes": False}

        def fake_get(url, headers=None, timeout=None, **kw):
            polls["n"] += 1
            cancelled["yes"] = True
            return _Resp(200, {"status": "processing", "transcriptionStatus": "PENDING"})

        slept = []
        monkeypatch.setattr(submagic.requests, "get", fake_get)
        monkeypatch.setattr(submagic.time, "sleep", lambda s: slept.append(s))
        monkeypatch.setattr(submagic, "_resolve_interrupt_checker",
                            lambda: (lambda: cancelled["yes"]))

        with pytest.raises(submagic.SubmagicInterrupted):
            submagic.NSSubmagicCaptions()._poll("k", "p", "transcriptionStatus", "COMPLETED")
        assert polls["n"] == 1, f"kept polling after cancel ({polls['n']} polls)"
        assert all(s <= 0.5 for s in slept), f"slept in one un-cancellable block: {slept}"


def test_the_resolver_finds_ComfyUI_own_flag(submagic, monkeypatch):
    """Every cancel test replaces the resolver, which leaves the one line that
    reaches ComfyUI untested — and its `except Exception` would swallow a typo'd
    import, disabling cancel in production with the suite still green."""
    flag = lambda: True
    mm = types.ModuleType("comfy.model_management")
    mm.processing_interrupted = flag
    mm.InterruptProcessingException = type("InterruptProcessingException", (BaseException,), {})
    comfy = types.ModuleType("comfy")
    comfy.__path__ = []
    comfy.model_management = mm
    monkeypatch.setitem(sys.modules, "comfy", comfy)
    monkeypatch.setitem(sys.modules, "comfy.model_management", mm)

    assert submagic._resolve_interrupt_checker() is flag, (
        "the resolver did not reach ComfyUI's flag")
    monkeypatch.undo()
    assert submagic._resolve_interrupt_checker()() is False, (
        "outside ComfyUI the resolver must report 'not cancelled'")
