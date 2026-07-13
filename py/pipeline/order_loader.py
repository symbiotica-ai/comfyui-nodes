# ABOUTME: Runner side of the Order Read node — loads a client order (local xlsx +
# ABOUTME: reference-image folder) and emits per-event specs for downstream nodes.
# Port of symbiotica-hub apps/web/src/lib/flows/order-read.ts.
from __future__ import annotations

import json
import os

from .order_sheet import (
    extract_order_rows,
    group_order_events,
    parse_xlsx_grid,
    template_groups,
)


def load_order(order_path: str, refs_path: str = "") -> dict:
    """Read the order xlsx + list the refs folder (names only — images are
    never opened) and group into events."""
    try:
        with open(order_path, "rb") as f:
            data = f.read()
    except OSError:
        raise ValueError(f"order file not readable: {order_path}")
    ref_files: list[str] = []
    if refs_path:
        try:
            ref_files = [n for n in os.listdir(refs_path) if not n.startswith(".")]
        except OSError:
            raise ValueError(f"references folder not readable: {refs_path}")
    events = group_order_events(extract_order_rows(parse_xlsx_grid(data)), ref_files)
    return {"events": events, "refFileCount": len(ref_files)}


def event_spec(events: list[dict], feature: str) -> dict:
    """The picked event's full spec: its template groups with complete asset
    dicts (the Template builder needs category/canvas/prompt/refFiles)."""
    event = next((e for e in events if e["feature"] == feature), None)
    if event is None:
        have = ", ".join(e["feature"] for e in events)
        raise ValueError(
            f'selected feature "{feature}" is not in the parsed order (have: {have})'
        )
    return {
        "feature": event["feature"],
        "eventName": event["eventName"],
        "templates": template_groups(event),
    }


def spec_wire_json(spec: dict) -> str:
    """Hub's orderOutput(selected) wire shape — trimmed per-asset keys."""
    return json.dumps(
        {
            "feature": spec["feature"],
            "eventName": spec["eventName"],
            "templates": [
                {
                    "template": g["template"],
                    "category": g["category"],
                    "canvas": g["canvas"],
                    "assets": [
                        {
                            "name": a["assetName"],
                            "id": a["assetId"],
                            "canvas": a["canvas"],
                            "plot": a["plot"],
                            "rotation": a["rotation"],
                            "prompt": a["prompt"],
                            "refFiles": a["refFiles"],
                        }
                        for a in g["assets"]
                    ],
                }
                for g in spec["templates"]
            ],
        },
        indent=1,
    )


def order_overview(events: list[dict]) -> dict:
    """Month overview — one summary entry per event (the node's own preview)."""
    out = []
    for e in events:
        named = [a for a in e["assets"] if a["assetName"]]
        out.append({
            "feature": e["feature"],
            "eventName": e["eventName"],
            "assetCount": len(e["assets"]),
            "named": len(named),
            "refMatched": len([a for a in named if a["refFiles"]]),
        })
    return {"events": out}
