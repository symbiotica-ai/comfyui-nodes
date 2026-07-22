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
