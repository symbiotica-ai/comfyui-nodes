# ABOUTME: Tests the group-module merge — tagged member nodes are replaced by
# ABOUTME: the library version, links relinked by slot name, ids kept.
import copy
import json

from _modules import GTAG, apply_modules, load_library, write_module

NAME = "controlnet"


def node(nid, ntype, pos, inputs=(), outputs=(), values=None, key=None, rev=1, snapshot=None):
    n = {
        "id": nid, "type": ntype, "pos": list(pos), "size": [200, 100], "flags": {},
        "order": 0, "mode": 0,
        "inputs": [{"name": i, "type": "IMAGE", "link": None} for i in inputs],
        "outputs": [{"name": o, "type": "IMAGE", "links": []} for o in outputs],
        "properties": {},
        "widgets_values": list(values) if values is not None else [],
    }
    if key is not None:
        n["properties"][GTAG] = {"name": NAME, "key": str(key), "rev": rev,
                                 "snapshot": list(snapshot if snapshot is not None else values or [])}
    return n


def connect(graph, link_id, a, a_slot, b, b_slot, as_dict=False):
    """Wire a->b in a root-shaped graph (array links) or a def (object links)."""
    if as_dict:
        graph["links"].append({"id": link_id, "origin_id": a["id"], "origin_slot": a_slot,
                               "target_id": b["id"], "target_slot": b_slot, "type": "IMAGE"})
    else:
        graph["links"].append([link_id, a["id"], a_slot, b["id"], b_slot, "IMAGE"])
    a["outputs"][a_slot]["links"].append(link_id)
    b["inputs"][b_slot]["link"] = link_id


def published_module(rev=2, padding=100, extra_node=False, drop_pad=False):
    """Module: Load(1) -> Pad(2) -> Preview(3), positions relative to the frame."""
    nodes = [
        node(1, "LoadImage", (10, 40), outputs=("IMAGE", "MASK"), values=["ref.png", "image"]),
        node(3, "PreviewImage", (500, 40), inputs=("images",), values=[]),
    ]
    links = []
    if not drop_pad:
        nodes.insert(1, node(2, "Padding", (250, 40), inputs=("image",), outputs=("image",),
                             values=[padding, "0, 0, 0", "color"]))
        links = [{"id": 1, "origin_id": 1, "origin_slot": 0, "target_id": 2, "target_slot": 0, "type": "IMAGE"},
                 {"id": 2, "origin_id": 2, "origin_slot": 0, "target_id": 3, "target_slot": 0, "type": "IMAGE"}]
    else:
        links = [{"id": 1, "origin_id": 1, "origin_slot": 0, "target_id": 3, "target_slot": 0, "type": "IMAGE"}]
    if extra_node:
        nodes.append(node(4, "ImageBlur", (250, 200), inputs=("image",), outputs=("image",), values=[3]))
        links.append({"id": 3, "origin_id": 1, "origin_slot": 0, "target_id": 4, "target_slot": 0, "type": "IMAGE"})
    return {"name": NAME, "rev": rev, "kind": "group",
            "group": {"title": "Controlnet", "color": "#3f789e", "flags": {}},
            "nodes": nodes, "links": links}


def workflow_with_group(as_def=False):
    """A root workflow holding an r1 instance of the module inside a frame at
    (1000, 1000), wired to an outside upscaler on both ends."""
    load = node(2999, "LoadImage", (1010, 1040), outputs=("IMAGE", "MASK"),
                values=["cube.png", "image"], key=1, snapshot=["ref.png", "image"])
    pad = node(3270, "Padding", (1250, 1040), inputs=("image",), outputs=("image",),
               values=[50, "0, 0, 0", "color"], key=2, snapshot=[50, "0, 0, 0", "color"])
    prev = node(3236, "PreviewImage", (1500, 1040), inputs=("images",), values=[], key=3, snapshot=[])
    source = node(10, "LoadImage", (100, 100), outputs=("IMAGE", "MASK"), values=["src.png", "image"])
    sink = node(11, "ImageUpscale", (2000, 100), inputs=("image",), values=[])
    graph = {"nodes": [source, load, pad, prev, sink], "links": [],
             "groups": [{"id": 7, "title": "Controlnet", "bounding": [1000, 1000, 800, 300], "color": "#3f789e", "flags": {}}]}
    as_dict = as_def
    connect(graph, 100, load, 0, pad, 0, as_dict)
    connect(graph, 101, pad, 0, prev, 0, as_dict)
    connect(graph, 102, pad, 0, sink, 0, as_dict)      # outgoing external link
    connect(graph, 103, source, 0, load, 0, as_dict) if False else None  # LoadImage has no inputs
    if as_def:
        graph.update({"id": "def-id", "version": 1, "state": {"lastNodeId": 3270, "lastLinkId": 103}})
        return {"nodes": [], "links": [], "last_node_id": 0, "last_link_id": 0,
                "definitions": {"subgraphs": [graph]}, "extra": {}}
    graph.update({"last_node_id": 3270, "last_link_id": 103, "extra": {}})
    return graph


def by_id(graph, nid):
    return next(n for n in graph["nodes"] if n["id"] == nid)


def links_of(graph):
    return {(l[1], l[2], l[3], l[4]) if isinstance(l, list) else
            (l["origin_id"], l["origin_slot"], l["target_id"], l["target_slot"]) for l in graph["links"]}


class TestGroupMerge:
    def test_changed_value_lands_and_local_value_survives(self):
        w = workflow_with_group()
        report = apply_modules(w, {NAME: published_module(padding=100)})
        assert report["updated"] == [{"name": NAME, "rev": 2}]
        # padding 50 -> 100 came from the module; the LoadImage file stays local
        assert by_id(w, 3270)["widgets_values"][0] == 100
        assert by_id(w, 2999)["widgets_values"][0] == "cube.png"
        assert by_id(w, 2999)["properties"][GTAG] == {
            "name": NAME, "key": "1", "rev": 2, "snapshot": ["ref.png", "image"]}

    def test_ids_positions_and_external_links_are_kept(self):
        w = workflow_with_group()
        apply_modules(w, {NAME: published_module()})
        assert sorted(n["id"] for n in w["nodes"]) == [10, 11, 2999, 3236, 3270]
        assert by_id(w, 3270)["pos"] == [1250, 1040]
        # internal links rebuilt with fresh ids, external link 102 untouched
        assert links_of(w) == {(2999, 0, 3270, 0), (3270, 0, 3236, 0), (3270, 0, 11, 0)}
        assert by_id(w, 11)["inputs"][0]["link"] == 102
        assert 102 in by_id(w, 3270)["outputs"][0]["links"]
        assert w["last_link_id"] >= 105

    def test_a_node_added_to_the_module_appears_at_its_relative_position(self):
        w = workflow_with_group()
        apply_modules(w, {NAME: published_module(extra_node=True)})
        blur = next(n for n in w["nodes"] if n["type"] == "ImageBlur")
        assert blur["id"] == 3271 and w["last_node_id"] == 3271
        assert blur["pos"] == [1250, 1200]
        assert blur["properties"][GTAG]["key"] == "4"
        assert (2999, 0, 3271, 0) in links_of(w)
        # frame grew to hold it
        x, y, wdt, hgt = w["groups"][0]["bounding"]
        assert y + hgt >= 1300 and x == 1000 and y == 1000

    def test_a_node_removed_from_the_module_drops_its_outside_link(self):
        w = workflow_with_group()
        report = apply_modules(w, {NAME: published_module(drop_pad=True)})
        assert all(n["type"] != "Padding" for n in w["nodes"])
        assert links_of(w) == {(2999, 0, 3236, 0)}
        assert by_id(w, 11)["inputs"][0]["link"] is None
        assert report["links_dropped"] == [{"module": NAME, "key": "2", "slot": "image"}]

    def test_instance_inside_a_subgraph_definition_with_object_links(self):
        w = workflow_with_group(as_def=True)
        apply_modules(w, {NAME: published_module(extra_node=True)})
        d = w["definitions"]["subgraphs"][0]
        assert by_id(d, 3270)["widgets_values"][0] == 100
        assert all(isinstance(l, dict) for l in d["links"])
        assert d["state"]["lastNodeId"] == 3271
        assert (2999, 0, 3271, 0) in links_of(d)

    def test_current_revision_and_foreign_names_are_left_alone(self):
        w = workflow_with_group()
        before = copy.deepcopy(w)
        assert apply_modules(w, {NAME: published_module(rev=1)})["changed"] is False
        assert apply_modules(w, {"other": published_module()})["changed"] is False
        assert w == before

    def test_two_instances_in_two_frames_sync_separately(self):
        w = workflow_with_group()
        second = copy.deepcopy(w)
        for n in second["nodes"][1:4]:
            n["id"] += 10000
            n["pos"][1] += 5000
            for i in n["inputs"]:
                i["link"] = None
            for o in n["outputs"]:
                o["links"] = []
        w["nodes"].extend(second["nodes"][1:4])
        w["groups"].append({"id": 8, "title": "Controlnet", "bounding": [1000, 6000, 800, 300], "flags": {}})
        report = apply_modules(w, {NAME: published_module()})
        assert len(report["updated"]) == 2
        assert by_id(w, 13270)["widgets_values"][0] == 100

    def test_widget_count_mismatch_keeps_local_values(self):
        w = workflow_with_group()
        by_id(w, 3270)["widgets_values"].append("extra")
        report = apply_modules(w, {NAME: published_module()})
        assert by_id(w, 3270)["widgets_values"] == [50, "0, 0, 0", "color", "extra"]
        assert report["values_skipped"] == [3270]


class TestGroupLibrary:
    def test_publish_strips_tags_and_links_and_bumps_rev(self, tmp_path):
        lib = str(tmp_path)
        w = workflow_with_group()
        members = [by_id(w, 2999), by_id(w, 3270), by_id(w, 3236)]
        payload = {"group": {"title": "Controlnet"}, "nodes": members,
                   "links": [{"id": 100, "origin_id": 2999, "origin_slot": 0, "target_id": 3270, "target_slot": 0, "type": "IMAGE"}]}
        first = write_module(lib, NAME, group=payload)
        second = write_module(lib, NAME, group=payload)
        assert (first["kind"], first["rev"], second["rev"]) == ("group", 1, 2)
        stored = load_library(lib)[NAME]
        assert stored["kind"] == "group"
        assert all(GTAG not in n["properties"] for n in stored["nodes"])
        assert all(i["link"] is None for n in stored["nodes"] for i in n["inputs"])
        assert stored["links"][0]["origin_id"] == 2999
        json.dumps(stored)
