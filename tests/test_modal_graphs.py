# ABOUTME: Tests the pinned recipe files and the binding of widget values into
# ABOUTME: them — what both the Modal Render node and the RNP server rely on.
import json

import pytest

from pipeline import modal_graphs


def test_pack_ships_the_qwen_recipe_and_it_validates():
    assert "qwen-image" in modal_graphs.recipes()
    graph = modal_graphs.load("qwen-image")
    names = [n for n, _, _ in modal_graphs.input_specs(graph)]
    assert names == ["prompt", "negative", "seed", "width", "height"]
    assert modal_graphs.defaults(graph)["width"] == 1024


def test_every_shipped_recipe_binds_only_to_real_inputs():
    for name in modal_graphs.recipes():
        graph = modal_graphs.load(name)
        for target in modal_graphs.manifest(graph)["bind"].values():
            assert target[1] in graph[target[0]]["inputs"]


def test_bind_writes_values_and_drops_the_manifest():
    graph = modal_graphs.load("qwen-image")
    bound = modal_graphs.bind(graph, {"prompt": "a cat", "seed": 7, "width": 512})
    assert modal_graphs.MANIFEST_KEY not in bound
    assert bound["6"]["inputs"]["text"] == "a cat"
    assert bound["9"]["inputs"]["seed"] == 7
    assert bound["8"]["inputs"]["width"] == 512
    assert bound["8"]["inputs"]["height"] == 1024
    # the loaded graph is untouched
    assert graph["6"]["inputs"]["text"] == ""


def test_bind_ignores_unbound_names_unless_strict():
    graph = modal_graphs.load("qwen-image")
    modal_graphs.bind(graph, {"nope": 1})
    with pytest.raises(ValueError, match="no input named 'nope'"):
        modal_graphs.bind(graph, {"nope": 1}, strict=True)


def test_missing_recipe_names_the_ones_that_exist():
    with pytest.raises(ValueError, match="qwen-image"):
        modal_graphs.load("wan-video")


@pytest.mark.parametrize("block, reason", [
    (None, "no _symbiotica"),
    ({"inputs": []}, "no inputs"),
    ({"inputs": [["p", "STRING"]], "bind": {"q": ["1", "text"]}}, "not an input"),
    ({"inputs": [["p", "STRING"]], "bind": {"p": ["9", "text"]}}, "does not have"),
    ({"inputs": [["p", "STRING"]], "bind": {"p": ["1", "nope"]}}, "does not have"),
    ({"inputs": [[1, 2]]}, "malformed"),
])
def test_manifest_rejects_broken_recipes(tmp_path, block, reason):
    graph = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": ""}}}
    if block is not None:
        graph["_symbiotica"] = block
    path = tmp_path / "bad.api.json"
    path.write_text(json.dumps(graph))
    with pytest.raises(ValueError, match=reason):
        modal_graphs.load("bad", recipe_dir=str(tmp_path))
