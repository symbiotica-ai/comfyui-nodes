# ABOUTME: Registration shim — exposes the V3 pipeline nodes through the repo's
# ABOUTME: V1 auto-discovery. Needed because ComfyUI's loader (nodes.py) ignores
# comfy_entrypoint when a package already exports NODE_CLASS_MAPPINGS (elif),
# and the V3 loader path does exactly this mapping anyway (nodes.py:2306).
from .pipeline.nodes import PIPELINE_NODE_CLASSES

NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

for _cls in PIPELINE_NODE_CLASSES:
    _schema = _cls.GET_SCHEMA()
    NODE_CLASS_MAPPINGS[_schema.node_id] = _cls
    if _schema.display_name:
        NODE_DISPLAY_NAME_MAPPINGS[_schema.node_id] = _schema.display_name
