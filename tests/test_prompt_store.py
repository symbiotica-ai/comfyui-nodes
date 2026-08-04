# ABOUTME: Read/write access to a project's prompt book — containment rules the
# ABOUTME: editor route depends on, and the backup a save leaves behind.
import os

import pytest

from pipeline.prompt_store import (PromptPathError, list_book, read_block,
                                   resolve, write_block)


def _book(tmp_path, rules=None, image=None, **types):
    d = tmp_path / "prompts"
    d.mkdir()
    for stem, text in types.items():
        (d / f"{stem}.md").write_text(text)
    for folder, files in (("_rules", rules), ("_image", image)):
        if not files:
            continue
        r = d / folder
        r.mkdir()
        for stem, text in files.items():
            (r / f"{stem}.md").write_text(text)
    return str(tmp_path)


def test_lists_rules_first_then_types(tmp_path):
    p = _book(tmp_path, rules={"01-a": "A", "02-b": "BB"},
              **{"Chair": "CHAIR", "Decoration": "DECO"})
    book = list_book(p)
    assert [e["name"] for e in book["rules"]] == ["_rules/01-a.md",
                                                  "_rules/02-b.md"]
    assert [e["name"] for e in book["types"]] == ["Chair.md", "Decoration.md"]
    assert book["types"][0]["title"] == "Chair"
    assert book["rules"][1]["chars"] == 2


def test_a_book_with_no_rules_lists_only_types(tmp_path):
    p = _book(tmp_path, **{"Chair": "C"})
    assert list_book(p)["rules"] == []


def test_reads_a_type_block_and_a_shared_rule(tmp_path):
    p = _book(tmp_path, rules={"03-light": "LIGHT"}, **{"Chair": "CHAIR"})
    assert read_block(p, "Chair.md") == "CHAIR"
    assert read_block(p, "_rules/03-light.md") == "LIGHT"


def test_traversal_out_of_the_book_is_refused(tmp_path):
    # The route hands user input straight to this — a crafted name must not be
    # able to read or overwrite a file outside the project's prompts folder.
    p = _book(tmp_path, **{"Chair": "C"})
    (tmp_path / "secret.md").write_text("SECRET")
    for name in ("../secret.md", "../../etc/passwd.md", "_rules/../../s.md"):
        with pytest.raises(PromptPathError):
            resolve(p, name)


def test_a_nested_folder_is_refused(tmp_path):
    # Prompts live in the book or its _rules/ — nowhere else, so a name cannot
    # quietly create a folder the composer will never read from.
    p = _book(tmp_path, **{"Chair": "C"})
    with pytest.raises(PromptPathError, match="_rules"):
        resolve(p, "deeper/Chair.md")


def test_a_non_markdown_name_is_refused(tmp_path):
    p = _book(tmp_path, **{"Chair": "C"})
    with pytest.raises(PromptPathError, match="not a prompt file"):
        resolve(p, "Chair.txt")


def test_no_project_is_refused(tmp_path):
    with pytest.raises(PromptPathError, match="no project"):
        resolve("", "Chair.md")


def test_saving_keeps_a_backup_of_what_it_replaced(tmp_path):
    p = _book(tmp_path, **{"Chair": "ORIGINAL"})
    write_block(p, "Chair.md", "EDITED")
    assert read_block(p, "Chair.md") == "EDITED\n"
    assert (tmp_path / "prompts" / "Chair.md.bak").read_text() == "ORIGINAL"


def test_saving_a_shared_rule_works_and_backs_up(tmp_path):
    p = _book(tmp_path, rules={"03-light": "SOFT"}, **{"Chair": "C"})
    write_block(p, "_rules/03-light.md", "HARD RIM")
    assert read_block(p, "_rules/03-light.md") == "HARD RIM\n"
    assert (tmp_path / "prompts" / "_rules" / "03-light.md.bak").read_text() \
        == "SOFT"


def test_a_new_rule_can_be_created(tmp_path):
    p = _book(tmp_path, rules={"01-a": "A"}, **{"Chair": "C"})
    write_block(p, "_rules/05-new.md", "NEW RULE")
    assert "_rules/05-new.md" in [e["name"] for e in list_book(p)["rules"]]


def test_a_trailing_newline_is_added_once(tmp_path):
    p = _book(tmp_path, **{"Chair": "C"})
    write_block(p, "Chair.md", "TEXT\n")
    assert read_block(p, "Chair.md") == "TEXT\n"


def test_lists_the_image_blocks_as_their_own_group(tmp_path):
    p = _book(tmp_path, rules={"01-a": "A"}, image={"01-image-model": "STYLE"},
              **{"Chair": "C"})
    book = list_book(p)
    assert [e["name"] for e in book["image"]] == ["_image/01-image-model.md"]
    # And they stay out of the other two groups — the panel shows three lists.
    assert [e["name"] for e in book["types"]] == ["Chair.md"]
    assert [e["name"] for e in book["rules"]] == ["_rules/01-a.md"]


def test_a_book_with_no_image_folder_lists_an_empty_group(tmp_path):
    p = _book(tmp_path, **{"Chair": "C"})
    assert list_book(p)["image"] == []


def test_an_image_block_can_be_read_and_created(tmp_path):
    p = _book(tmp_path, **{"Chair": "C"})
    write_block(p, "_image/01-image-model.md", "FLAT CEL SHADING")
    assert read_block(p, "_image/01-image-model.md") == "FLAT CEL SHADING\n"
    assert os.path.isdir(str(tmp_path / "prompts" / "_image"))


def test_backups_are_not_listed_as_blocks(tmp_path):
    # .bak and .before-split sit beside the real files; listing them would offer
    # the user a "prompt" that the composer never reads.
    p = _book(tmp_path, **{"Chair": "C"})
    write_block(p, "Chair.md", "EDITED")
    (tmp_path / "prompts" / "Chair.md.before-split").write_text("OLD")
    assert [e["name"] for e in list_book(p)["types"]] == ["Chair.md"]
