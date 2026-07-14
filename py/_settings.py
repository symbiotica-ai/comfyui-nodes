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
