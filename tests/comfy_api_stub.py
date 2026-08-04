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
    """Mirrors the real Schema closely enough to assert on.

    Every remaining kwarg is KEPT as an attribute rather than swallowed: a
    behaviour-changing flag like `is_input_list` is invisible to a test that
    only sees the fields this stub happens to name, and its absence would look
    exactly like a passing test."""

    def __init__(self, node_id=None, display_name=None, category=None,
                 inputs=None, outputs=None, is_input_list=False, **kw):
        self.node_id = node_id
        self.display_name = display_name
        self.category = category
        self.inputs = inputs or []
        self.outputs = outputs or []
        self.is_input_list = is_input_list
        self.__dict__.update(kw)


class ComfyNode:
    @classmethod
    def GET_SCHEMA(cls):
        """Build the node's schema, as ComfyUI's own io.ComfyNode does. The
        registration shim calls this on every class in PIPELINE_NODE_CLASSES,
        so a define_schema that raises must be reachable from a test."""
        return cls.define_schema()


class NodeOutput:
    def __init__(self, *args, ui=None):
        self.args = args
        # What the node draws on its own body, which ComfyUI carries alongside
        # the wire values rather than in them — a node can say something on the
        # canvas without that showing up as an output.
        self.ui = ui


class _DynamicCombo(_IOType):
    """A combo whose chosen option carries its own inputs.

    The generic `_IOType` already builds the Input, because `_IOValue` keeps
    every kwarg — what it cannot express is `Option`, and a schema that calls
    it would fail here for a reason that says nothing about the node."""

    class Option:
        def __init__(self, label, inputs=None, **kw):
            self.label = label
            self.inputs = inputs or []
            self.__dict__.update(kw)


class _Autogrow(_IOType):
    """Slots that grow as they are filled — `image_1..N` rather than a batch.

    At execute time ComfyUI hands these over as a DICT keyed by slot name, not
    a list, and a slot may hold a batch of its own. Tests that build the value
    by hand have to match that shape or they verify a graph nobody runs."""

    class TemplateNames:
        def __init__(self, template_input, names=None, min=0, **kw):
            self.template_input = template_input
            self.names = list(names or [])
            self.min = min
            self.__dict__.update(kw)

    class TemplatePrefix:
        def __init__(self, template_input, prefix="", max=0, min=0, **kw):
            self.template_input = template_input
            self.prefix = prefix
            self.max = max
            self.min = min
            self.__dict__.update(kw)


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
        String=_IOType, Boolean=_IOType, Custom=lambda name: _IOType,
        DynamicCombo=_DynamicCombo, Autogrow=_Autogrow,
        # Named values a schema lists rather than a type it builds from.
        Hidden=types.SimpleNamespace(unique_id="unique_id"))
    latest = types.ModuleType("comfy_api.latest")
    latest.io = io_ns
    # Keeps the text the node meant to show, so a test can assert on what lands
    # on the canvas rather than only on the wire.
    latest.ui = types.SimpleNamespace(
        PreviewText=lambda value, **kw: types.SimpleNamespace(value=value))
    pkg = types.ModuleType("comfy_api")
    pkg.latest = latest
    return pkg, latest
