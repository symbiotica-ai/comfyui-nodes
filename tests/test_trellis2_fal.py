# ABOUTME: Tests for the Trellis 2 (fal) image-to-3D node's pure helpers —
# ABOUTME: data-URI encoding, request payload shape, and response parsing.
import base64
import io

import numpy as np
import pytest
from PIL import Image

from trellis2_fal import build_payload, glb_from_response, image_to_data_uri


def test_image_to_data_uri_roundtrips_png():
    arr = (np.linspace(0, 1, 4 * 4 * 3, dtype=np.float32)).reshape(4, 4, 3)
    uri = image_to_data_uri(arr)
    assert uri.startswith("data:image/png;base64,")
    decoded = Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1])))
    assert decoded.size == (4, 4)


def test_build_payload_defaults():
    payload = build_payload("data:image/png;base64,x", resolution=1024, seed=-1, texture_size=2048)
    assert payload == {
        "image_url": "data:image/png;base64,x",
        "resolution": 1024,
        "texture_size": 2048,
    }


def test_build_payload_carries_a_fixed_seed():
    payload = build_payload("u", resolution=512, seed=42, texture_size=1024)
    assert payload["seed"] == 42


def test_glb_from_response_returns_the_mesh_url():
    resp = {"model_glb": {"url": "https://v3b.fal.media/files/x.glb"}}
    assert glb_from_response(resp) == "https://v3b.fal.media/files/x.glb"


def test_glb_from_response_raises_on_missing_mesh():
    with pytest.raises(ValueError, match="model_glb"):
        glb_from_response({"detail": "quota exceeded"})
