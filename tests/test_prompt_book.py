# ABOUTME: Tests for the prompt book — an order's asset types resolved to the
# ABOUTME: per-type architect prompts stored under
# ABOUTME: <project>/prompts/<Exact Category Name>.md.
import pytest

from pipeline.prompt_book import (MissingPromptsError, prompts_dir,
                                  resolve_category_prompts)


def _book(tmp_path, **files):
    d = tmp_path / "prompts"
    d.mkdir()
    for stem, text in files.items():
        (d / f"{stem}.md").write_text(text)
    return str(tmp_path)


def test_resolves_each_category_to_its_file(tmp_path):
    p = _book(tmp_path, **{"Decoration": "DECO", "Food - 3 stages": "FOOD"})
    assert resolve_category_prompts(
        p, ["Decoration", "Food - 3 stages"]) == ["DECO", "FOOD"]


def test_repeats_resolve_identically(tmp_path):
    # Three paginated food sheets share one type — and one file read.
    p = _book(tmp_path, **{"Food - 3 stages": "FOOD"})
    assert resolve_category_prompts(p, ["Food - 3 stages"] * 3) == ["FOOD"] * 3


def test_missing_files_are_reported_together(tmp_path):
    # All at once: fail, write one file, fail again is the loop this prevents.
    p = _book(tmp_path, **{"Decoration": "DECO"})
    with pytest.raises(MissingPromptsError) as e:
        resolve_category_prompts(p, ["Decoration", "Signage",
                                     "Building - 4 stages"])
    assert [c for c, _ in e.value.missing] == ["Building - 4 stages", "Signage"]
    assert "Building - 4 stages.md" in str(e.value)
    assert "Signage.md" in str(e.value)


def test_empty_file_counts_as_missing(tmp_path):
    # A blank system prompt degrades output silently — worse than not running.
    p = _book(tmp_path, **{"Decoration": "   \n  "})
    with pytest.raises(MissingPromptsError):
        resolve_category_prompts(p, ["Decoration"])


def test_blank_category_is_its_own_error(tmp_path):
    # Would otherwise resolve to <project>/prompts/.md
    p = _book(tmp_path, **{"Decoration": "DECO"})
    with pytest.raises(ValueError, match="blank asset type"):
        resolve_category_prompts(p, ["Decoration", "  "])


def test_an_en_dash_is_a_different_type_not_a_silent_merge(tmp_path):
    # An en dash from an xlsx export used to slugify onto the hyphen form, so
    # two spellings quietly shared one prompt. Named verbatim they are two
    # files, and the missing one is reported by the exact name to create —
    # which is also how you notice the order sheet has a stray dash.
    p = _book(tmp_path, **{"Food - 3 stages": "FOOD"})
    with pytest.raises(MissingPromptsError, match="Food – 3 stages.md"):
        resolve_category_prompts(p, ["Food - 3 stages", "Food – 3 stages"])


def test_missing_prompts_dir_names_every_type(tmp_path):
    with pytest.raises(MissingPromptsError) as e:
        resolve_category_prompts(str(tmp_path), ["Decoration", "Signage"])
    assert len(e.value.missing) == 2


def test_prompts_dir_is_under_the_project():
    assert prompts_dir("/a/b").endswith("/a/b/prompts")
