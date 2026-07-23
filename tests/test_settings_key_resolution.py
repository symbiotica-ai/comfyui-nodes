# ABOUTME: Every provider whose key the Settings UI collects must actually read
# ABOUTME: it, or the recommended path silently fails and keys go into widgets.
import os
import sys
import types

import pytest


@pytest.fixture
def nodes(monkeypatch):
    """The provider nodes, importable outside ComfyUI."""
    import importlib
    if "folder_paths" not in sys.modules:
        fp = types.ModuleType("folder_paths")
        for name in ("get_user_directory", "get_output_directory",
                     "get_temp_directory", "get_input_directory"):
            setattr(fp, name, lambda: "/nonexistent")
        sys.modules["folder_paths"] = fp
    if "symbiotica_py" not in sys.modules:
        pkg = types.ModuleType("symbiotica_py")
        pkg.__path__ = [os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "py")]
        sys.modules["symbiotica_py"] = pkg
    return {name: importlib.import_module(f"symbiotica_py.{name}")
            for name in ("submagic_captions", "wavespeed_client",
                         "grok_client", "visual_overlay")}


@pytest.fixture
def settings(monkeypatch):
    """Pretend the user pasted keys into the Settings UI."""
    import symbiotica_py._settings as s  # noqa: F401  (imported for patching)
    store = {}

    def fake(setting_id, default=None):
        return store.get(setting_id, default)
    monkeypatch.setattr(s, "get_comfy_setting", fake)
    return store


# The Settings UI registers all of these (web/js/symbiotica_settings.js) and
# tells the user they are safe to share. A provider that ignores its own entry
# sends the user to the api_key widget instead, which the workflow file keeps.
# (module, class, how to ask it for a key, env name). The client nodes hand
# back a wire dict instead of a string, so each case says how to read it.
CASES = [
    ("submagic_captions", "NSSubmagicCaptions",
     lambda n, k: n._resolve_api_key(k), "SUBMAGIC_API_KEY"),
    ("visual_overlay", "NSVisualOverlay",
     lambda n, k: n._resolve_api_key(k), "ANTHROPIC_API_KEY"),
    ("grok_client", "NSGrokClient",
     lambda n, k: n.create_client(k)[0]["api_key"], "XAI_API_KEY"),
    ("wavespeed_client", "NSWaveSpeedClient",
     lambda n, k: n.create_client(k)[0]["api_key"], "WAVESPEED_API_KEY"),
]


@pytest.mark.parametrize("module,cls,ask,env", CASES)
def test_settings_value_is_used(nodes, settings, monkeypatch, module, cls,
                                ask, env):
    monkeypatch.delenv(env, raising=False)
    settings[f"Symbiotica.{env}"] = "from-settings"
    assert ask(getattr(nodes[module], cls)(), "") == "from-settings"


@pytest.mark.parametrize("module,cls,ask,env", CASES)
def test_typed_key_still_wins(nodes, settings, module, cls, ask, env):
    settings[f"Symbiotica.{env}"] = "from-settings"
    assert ask(getattr(nodes[module], cls)(), "typed") == "typed"
