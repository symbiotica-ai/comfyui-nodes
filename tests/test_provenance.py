# ABOUTME: The per-render record — a hash per BLOCK so feedback can name which
# ABOUTME: rule was at fault, and a log that survives a killed run.
import json

from pipeline.provenance import (append_records, block_manifest, build_record,
                                 log_path, read_records, sha)


def _book(tmp_path, rules=None, **types):
    d = tmp_path / "prompts"
    d.mkdir()
    for stem, text in types.items():
        (d / f"{stem}.md").write_text(text)
    if rules:
        r = d / "_rules"
        r.mkdir()
        for stem, text in rules.items():
            (r / f"{stem}.md").write_text(text)
    return str(tmp_path)


def test_manifest_hashes_each_block_separately(tmp_path):
    # One hash over the composed prompt could not tell a lighting change from a
    # negatives change — which is the whole point of aiming feedback.
    p = _book(tmp_path, rules={"01-refs": "REFS", "03-light": "LIGHT"},
              **{"Chair": "CHAIR"})
    man = block_manifest(p, "Chair")
    assert [b["block"] for b in man] == ["_rules/01-refs.md",
                                         "_rules/03-light.md", "Chair.md"]
    assert len({b["sha"] for b in man}) == 3


def test_manifest_order_matches_composition(tmp_path):
    p = _book(tmp_path, rules={"02-b": "B", "01-a": "A"}, **{"Chair": "C"})
    assert [b["block"] for b in block_manifest(p, "Chair")][:2] == [
        "_rules/01-a.md", "_rules/02-b.md"]


def test_editing_one_rule_changes_only_its_hash(tmp_path):
    p = _book(tmp_path, rules={"01-refs": "REFS", "03-light": "SOFT"},
              **{"Chair": "CHAIR"})
    before = {b["block"]: b["sha"] for b in block_manifest(p, "Chair")}
    (tmp_path / "prompts" / "_rules" / "03-light.md").write_text("HARD RIM")
    after = {b["block"]: b["sha"] for b in block_manifest(p, "Chair")}
    assert after["_rules/03-light.md"] != before["_rules/03-light.md"]
    assert after["_rules/01-refs.md"] == before["_rules/01-refs.md"]
    assert after["Chair.md"] == before["Chair.md"]


def test_a_blank_rule_is_not_in_the_manifest(tmp_path):
    # It is skipped when composing, so recording it would describe a prompt
    # that was never sent.
    p = _book(tmp_path, rules={"01-a": "A", "02-empty": "  \n "},
              **{"Chair": "C"})
    assert [b["block"] for b in block_manifest(p, "Chair")] == [
        "_rules/01-a.md", "Chair.md"]


def test_record_hashes_the_text_actually_sent(tmp_path):
    p = _book(tmp_path, rules={"01-a": "A"}, **{"Chair": "C"})
    rec = build_record(project_path=p, asset_name="Ghost Bakery Queue",
                       category="Chair", system_prompt="A\n\nC",
                       reference="Woodland.png", seed=7)
    assert rec["prompt_sha"] == sha("A\n\nC")
    assert rec["asset"] == "Ghost Bakery Queue"
    assert rec["reference"] == "Woodland.png" and rec["seed"] == 7
    assert len(rec["blocks"]) == 2


def test_the_record_stays_true_after_the_files_change(tmp_path):
    # The hash is of the sent text, not of today's files — a record that
    # silently re-points at edited prompts is worse than no record.
    p = _book(tmp_path, rules={"01-a": "A"}, **{"Chair": "C"})
    rec = build_record(project_path=p, asset_name="X", category="Chair",
                       system_prompt="A\n\nC")
    (tmp_path / "prompts" / "Chair.md").write_text("COMPLETELY DIFFERENT")
    assert rec["prompt_sha"] == sha("A\n\nC")


def test_log_is_one_json_object_per_line(tmp_path):
    p = _book(tmp_path, **{"Chair": "C"})
    recs = [build_record(project_path=p, asset_name=f"a{i}", category="Chair",
                         system_prompt="S") for i in range(3)]
    assert append_records(p, recs, timestamp="20260803-101500") == 3
    lines = open(log_path(p), encoding="utf-8").read().strip().split("\n")
    assert len(lines) == 3
    assert json.loads(lines[0])["at"] == "20260803-101500"


def test_appending_keeps_earlier_runs(tmp_path):
    p = _book(tmp_path, **{"Chair": "C"})
    one = build_record(project_path=p, asset_name="first", category="Chair",
                       system_prompt="S")
    append_records(p, [one])
    append_records(p, [build_record(project_path=p, asset_name="second",
                                    category="Chair", system_prompt="S")])
    assert [r["asset"] for r in read_records(p)] == ["first", "second"]


def test_a_truncated_line_does_not_hide_the_good_records(tmp_path):
    # A killed run can leave half a line. Everything before it must still read.
    p = _book(tmp_path, **{"Chair": "C"})
    append_records(p, [build_record(project_path=p, asset_name="good",
                                    category="Chair", system_prompt="S")])
    with open(log_path(p), "a", encoding="utf-8") as fh:
        fh.write('{"asset": "half-writ')
    assert [r["asset"] for r in read_records(p)] == ["good"]


def test_reading_a_project_with_no_log_is_empty_not_an_error(tmp_path):
    assert read_records(_book(tmp_path, **{"Chair": "C"})) == []


def test_an_unwritable_log_does_not_lose_the_images(tmp_path):
    # append_records is called after the PNGs are on disk; raising here would
    # fail a render that already succeeded.
    assert append_records("/nonexistent-root-xyz", [{"asset": "a"}]) == 0
