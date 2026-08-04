# ABOUTME: The Pick node's routes — the buffer is addressed by node id, never by
# ABOUTME: a caller-supplied path, and clearing deletes what it says it deletes.
import asyncio
import importlib
import os
import sys
import types

import pytest
from PIL import Image


def _load_routes(monkeypatch, output_dir):
    fake_server = types.ModuleType("server")

    class _Routes:
        def get(self, _path):
            def deco(fn):
                return fn
            return deco

        post = get

    fake_server.PromptServer = types.SimpleNamespace(
        instance=types.SimpleNamespace(routes=_Routes()))
    monkeypatch.setitem(sys.modules, "server", fake_server)
    monkeypatch.setitem(sys.modules, "aiohttp", types.ModuleType("aiohttp"))
    web = types.ModuleType("aiohttp.web")
    web.json_response = lambda body, status=200: {"body": body, "status": status}
    web.FileResponse = lambda *a, **k: None
    sys.modules["aiohttp"].web = web
    monkeypatch.setitem(sys.modules, "aiohttp.web", web)

    fp = types.ModuleType("folder_paths")
    fp.get_output_directory = lambda: str(output_dir)
    fp.get_input_directory = lambda: str(output_dir)
    monkeypatch.setitem(sys.modules, "folder_paths", fp)

    import pipeline.routes as routes
    importlib.reload(routes)
    return routes


class _Req:
    def __init__(self, body=None, **query):
        self.query = query
        self._body = body

    async def json(self):
        if self._body is None:
            raise ValueError("no body")
        return self._body


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def env(monkeypatch, tmp_path):
    out = tmp_path / "output"
    out.mkdir()
    routes = _load_routes(monkeypatch, out)
    return types.SimpleNamespace(routes=routes, out=out)


def seed(env, node_id, colours, tag=None):
    from pipeline.pick_buffer import add_image, buffer_dir
    d = buffer_dir(str(env.out), node_id)
    made = []
    for c in colours:
        made.append(add_image(d, Image.new("RGB", (6, 6), (c, c, c)), tag=tag))
    return d, made


class TestListing:
    def test_an_empty_node_lists_nothing_rather_than_failing(self, env):
        res = _run(env.routes.pick_list(_Req(node_id="99")))
        assert res["body"] == {"ok": True, "images": [], "groups": []}

    def test_candidates_come_back_with_their_paths_and_tags(self, env):
        seed(env, "7", [10, 20], tag={"asset": "cake", "category": "Food"})
        body = _run(env.routes.pick_list(_Req(node_id="7")))["body"]
        assert len(body["images"]) == 2
        first = body["images"][0]
        assert os.path.isfile(first["path"])
        assert os.path.isfile(first["thumb"])
        assert first["group"] == "Food / cake"
        assert body["groups"] == [{"key": "Food / cake", "count": 2}]

    def test_the_thumbnail_served_is_not_the_full_image(self, env):
        """The grid draws them all at once; the full renders are the download
        the double-click is for."""
        seed(env, "7", [10])
        first = _run(env.routes.pick_list(_Req(node_id="7")))["body"]["images"][0]
        assert first["thumb"] != first["path"]

    def test_one_node_never_sees_another_nodes_candidates(self, env):
        seed(env, "1", [10])
        seed(env, "2", [20, 30])
        assert len(_run(env.routes.pick_list(_Req(node_id="1")))["body"]["images"]) == 1
        assert len(_run(env.routes.pick_list(_Req(node_id="2")))["body"]["images"]) == 2


class TestServingTheThumbnails:
    """Found live: the node drew a grid of broken images while reporting the
    right count. `is_allowed` consults only the folders an execution
    registered — never `declared_roots()` — so listing candidates without
    registering their buffer hands back paths whose every thumbnail 403s."""

    def test_listing_makes_that_buffer_servable(self, env):
        _, made = seed(env, "7", [10])
        body = _run(env.routes.pick_list(_Req(node_id="7")))["body"]
        assert env.routes.is_allowed(body["images"][0]["thumb"])
        assert env.routes.is_allowed(body["images"][0]["path"])

    def test_listing_one_node_does_not_open_another_nodes_buffer(self, env):
        seed(env, "1", [10])
        _, other = seed(env, "2", [20])
        _run(env.routes.pick_list(_Req(node_id="1")))
        from pipeline.pick_buffer import buffer_dir
        path = os.path.join(buffer_dir(str(env.out), "2"), other[0]["file"])
        assert env.routes.is_allowed(path) is None

    def test_listing_does_not_open_the_rest_of_the_output_directory(self, env):
        """Registering the buffer must not register its parent: the output
        directory holds every render this install has ever written."""
        seed(env, "7", [10])
        _run(env.routes.pick_list(_Req(node_id="7")))
        loose = env.out / "someone-elses-render.png"
        Image.new("RGB", (4, 4)).save(loose)
        assert env.routes.is_allowed(str(loose)) is None

    def test_an_empty_buffer_registers_nothing(self, env):
        assert _run(env.routes.pick_list(_Req(node_id="404")))["body"]["ok"] is True


class TestTheBufferIsAddressedByNodeId:
    def test_a_traversing_node_id_cannot_reach_out_of_the_output_directory(self, env):
        """The caller names a node, never a path — the id is reduced to a bare
        directory segment before it is joined, so there is nothing to escape
        with."""
        outside = env.out.parent / "secret"
        outside.mkdir()
        (outside / "index.json").write_text('[{"id":"x","file":"x.png"}]')
        res = _run(env.routes.pick_list(_Req(node_id="../../secret")))
        assert res["body"]["images"] == []

    def test_a_missing_node_id_is_not_an_error(self, env):
        assert _run(env.routes.pick_list(_Req()))["body"]["ok"] is True


class TestClearing:
    def test_named_candidates_are_deleted(self, env):
        d, made = seed(env, "7", [10, 20, 30])
        res = _run(env.routes.pick_clear(
            _Req(body={"node_id": "7", "ids": [made[0]["id"]]})))
        assert res["body"] == {"ok": True, "removed": 1}
        assert not os.path.exists(os.path.join(d, made[0]["file"]))
        assert os.path.exists(os.path.join(d, made[1]["file"]))

    def test_no_ids_clears_the_whole_buffer(self, env):
        seed(env, "7", [10, 20])
        res = _run(env.routes.pick_clear(_Req(body={"node_id": "7"})))
        assert res["body"]["removed"] == "all"
        assert _run(env.routes.pick_list(_Req(node_id="7")))["body"]["images"] == []

    def test_an_empty_id_list_still_means_clear_everything(self, env):
        """An empty list is what "I selected nothing to delete individually"
        looks like, and the button that sends it is the clear-all button."""
        seed(env, "7", [10, 20])
        _run(env.routes.pick_clear(_Req(body={"node_id": "7", "ids": []})))
        assert _run(env.routes.pick_list(_Req(node_id="7")))["body"]["images"] == []

    def test_a_request_with_no_body_is_refused_not_a_crash(self, env):
        res = _run(env.routes.pick_clear(_Req()))
        assert res["status"] == 400
