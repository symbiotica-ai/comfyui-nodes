# ABOUTME: Tests the UGC preset catalogs and the preset-picker node's output block.
from _hypereel_presets import HOOKS, SETTINGS, STYLES


class TestCatalogs:
    def test_full_catalogs_ported(self):
        assert len(STYLES) == 14 and len(HOOKS) == 10 and len(SETTINGS) == 15

    def test_known_presets_present_with_real_templates(self):
        style_names = " ".join(STYLES).lower()
        assert "ugc" in style_names
        assert all(len(t) > 60 for t in STYLES.values())
        assert all(len(t) > 40 for t in HOOKS.values())
        assert all(len(t) > 40 for t in SETTINGS.values())

    def test_no_unescaped_artifacts(self):
        for cat in (STYLES, HOOKS, SETTINGS):
            for t in cat.values():
                assert "\\'" not in t and "\\u" not in t


class TestNotesBlock:
    def test_notes_block_is_prelabeled(self):
        from _hypereel_presets import build_notes
        style = next(iter(STYLES))
        hook = next(iter(HOOKS))
        setting = next(iter(SETTINGS))
        notes = build_notes(style, hook, setting)
        assert notes.startswith("STYLE NOTE: " + STYLES[style])
        assert "\nHOOK PATTERN: " in notes and "\nSETTING NOTE: " in notes


class TestAdPrompt:
    def test_full_assembly_in_order(self):
        from _hypereel_presets import build_ad_prompt
        style = next(iter(STYLES)); hook = next(iter(HOOKS)); setting = next(iter(SETTINGS))
        p = build_ad_prompt("PRODUCT: X - Y. Platform: mobile app. CTA rule: store download.",
                            style, hook, setting)
        assert p.startswith("PRODUCT: X")
        assert "\nCREATOR: defined entirely by @Image1.\n" in p
        assert "STYLE NOTE: " in p and p.index("CREATOR") < p.index("STYLE NOTE")

    def test_persona_rides_the_creator_line(self):
        from _hypereel_presets import build_ad_prompt
        style = next(iter(STYLES)); hook = next(iter(HOOKS)); setting = next(iter(SETTINGS))
        p = build_ad_prompt("PRODUCT: X", style, hook, setting, persona="dry humor, low energy")
        assert "PERSONA: dry humor, low energy" in p.split("\n")[1]

    def test_system_prompt_carries_the_format_contract(self):
        from _hypereel_presets import SYSTEM_PROMPT
        assert "Shot 1" in SYSTEM_PROMPT and "@Image1" in SYSTEM_PROMPT
        assert "ABSOLUTELY NO rendered text" in SYSTEM_PROMPT
        assert len(SYSTEM_PROMPT) > 3000
