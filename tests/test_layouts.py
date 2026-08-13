# ABOUTME: The grid layout an asset type is drawn on — how a category names it,
# ABOUTME: and how a new version wins without anything being renamed.
import os

import pytest

from pipeline.layouts import (layouts_dir, list_layouts, newest_for,
                              pick_layout)


def project_with(tmp_path, *names):
    root = tmp_path / "bakery"
    folder = root / "datasets" / "layouts"
    folder.mkdir(parents=True)
    for name in names:
        (folder / name).write_bytes(b"")
    return str(root)


class TestWhatTheFolderHolds:
    def test_only_images_and_never_dotfiles(self, tmp_path):
        project = project_with(tmp_path, "Chair.png", "notes.txt",
                               ".DS_Store", "Table.webp")
        assert list_layouts(project) == ["Chair.png", "Table.webp"]

    def test_a_missing_folder_is_empty_not_an_error(self, tmp_path):
        assert list_layouts(str(tmp_path / "nowhere")) == []

    def test_the_folder_is_under_datasets(self, tmp_path):
        assert layouts_dir("/p/bakery") == os.path.join(
            "/p/bakery", "datasets", "layouts")


class TestWhichFileACategoryNames:
    def test_the_plain_category(self, tmp_path):
        project = project_with(tmp_path, "Food - 3 stages.png", "Chair.png")
        assert os.path.basename(
            pick_layout(project, "Food - 3 stages")) == "Food - 3 stages.png"

    def test_a_bucket_narrows_it(self, tmp_path):
        project = project_with(tmp_path, "Food - 3 stages.png",
                               "Food - 3 stages - Drinks.png")
        assert os.path.basename(
            pick_layout(project, "Food - 3 stages", "Drinks")
        ) == "Food - 3 stages - Drinks.png"

    def test_a_bucket_with_no_layout_falls_back(self, tmp_path):
        """A narrowing, never a demand — the same ladder the recipe climbs."""
        project = project_with(tmp_path, "Food - 3 stages.png")
        assert os.path.basename(
            pick_layout(project, "Food - 3 stages", "Drinks")
        ) == "Food - 3 stages.png"

    def test_a_category_with_nothing_is_empty(self, tmp_path):
        project = project_with(tmp_path, "Chair.png")
        assert pick_layout(project, "Wallpaper") == ""

    def test_nothing_wired_names_nothing(self, tmp_path):
        project = project_with(tmp_path, "Chair.png")
        assert pick_layout(project, "") == ""


class TestANewVersionWinsWithoutARename:
    """"add grid-food7 without renaming anything" — a new version is a new
    file, and the newest one is what runs."""

    def test_the_highest_number_wins(self, tmp_path):
        project = project_with(tmp_path, "Food - 3 stages.png",
                               "Food - 3 stages-6.png",
                               "Food - 3 stages-7.png")
        assert os.path.basename(
            pick_layout(project, "Food - 3 stages")) == "Food - 3 stages-7.png"

    def test_ten_beats_nine(self, tmp_path):
        # Sorted as text, `-10` lands before `-9` and the older file wins.
        project = project_with(tmp_path, "Chair-9.png", "Chair-10.png")
        assert os.path.basename(pick_layout(project, "Chair")) == "Chair-10.png"

    def test_a_v_prefix_and_other_separators_count(self, tmp_path):
        for name in ("Chair_v2.png", "Chair 2.png", "Chair.2.png"):
            project = project_with(tmp_path / name, "Chair.png", name)
            assert os.path.basename(pick_layout(project, "Chair")) == name

    def test_a_longer_name_is_not_a_version_of_a_shorter_one(self, tmp_path):
        # `Food - 3 stages - Drinks` must never answer for `Food - 3 stages`,
        # or every food asset would be drawn on the drinks grid.
        project = project_with(tmp_path, "Food - 3 stages - Drinks.png")
        assert pick_layout(project, "Food - 3 stages") == ""

    def test_newest_for_answers_nothing_for_no_name(self, tmp_path):
        project = project_with(tmp_path, "Chair.png")
        assert newest_for(project, "") == ""


class TestPinningOneByName:
    def test_a_pinned_name_beats_the_category(self, tmp_path):
        project = project_with(tmp_path, "Chair.png", "experiment-4.png")
        assert os.path.basename(
            pick_layout(project, "Chair", "", "experiment-4.png")
        ) == "experiment-4.png"

    def test_a_pin_without_the_extension_still_finds_it(self, tmp_path):
        project = project_with(tmp_path, "experiment-4.png")
        assert os.path.basename(
            pick_layout(project, "", "", "experiment-4")) == "experiment-4.png"

    def test_a_pin_cannot_reach_outside_the_folder(self, tmp_path):
        """Matched against the listing rather than joined onto the path — the
        same reason the prompt store resolves a block by name."""
        project = project_with(tmp_path, "Chair.png")
        (tmp_path / "bakery" / "secret.png").write_bytes(b"")
        assert pick_layout(project, "Chair", "", "../secret.png") == ""

    def test_a_pin_that_is_gone_names_nothing_rather_than_guessing(self, tmp_path):
        project = project_with(tmp_path, "Chair.png")
        assert pick_layout(project, "Chair", "", "deleted.png") == ""
