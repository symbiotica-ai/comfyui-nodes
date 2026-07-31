# ABOUTME: The Hypereel UGC preset catalogs and the notes-block builder. The
# ABOUTME: catalog data is a separate module so it can be left out of a build.
try:
    # Relative inside the pack, top-level when the tests put py/ on the path.
    try:
        from ._hypereel_preset_data import HOOKS, SETTINGS, STYLES
    except ImportError:
        from _hypereel_preset_data import HOOKS, SETTINGS, STYLES
except ImportError:
    HOOKS, SETTINGS, STYLES = {}, {}, {}

NO_CATALOG = "(preset catalog not bundled)"


def catalogs_bundled() -> bool:
    """Whether the preset templates shipped with this build."""
    return bool(STYLES and HOOKS and SETTINGS)


def names(catalog) -> list:
    """Dropdown entries for a catalog — a single placeholder when the templates
    are absent, because an empty combo gives the user nothing to read."""
    return list(catalog) or [NO_CATALOG]


def require_catalogs() -> None:
    """Fail with the reason. Without this the first lookup raises a bare KeyError,
    which reads as a pack bug rather than a build that ships no templates."""
    if not catalogs_bundled():
        raise RuntimeError(
            "the Hypereel preset catalog is not bundled with this build — "
            "this node needs the full pack")



def build_notes(style, hook, setting):
    """The pre-labeled block the script LLM consumes after the product summary."""
    require_catalogs()
    return (f"STYLE NOTE: {STYLES[style]}\n"
            f"HOOK PATTERN: {HOOKS[hook]}\n"
            f"SETTING NOTE: {SETTINGS[setting]}")


