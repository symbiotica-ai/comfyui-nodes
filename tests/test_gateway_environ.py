# ABOUTME: Tests for gateway config on a box with no environment to set —
# ABOUTME: Comfy Desktop, where the Settings UI is the only channel there is.
import pytest

import _settings
from _settings import gateway_environ

GATEWAY_NAMES = ("SYMBIOTICA_AIG_BASE", "SYMBIOTICA_AIG_TOKEN",
                 "ORDER_STUDIO", "SYMBIOTICA_AIG_SURFACE")


@pytest.fixture
def settings(monkeypatch):
    """The Settings UI, as a dict a test can fill in.

    Patched at `get_comfy_setting` rather than by writing a
    comfy.settings.json, because the reader needs `folder_paths` from a
    running ComfyUI and returns the default for every id without it — which
    would make every one of these tests pass against a resolver that read
    nothing at all."""
    values = {}
    monkeypatch.setattr(_settings, "get_comfy_setting",
                        lambda key, default=None: values.get(key, default))
    for name in GATEWAY_NAMES:
        monkeypatch.delenv(name, raising=False)
    return values


def test_settings_supply_the_gateway_when_the_environment_has_none(settings):
    settings["Symbiotica.SYMBIOTICA_AIG_BASE"] = "https://gw.example/v1/acct/gw"
    settings["Symbiotica.SYMBIOTICA_AIG_TOKEN"] = "tok-from-settings"
    settings["Symbiotica.ORDER_STUDIO"] = "comfy-desktop"
    environ = gateway_environ()
    assert environ["SYMBIOTICA_AIG_BASE"] == "https://gw.example/v1/acct/gw"
    assert environ["SYMBIOTICA_AIG_TOKEN"] == "tok-from-settings"
    assert environ["ORDER_STUDIO"] == "comfy-desktop"


def test_a_configured_environment_is_left_whole(settings, monkeypatch):
    # An order sandbox gets all of this from one secret. A Settings value
    # reaching in to replace a single member of that group is how an env base
    # comes to be paired with a stale Settings token — which the gateway
    # refuses as 2009, "we rejected your own credential", sending whoever reads
    # it to the secret store when the fault is a text field in the UI.
    monkeypatch.setenv("SYMBIOTICA_AIG_BASE", "https://gw.example/v1/acct/gw")
    monkeypatch.setenv("SYMBIOTICA_AIG_TOKEN", "tok-from-secret")
    monkeypatch.setenv("ORDER_STUDIO", "teilor")
    settings["Symbiotica.SYMBIOTICA_AIG_TOKEN"] = "tok-from-settings"
    settings["Symbiotica.ORDER_STUDIO"] = "comfy-desktop"
    environ = gateway_environ()
    assert environ["SYMBIOTICA_AIG_TOKEN"] == "tok-from-secret"
    assert environ["ORDER_STUDIO"] == "teilor"


def test_a_sandbox_whose_secret_failed_is_still_reported_as_one(settings,
                                                                monkeypatch):
    # The launcher sets ORDER_STUDIO whether or not the secret populated, so
    # that pair — a studio with no base — is how a broken sandbox announces
    # itself, and `resolve_transport` refuses it by name. Letting Settings
    # supply the missing base would answer that with a desktop's own
    # credentials: the render succeeds, and the studio's spend silently leaves
    # its own key.
    monkeypatch.setenv("ORDER_STUDIO", "teilor")
    settings["Symbiotica.SYMBIOTICA_AIG_BASE"] = "https://gw.example/v1/acct/gw"
    settings["Symbiotica.SYMBIOTICA_AIG_TOKEN"] = "tok-from-settings"
    settings["Symbiotica.ORDER_STUDIO"] = "comfy-desktop"
    environ = gateway_environ()
    assert environ.get("SYMBIOTICA_AIG_BASE", "") == ""
    assert environ["ORDER_STUDIO"] == "teilor"


def test_a_base_without_its_token_names_the_field_to_fill(settings):
    # `resolve_transport` refuses this pair too, but it tells the reader to
    # check the symbiotica-comfy-aigateway secret — a thing a desktop box has
    # no access to and its owner has never seen.
    settings["Symbiotica.SYMBIOTICA_AIG_BASE"] = "https://gw.example/v1/acct/gw"
    settings["Symbiotica.ORDER_STUDIO"] = "comfy-desktop"
    with pytest.raises(ValueError) as err:
        gateway_environ()
    message = str(err.value)
    assert "Settings" in message
    assert "SYMBIOTICA_AIG_TOKEN" in message
    assert "symbiotica-comfy-aigateway" not in message


def test_a_base_without_a_studio_names_the_field_to_fill(settings):
    # The field carries a default, so an empty one means somebody cleared it.
    # Left alone it reaches the gateway arm's own refusal, which talks about an
    # order sandbox setting it alongside the secret.
    settings["Symbiotica.SYMBIOTICA_AIG_BASE"] = "https://gw.example/v1/acct/gw"
    settings["Symbiotica.SYMBIOTICA_AIG_TOKEN"] = "tok-from-settings"
    with pytest.raises(ValueError) as err:
        gateway_environ()
    message = str(err.value)
    assert "Settings" in message
    assert "ORDER_STUDIO" in message


def test_a_desktop_render_is_not_counted_as_an_order(settings):
    # `studio_tag` calls an untagged run an order, which is right for every
    # sandbox and wrong for this box. Counted as orders, canvas renders inflate
    # order spend under a label that reads correctly.
    settings["Symbiotica.SYMBIOTICA_AIG_BASE"] = "https://gw.example/v1/acct/gw"
    settings["Symbiotica.SYMBIOTICA_AIG_TOKEN"] = "tok-from-settings"
    settings["Symbiotica.ORDER_STUDIO"] = "comfy-desktop"
    assert gateway_environ()["SYMBIOTICA_AIG_SURFACE"] == "canvas"


def test_a_surface_the_box_declares_is_kept(settings, monkeypatch):
    monkeypatch.setenv("SYMBIOTICA_AIG_SURFACE", "smoke-test")
    settings["Symbiotica.SYMBIOTICA_AIG_BASE"] = "https://gw.example/v1/acct/gw"
    settings["Symbiotica.SYMBIOTICA_AIG_TOKEN"] = "tok-from-settings"
    settings["Symbiotica.ORDER_STUDIO"] = "comfy-desktop"
    assert gateway_environ()["SYMBIOTICA_AIG_SURFACE"] == "smoke-test"


def test_an_unconfigured_box_is_left_exactly_as_it_was(settings, monkeypatch):
    # Nothing in Settings, nothing in the environment: the direct arms and
    # their own key ladders must still be reachable, and the gateway names must
    # not appear as empty strings, which read as configured-but-blank.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "personal")
    environ = gateway_environ()
    assert environ["ANTHROPIC_API_KEY"] == "personal"
    assert "SYMBIOTICA_AIG_BASE" not in environ
