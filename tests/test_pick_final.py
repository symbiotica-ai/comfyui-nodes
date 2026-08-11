# ABOUTME: Approving a render writes a `_final` copy beside it — the approval
# ABOUTME: as a file, so a second node can read it. A tick cannot be read.
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "py"))

from pipeline.pick_folder import (FINAL_STAGE, approve, final_name, finals_in,
                                  images_in, listing_for, name_matches_prefix,
                                  parent_of)


def write(folder, *names):
    from PIL import Image
    os.makedirs(folder, exist_ok=True)
    for name in names:
        Image.new("RGB", (4, 4)).save(os.path.join(folder, name))


class TestTheNameCarriesTheApproval:
    def test_the_final_lists_under_its_own_stage(self):
        """`names="_final"` has to find it through the machinery that already
        exists, or the approved view needs code the pack does not need."""
        assert name_matches_prefix(final_name("_base_00007_.png"), FINAL_STAGE)

    def test_the_name_says_which_render_was_approved(self):
        """The trailing counter is what `parent_of` strips to read the mark
        back — without one it resolves to the parent's STAGE, not the parent."""
        assert parent_of(final_name("_base_00007_.png")) == "_base_00007_"

    def test_it_does_not_list_under_the_render_stage(self):
        """Otherwise approving doubles every asset in the grid it came from."""
        assert not name_matches_prefix(final_name("_base_00007_.png"), "_base")

    def test_the_extension_is_kept(self):
        assert final_name("_base_00007_.webp").endswith(".webp")


class TestApproving:
    def test_it_copies_and_leaves_the_render(self, tmp_path):
        """A rename would break the tick that points at the render AND orphan
        any edit whose filename carries `_from.<it>`."""
        folder = str(tmp_path)
        write(folder, "_base_00007_.png")
        written = approve(folder, ["_base_00007_.png"])
        assert [os.path.basename(p) for p in written] == [
            "_final_from._base_00007__00001_.png"]
        assert os.path.isfile(os.path.join(folder, "_base_00007_.png"))

    def test_the_final_sits_beside_its_render(self, tmp_path):
        """The folder the picker lists — approving must not move work out of
        view."""
        folder = str(tmp_path)
        write(folder, "_base_00007_.png")
        written = approve(folder, ["_base_00007_.png"])
        assert os.path.dirname(written[0]) == folder

    def test_un_approving_removes_it(self, tmp_path):
        """The badge and the file have to agree: the tracker reads the file."""
        folder = str(tmp_path)
        write(folder, "_base_00007_.png")
        approve(folder, ["_base_00007_.png"])
        approve(folder, ["_base_00007_.png"], on=False)
        assert images_in(folder, FINAL_STAGE) == []
        assert os.path.isfile(os.path.join(folder, "_base_00007_.png"))

    def test_a_name_the_node_does_not_show_is_refused(self, tmp_path):
        """Scoped like `discard`: matched against the listing, never joined
        onto a path, so a request can no more approve by path than read by
        one."""
        folder = str(tmp_path / "asset")
        write(folder, "_base_00007_.png")
        outside = tmp_path / "secret.png"
        write(str(tmp_path), "secret.png")
        assert approve(folder, ["../secret.png", "secret.png"]) == []
        assert os.path.isfile(str(outside))

    def test_approving_an_approval_does_nothing(self, tmp_path):
        """A `_final` of a `_final` lists under the same stage as its own
        parent and reads as a second approved render for the asset."""
        folder = str(tmp_path)
        write(folder, "_base_00007_.png")
        approve(folder, ["_base_00007_.png"])
        again = approve(folder, ["_final_from._base_00007__00001_.png"])
        assert again == []
        assert len(images_in(folder, FINAL_STAGE)) == 1

    def test_approving_twice_leaves_one_file(self, tmp_path):
        """The name is derived from the render, so the second click rewrites
        the same file rather than stacking copies."""
        folder = str(tmp_path)
        write(folder, "_base_00007_.png")
        approve(folder, ["_base_00007_.png"])
        approve(folder, ["_base_00007_.png"])
        assert len(images_in(folder, FINAL_STAGE)) == 1

    def test_two_renders_approve_independently(self, tmp_path):
        folder = str(tmp_path)
        write(folder, "_base_00007_.png", "_base_00008_.png")
        approve(folder, ["_base_00007_.png", "_base_00008_.png"])
        approve(folder, ["_base_00007_.png"], on=False)
        assert list(finals_in(folder)) == ["_base_00008_"]


class TestThePrefixLayout:
    """A render is `<category>/<asset>_00001_.png` as often as it is
    `<category>/<asset>/_base_00001_.png` — the last segment of a save prefix
    names the FILE. Every test above builds the directory layout, and that is
    what hid this: a `_final` written beside its source in the prefix layout is
    filtered out by the asset prefix before its own tag is read, so the board
    it exists to fill could never fill."""

    def test_the_approval_is_visible_where_the_render_is_a_prefix(self, tmp_path):
        category = tmp_path / "Crate Icon"
        write(str(category), "Pastel Chest_00001_.png")
        target = str(category / "Pastel Chest")
        approve(target, ["Pastel Chest_00001_.png"])
        listed = [e["name"] for e in listing_for(target, only=[FINAL_STAGE])]
        assert listed == ["_final_from.Pastel Chest_00001__00001_.png"]

    def test_it_lands_in_the_asset_folder_not_beside_the_render(self, tmp_path):
        category = tmp_path / "Crate Icon"
        write(str(category), "Pastel Chest_00001_.png")
        target = str(category / "Pastel Chest")
        written = approve(target, ["Pastel Chest_00001_.png"])
        assert os.path.dirname(written[0]) == target

    def test_the_render_still_lists_under_its_own_name(self, tmp_path):
        """Approving must not take the render out of the grid it was ticked
        in."""
        category = tmp_path / "Crate Icon"
        write(str(category), "Pastel Chest_00001_.png")
        target = str(category / "Pastel Chest")
        approve(target, ["Pastel Chest_00001_.png"])
        assert "Pastel Chest_00001_.png" in [e["name"] for e in
                                             listing_for(target)]

    def test_un_approving_finds_it_there_too(self, tmp_path):
        category = tmp_path / "Crate Icon"
        write(str(category), "Pastel Chest_00001_.png")
        target = str(category / "Pastel Chest")
        approve(target, ["Pastel Chest_00001_.png"])
        approve(target, ["Pastel Chest_00001_.png"], on=False)
        assert listing_for(target, only=[FINAL_STAGE]) == []


class TestReadingApprovalsBack:
    def test_finals_in_maps_render_to_its_final(self, tmp_path):
        folder = str(tmp_path)
        write(folder, "_base_00007_.png")
        approve(folder, ["_base_00007_.png"])
        assert list(finals_in(folder)) == ["_base_00007_"]

    def test_a_folder_with_no_approval_is_empty(self, tmp_path):
        folder = str(tmp_path)
        write(folder, "_base_00007_.png")
        assert finals_in(folder) == {}

    def test_the_approved_view_is_just_a_names_prefix(self, tmp_path):
        """What makes this cost nothing: `_final` is a stage, so the existing
        listing narrows to approvals with no new argument."""
        folder = str(tmp_path)
        write(folder, "_base_00007_.png", "_base_00008_.png")
        approve(folder, ["_base_00008_.png"])
        listed = listing_for(folder, only=[FINAL_STAGE])
        assert [e["name"] for e in listed] == [
            "_final_from._base_00008__00001_.png"]
