# ABOUTME: Tests the Seedance video core — the models it offers, the limits each
# ABOUTME: one carries, and the request it builds for Cloudflare's /ai/run.
import pytest

from pipeline import seedance_video as core


def test_the_four_models_are_the_ones_the_official_node_offers():
    """Same labels, same order, so a graph built against ComfyUI's node reads
    the same here."""
    assert list(core.MODELS) == ["Seedance 2.5", "Seedance 2.0",
                                 "Seedance 2.0 Fast", "Seedance 2.0 Mini"]


def test_each_label_maps_to_the_slug_cloudflares_catalog_answers_to():
    assert core.MODELS["Seedance 2.5"] == "bytedance/seedance-2.5"
    assert core.MODELS["Seedance 2.0"] == "bytedance/seedance-2.0"
    assert core.MODELS["Seedance 2.0 Fast"] == "bytedance/seedance-2.0-fast"
    assert core.MODELS["Seedance 2.0 Mini"] == "bytedance/seedance-2.0-mini"


def test_seedance_25_carries_the_reference_counts_the_official_node_offers():
    """30 / 10 / 10 is what ComfyUI's node offers and what the catalog
    accepts, so the 2.5 option loses nothing to routing through us."""
    limits = core.LIMITS["Seedance 2.5"]
    assert limits.max_images == 30
    assert limits.max_videos == 10
    assert limits.max_audios == 10


def test_the_20_family_is_capped_where_the_catalog_caps_it_not_where_bytedance_does():
    """BytePlus itself takes 9 images, 3 videos and 3 audios for these, but the
    catalog wrapper we route through takes 4 and a single video. Offering the
    larger numbers would be offering slots the call cannot carry."""
    for label in ("Seedance 2.0", "Seedance 2.0 Fast", "Seedance 2.0 Mini"):
        limits = core.LIMITS[label]
        assert limits.max_images == 4, label
        assert limits.max_videos == 1, label


def test_mini_alone_among_the_20_family_takes_a_reference_audio():
    """The catalog gives Mini a singular `reference_audio` the other two do not
    have at all. Sending one to Fast is refused as an unsupported field, so the
    audio slot has to be Mini's alone."""
    assert core.LIMITS["Seedance 2.0 Mini"].max_audios == 1
    assert core.LIMITS["Seedance 2.0"].max_audios == 0
    assert core.LIMITS["Seedance 2.0 Fast"].max_audios == 0


def test_only_25_is_offered_the_resolutions_it_actually_renders():
    assert core.LIMITS["Seedance 2.5"].resolutions == ["480p", "720p"]
    assert core.LIMITS["Seedance 2.0"].resolutions == [
        "480p", "720p", "1080p", "4k"]
    assert core.LIMITS["Seedance 2.0 Fast"].resolutions == ["480p", "720p"]
    assert core.LIMITS["Seedance 2.0 Mini"].resolutions == ["480p", "720p"]


def test_adaptive_is_offered_only_where_the_catalog_accepts_it():
    """ComfyUI's node offers 'adaptive' on every model and even defaults the
    2.0 options to it. The catalog rejects it outside 2.5, so offering it
    there would be a combo entry whose every render 400s."""
    assert "adaptive" in core.LIMITS["Seedance 2.5"].ratios
    for label in ("Seedance 2.0", "Seedance 2.0 Fast", "Seedance 2.0 Mini"):
        assert "adaptive" not in core.LIMITS[label].ratios, label


def test_duration_stops_where_the_catalog_stops_it():
    """4-30 on 2.5, 4-12 on the rest — the official node says 4-15 for the 2.0
    family, which is BytePlus's own ceiling rather than this wrapper's."""
    assert (core.LIMITS["Seedance 2.5"].min_duration,
            core.LIMITS["Seedance 2.5"].max_duration) == (4, 30)
    assert (core.LIMITS["Seedance 2.0"].min_duration,
            core.LIMITS["Seedance 2.0"].max_duration) == (4, 12)
