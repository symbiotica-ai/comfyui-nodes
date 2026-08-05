# ABOUTME: The Pick node's routes — the panel lists the folder the node itself
# ABOUTME: resolved, never a path a caller talked its way into, and thumbnails
# ABOUTME: are shrunk on the way out rather than kept anywhere.
import asyncio
import importlib
import io
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
    web.Response = lambda **kw: {"response": kw, "status": 200}
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
    import pipeline.pick_folder as pick_folder
    importlib.reload(pick_folder)
    return types.SimpleNamespace(routes=routes, out=out, pick=pick_folder,
                                 tmp=tmp_path)


def renders(folder, names, size=(40, 30), colour=10):
    os.makedirs(folder, exist_ok=True)
    for i, name in enumerate(names):
        Image.new("RGB", size, (colour + i, 0, 0)).save(
            os.path.join(folder, name))
    return folder


class TestListingWhatTheNodeResolved:
    """Asset and category arrive on wires, so the panel cannot work out which
    folder to list — it asks for the one the node itself landed on."""

    def test_a_node_that_has_never_run_lists_nothing(self, env):
        res = _run(env.routes.pick_list(_Req(node_id="99")))
        assert res["body"] == {"ok": True, "images": [], "folder": ""}

    def test_the_folder_the_node_resolved_is_listed(self, env):
        renders(str(env.out / "Oct" / "Food"),
                ("Spookies_00001_.png", "Spookies_00002_.png",
                 "Ghosts_00001_.png"))
        env.pick.remember("7", str(env.out / "Oct" / "Food" / "Spookies"))
        body = _run(env.routes.pick_list(_Req(node_id="7")))["body"]
        assert [i["name"] for i in body["images"]] == [
            "Spookies_00001_.png", "Spookies_00002_.png"]
        assert [i["index"] for i in body["images"]] == [1, 2]
        assert os.path.isfile(body["images"][0]["path"])

    def test_one_node_never_sees_another_nodes_folder(self, env):
        renders(str(env.out / "a"), ("x.png",))
        renders(str(env.out / "b"), ("y.png", "z.png"))
        env.pick.remember("1", str(env.out / "a"))
        env.pick.remember("2", str(env.out / "b"))
        assert len(_run(env.routes.pick_list(_Req(node_id="1")))["body"]["images"]) == 1
        assert len(_run(env.routes.pick_list(_Req(node_id="2")))["body"]["images"]) == 2

    def test_an_explicit_folder_is_listed_for_browsing(self, env):
        renders(str(env.out / "elsewhere"), ("x.png",))
        body = _run(env.routes.pick_list(
            _Req(node_id="7", folder=str(env.out / "elsewhere"))))["body"]
        assert [i["name"] for i in body["images"]] == ["x.png"]

    def test_a_relative_folder_resolves_under_the_output_directory(self, env):
        """What `save_paths` emits, and what people paste in."""
        renders(str(env.out / "Oct" / "Food"), ("Spookies_00001_.png",))
        body = _run(env.routes.pick_list(
            _Req(node_id="7", folder="Oct/Food/Spookies")))["body"]
        assert [i["name"] for i in body["images"]] == ["Spookies_00001_.png"]

    def test_a_folder_outside_every_declared_root_is_refused(self, env):
        renders(str(env.tmp / "outside"), ("x.png",))
        res = _run(env.routes.pick_list(
            _Req(node_id="7", folder=str(env.tmp / "outside"))))
        assert res["status"] == 403

    def test_traversal_out_of_a_declared_root_is_refused(self, env):
        renders(str(env.tmp / "outside"), ("x.png",))
        res = _run(env.routes.pick_list(
            _Req(node_id="7", folder="../outside")))
        assert res["status"] == 403


class TestServingTheThumbnails:
    """Found live once already: the node drew a grid of broken images while
    reporting the right count. `is_allowed` consults only the folders an
    execution or a browse route registered, never `declared_roots()`."""

    def test_listing_makes_the_images_servable(self, env):
        renders(str(env.out / "Oct" / "Food"), ("Spookies_00001_.png",))
        env.pick.remember("7", str(env.out / "Oct" / "Food" / "Spookies"))
        body = _run(env.routes.pick_list(_Req(node_id="7")))["body"]
        assert env.routes.is_allowed(body["images"][0]["path"]) is not None

    def test_an_unlisted_path_is_not_servable(self, env):
        renders(str(env.out / "Oct" / "Food"), ("Spookies_00001_.png",))
        res = _run(env.routes.pick_thumb(
            _Req(path=str(env.out / "Oct" / "Food" / "Spookies_00001_.png"))))
        assert res["status"] == 403

    def test_a_thumbnail_is_smaller_than_the_render(self, env):
        """The grid draws every image at once; serving full renders into a
        strip of 128px tiles is what makes the node feel broken."""
        renders(str(env.out / "Food"), ("a.png",), size=(400, 300))
        env.pick.remember("7", str(env.out / "Food"))
        _run(env.routes.pick_list(_Req(node_id="7")))
        res = _run(env.routes.pick_thumb(
            _Req(path=str(env.out / "Food" / "a.png"), px="64")))
        with Image.open(io.BytesIO(res["response"]["body"])) as img:
            assert max(img.size) == 64

    def test_transparency_survives_the_shrink(self, env):
        """A background-removed render judged on a black rectangle is not the
        image that was approved."""
        os.makedirs(str(env.out / "Food"), exist_ok=True)
        Image.new("RGBA", (40, 40), (10, 20, 30, 0)).save(
            str(env.out / "Food" / "a.png"))
        env.pick.remember("7", str(env.out / "Food"))
        _run(env.routes.pick_list(_Req(node_id="7")))
        res = _run(env.routes.pick_thumb(
            _Req(path=str(env.out / "Food" / "a.png"))))
        with Image.open(io.BytesIO(res["response"]["body"])) as img:
            assert img.mode == "RGBA"

    def test_an_absurd_size_is_clamped_rather_than_honoured(self, env):
        renders(str(env.out / "Food"), ("a.png",), size=(40, 40))
        env.pick.remember("7", str(env.out / "Food"))
        _run(env.routes.pick_list(_Req(node_id="7")))
        res = _run(env.routes.pick_thumb(
            _Req(path=str(env.out / "Food" / "a.png"), px="99999")))
        assert res["status"] == 200

    def test_a_file_that_is_not_an_image_is_refused(self, env):
        os.makedirs(str(env.out / "Food"), exist_ok=True)
        (env.out / "Food" / "broken.png").write_bytes(b"not an image")
        renders(str(env.out / "Food"), ("a.png",))
        env.pick.remember("7", str(env.out / "Food"))
        _run(env.routes.pick_list(_Req(node_id="7")))
        res = _run(env.routes.pick_thumb(
            _Req(path=str(env.out / "Food" / "broken.png"))))
        assert res["status"] == 400


class TestWhichLayoutANameMeans:
    def test_files_named_after_it_win_over_the_folder_of_that_name(self, env):
        """The directory of the same name holds the steps that come after —
        listing both put every edit among the renders to choose a base from."""
        renders(str(env.out / "Food"), ("Spookies_00001_.png",))
        renders(str(env.out / "Food" / "Spookies"), ("edits_00001_.png",),
                colour=90)
        env.pick.remember("7", str(env.out / "Food" / "Spookies"))
        body = _run(env.routes.pick_list(_Req(node_id="7")))["body"]
        assert [i["name"] for i in body["images"]] == ["Spookies_00001_.png"]

    def test_a_stage_reads_inside_the_assets_folder(self, env):
        renders(str(env.out / "Food"), ("Spookies_00001_.png",))
        renders(str(env.out / "Food" / "Spookies"), ("edits_00001_.png",),
                colour=90)
        env.pick.remember("7", str(env.out / "Food" / "Spookies" / "edits"))
        body = _run(env.routes.pick_list(_Req(node_id="7")))["body"]
        assert [i["name"] for i in body["images"]] == ["edits_00001_.png"]


class TestListingAShortlist:
    """A picker fed by another lists exactly what that one approved, so the
    panel has to be able to ask for the same narrowed set."""

    def test_only_the_approved_names_come_back(self, env):
        renders(str(env.out / "Food"), ("a.png", "b.png", "c.png"))
        env.pick.remember("7", str(env.out / "Food"), ["a.png", "c.png"])
        body = _run(env.routes.pick_list(_Req(node_id="7")))["body"]
        assert [i["name"] for i in body["images"]] == ["a.png", "c.png"]
        assert body["shortlist"] is True

    def test_a_folder_read_is_not_a_shortlist(self, env):
        renders(str(env.out / "Food"), ("a.png",))
        env.pick.remember("7", str(env.out / "Food"))
        body = _run(env.routes.pick_list(_Req(node_id="7")))["body"]
        assert body["shortlist"] is False

    def test_browsing_by_name_ignores_any_shortlist(self, env):
        """Browsing a folder is browsing a whole folder; a shortlist belongs to
        the picker that made it."""
        renders(str(env.out / "Food"), ("a.png", "b.png"))
        env.pick.remember("7", str(env.out / "Food"), ["a.png"])
        body = _run(env.routes.pick_list(
            _Req(node_id="7", folder=str(env.out / "Food"))))["body"]
        assert len(body["images"]) == 2
