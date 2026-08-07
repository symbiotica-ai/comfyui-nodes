# ABOUTME: One contract every node in the pack has to keep — each input the
# ABOUTME: schema declares must be one its execute and lifecycle methods accept.
import importlib
import inspect
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(__file__))
from comfy_api_stub import build_modules

LIFECYCLE = ("execute", "fingerprint_inputs", "check_lazy_status")


@pytest.fixture(scope="module")
def pack(tmp_path_factory):
    """The whole pack loaded the way ComfyUI loads it, from the repo root.

    Not one node module: `__init__.py` walks `py/` and catches per module, so a
    contract only checkable across the whole mapping needs the whole mapping.

    Everything this puts in `sys.modules` comes back out. Loading the pack
    installs a stubbed `comfy_api` and every module under `py/`; left behind,
    they answer imports in tests that run later, and a test asserting the real
    thing is ABSENT then finds the stub and passes for the wrong reason.
    """
    before = set(sys.modules)
    path_len = len(sys.path)
    pkg, latest = build_modules()
    sys.modules["comfy_api"] = pkg
    sys.modules["comfy_api.latest"] = latest
    out = tmp_path_factory.mktemp("output")
    fp = types.ModuleType("folder_paths")
    fp.get_output_directory = lambda: str(out)
    fp.get_input_directory = lambda: str(out)
    fp.get_temp_directory = lambda: str(out)
    sys.modules["folder_paths"] = fp
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.dirname(root))
    try:
        yield importlib.import_module(os.path.basename(root))
    finally:
        for name in set(sys.modules) - before:
            sys.modules.pop(name, None)
        del sys.path[:len(sys.path) - path_len]


def test_every_declared_input_is_one_the_node_can_accept(pack):
    """ComfyUI hands `execute` a keyword per input, so an input the schema
    declares and the signature omits is a TypeError the moment it is used.

    A WIRED input is passed even when the schema no longer declares it —
    `get_input_data` takes the link branch on `not input_info` — so removing an
    input does not spare a graph that still wires it. Nothing here can fix that
    graph, but this keeps the pack's own half of the contract: whatever a node
    offers, it accepts.
    """
    broken = []
    checked = 0
    for name, cls in sorted(pack.NODE_CLASS_MAPPINGS.items()):
        # V1 nodes declare inputs through INPUT_TYPES and take them positionally
        # by another route; this contract is about the V3 schema.
        if not hasattr(cls, "GET_SCHEMA"):
            continue
        try:
            schema = cls.GET_SCHEMA()
        except Exception as exc:                    # pragma: no cover
            broken.append(f"{name}: schema raised {exc!r}")
            continue
        checked += 1
        declared = {i.id for i in (schema.inputs or []) if getattr(i, "id", None)}
        for method in LIFECYCLE:
            fn = getattr(cls, method, None)
            if fn is None:
                continue
            try:
                params = inspect.signature(fn).parameters
            except (TypeError, ValueError):          # pragma: no cover
                continue
            if any(p.kind is p.VAR_KEYWORD for p in params.values()):
                continue
            absent = declared - (set(params) - {"cls", "self"})
            if absent:
                broken.append(f"{name}.{method} cannot accept: "
                              f"{', '.join(sorted(absent))}")
    assert broken == []
    # An empty list is only reassuring if the loop actually ran.
    # Most of the pack is V1; the pipeline nodes are the V3 ones. The floor
    # is here so an import failure that empties the mapping cannot read as a
    # clean run.
    assert checked >= 30, f"only {checked} V3 nodes reached the check"


def test_the_whole_pack_registers(pack):
    """A module that raises on import drops its nodes with only a console
    traceback, so a release can lose nodes without failing a single test."""
    assert len(pack.NODE_CLASS_MAPPINGS) >= 128
