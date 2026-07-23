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


def build_modules():
    """Fresh comfy_api + comfy_api.latest modules, for the caller to install
    via monkeypatch.setitem(sys.modules, ...) so it auto-reverts."""
    io_ns = types.SimpleNamespace(
        ComfyNode=ComfyNode, Schema=Schema, NodeOutput=NodeOutput,
        String=_IOType, Boolean=_IOType, Custom=lambda name: _IOType)
    latest = types.ModuleType("comfy_api.latest")
    latest.io = io_ns
    latest.ui = types.SimpleNamespace()
    pkg = types.ModuleType("comfy_api")
    pkg.latest = latest
    return pkg, latest
