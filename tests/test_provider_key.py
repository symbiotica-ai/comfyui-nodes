# ABOUTME: Tests for provider key resolution — a node's key may come from its
# ABOUTME: widget or from Settings, and a missing one must say where to put it.
import os
import sys
import types

import pytest

from _settings import resolve_provider_key


def test_widget_key_wins(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "from-env")
    assert resolve_provider_key("from-widget", ["ELEVENLABS_API_KEY"],
                                "ElevenLabs") == "from-widget"


def test_blank_widget_falls_back(monkeypatch):
    # Leaving the widget empty is the whole point: a key typed into a widget is
    # saved into the workflow JSON, so a shared workflow carries a live key.
    monkeypatch.setenv("ELEVENLABS_API_KEY", "from-env")
    assert resolve_provider_key("", ["ELEVENLABS_API_KEY"],
                                "ElevenLabs") == "from-env"


def test_whitespace_widget_is_blank(monkeypatch):
    monkeypatch.setenv("ELEVENLABS_API_KEY", "from-env")
    assert resolve_provider_key("   ", ["ELEVENLABS_API_KEY"],
                                "ElevenLabs") == "from-env"


def test_missing_key_says_where_to_put_it(monkeypatch):
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    with pytest.raises(Exception) as err:
        resolve_provider_key("", ["ELEVENLABS_API_KEY"], "ElevenLabs")
    message = str(err.value)
    assert "ElevenLabs" in message
    assert "Settings" in message
    assert "ELEVENLABS_API_KEY" in message


# --- the nodes actually use it ------------------------------------------------
# Without these, deleting the resolve_provider_key call from either node passes
# the whole suite and quietly restores the leak.

@pytest.fixture
def eleven_nodes(monkeypatch):
    """py/music.py and py/sound_effects.py, importable outside ComfyUI."""
    if "folder_paths" not in sys.modules:
        fp = types.ModuleType("folder_paths")
        fp.get_user_directory = lambda: "/nonexistent"
        fp.get_output_directory = lambda: "/tmp"
        fp.get_temp_directory = lambda: "/tmp"
        sys.modules["folder_paths"] = fp
    # These modules use relative imports (`from ._bins import ...`), so they
    # need a parent package. ComfyUI supplies one at runtime; here a synthetic
    # package rooted at py/ stands in, the same shape the real one has.
    import importlib
    if "comfy_api" not in sys.modules:
        # execute() imports comfy_api at the top, before it can decide it has
        # nothing to do — enough of it to get past the import.
        latest = types.ModuleType("comfy_api.latest")
        latest.InputImpl = types.SimpleNamespace(VideoFromFile=object)
        api = types.ModuleType("comfy_api"); api.__path__ = []; api.latest = latest
        sys.modules["comfy_api"] = api
        sys.modules["comfy_api.latest"] = latest
    if "symbiotica_py" not in sys.modules:
        pkg = types.ModuleType("symbiotica_py")
        pkg.__path__ = [os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "py")]
        sys.modules["symbiotica_py"] = pkg
    music = importlib.import_module("symbiotica_py.music")
    sfx = importlib.import_module("symbiotica_py.sound_effects")
    return music, sfx


def test_music_resolves_the_key_when_the_widget_is_blank(eleven_nodes, monkeypatch):
    music, _ = eleven_nodes
    monkeypatch.setenv("ELEVENLABS_API_KEY", "from-settings")
    seen = {}
    monkeypatch.setattr(music.requests, "post",
                        lambda *a, **k: seen.update(headers=k.get("headers", {}))
                        or (_ for _ in ()).throw(RuntimeError("stop here")))
    with pytest.raises(RuntimeError):
        music.NSMusic()._call_elevenlabs_music("", "a tune", 30000, True, 0, [])
    assert seen["headers"]["xi-api-key"] == "from-settings"


def test_sound_effects_resolves_the_key_when_the_widget_is_blank(eleven_nodes, monkeypatch):
    _, sfx = eleven_nodes
    monkeypatch.setenv("ELEVENLABS_API_KEY", "from-settings")
    seen = {}
    monkeypatch.setattr(sfx.requests, "post",
                        lambda *a, **k: seen.update(headers=k.get("headers", {}))
                        or (_ for _ in ()).throw(RuntimeError("stop here")))
    with pytest.raises(RuntimeError):
        sfx.NSSoundEffects()._call_elevenlabs("", "a whoosh", 2.0, 0.7, [])
    assert seen["headers"]["xi-api-key"] == "from-settings"


def test_a_muted_music_node_needs_no_key_at_all(eleven_nodes, monkeypatch):
    # Blanking the prompt is how a workflow mutes this node. It returns the
    # video untouched and calls nothing, so demanding a key would break setups
    # that never had one.
    music, _ = eleven_nodes
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    video, audio = music.NSMusic().execute("   ", "", duration_sec=30.0, video="V")
    assert video == "V" and audio is None
