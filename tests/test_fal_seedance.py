# ABOUTME: Tests the fal Seedance arm — which endpoint each model is, what it
# ABOUTME: accepts, and the request and reply shapes fal speaks.
import pytest

from pipeline import fal_seedance as fal


def test_every_model_maps_to_its_own_fal_endpoint():
    """fal splits the models across separate endpoints rather than taking a
    model name in the body, so the label chooses the URL."""
    assert fal.ENDPOINTS["Seedance 2.5"] == (
        "bytedance/seedance-2.5/reference-to-video")
    assert fal.ENDPOINTS["Seedance 2.0"] == (
        "bytedance/seedance-2.0/reference-to-video")
    assert fal.ENDPOINTS["Seedance 2.0 Fast"] == (
        "bytedance/seedance-2.0/fast/reference-to-video")
    assert fal.ENDPOINTS["Seedance 2.0 Mini"] == (
        "bytedance/seedance-2.0/mini/reference-to-video")


def test_the_labels_are_the_ones_the_canvas_already_shows():
    from pipeline import seedance_video as core
    assert list(fal.ENDPOINTS) == list(core.MODELS)


def test_25_carries_the_counts_the_official_node_offers():
    limits = fal.LIMITS["Seedance 2.5"]
    assert (limits.max_images, limits.max_videos, limits.max_audios) == (
        30, 10, 10)


def test_the_20_family_carries_bytedances_own_counts_not_cloudflares():
    """Through fal these are 9 / 3 / 3 — what ByteDance itself takes. The
    Cloudflare catalog route caps the same models at 4 / 1 / 0."""
    for label in ("Seedance 2.0", "Seedance 2.0 Fast", "Seedance 2.0 Mini"):
        limits = fal.LIMITS[label]
        assert (limits.max_images, limits.max_videos,
                limits.max_audios) == (9, 3, 3), label


def test_each_model_offers_the_resolutions_fal_documents_for_it():
    assert fal.LIMITS["Seedance 2.5"].resolutions == ["480p", "720p", "1080p"]
    assert fal.LIMITS["Seedance 2.0"].resolutions == [
        "480p", "720p", "1080p", "4k"]
    assert fal.LIMITS["Seedance 2.0 Fast"].resolutions == ["480p", "720p"]
    assert fal.LIMITS["Seedance 2.0 Mini"].resolutions == ["480p", "720p"]


def test_auto_is_offered_on_every_model_because_fal_takes_it_everywhere():
    """`auto` is fal's name for what ByteDance calls `adaptive`, and unlike the
    Cloudflare catalog it is accepted on all four models — so editing and
    extending a clip work throughout."""
    for label in fal.ENDPOINTS:
        assert "auto" in fal.LIMITS[label].ratios, label
        assert "auto" in fal.LIMITS[label].durations, label


def test_25_runs_to_thirty_seconds_where_the_20_family_stops_at_fifteen():
    assert "30" in fal.LIMITS["Seedance 2.5"].durations
    assert "30" not in fal.LIMITS["Seedance 2.0"].durations
    assert "15" in fal.LIMITS["Seedance 2.0"].durations


def a_request(label="Seedance 2.5", images=(), videos=(), audios=(), **over):
    values = {"prompt": "a cat", "resolution": "720p", "ratio": "16:9",
              "duration": "5", "generate_audio": True}
    values.update(over)
    return fal.build_request(values, list(images), list(videos), list(audios))


def test_the_request_names_the_reference_fields_fal_reads():
    body = a_request(images=["i"], videos=["v"], audios=["a"])
    assert body["image_urls"] == ["i"]
    assert body["video_urls"] == ["v"]
    assert body["audio_urls"] == ["a"]


def test_the_ratio_widget_is_sent_as_the_aspect_ratio_fal_reads():
    assert a_request()["aspect_ratio"] == "16:9"
    assert "ratio" not in a_request()


def test_a_reference_kind_with_nothing_wired_is_left_out_entirely():
    body = a_request()
    for key in ("image_urls", "video_urls", "audio_urls"):
        assert key not in body, key


def test_the_model_is_not_named_in_the_body_because_the_url_names_it():
    assert "model" not in a_request()


def test_video_editing_hands_the_length_and_shape_back_to_the_source_clip():
    """fal spells this `auto` on both fields, and takes it as an enum member
    rather than as an absent key — so unlike the Cloudflare catalog route there
    is nothing to infer."""
    body = a_request(video_editing=True, videos=["v"])
    assert body["aspect_ratio"] == "auto"
    assert body["duration"] == "auto"


def test_the_seed_rides_along_when_one_is_asked_for():
    body = fal.build_request({"prompt": "p", "resolution": "720p",
                              "ratio": "16:9", "duration": "5",
                              "generate_audio": False}, [], [], [], seed=11)
    assert body["seed"] == 11


def test_the_video_url_is_read_from_the_file_fal_hands_back():
    """fal returns the output as a File object with its own `url`, not as a
    bare string."""
    assert fal.video_url({"video": {"url": "https://fal.media/out.mp4"},
                          "seed": 3}) == "https://fal.media/out.mp4"


def test_a_reply_without_a_video_says_what_came_back_instead():
    with pytest.raises(RuntimeError) as raised:
        fal.video_url({"detail": "content policy"})
    assert "content policy" in str(raised.value)


def test_the_transport_reaches_fal_through_the_gateways_own_fal_path():
    """fal is a passthrough provider, so this is the same arm the Gemini and
    Claude nodes use — which is the whole reason to prefer it: the studio's own
    stored key pays, by alias."""
    environ = {"SYMBIOTICA_AIG_BASE": "https://gw.example.invalid/v1/a/g",
               "SYMBIOTICA_AIG_TOKEN": "gateway-token-not-a-real-one",
               "ORDER_STUDIO": "example-studio"}
    sent = fal.resolve_transport(environ, "Seedance 2.5", lambda: "unused")
    assert sent.url == ("https://gw.example.invalid/v1/a/g/fal/"
                        "bytedance/seedance-2.5/reference-to-video")
    assert sent.headers["cf-aig-byok-alias"] == "example-studio"


def test_the_direct_arm_presents_the_key_the_way_fal_wants_it():
    """fal wants `Authorization: Key <token>`, not Bearer. Sent as Bearer it
    is a 401 that reads like a bad key."""
    environ = {}
    sent = fal.resolve_transport(environ, "Seedance 2.0",
                                 lambda: "fal-key-not-a-real-one")
    assert sent.url == ("https://fal.run/bytedance/seedance-2.0/"
                        "reference-to-video")
    assert sent.headers["Authorization"] == "Key fal-key-not-a-real-one"


GATEWAY = {"SYMBIOTICA_AIG_BASE": "https://gw.example.invalid/v1/a/g",
           "SYMBIOTICA_AIG_TOKEN": "gateway-token-not-a-real-one",
           "ORDER_STUDIO": "example-studio"}
CATALOG = {"SYMBIOTICA_CF_ACCOUNT_ID": "acct-tag",
           "SYMBIOTICA_CF_API_TOKEN": "cf-api-token-not-a-real-one",
           "SYMBIOTICA_AIG_GATEWAY_ID": "symbiotica-hub-dev",
           "ORDER_STUDIO": "example-studio"}


def test_a_configured_gateway_goes_to_fal_not_the_catalog():
    """Both are reachable on an order sandbox, and fal is the one where the
    studio's own key pays. Choosing the catalog there would take the spend out
    of the BYOK boundary while a perfectly good fal route sat unused."""
    assert fal.chosen_arm(dict(GATEWAY, **CATALOG), has_key=False) == "fal"


def test_a_box_with_only_a_personal_fal_key_still_goes_to_fal():
    assert fal.chosen_arm({}, has_key=True) == "fal"


def test_a_box_with_only_the_catalog_configured_falls_back_to_it():
    assert fal.chosen_arm(dict(CATALOG), has_key=False) == "catalog"


def test_a_box_with_neither_says_so_naming_both_ways_in():
    with pytest.raises(ValueError) as raised:
        fal.chosen_arm({}, has_key=False)
    assert "SYMBIOTICA_AIG_BASE" in str(raised.value)
    assert "SYMBIOTICA_CF_ACCOUNT_ID" in str(raised.value)


def test_the_catalog_arm_refuses_the_reference_videos_it_cannot_carry():
    """The schema offers fal's slots, so a graph wired for fal can reach a box
    that has only the catalog. Refused by name rather than dropped: a render
    that silently ignored the clips would come back looking finished."""
    with pytest.raises(ValueError) as raised:
        fal.check_catalog_can_carry("Seedance 2.5", images=1, videos=2,
                                    audios=0)
    assert "reference video" in str(raised.value).lower()


def test_the_catalog_arm_refuses_more_images_than_it_takes():
    with pytest.raises(ValueError) as raised:
        fal.check_catalog_can_carry("Seedance 2.0", images=9, videos=0,
                                    audios=0)
    assert "4" in str(raised.value)


def test_the_catalog_arm_accepts_what_it_can_carry():
    assert fal.check_catalog_can_carry("Seedance 2.5", images=3, videos=0,
                                       audios=1) is None


class FakeVideo:
    """A ComfyUI VIDEO, as far as this module ever touches one."""

    def __init__(self, payload=b"mp4bytes", seconds=5.0):
        self.payload = payload
        self.seconds = seconds
        self.saved_as = None

    def get_duration(self):
        return self.seconds

    def save_to(self, buffer, format=None, codec=None):
        self.saved_as = (format, codec)
        buffer.write(self.payload)


def test_a_reference_clip_is_encoded_as_a_data_uri():
    assert fal.video_data_uri(FakeVideo(), "Seedance 2.5").startswith(
        "data:video/mp4;base64,")


def test_a_clip_shorter_than_the_provider_takes_is_refused():
    """1.8s is the floor fal documents and the provider enforces."""
    with pytest.raises(ValueError) as raised:
        fal.video_data_uri(FakeVideo(seconds=1.0), "Seedance 2.5")
    assert "1.8" in str(raised.value)


def test_a_clip_of_one_point_nine_seconds_is_accepted():
    assert fal.video_data_uri(FakeVideo(seconds=1.9), "Seedance 2.5")


def test_a_clip_longer_than_the_model_takes_names_the_model():
    fal.video_data_uri(FakeVideo(seconds=25.0), "Seedance 2.5")
    with pytest.raises(ValueError) as raised:
        fal.video_data_uri(FakeVideo(seconds=25.0), "Seedance 2.0")
    assert "Seedance 2.0" in str(raised.value)
