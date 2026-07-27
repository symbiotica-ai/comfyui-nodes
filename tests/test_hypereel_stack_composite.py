# ABOUTME: Node-level regression for HypereelStackComposite — a masked pair must
# ABOUTME: not let the facecam's native fps clobber the node's requested fps.
import importlib
import sys
import types

import numpy as np
import pytest


class _FakeVideo:
    def save_to(self, path, **kw):
        open(path, "wb").close()


class _FakeMask:
    def cpu(self):
        return self

    def numpy(self):
        return np.zeros((1, 4, 4), dtype=np.float32)


@pytest.fixture()
def node(monkeypatch, tmp_path):
    fp = types.ModuleType("folder_paths")
    fp.get_output_directory = lambda: str(tmp_path)
    monkeypatch.setitem(sys.modules, "folder_paths", fp)
    latest = types.ModuleType("comfy_api.latest")
    latest.InputImpl = types.SimpleNamespace(VideoFromFile=lambda p: ("VIDEO", p))
    capi = types.ModuleType("comfy_api")
    capi.latest = latest
    monkeypatch.setitem(sys.modules, "comfy_api", capi)
    monkeypatch.setitem(sys.modules, "comfy_api.latest", latest)
    pkg = types.ModuleType("symbiotica")
    pkg.__path__ = ["py"]
    monkeypatch.setitem(sys.modules, "symbiotica", pkg)
    glow = importlib.import_module("symbiotica._hypereel_glow")
    ff = importlib.import_module("symbiotica._hypereel_ffmpeg")
    mod = importlib.import_module("symbiotica.hypereel_stack_composite")
    importlib.reload(mod)
    # The facecam's native fps is 24; the node's requested output fps will be 30.
    monkeypatch.setattr(glow, "probe_video", lambda ffprobe, path: (100, 100, 24, 48))
    monkeypatch.setattr(ff, "write_gray_video", lambda *a, **k: None)
    captured = {}

    def fake_compose_pairs(pairs, out, **kw):
        captured.update(kw)
        return len(pairs)

    monkeypatch.setattr(mod, "compose_pairs", fake_compose_pairs)
    return mod, captured


def test_masked_pair_keeps_requested_fps(node):
    mod, captured = node
    comp = mod.HypereelStackComposite()
    comp.compose(_FakeVideo(), _FakeVideo(), layout=mod.DEFAULT_LAYOUT,
                 corner="bottom-right", game_audio_gain=0.3, fps=30, crf=20,
                 mask_1=_FakeMask())
    assert captured["fps"] == 30  # not the facecam's native 24
