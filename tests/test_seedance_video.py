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
    assert limits.max_audios == 10


def test_the_20_family_is_capped_where_the_catalog_caps_it_not_where_bytedance_does():
    """BytePlus itself takes 9 reference images for these, but the catalog
    wrapper we route through takes 4. Offering the larger number would be
    offering slots the call cannot carry."""
    for label in ("Seedance 2.0", "Seedance 2.0 Fast", "Seedance 2.0 Mini"):
        assert core.LIMITS[label].max_images == 4, label


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


def a_request(label="Seedance 2.5", images=(), audios=(), **over):
    values = {"prompt": "a cat", "resolution": "720p", "ratio": "16:9",
              "duration": 5, "generate_audio": True, "output_format": "mp4"}
    values.update(over)
    return core.build_request(label, values, seed=7, watermark=False,
                              images=list(images), audios=list(audios))


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


def test_25_sends_its_references_as_the_two_arrays():
    body = a_request(images=["data:image/png;base64,AA"],
                     audios=["data:audio/mp3;base64,CC"])
    assert body["input"]["reference_images"] == ["data:image/png;base64,AA"]
    assert body["input"]["reference_audios"] == ["data:audio/mp3;base64,CC"]


def test_no_model_is_sent_a_reference_video_at_all():
    """ByteDance takes a reference video only as a web URL. A data URI passes
    Cloudflare's own schema check and is then refused upstream —
    "reference_video must be provided as a web url" — and everything this node
    can encode is inline, so there is nothing to put in the field."""
    for label in core.MODELS:
        body = a_request(label)
        assert "reference_video" not in body["input"], label
        assert "reference_videos" not in body["input"], label


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


def test_without_video_editing_the_duration_widget_is_sent_as_set():
    assert a_request(duration=12)["input"]["duration"] == 12


def test_seed_and_watermark_ride_alongside_the_per_model_widgets():
    body = a_request()
    assert body["input"]["seed"] == 7
    assert body["input"]["watermark"] is False
    assert body["input"]["generate_audio"] is True


def test_the_ceiling_is_the_one_the_gateways_log_limit_dictates():
    """Anchored to the literal rather than derived: Cloudflare's log ceiling is
    10 MB, and the margin below it is for what JSON encoding adds on top of the
    bytes counted. A test that recomputed this from the constant would pass
    whatever the constant said."""
    assert core.MAX_REQUEST_BYTES == 8_000_000


def test_a_reference_set_over_the_log_ceiling_is_refused_rather_than_trimmed():
    """Cloudflare stores no log above 10 MB and AI Gateway analytics reads the
    log, so an oversized call renders without its spend ever reaching the
    studio's row — the one outcome routing through the gateway exists to
    prevent. Same ceiling and same reasoning as the Claude node."""
    with pytest.raises(ValueError) as raised:
        core.check_reference_size(["x" * 8_000_001])
    assert "attributed" in str(raised.value)


def test_a_reference_set_inside_the_ceiling_passes_silently():
    assert core.check_reference_size(["x" * 8_000_000]) is None


def test_the_refusal_says_how_far_over_it_went():
    """A ceiling the message does not quantify leaves the reader guessing
    whether to drop one clip or nine."""
    with pytest.raises(ValueError) as raised:
        core.check_reference_size(["x" * 5_000_000, "y" * 5_000_000])
    assert "10000000" in str(raised.value)
    assert "8000000" in str(raised.value)


def test_the_ceiling_is_read_across_every_reference_not_each_one():
    """Five clips of two megabytes each are over budget together and inside it
    apiece. Checking them one at a time would let the set through."""
    with pytest.raises(ValueError):
        core.check_reference_size(["z" * 2_000_000] * 5)


# One real reply, trimmed. The URL sits under `result.result`, not `result`:
# Cloudflare's own envelope wraps the run, and the run carries a `result` of
# its own. Written out from a render rather than inferred, because inferring it
# is exactly how the first version of this reader got it wrong.
A_FINISHED_RUN = {
    "success": True, "errors": [], "messages": [],
    "result": {"state": "Completed",
               "result": {"video": "https://ark.example/out.mp4?X-Tos-Expires=86400"},
               "gatewayMetadata": {"keySource": "Unified"}},
}


def test_the_video_url_is_read_from_where_the_catalog_puts_it():
    assert core.video_url(A_FINISHED_RUN) == (
        "https://ark.example/out.mp4?X-Tos-Expires=86400")


def test_the_url_is_not_looked_for_one_level_too_high():
    """The run's own envelope carries `state` and `gatewayMetadata` alongside
    its result. A reader that treats the outer `result` as the run's result
    finds no video and throws on every successful render."""
    assert "video" not in A_FINISHED_RUN["result"]


def test_a_reply_without_a_video_says_what_came_back_instead():
    """The catalog answers 200 with its own envelope, so a refusal that is not
    an HTTP error still arrives here. Quoting the reply is most of the
    diagnosis; a bare 'no video' sends the reader to the wrong system."""
    with pytest.raises(RuntimeError) as raised:
        core.video_url({"result": {}, "state": "Failed",
                        "error": "content policy"})
    assert "content policy" in str(raised.value)


def test_an_unfinished_run_is_not_read_as_a_finished_one():
    """`state` is the catalog's own word for whether the run completed. A body
    that carries a state other than Completed and no video is a run that did
    not finish, not a malformed reply."""
    with pytest.raises(RuntimeError) as raised:
        core.video_url({"result": {}, "state": "Queued"})
    assert "Queued" in str(raised.value)


def a_pil(width, height, colour=(120, 40, 200)):
    from PIL import Image
    return Image.new("RGB", (width, height), colour)


def test_a_reference_image_is_encoded_as_the_data_uri_the_catalog_reads():
    uri = core.image_data_uri(a_pil(800, 600))
    assert uri.startswith("data:image/jpeg;base64,")


def test_an_oversized_image_is_brought_under_the_long_side_ceiling():
    """Seedance renders 720p at most on 2.5. A 5000px reference adds no detail
    the model can use and spends the whole request budget saying so."""
    import base64, io
    from PIL import Image
    uri = core.image_data_uri(a_pil(5000, 2500))
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert max(Image.open(io.BytesIO(raw)).size) == core.MAX_IMAGE_EDGE


def test_a_small_image_is_left_at_its_own_size():
    import base64, io
    from PIL import Image
    uri = core.image_data_uri(a_pil(640, 480))
    raw = base64.b64decode(uri.split(",", 1)[1])
    assert Image.open(io.BytesIO(raw)).size == (640, 480)


def test_an_image_too_small_for_seedance_is_refused_by_name():
    """ByteDance takes nothing under 300px a side. Sent anyway it fails at the
    provider, where the message names neither the node nor the slot."""
    with pytest.raises(ValueError) as raised:
        core.image_data_uri(a_pil(200, 400))
    assert "300" in str(raised.value)


def test_an_image_too_long_and_thin_is_refused_by_name():
    """The accepted aspect range is 0.4 to 2.5; a panorama outside it is
    refused here rather than at the provider."""
    with pytest.raises(ValueError) as raised:
        core.image_data_uri(a_pil(3000, 400))
    assert "aspect" in str(raised.value).lower()


def an_audio(seconds=5.0, rate=16000, channels=1):
    import numpy as np
    samples = int(seconds * rate)
    tone = np.sin(np.linspace(0, 220 * 2 * np.pi * seconds, samples))
    return {"waveform": np.tile(tone, (1, channels, 1)).astype("float32"),
            "sample_rate": rate}


def test_a_reference_audio_is_encoded_as_the_data_uri_the_catalog_reads():
    assert core.audio_data_uri(an_audio(), "Seedance 2.5").startswith(
        "data:audio/wav;base64,")


def test_the_encoded_audio_keeps_its_own_rate_and_length():
    import base64, io, wave
    uri = core.audio_data_uri(an_audio(3.0, rate=22050), "Seedance 2.5")
    raw = base64.b64decode(uri.split(",", 1)[1])
    with wave.open(io.BytesIO(raw)) as handle:
        assert handle.getframerate() == 22050
        assert handle.getnframes() == int(3.0 * 22050)


def test_an_audio_shorter_than_seedance_accepts_is_refused_by_length():
    """ByteDance refuses anything under 1.8s, which it says in those words:
    "audio duration (seconds) ... must be greater than or equal to 1.8". Caught
    here the message says how long the clip was as well."""
    with pytest.raises(ValueError) as raised:
        core.audio_data_uri(an_audio(1.0), "Seedance 2.5")
    assert "1.0" in str(raised.value)


def test_a_clip_between_one_point_eight_and_two_seconds_is_accepted():
    """The floor is 1.8, not 2. Rounding it up to a tidier number refuses
    clips the provider takes, and does it silently."""
    assert core.audio_data_uri(an_audio(1.9), "Seedance 2.5")


def test_an_audio_longer_than_the_model_takes_is_refused_by_model():
    """2.5 takes thirty seconds of reference audio; Mini takes fifteen. The
    same clip is fine on one and refused on the other, so the message has to
    name which model it was measured against."""
    core.audio_data_uri(an_audio(20.0), "Seedance 2.5")
    with pytest.raises(ValueError) as raised:
        core.audio_data_uri(an_audio(20.0), "Seedance 2.0 Mini")
    assert "Seedance 2.0 Mini" in str(raised.value)


def test_a_render_that_left_the_byok_boundary_says_so():
    """`keySource: Unified` means no stored ByteDance key paid — Cloudflare's
    own balance did. The render succeeds either way, so nothing else in the
    system would ever mention it, and unattributed spend that renders fine is
    the failure this pack exists to make loud."""
    said = core.key_source_warning(A_FINISHED_RUN)
    assert "Unified" in said


def test_a_render_billed_to_a_stored_key_says_nothing():
    billed = {"result": {"state": "Completed", "result": {"video": "u"},
                         "gatewayMetadata": {"keySource": "BYOK"}}}
    assert core.key_source_warning(billed) == ""


def test_a_reply_that_names_no_key_source_is_not_reported_as_one():
    """Absent is not the same as Unified. Warning on a field Cloudflare simply
    did not send would train the reader to ignore the warning."""
    assert core.key_source_warning({"result": {"state": "Completed"}}) == ""
