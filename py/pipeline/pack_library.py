# ABOUTME: On-disk store for Auto Packer "templates" — a saved recipe (order +
# ABOUTME: preset + settings + overrides) plus the packed sheet PNGs, one folder
# ABOUTME: per template under a project's templates/ subfolder.
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

from .order_sheet import slugify


def templates_dir(project_path: str) -> str:
    """The templates/ subfolder of a client project folder (the same folder that
    holds orders/ and reference-assets/). Empty string when no project given."""
    project_path = (project_path or "").strip()
    return os.path.join(project_path, "templates") if project_path else ""


def _template_subdir(base_dir: str, name: str) -> tuple[str, str]:
    """(slug, absolute subfolder) for a template name under base_dir. The subdir
    is realpath-checked to stay inside base_dir so a crafted name can't escape."""
    stem = slugify(name) or "template"
    root = os.path.realpath(base_dir)
    sub = os.path.realpath(os.path.join(root, stem))
    if not (sub == root or sub.startswith(root + os.sep)):
        raise ValueError("template name escapes the templates folder")
    return stem, sub


def write_pack_template(base_dir: str, name: str, sheet_images,
                        sidecar: dict) -> dict:
    """Write one template folder: sheet-000.png … + template.json, together in
    base_dir/<slug>/. Re-saving the same name overwrites (stale sheet-*.png are
    cleared first, so a shorter re-pack doesn't leave stragglers). sheet_images
    is a list of PIL Images. Returns {name, dir, sheets, sheetCount}."""
    stem, sub = _template_subdir(base_dir, name)
    os.makedirs(sub, exist_ok=True)
    for old in os.listdir(sub):
        if old.startswith("sheet-") and old.endswith(".png"):
            try:
                os.remove(os.path.join(sub, old))
            except OSError:
                pass
    sheet_files = []
    for i, img in enumerate(sheet_images):
        fname = f"sheet-{i:03d}.png"
        img.convert("RGB").save(os.path.join(sub, fname))
        sheet_files.append(fname)
    doc = {
        "name": stem,
        "savedAt": datetime.now().isoformat(timespec="seconds"),
        "sheets": sheet_files,
        "sheetCount": len(sheet_files),
        **sidecar,
    }
    with open(os.path.join(sub, "template.json"), "w") as f:
        json.dump(doc, f, indent=1)
    return {"name": stem, "dir": sub, "sheets": sheet_files,
            "sheetCount": len(sheet_files)}


def load_pack_template(base_dir: str, name: str) -> dict | None:
    """Read one template's template.json (by name/slug). None when absent or
    unreadable. Injects dir (abs) + sheetPaths (abs paths of sheets present)."""
    if not base_dir or not (name or "").strip():
        return None
    try:
        stem, sub = _template_subdir(base_dir, name)
    except ValueError:
        return None
    path = os.path.join(sub, "template.json")
    try:
        with open(path) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(doc, dict):
        return None
    doc["dir"] = sub
    doc["sheetPaths"] = [os.path.join(sub, s) for s in doc.get("sheets", [])
                         if os.path.isfile(os.path.join(sub, s))]
    return doc


def list_pack_templates(base_dir: str) -> list[dict]:
    """Every readable template under base_dir, sorted by name. Each is its
    template.json plus dir (abs) + sheetPaths (abs). A missing dir is an empty
    list; a corrupt sidecar is skipped, never fatal."""
    if not base_dir or not os.path.isdir(base_dir):
        return []
    out = []
    for entry in sorted(os.listdir(base_dir)):
        sub = os.path.join(base_dir, entry)
        if not os.path.isdir(sub):
            continue
        doc = load_pack_template(base_dir, entry)
        if doc is not None:
            out.append(doc)
    return sorted(out, key=lambda d: str(d.get("name", "")))


def delete_pack_template(base_dir: str, name: str) -> bool:
    """Remove one template folder. basename/realpath-guarded to base_dir. True
    when something was removed, False when absent (never an error)."""
    if not base_dir or not (name or "").strip():
        return False
    try:
        stem, sub = _template_subdir(base_dir, name)
    except ValueError:
        return False
    if os.path.isdir(sub):
        shutil.rmtree(sub, ignore_errors=True)
        return True
    return False


# A save can land in the project's templates/ OR, when that folder is unwritable
# (a read-only Modal Volume) or absent (no project_path, e.g. Files Read), in
# output/templates. So the browse side must read BOTH — otherwise a saved
# template is invisible and can never be reloaded. These merge across the dirs.
def list_pack_templates_dirs(dirs) -> list[dict]:
    """Merge templates across dirs, de-duped by name (earlier dir wins — the
    project folder is passed first, so a filed template shadows a fallback one
    of the same name). Sorted by name."""
    seen: dict[str, dict] = {}
    for base in dirs:
        for d in list_pack_templates(base):
            seen.setdefault(str(d.get("name", "")), d)
    return sorted(seen.values(), key=lambda d: str(d.get("name", "")))


def load_pack_template_dirs(dirs, name) -> dict | None:
    """First readable template named `name` across dirs (project dir first)."""
    for base in dirs:
        doc = load_pack_template(base, name)
        if doc is not None:
            return doc
    return None


def delete_pack_template_dirs(dirs, name) -> bool:
    """Delete `name` from every dir it exists in. True if anything was removed."""
    removed = False
    for base in dirs:
        if delete_pack_template(base, name):
            removed = True
    return removed


def resolve_pack_inputs(*, order, preset, settings, category, overrides,
                        template):
    """Layer a Template Library `template` bundle under the node's own inputs:
    the node's wired order/preset/settings and its category/overrides widgets
    WIN; the template supplies whatever the node left at its default. Returns
    {order, preset, settings, category, overrides} of effective values.

    A template is a dict {order, preset, settings, category, overrides, name}.
    order/preset/settings are considered "set" on the node when they are dicts;
    category is "set" when it is not the "All" default; overrides is "set" when
    it is not empty ("" or "{}"). This keeps the widget the source of truth once
    the user (or the Library's JS) has populated it, and falls back to the frozen
    recipe otherwise — so a headless queue with no JS still reproduces it."""
    tpl = template if isinstance(template, dict) else None

    def _dict(v):
        return v if isinstance(v, dict) else None

    eff_order = _dict(order) if _dict(order) and "assets" in order else None
    if eff_order is None and tpl:
        eff_order = _dict(tpl.get("order"))

    eff_preset = _dict(preset)
    if eff_preset is None and tpl:
        eff_preset = _dict(tpl.get("preset"))

    eff_settings = _dict(settings)
    if eff_settings is None and tpl:
        eff_settings = _dict(tpl.get("settings"))

    # "" (the node's unset default) defers to the template; a concrete pick —
    # INCLUDING an explicit "All" — is the user's choice and wins. Using "All"
    # itself as the sentinel would make "pack every category" impossible to
    # choose over a template whose saved category was narrower.
    raw = (category or "").strip()
    if tpl and raw == "":
        cat = str(tpl.get("category") or "All").strip() or "All"
    else:
        cat = raw or "All"

    ov = (overrides or "").strip()
    if tpl and ov in ("", "{}"):
        tpl_ov = tpl.get("overrides")
        ov = json.dumps(tpl_ov) if isinstance(tpl_ov, dict) else "{}"

    return {"order": eff_order, "preset": eff_preset or {},
            "settings": eff_settings or {}, "category": cat,
            "overrides": ov or "{}"}
