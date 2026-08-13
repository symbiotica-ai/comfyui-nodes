# ABOUTME: The grid layout an asset type is drawn on — how a category names it,
# ABOUTME: and how a new version wins without anything being renamed.
import os

import pytest

from pipeline.layouts import (built_dir, layouts_dir, list_layouts,
                              newest_for, newest_in, pick_layout)


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


class TestAssetkitsOwnFolders:
    """assetkit builds them into `datasets/dataset-single/<Category> Layout/`
    and names them its own way. Read in place rather than copied here — the
    file is already on disk, and a second copy is a second thing to keep in
    step."""

    def built(self, tmp_path, folder, *names):
        root = tmp_path / "bakery"
        where = root / "datasets" / "dataset-single" / folder
        where.mkdir(parents=True, exist_ok=True)
        for name in names:
            (where / name).write_bytes(b"")
        return str(root)

    def test_the_built_folder_answers_for_the_category(self, tmp_path):
        project = self.built(tmp_path, "Chair Layout", "Chair-layout-01.png")
        assert os.path.basename(
            pick_layout(project, "Chair")) == "Chair-layout-01.png"

    def test_assetkit_s_underscores_still_match(self, tmp_path):
        """`Chair Layout` beside `Food_-_3_stages Layout` — matching on the
        exact string finds one and misses the other."""
        project = self.built(tmp_path, "Food_-_3_stages Layout",
                             "Food_-_3_stages-layout-01.png")
        assert os.path.basename(pick_layout(project, "Food - 3 stages")) \
            == "Food_-_3_stages-layout-01.png"

    def test_the_highest_numbered_sheet_wins(self, tmp_path):
        project = self.built(tmp_path, "Chair Layout", "Chair-layout-01.png",
                             "Chair-layout-06.png", "Chair-layout-10.png")
        assert os.path.basename(
            pick_layout(project, "Chair")) == "Chair-layout-10.png"

    def test_a_hand_placed_file_beats_the_built_one(self, tmp_path):
        """`datasets/layouts/` is the override — how a grid gets tried without
        rebuilding the set."""
        project = self.built(tmp_path, "Chair Layout", "Chair-layout-01.png")
        layouts = tmp_path / "bakery" / "datasets" / "layouts"
        layouts.mkdir(parents=True)
        (layouts / "Chair.png").write_bytes(b"")
        assert os.path.basename(pick_layout(project, "Chair")) == "Chair.png"

    def test_a_bucket_folder_beats_the_plain_category(self, tmp_path):
        project = self.built(tmp_path, "Food - 3 stages Layout",
                             "Food-layout-01.png")
        self.built(tmp_path, "Food - 3 stages - Drinks Layout",
                   "Drinks-layout-01.png")
        assert os.path.basename(
            pick_layout(project, "Food - 3 stages", "Drinks")
        ) == "Drinks-layout-01.png"

    def test_a_bucket_with_no_built_folder_falls_back(self, tmp_path):
        project = self.built(tmp_path, "Chair Layout", "Chair-layout-01.png")
        assert os.path.basename(
            pick_layout(project, "Chair", "Drinks")) == "Chair-layout-01.png"

    def test_a_category_with_no_folder_finds_nothing(self, tmp_path):
        project = self.built(tmp_path, "Chair Layout", "Chair-layout-01.png")
        assert pick_layout(project, "Wallpaper") == ""

    def test_a_folder_of_non_images_finds_nothing(self, tmp_path):
        project = self.built(tmp_path, "Chair Layout", "notes.txt")
        assert pick_layout(project, "Chair") == ""

    def test_no_category_never_matches_a_bare_layout_folder(self, tmp_path):
        """An empty category must not resolve to a folder called "Layout"."""
        project = self.built(tmp_path, "Layout", "anything-01.png")
        assert pick_layout(project, "") == ""
