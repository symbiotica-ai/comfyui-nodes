# ABOUTME: Tests that the pack still behaves sanely when the preset catalog data is
# ABOUTME: not bundled — the node says so instead of failing silently or by KeyError.
import importlib
import sys

import pytest


@pytest.fixture
def without_data(monkeypatch):
    """The published pack ships without the catalog data module."""
    sys.modules.pop("_hypereel_presets", None)
    sys.modules.pop("_hypereel_preset_data", None)
    # A None entry makes the import raise, which is what a build without the
    # data module looks like from inside _hypereel_presets.
    monkeypatch.setitem(sys.modules, "_hypereel_preset_data", None)
    import _hypereel_presets as p
    return importlib.reload(p)


@pytest.fixture
def with_data():
    for mod in ("_hypereel_presets", "_hypereel_preset_data"):
        sys.modules.pop(mod, None)
    import _hypereel_presets as p
    return importlib.reload(p)


class TestWithoutTheCatalog:
    def test_the_catalogs_are_empty_rather_than_missing(self, without_data):
        assert without_data.STYLES == {}
        assert without_data.HOOKS == {}
        assert without_data.SETTINGS == {}

    def test_it_reports_that_the_catalog_is_absent(self, without_data):
        assert without_data.catalogs_bundled() is False

    def test_the_notes_builder_says_why_instead_of_KeyError(self, without_data):
        # A bare KeyError reads as a pack bug. Name the cause.
        with pytest.raises(RuntimeError) as err:
            without_data.build_notes("UGC", "x", "y")
        assert "not bundled" in str(err.value).lower()


class TestWithTheCatalog:
    def test_the_catalogs_load_when_bundled(self, with_data):
        assert with_data.catalogs_bundled() is True
        assert len(with_data.STYLES) > 0
        assert len(with_data.HOOKS) > 0
        assert len(with_data.SETTINGS) > 0


class TestPackaging:
    def test_the_catalog_data_is_excluded_from_the_published_zip(self):
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        ignore = open(os.path.join(root, ".comfyignore")).read()
        assert "_hypereel_preset_data.py" in ignore, (
            "the catalog data would ship in the published zip")
