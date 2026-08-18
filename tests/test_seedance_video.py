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


def a_request(label="Seedance 2.5", images=(), videos=(), audios=(), **over):
    values = {"prompt": "a cat", "resolution": "720p", "ratio": "16:9",
              "duration": 5, "generate_audio": True, "output_format": "mp4"}
    values.update(over)
    return core.build_request(label, values, seed=7, watermark=False,
                              images=list(images), videos=list(videos),
                              audios=list(audios))


def test_the_request_names_the_catalog_slug_and_nests_everything_under_input():
    body = a_request()
    assert body["model"] == "bytedance/seedance-2.5"
    assert set(body) == {"model", "input"}
    assert body["input"]["prompt"] == "a cat"


def test_the_ratio_widget_is_sent_under_the_name_the_catalog_reads():
    """ComfyUI's node calls it `ratio`; the catalog calls it `aspect_ratio`
    and refuses `ratio` as an unsupported field."""
    assert a_request()["input"]["aspect_ratio"] == "16:9"
    assert "ratio" not in a_request()["input"]


def test_25_sends_its_references_as_the_three_arrays():
    body = a_request(images=["data:image/png;base64,AA"],
                     videos=["data:video/mp4;base64,BB"],
                     audios=["data:audio/mp3;base64,CC"])
    assert body["input"]["reference_images"] == ["data:image/png;base64,AA"]
    assert body["input"]["reference_videos"] == ["data:video/mp4;base64,BB"]
    assert body["input"]["reference_audios"] == ["data:audio/mp3;base64,CC"]


def test_the_20_family_sends_its_single_video_as_a_bare_string():
    """`reference_videos` does not exist on these models — the catalog refuses
    the whole request naming it as an unsupported field, so a list here is not
    a near miss, it is a failed render."""
    body = a_request("Seedance 2.0", videos=["data:video/mp4;base64,BB"])
    assert body["input"]["reference_video"] == "data:video/mp4;base64,BB"
    assert "reference_videos" not in body["input"]


def test_mini_sends_its_single_audio_as_a_bare_string():
    body = a_request("Seedance 2.0 Mini", audios=["data:audio/mp3;base64,CC"])
    assert body["input"]["reference_audio"] == "data:audio/mp3;base64,CC"
    assert "reference_audios" not in body["input"]


def test_a_reference_kind_with_nothing_wired_is_left_out_entirely():
    """An empty array is a claim that references were considered. Omitting the
    key leaves the model's own default behaviour untouched."""
    body = a_request()
    for key in ("reference_images", "reference_videos", "reference_audios",
                "reference_video", "reference_audio"):
        assert key not in body["input"], key


def test_output_format_rides_only_on_the_model_that_has_it():
    assert a_request(output_format="mov")["input"]["output_format"] == "mov"
    assert "output_format" not in a_request(
        "Seedance 2.0", output_format="mov")["input"]


def test_video_editing_hands_the_length_and_shape_back_to_the_source_clip():
    """ComfyUI's node says this as ratio='adaptive' with duration=-1. The
    catalog rejects -1 (duration must be >= 4) but leaves duration optional,
    so the same thing is said here by omitting it."""
    body = a_request(video_editing=True,
                     videos=["data:video/mp4;base64,BB"])
    assert body["input"]["aspect_ratio"] == "adaptive"
    assert "duration" not in body["input"]


def test_without_video_editing_the_duration_widget_is_sent_as_set():
    assert a_request(duration=12)["input"]["duration"] == 12


def test_seed_and_watermark_ride_alongside_the_per_model_widgets():
    body = a_request()
    assert body["input"]["seed"] == 7
    assert body["input"]["watermark"] is False
    assert body["input"]["generate_audio"] is True


def test_a_reference_set_over_the_log_ceiling_is_refused_rather_than_trimmed():
    """Cloudflare stores no log above 10 MB and AI Gateway analytics reads the
    log, so an oversized call renders without its spend ever reaching the
    studio's row — the one outcome routing through the gateway exists to
    prevent. Same ceiling and same reasoning as the Claude node."""
    huge = "data:video/mp4;base64," + "A" * core.MAX_REQUEST_BYTES
    with pytest.raises(ValueError) as raised:
        core.check_reference_size([huge])
    assert "attributed" in str(raised.value)


def test_a_reference_set_inside_the_ceiling_passes_silently():
    assert core.check_reference_size(["data:image/png;base64,AA"]) is None


def test_the_refusal_says_how_far_over_it_went():
    """A ceiling the message does not quantify leaves the reader guessing
    whether to drop one clip or nine."""
    huge = "data:video/mp4;base64," + "A" * core.MAX_REQUEST_BYTES
    with pytest.raises(ValueError) as raised:
        core.check_reference_size([huge])
    assert str(len(huge)) in str(raised.value)
    assert str(core.MAX_REQUEST_BYTES) in str(raised.value)
