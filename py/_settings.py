# ABOUTME: Reads Symbiotica API keys from ComfyUI's user settings
# ABOUTME: (comfy.settings.json) — set via the Settings UI, never in workflows.
# Pattern borrowed from eRepublik-Labs/comfyui-nodes-erpk settings.py.
import json
import os


def get_comfy_setting(setting_id: str, default=None):
    """A value from the user's comfy.settings.json (Settings UI storage).
    Values live server-side per user — they never enter workflow JSON, so
    workflows stay shareable. Returns default when unset/blank/unreadable."""
    try:
        import folder_paths
        user_dir = folder_paths.get_user_directory()
    except Exception:
        return default
    path = os.path.join(user_dir, "default", "comfy.settings.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (OSError, json.JSONDecodeError):
        return default
    value = settings.get(setting_id, default)
    if isinstance(value, str) and not value.strip():
        return default
    return value


def setting_key(provider_env: str) -> str:
    """Map an env-var name to its Settings UI id, e.g. ANTHROPIC_API_KEY ->
    Symbiotica.ANTHROPIC_API_KEY."""
    return f"Symbiotica.{provider_env}"


def resolve_key(env_names: list[str]) -> str | None:
    """Provider key lookup: Settings UI first (per this pack's ids), then the
    environment — first hit wins."""
    for env in env_names:
        value = get_comfy_setting(setting_key(env))
        if value:
            return str(value).strip()
    for env in env_names:
        value = os.environ.get(env, "").strip()
        if value:
            return value
    return None



def resolve_provider_key(api_key: str, env_names: list[str], provider: str) -> str:
    """The key for one node call: what was typed on the node, else Settings or
    the environment. Raises with somewhere to put it when there is none.

    A key typed into a node widget is stored in the workflow JSON, so a shared
    or committed workflow carries it. Leaving the widget empty is the point —
    the value then lives per-user, server-side, and never travels."""
    key = (api_key or "").strip()
    if not key:
        key = resolve_key(env_names) or ""
    if not key:
        raise Exception(
            f"{provider} API key required. Set it in Settings → Symbiotica, "
            f"or the {env_names[0]} environment variable. Typing it on the node "
            f"works too, but saves the key into the workflow file."
        )
    return key


def key_from_settings(*env_names) -> str | None:
    """The Settings UI value for a provider, ignoring env vars and config files.

    For resolvers that already have their own precedence between a widget,
    config.ini, and the environment: this slots Settings in without disturbing
    the rest of the chain."""
    for env in env_names:
        value = get_comfy_setting(setting_key(env))
        if value:
            return str(value).strip()
    return None



# The gateway config that a box with no environment to set must get from the
# Settings UI. Read and applied as a GROUP: an env base paired with a Settings
# token fails as gateway code 2009, which reads as "the gateway rejected our
# own credential" and sends whoever reads it to the secret store when the fault
# is a text field in the UI.
GATEWAY_SETTINGS = ("SYMBIOTICA_AIG_BASE", "SYMBIOTICA_AIG_TOKEN",
                    "ORDER_STUDIO")

# What a run started by hand on somebody's own machine is called in gateway
# analytics, where it must not be counted as an order.
CANVAS_SURFACE = "canvas"

# The BYOK alias a desktop box bills when nobody names another. It lives here
# rather than only in the Settings UI because ComfyUI writes a setting into
# comfy.settings.json only when somebody EDITS it — a field registered with a
# default writes nothing, so a default declared only over there is one this
# side can never read. The two spellings are held together by a test.
DEFAULT_STUDIO = "comfy-desktop"


def gateway_environ() -> dict:
    """`os.environ`, plus the gateway config the Settings UI holds.

    Comfy Desktop is an Electron app that launches its own Python, so there is
    no environment to put `SYMBIOTICA_AIG_BASE` in. Without this, every gateway
    node on a desktop box falls to its direct arm and spends a personal key."""
    environ = dict(os.environ)
    # Anything the environment already says about the gateway is the whole of
    # what it says. A studio with no base is how a sandbox whose secret failed
    # to populate announces itself, and `resolve_transport` refuses it by name;
    # answering that with a desktop's own credentials would let the render
    # succeed while the studio's spend left its own key.
    if any((environ.get(name) or "").strip()
           for name in ("SYMBIOTICA_AIG_BASE", "ORDER_STUDIO")):
        return environ
    base = key_from_settings("SYMBIOTICA_AIG_BASE") or ""
    if not base:
        return environ
    group = dict({name: (key_from_settings(name) or "")
                  for name in GATEWAY_SETTINGS},
                 SYMBIOTICA_AIG_BASE=base)
    group["ORDER_STUDIO"] = group["ORDER_STUDIO"] or DEFAULT_STUDIO
    for name in GATEWAY_SETTINGS:
        if not group[name]:
            raise ValueError(
                f"Settings → Symbiotica → AI Gateway has a gateway base "
                f"but no {name}. All three go together: a base on its own "
                f"either fails asking for a credential this box does not hold, "
                f"or bills spend that reaches no studio's row.")
    environ.update(group)
    # What kind of run this is. Left unset it defaults to `order`, so a canvas
    # render would join the order totals under a label that reads correctly —
    # the one kind of wrong number nobody thinks to question. Not a field,
    # because a field is a thing that can be cleared.
    environ["SYMBIOTICA_AIG_SURFACE"] = (
        (environ.get("SYMBIOTICA_AIG_SURFACE") or "").strip() or CANVAS_SURFACE)
    return environ
