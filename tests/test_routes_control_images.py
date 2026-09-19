# ABOUTME: The control-image routes — the folder the node names is the folder
# ABOUTME: they browse and write, and every name resolves inside it or not at all.
import asyncio
import importlib
import os
import sys
import types
from types import SimpleNamespace

import pytest


class _Routes:
    def get(self, path):
        def deco(fn):
            return fn
        return deco
    post = get


@pytest.fixture()
def routes_mod(monkeypatch):
    captured = {}

    def json_response(body, status=200):
        captured.clear()
        captured.update(body=body, status=status)
        return SimpleNamespace(body=body, status=status)

    server = SimpleNamespace(instance=SimpleNamespace(routes=_Routes()))
    monkeypatch.setitem(sys.modules, "server", SimpleNamespace(PromptServer=server))
    fake_web = types.ModuleType("aiohttp.web")
    fake_web.json_response = json_response
    fake_aiohttp = types.ModuleType("aiohttp")
    fake_aiohttp.web = fake_web
    monkeypatch.setitem(sys.modules, "aiohttp", fake_aiohttp)
    monkeypatch.setitem(sys.modules, "aiohttp.web", fake_web)
    from pipeline import routes as mod
    importlib.reload(mod)
    mod._captured = captured
    return mod


def _get(**query):
    return SimpleNamespace(query=query)


def _post(body):
    async def _json():
        return body
    return SimpleNamespace(json=_json)


class _Upload(dict):
    """What aiohttp hands back for a multipart POST: plain fields by key, and
    every file part under one."""

    def __init__(self, fields, files):
        super().__init__(fields)
        self._files = files

    def getall(self, key, default=None):
        return self._files if key == "files" else (default or [])


def _upload(fields, files):
    parsed = _Upload(fields, files)

    async def _post_body():
        return parsed
    return SimpleNamespace(post=_post_body)


def _file(name, data=b"PNG"):
    return SimpleNamespace(filename=name, file=SimpleNamespace(
        read=lambda: data))


@pytest.fixture()
def library(tmp_path):
    """A folder nothing has declared — somewhere on his disk, which is the
    only place his control images have ever been."""
    root = tmp_path / "projects" / "symbiotica" / "controlnet-images"
    (root / "general").mkdir(parents=True)
    (root / "general" / "1x1-box.png").write_bytes(b"x")
    return root


def test_a_folder_nobody_declared_is_browsed(routes_mod, library, monkeypatch):
    # "the node should browse the files from the path i input regardless of
    # whether i am on modal, local, etc" — the path IS the answer.
    monkeypatch.setattr(routes_mod, "_operator_roots", lambda: [])
    monkeypatch.setattr(routes_mod, "_template_dir", lambda: None)
    asyncio.run(routes_mod.control_images(_get(path=str(library))))
    body = routes_mod._captured["body"]
    assert routes_mod._captured["status"] == 200
    assert body["images"] == ["general/1x1-box.png"]
    assert body["folders"] == ["general"]


def test_browsing_makes_its_previews_servable(routes_mod, library, monkeypatch):
    # Each row's thumbnail goes back through the image routes, which serve
    # registered folders only.
    monkeypatch.setattr(routes_mod, "_operator_roots", lambda: [])
    assert routes_mod.is_allowed(str(library / "general" / "1x1-box.png")) is None
    asyncio.run(routes_mod.control_images(_get(path=str(library))))
    assert routes_mod.is_allowed(
        str(library / "general" / "1x1-box.png")) == os.path.realpath(
            str(library / "general" / "1x1-box.png"))


def test_a_path_that_is_not_one_is_refused(routes_mod):
    for path in ["", "relative/folder"]:
        asyncio.run(routes_mod.control_images(_get(path=path)))
        assert routes_mod._captured["status"] == 400


def test_a_folder_is_made_renamed_and_deleted(routes_mod, library):
    asyncio.run(routes_mod.control_images_mkdir(
        _post({"path": str(library), "name": "masks"})))
    assert (library / "masks").is_dir()

    asyncio.run(routes_mod.control_images_rename(
        _post({"path": str(library), "from": "masks", "to": "alpha"})))
    assert (library / "alpha").is_dir() and not (library / "masks").exists()

    asyncio.run(routes_mod.control_images_delete(
        _post({"path": str(library), "name": "alpha"})))
    assert not (library / "alpha").exists()
    assert routes_mod._captured["status"] == 200


def test_every_name_resolves_inside_the_folder_it_named(routes_mod, library,
                                                        tmp_path):
    # Containment is what decides what a request can touch, in place of an
    # allowlist of folders declared somewhere else.
    outside = tmp_path / "projects" / "secret"
    outside.mkdir(parents=True)
    (outside / "keep.png").write_bytes(b"x")

    for call, payload in [
        (routes_mod.control_images_mkdir, {"name": "../secret/made"}),
        (routes_mod.control_images_delete, {"name": "../secret/keep.png"}),
        (routes_mod.control_images_rename,
         {"from": "general/1x1-box.png", "to": "../secret/taken.png"}),
    ]:
        asyncio.run(call(_post({"path": str(library), **payload})))
        assert routes_mod._captured["status"] == 400, payload

    assert (outside / "keep.png").exists()
    assert list(os.listdir(outside)) == ["keep.png"]
    assert (library / "general" / "1x1-box.png").exists()


def test_dropped_files_land_in_the_folder_they_were_dropped_on(routes_mod,
                                                               library):
    asyncio.run(routes_mod.control_images_upload(_upload(
        {"path": str(library), "folder": "general"},
        [_file("mask.png"), _file("notes.txt"), _file("../escape.png")])))
    body = routes_mod._captured["body"]
    assert body["saved"] == ["general/mask.png", "general/escape.png"]
    assert body["refused"] and "notes.txt" in body["refused"][0]
    assert (library / "general" / "mask.png").read_bytes() == b"PNG"
    # A path in the name does not decide where the file lands.
    assert (library / "general" / "escape.png").exists()


def test_a_dropped_name_already_taken_never_overwrites(routes_mod, library):
    asyncio.run(routes_mod.control_images_upload(_upload(
        {"path": str(library), "folder": "general"},
        [_file("1x1-box.png", b"NEW")])))
    assert routes_mod._captured["body"]["saved"] == ["general/1x1-box-2.png"]
    assert (library / "general" / "1x1-box.png").read_bytes() == b"x"
