# ABOUTME: Tests for provider key resolution — a node's key may come from its
# ABOUTME: widget or from Settings, and a missing one must say where to put it.
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
