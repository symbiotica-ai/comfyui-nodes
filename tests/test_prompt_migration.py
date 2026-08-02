# ABOUTME: The one-time split of monolithic per-type prompts into shared
# ABOUTME: _rules/ blocks plus the type-specific remainder.
import os

import pytest

from pipeline.prompt_book import resolve_category_prompts
from pipeline.prompt_migration import (apply_migration, plan_migration,
                                       renumber, split_sections)

DECO = """ROLE
You are an architect for decorations.

YOUR JOB
Emit JSON.

HARD RULES YOU MUST ALWAYS ENCODE IN THE JSON
1. REFERENCE USAGE SPLIT — deco wording, short.
2. STYLE LOCK — match the reference exactly.
3. UNIFIED LIGHTING — one key light.
4. TWO UNIQUE RENDERS — left and right.
"""

FOOD = """ROLE
You are an architect for food.

YOUR JOB
Emit JSON.

HARD RULES YOU MUST ALWAYS ENCODE IN THE JSON
1. REFERENCE USAGE SPLIT — food wording, considerably longer than the deco one.
2. STYLE LOCK — short.
3. UNIFIED LIGHTING — a much longer lighting rule with more detail in it.
4. NEGATIVES — no blur, no text.
5. THREE UNIQUE RENDERS — prep, ready, serving.
"""


def _book(tmp_path, **files):
    d = tmp_path / "prompts"
    d.mkdir()
    for stem, text in files.items():
        (d / f"{stem}.md").write_text(text)
    return str(tmp_path)


def test_split_keeps_the_preamble_separate():
    secs = split_sections(DECO)
    assert secs[0][0] == "", "ROLE / YOUR JOB is not a numbered rule"
    assert "ROLE" in secs[0][1]
    assert [h for h, _ in secs[1:]] == [
        "REFERENCE USAGE SPLIT", "STYLE LOCK", "UNIFIED LIGHTING",
        "TWO UNIQUE RENDERS"]


def test_plan_takes_the_longest_wording_and_names_its_source(tmp_path):
    p = _book(tmp_path, **{"Decoration": DECO, "Food - 3 stages": FOOD})
    plan = plan_migration(p)
    by = {b["heading"]: b for b in plan["extracted"]}
    # Food's reference and lighting rules are the longer ones; style is deco's.
    assert by["REFERENCE USAGE SPLIT"]["source"] == "Food - 3 stages"
    assert by["UNIFIED LIGHTING"]["source"] == "Food - 3 stages"
    assert by["STYLE LOCK"]["source"] == "Decoration"


def test_a_rule_absent_from_some_types_is_still_extracted(tmp_path):
    # NEGATIVES is in food only, as it is in 6 of his 8 real prompts.
    p = _book(tmp_path, **{"Decoration": DECO, "Food - 3 stages": FOOD})
    plan = plan_migration(p)
    neg = [b for b in plan["extracted"] if b["heading"] == "NEGATIVES"]
    assert neg and neg[0]["in_types"] == ["Food - 3 stages"]


def test_apply_writes_the_rules_and_shrinks_the_type_files(tmp_path):
    p = _book(tmp_path, **{"Decoration": DECO, "Food - 3 stages": FOOD})
    res = apply_migration(p)
    rules = sorted(os.listdir(res["rules_dir"]))
    assert rules == ["01-reference-usage-split.md", "02-style-lock.md",
                     "03-unified-lighting.md", "04-negatives.md"]
    for c in res["changed"]:
        assert c["after"] < c["before"], f"{c['category']} did not shrink"
    left = (tmp_path / "prompts" / "Decoration.md").read_text()
    assert "STYLE LOCK" not in left and "TWO UNIQUE RENDERS" in left
    assert "ROLE" in left, "the type's preamble must survive"


def test_the_composed_prompt_still_carries_every_rule(tmp_path):
    # The point of the whole exercise: splitting must not lose text.
    p = _book(tmp_path, **{"Decoration": DECO, "Food - 3 stages": FOOD})
    apply_migration(p)
    composed = resolve_category_prompts(p, ["Decoration"])[0]
    for rule in ("REFERENCE USAGE SPLIT", "STYLE LOCK", "UNIFIED LIGHTING",
                 "TWO UNIQUE RENDERS"):
        assert rule in composed, f"{rule} vanished from the composed prompt"
    assert composed.index("STYLE LOCK") < composed.index("TWO UNIQUE RENDERS")


def test_what_is_left_is_renumbered_without_gaps(tmp_path):
    p = _book(tmp_path, **{"Decoration": DECO, "Food - 3 stages": FOOD})
    apply_migration(p)
    food = (tmp_path / "prompts" / "Food - 3 stages.md").read_text()
    # Only THREE UNIQUE RENDERS survives; a gappy "5." reads as a missing rule.
    assert "1. THREE UNIQUE RENDERS" in food


def test_backups_are_written_before_anything_is_modified(tmp_path):
    p = _book(tmp_path, **{"Decoration": DECO, "Food - 3 stages": FOOD})
    apply_migration(p)
    backup = tmp_path / "prompts" / "Decoration.md.before-split"
    assert backup.exists() and backup.read_text() == DECO


def test_running_twice_is_refused(tmp_path):
    p = _book(tmp_path, **{"Decoration": DECO, "Food - 3 stages": FOOD})
    apply_migration(p)
    with pytest.raises(FileExistsError, match="already"):
        apply_migration(p)


def test_a_book_with_no_shared_rules_is_refused(tmp_path):
    p = _book(tmp_path, **{"Decoration": "ROLE\nno numbered rules here\n"})
    with pytest.raises(ValueError, match="nothing to split"):
        apply_migration(p)


def test_renumber_leaves_a_gapless_sequence():
    secs = split_sections(FOOD)
    kept = [(h, b) for h, b in secs if h in ("", "NEGATIVES",
                                             "THREE UNIQUE RENDERS")]
    out = renumber(kept)
    assert "1. NEGATIVES" in out and "2. THREE UNIQUE RENDERS" in out
