# ABOUTME: Tests for the prompt book — an order's asset types resolved to the
# ABOUTME: per-type architect prompts stored under
# ABOUTME: <project>/prompts/<Exact Category Name>.md.
import pytest

from pipeline.prompt_book import (MissingPromptsError, compose_detail,
                                  compose_image_prompt, prompts_dir,
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


def _with_rules(tmp_path, rules, **types):
    p = _book(tmp_path, **types)
    d = tmp_path / "prompts" / "_rules"
    d.mkdir()
    for name, text in rules.items():
        (d / f"{name}.md").write_text(text)
    return p


def test_shared_rules_come_first_and_the_type_block_last(tmp_path):
    # The type block wins ties by position: it is the most specific instruction
    # and sits where a long prompt is weighted heaviest.
    p = _with_rules(tmp_path, {"02-style": "STYLE", "01-reference": "REFS"},
                    **{"Decoration": "DECO BLOCK"})
    assert resolve_category_prompts(p, ["Decoration"]) == [
        "REFS\n\nSTYLE\n\nDECO BLOCK"]


def test_rules_order_follows_the_filename_prefix(tmp_path):
    p = _with_rules(tmp_path, {"03-c": "C", "01-a": "A", "02-b": "B"},
                    **{"Decoration": "D"})
    assert resolve_category_prompts(p, ["Decoration"]) == ["A\n\nB\n\nC\n\nD"]


def test_no_rules_directory_is_todays_behaviour(tmp_path):
    # Nothing may change for a project that has not been split into blocks.
    p = _book(tmp_path, **{"Decoration": "JUST THE TYPE"})
    assert resolve_category_prompts(p, ["Decoration"]) == ["JUST THE TYPE"]


def test_blank_rule_files_are_skipped_not_emitted(tmp_path):
    # An emptied rule must vanish from the prompt, not leave a hole in it.
    p = _with_rules(tmp_path, {"01-a": "A", "02-empty": "   \n ", "03-c": "C"},
                    **{"Decoration": "D"})
    assert resolve_category_prompts(p, ["Decoration"]) == ["A\n\nC\n\nD"]


def test_every_type_shares_the_rules_and_differs_by_its_own_block(tmp_path):
    p = _with_rules(tmp_path, {"01-lighting": "LIGHT"},
                    **{"Decoration": "DECO", "Food - 3 stages": "FOOD"})
    out = resolve_category_prompts(p, ["Decoration", "Food - 3 stages"])
    assert out == ["LIGHT\n\nDECO", "LIGHT\n\nFOOD"]


def test_a_missing_type_block_still_raises_even_with_rules(tmp_path):
    # The shared half describes the game, not this asset — it cannot stand in.
    p = _with_rules(tmp_path, {"01-lighting": "LIGHT"}, **{"Decoration": "D"})
    with pytest.raises(MissingPromptsError, match="Signage.md"):
        resolve_category_prompts(p, ["Decoration", "Signage"])


def test_non_markdown_files_in_rules_are_ignored(tmp_path):
    p = _with_rules(tmp_path, {"01-a": "A"}, **{"Decoration": "D"})
    (tmp_path / "prompts" / "_rules" / "notes.txt").write_text("NOT A RULE")
    assert resolve_category_prompts(p, ["Decoration"]) == ["A\n\nD"]


def _with_image(tmp_path, image, rules=None, **types):
    p = _with_rules(tmp_path, rules or {}, **types)
    d = tmp_path / "prompts" / "_image"
    d.mkdir()
    for name, text in image.items():
        (d / f"{name}.md").write_text(text)
    return p


def test_image_prompt_joins_its_blocks_in_filename_order(tmp_path):
    p = _with_image(tmp_path, {"02-light": "LIGHT", "01-style": "STYLE"},
                    **{"Decoration": "D"})
    assert compose_image_prompt(p) == "STYLE\n\nLIGHT"


def test_image_prompt_is_empty_before_the_folder_exists(tmp_path):
    # The node carrying this output is the editor that creates the folder, so
    # absence has to load rather than raise.
    p = _book(tmp_path, **{"Decoration": "D"})
    assert compose_image_prompt(p) == ""


def test_image_blocks_stay_out_of_the_architect_prompt(tmp_path):
    # Two documents in one book: what the asset IS goes to the LLM, how it is
    # DRAWN goes to the image model. Leaking either way doubles a rule.
    p = _with_image(tmp_path, {"01-style": "IMAGE STYLE"},
                    rules={"01-a": "RULE"}, **{"Decoration": "DECO"})
    assert resolve_category_prompts(p, ["Decoration"]) == ["RULE\n\nDECO"]


def test_composed_detail_is_byte_identical_to_what_the_queue_resolves(tmp_path):
    # The point of the preview: if these two ever differ, the preview lies at
    # exactly the moment it is consulted.
    p = _with_rules(tmp_path, {"01-a": "A", "02-b": "B"}, **{"Chair": "CHAIR"})
    detail = compose_detail(p, "Chair")
    assert detail["text"] == resolve_category_prompts(p, ["Chair"])[0]


def test_composed_detail_names_its_blocks_in_order_with_sizes(tmp_path):
    p = _with_rules(tmp_path, {"01-a": "AAA", "02-b": "B"}, **{"Chair": "CH"})
    assert compose_detail(p, "Chair")["blocks"] == [
        {"name": "_rules/01-a.md", "chars": 3},
        {"name": "_rules/02-b.md", "chars": 1},
        {"name": "Chair.md", "chars": 2},
    ]


def test_composed_detail_of_a_missing_type_raises(tmp_path):
    p = _with_rules(tmp_path, {"01-a": "A"}, **{"Chair": "C"})
    with pytest.raises(MissingPromptsError, match="Signage.md"):
        compose_detail(p, "Signage")


def test_composed_detail_needs_a_type(tmp_path):
    p = _book(tmp_path, **{"Chair": "C"})
    with pytest.raises(ValueError, match="no asset type"):
        compose_detail(p, "  ")
