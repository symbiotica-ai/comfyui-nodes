# ABOUTME: Factory for a minimal comfy_api.latest stub. build_modules() returns
# ABOUTME: fresh module objects for a test's own monkeypatch.setitem install.
import types


class _IOValue:
    def __init__(self, id=None, display_name=None, **kw):
        self.id = id
        self.display_name = display_name
        self.__dict__.update(kw)


class _IOType:
    Input = staticmethod(lambda id, **kw: _IOValue(id=id, **kw))
    Output = staticmethod(lambda **kw: _IOValue(**kw))


class Schema:
    def __init__(self, node_id=None, category=None, inputs=None,
                 outputs=None, **kw):
        self.node_id = node_id
        self.category = category
        self.inputs = inputs or []
        self.outputs = outputs or []


class ComfyNode:
    pass


class NodeOutput:
    def __init__(self, *args):
        self.args = args


class _IONamespace(types.SimpleNamespace):
    """`io`, with every datatype we did not list behaving like a plain IO type.

    A schema only needs Input/Output factories from io.Image, io.Int, io.Mask…,
    never their real semantics — and hard-coding the list means a node that
    starts using one more type fails here for no useful reason."""

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return _IOType


def build_modules():
    """Fresh comfy_api + comfy_api.latest modules, for the caller to install
    via monkeypatch.setitem(sys.modules, ...) so it auto-reverts."""
    io_ns = _IONamespace(
        ComfyNode=ComfyNode, Schema=Schema, NodeOutput=NodeOutput,
        String=_IOType, Boolean=_IOType, Custom=lambda name: _IOType)
    latest = types.ModuleType("comfy_api.latest")
    latest.io = io_ns
    latest.ui = types.SimpleNamespace()
    pkg = types.ModuleType("comfy_api")
    pkg.latest = latest
    return pkg, latest
