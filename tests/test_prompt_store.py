# ABOUTME: Read/write access to a folder of prompt files — the listing the
# ABOUTME: Prompts dropdown shows, containment, the backup a save leaves behind.
import os

import pytest

from pipeline.prompt_store import (PromptPathError, list_files, list_folders,
                                   make_folder, read_file, rename,
                                   resolve_file, write_file)


def _folder(tmp_path, **files):
    d = tmp_path / "prompts"
    d.mkdir()
    for name, text in files.items():
        path = d / name.replace("__", "/")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return str(d)


# --- listing ------------------------------------------------------------------

def test_lists_every_text_file_with_its_subfolder(tmp_path):
    p = _folder(tmp_path, **{"_rules__01-a.md": "A", "Chair.md": "C",
                             "notes.txt": "N", "_image__01-model.md": "M"})
    assert list_files(p) == ["Chair.md", "_image/01-model.md",
                             "_rules/01-a.md", "notes.txt"]


def test_a_nested_subfolder_is_listed_too(tmp_path):
    p = _folder(tmp_path, **{"a__b__deep.md": "D"})
    assert list_files(p) == ["a/b/deep.md"]


def test_backups_dotfiles_and_other_types_are_not_listed(tmp_path):
    p = _folder(tmp_path, **{"Chair.md": "C", "Chair.md.bak": "OLD",
                             ".hidden.md": "H", "recipe.json": "{}",
                             ".git__x.md": "G"})
    assert list_files(p) == ["Chair.md"]


def test_a_missing_folder_lists_nothing(tmp_path):
    assert list_files(str(tmp_path / "nope")) == []
    assert list_files("") == []


def test_lists_every_subfolder_including_empty_and_nested(tmp_path):
    p = _folder(tmp_path, **{"_rules__01-a.md": "A", "a__b__deep.md": "D"})
    os.makedirs(os.path.join(p, "_flip"))            # empty: still offered
    os.makedirs(os.path.join(p, ".git", "objects"))  # dot-folder: never
    assert list_folders(p) == ["_flip", "_rules", "a", "a/b"]


def test_a_missing_path_lists_no_folders(tmp_path):
    assert list_folders(str(tmp_path / "nope")) == []
    assert list_folders("") == []


# --- containment --------------------------------------------------------------

def test_traversal_out_of_the_folder_is_refused(tmp_path):
    p = _folder(tmp_path)
    (tmp_path / "secret.md").write_text("S")
    with pytest.raises(PromptPathError):
        resolve_file(p, "../secret.md")
    with pytest.raises(PromptPathError):
        read_file(p, "../secret.md")


def test_a_non_text_name_is_refused(tmp_path):
    p = _folder(tmp_path)
    with pytest.raises(PromptPathError):
        resolve_file(p, "recipe.json")
    with pytest.raises(PromptPathError):
        resolve_file(p, "Chair.md.bak")


def test_no_folder_is_refused(tmp_path):
    with pytest.raises(PromptPathError):
        resolve_file("", "Chair.md")
    with pytest.raises(PromptPathError):
        resolve_file(str(tmp_path), "")


def test_a_txt_file_reads_and_writes(tmp_path):
    p = _folder(tmp_path, **{"notes.txt": "N\n"})
    assert read_file(p, "notes.txt") == "N\n"
    write_file(p, "notes.txt", "NN")
    assert read_file(p, "notes.txt") == "NN\n"


# --- saving -------------------------------------------------------------------

def test_saving_keeps_a_backup_of_what_it_replaced(tmp_path):
    p = _folder(tmp_path, **{"Chair.md": "OLD\n"})
    out = write_file(p, "Chair.md", "NEW\n")
    assert out == {"name": "Chair.md", "chars": 4}
    assert read_file(p, "Chair.md") == "NEW\n"
    assert open(os.path.join(p, "Chair.md.bak")).read() == "OLD\n"


def test_a_new_file_in_a_new_subfolder_is_created(tmp_path):
    p = _folder(tmp_path)
    write_file(p, "_rules/09-new.md", "RULE")
    assert read_file(p, "_rules/09-new.md") == "RULE\n"
    assert not os.path.exists(os.path.join(p, "_rules", "09-new.md.bak"))


def test_a_trailing_newline_is_added_once(tmp_path):
    p = _folder(tmp_path)
    write_file(p, "A.md", "x\n")
    assert read_file(p, "A.md") == "x\n"
    write_file(p, "B.md", "")
    assert read_file(p, "B.md") == ""


def test_a_backslash_name_is_read_as_a_path(tmp_path):
    p = _folder(tmp_path, **{"_rules__01-a.md": "A"})
    assert read_file(p, "_rules\\01-a.md") == "A"
    assert write_file(p, "_rules\\01-a.md", "B")["name"] == "_rules/01-a.md"


# --- folders ------------------------------------------------------------------

def test_a_subfolder_is_created_inside_the_folder(tmp_path):
    p = _folder(tmp_path)
    assert make_folder(p, "_flip") == {"name": "_flip"}
    assert os.path.isdir(os.path.join(p, "_flip"))
    assert make_folder(p, "_flip") == {"name": "_flip"}   # existing is fine
    assert make_folder(p, "a/b/") == {"name": "a/b"}
    assert os.path.isdir(os.path.join(p, "a", "b"))


def test_a_folder_cannot_climb_out(tmp_path):
    p = _folder(tmp_path)
    with pytest.raises(PromptPathError):
        make_folder(p, "../escape")
    with pytest.raises(PromptPathError):
        make_folder(p, "")
    with pytest.raises(PromptPathError):
        make_folder(p, ".")
    assert not os.path.exists(str(tmp_path / "escape"))


# --- renaming -----------------------------------------------------------------

def test_a_file_is_renamed_in_place(tmp_path):
    p = _folder(tmp_path, **{"_rules__01-a.md": "A"})
    assert rename(p, "_rules/01-a.md", "_rules/01-b.md") == {
        "from": "_rules/01-a.md", "to": "_rules/01-b.md"}
    assert list_files(p) == ["_rules/01-b.md"]
    assert read_file(p, "_rules/01-b.md") == "A"


def test_a_folder_is_renamed_with_everything_in_it(tmp_path):
    p = _folder(tmp_path, **{"_rules__01-a.md": "A", "_rules__old__x.md": "X"})
    rename(p, "_rules", "rules")
    assert list_folders(p) == ["rules", "rules/old"]
    assert list_files(p) == ["rules/01-a.md", "rules/old/x.md"]


def test_a_rename_never_lands_on_an_existing_name(tmp_path):
    p = _folder(tmp_path, **{"A.md": "A", "B.md": "B"})
    with pytest.raises(PromptPathError):
        rename(p, "A.md", "B.md")
    assert read_file(p, "B.md") == "B"


def test_a_rename_stays_inside_and_keeps_a_prompt_extension(tmp_path):
    p = _folder(tmp_path, **{"A.md": "A"})
    with pytest.raises(PromptPathError):
        rename(p, "A.md", "../A.md")
    with pytest.raises(PromptPathError):
        rename(p, "A.md", "A.json")
    with pytest.raises(PromptPathError):
        rename(p, "missing.md", "B.md")
    with pytest.raises(PromptPathError):
        rename(p, "", "B")
    assert list_files(p) == ["A.md"]


# --- recipes ------------------------------------------------------------------

class TestRecipes:
    """A recipe is a saved set of blocks — the preset that turns "change three
    prompts" into "change one widget"."""

    def test_a_saved_recipe_comes_back_with_its_slots(self, tmp_path):
        from pipeline.prompt_store import recipes, write_recipe
        book = tmp_path / "prompts"
        (book / "_rules").mkdir(parents=True)
        (book / "_flip").mkdir(parents=True)
        (book / "_rules" / "01-llm-prompt.md").write_text("A\n")
        (book / "_flip" / "01-flip.md").write_text("B\n")
        write_recipe(str(tmp_path), "Decoration", [
            {"block": "_rules/01-llm-prompt.md", "version": ""},
            {"block": "_flip/01-flip.md", "version": "tight"}])
        saved = recipes(str(tmp_path))
        assert [r["name"] for r in saved] == ["Decoration"]
        assert saved[0]["slots"] == [
            {"block": "_rules/01-llm-prompt.md", "version": ""},
            {"block": "_flip/01-flip.md", "version": "tight"}]

    def test_a_recipe_cannot_name_a_file_outside_the_book(self, tmp_path):
        """A recipe the reader trusts is a file-read primitive if it can point
        anywhere on disk."""
        from pipeline.prompt_store import PromptPathError, write_recipe
        (tmp_path / "prompts").mkdir()
        with pytest.raises(PromptPathError):
            write_recipe(str(tmp_path), "Bad",
                         [{"block": "../../../etc/passwd.md"}])

    def test_a_recipe_name_is_a_name_not_a_path(self, tmp_path):
        from pipeline.prompt_store import PromptPathError, write_recipe
        (tmp_path / "prompts").mkdir()
        with pytest.raises(PromptPathError):
            write_recipe(str(tmp_path), "../escape", [])

    def test_deleting_a_recipe_leaves_its_blocks(self, tmp_path):
        from pipeline.prompt_store import (delete_recipe, recipes,
                                           write_recipe)
        book = tmp_path / "prompts"
        (book / "_rules").mkdir(parents=True)
        (book / "_rules" / "01-llm-prompt.md").write_text("A\n")
        write_recipe(str(tmp_path), "Gone",
                     [{"block": "_rules/01-llm-prompt.md"}])
        assert delete_recipe(str(tmp_path), "Gone")["removed"] is True
        assert recipes(str(tmp_path)) == []
        assert (book / "_rules" / "01-llm-prompt.md").exists()
