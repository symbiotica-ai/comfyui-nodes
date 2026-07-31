# ABOUTME: On-disk store for Auto Packer "templates" — a saved recipe (order +
# ABOUTME: preset + settings + overrides) plus the packed sheet PNGs, one folder
# ABOUTME: per template, split by KIND: order templates beside the month's order,
# ABOUTME: reference templates project-level (universal, any order).
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime

from .order_sheet import slugify

# The two kinds of saved pack. They differ in what they are FOR and therefore in
# where they live:
#   order      — packed from an Order Specs event: the design guide for ONE
#                month's order, so it lives beside that order's client refs
#                (<project>/orders/<Client-Month>/templates/).
#   reference  — packed from the Reference Browser over the game's asset
#                library: a style guide that is valid for any month, so it lives
#                project-level (<project>/templates/reference/).
KIND_ORDER = "order"
KIND_REFERENCE = "reference"
KINDS = (KIND_ORDER, KIND_REFERENCE)

# Directory names that hold a pool rather than one template.
POOL_DIRS = (KIND_REFERENCE, "orders")


def templates_dir(project_path: str) -> str:
    """The templates/ subfolder of a client project folder (the same folder that
    holds orders/ and reference-assets/). Empty string when no project given.

    This is the LEGACY flat pool — templates saved before the order/reference
    split. New saves go to reference_templates_dir / order_templates_dir; this
    folder is still browsed so old templates stay reloadable."""
    project_path = (project_path or "").strip()
    return os.path.join(project_path, "templates") if project_path else ""


def reference_templates_dir(project_path: str) -> str:
    """Where reference (game-asset) templates live: <project>/templates/reference.
    Deliberately month-free — a style guide built from the sprite catalog applies
    to every order."""
    base = templates_dir(project_path)
    return os.path.join(base, KIND_REFERENCE) if base else ""


def _resolved_month(project_path: str, month: str) -> dict:
    from .project_layout import resolve_month
    try:
        return resolve_month(project_path, month) or {}
    except (OSError, ValueError):
        return {}


def order_month_key(project_path: str, month: str) -> str:
    """One folder stem per month, whatever alias named it.

    "" (the node's "first month"), "October", and "Bakery October Art.xlsx" all
    denote the same order — keying folders off the raw widget string would file
    one month's templates in three places, and a save would land where no browse
    looks."""
    canon = _resolved_month(project_path, month).get("month") or ""
    return canon or (month or "")


def order_templates_dir(project_path: str, month: str = "") -> str:
    """Where a month's order templates live: the templates/ folder INSIDE that
    month's client-refs folder (<project>/orders/<Client-Month>/templates), so
    the month order stays self-contained — xlsx, client refs, and the design
    sheets built from them.

    When the month has no refs folder (or none could be resolved) it falls back
    to <project>/templates/orders/<month>, which keeps order templates month-
    scoped and still out of the reference pool. "" when there is no project."""
    project_path = (project_path or "").strip()
    if not project_path:
        return ""
    resolved = _resolved_month(project_path, month)
    refs = resolved.get("refs_path") or ""
    if refs:
        return os.path.join(refs, "templates")
    stem = slugify(resolved.get("month") or month) or "unscheduled"
    return os.path.join(templates_dir(project_path), "orders", stem)


def output_kind_dir(output_templates_dir: str, kind: str, month: str = "") -> str:
    """The same split under ComfyUI's output/templates — the fallback used when
    the project folder is unwritable (a read-only Modal Volume) or absent. Keeps
    a fallback save in its own kind, so the Library's filter still holds."""
    base = (output_templates_dir or "").strip()
    if not base:
        return ""
    if kind == KIND_REFERENCE:
        return os.path.join(base, KIND_REFERENCE)
    return os.path.join(base, "orders", slugify(month) or "unscheduled")


def kind_of_order(order) -> str:
    """Which kind an ORDER payload packs into. Order Specs and the Reference
    Browser both stamp `source`; anything older (a frozen order inside a saved
    template, a hand-built payload) is inferred — an order read from a month's
    xlsx carries a month and/or the shared catalog root, a library pick carries
    neither."""
    if not isinstance(order, dict):
        return KIND_ORDER
    src = str(order.get("source") or "").strip().lower()
    if src in KINDS:
        return src
    if str(order.get("month") or "").strip() or str(order.get("assetsRoot") or "").strip():
        return KIND_ORDER
    return KIND_REFERENCE


def split_qualified(name: str) -> tuple[str, str]:
    """("order"|"reference"|"", slug) for a possibly kind-qualified template id.

    The Library writes "order/mini-1-food" into its `selected`/`checked` widgets
    so the same slug can exist in both kinds; a bare slug (every workflow saved
    before the split) still resolves, first dir wins."""
    raw = str(name or "").strip().strip("/")
    head, sep, tail = raw.partition("/")
    if sep and head.lower() in KINDS and tail:
        return head.lower(), tail
    return "", raw


def qualified_name(kind: str, name: str) -> str:
    """"order/mini-1-food" for a kinded template, the bare slug for a legacy
    (unkinded) one — the id the Library puts on the wire."""
    kind = (kind or "").strip().lower()
    return f"{kind}/{name}" if kind in KINDS else str(name or "")


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
    # Kind rides in the sidecar for every save after the split; a legacy flat
    # template gets it inferred from its frozen order, so the browser can badge
    # it and a re-save routes it to the right folder.
    kind = str(doc.get("kind") or "").strip().lower()
    doc["kind"] = kind if kind in KINDS else kind_of_order(doc.get("order"))
    doc["key"] = qualified_name(doc["kind"], doc.get("name", stem))
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
    """Merge templates across dirs, de-duped by (kind, name) — earlier dir wins,
    so a filed template shadows a fallback one of the same name, while the SAME
    slug saved as both an order and a reference template stays two rows. Sorted
    by name (kind breaks ties)."""
    seen: dict[tuple[str, str], dict] = {}
    for base in dirs:
        for d in list_pack_templates(base):
            seen.setdefault((str(d.get("kind", "")), str(d.get("name", ""))), d)
    return sorted(seen.values(),
                  key=lambda d: (str(d.get("name", "")), str(d.get("kind", ""))))


def load_pack_template_dirs(dirs, name) -> dict | None:
    """First readable template `name` across dirs (project dir first). `name` may
    be kind-qualified ("reference/blossom-tower"), in which case a template of
    another kind with that slug is skipped rather than returned."""
    want_kind, slug = split_qualified(name)
    for base in dirs:
        doc = load_pack_template(base, slug)
        if doc is None:
            continue
        if want_kind and str(doc.get("kind", "")) != want_kind:
            continue
        return doc
    return None


def delete_pack_template_dirs(dirs, name) -> bool:
    """Delete `name` from every dir it exists in. True if anything was removed.
    A kind-qualified name only deletes templates of that kind — deleting the
    order template must never take the same-named reference one with it."""
    want_kind, slug = split_qualified(name)
    removed = False
    for base in dirs:
        # A pool root is never a template, whatever it carries. Pre-split saves
        # went flat into templates/<slug>, so a template named after a pool sits
        # exactly where that pool now lives — sidecar included.
        if slug in POOL_DIRS:
            continue
        # The target must BE a template, not merely a folder of that name: the
        # pools (reference/, orders/) live inside a dir that is itself a delete
        # base, so an unqualified pool name would otherwise take the whole pool.
        doc = load_pack_template(base, slug)
        if doc is None:
            continue
        if want_kind and str(doc.get("kind", "")) != want_kind:
            continue
        if delete_pack_template(base, slug):
            removed = True
    return removed


def _every_order_dir(project_path: str, output_templates_dir: str = "") -> list[str]:
    """Every month's order pool, plus any output-fallback month folder on disk.

    A save follows the ORDER's month while the Library browses its own — so
    "All" has to cover them all, or a template saved for November is in no pool
    the October-defaulted Library ever scans."""
    from .project_layout import list_order_months
    try:
        months = [o.get("label", "") for o in list_order_months(project_path)]
    except (OSError, ValueError):
        months = []
    dirs = []
    for m in months:
        dirs.append(order_templates_dir(project_path, m))
        dirs.append(output_kind_dir(output_templates_dir, KIND_ORDER, m))
    # Month folders under the output fallback that no order names — e.g.
    # "unscheduled", written when the packing order had no month at all.
    base = (output_templates_dir or "").strip()
    root = os.path.join(base, "orders") if base else ""
    try:
        for e in sorted(os.listdir(root)) if root else []:
            if os.path.isdir(os.path.join(root, e)):
                dirs.append(os.path.join(root, e))
    except OSError:
        pass
    return dirs


def pack_dirs(project_path: str, kind: str = "", month: str = "",
              output_templates_dir: str = "") -> list[str]:
    """Every folder to browse for `kind`, most-specific first.

    kind "order"/"reference" narrows to that kind's folders (project first, then
    the output/templates fallback). Anything else ("", "all") returns all of
    them — every month's order pool, not only the asked-for one — PLUS the
    legacy flat pools, so a template saved before the split is still visible
    under All, which is where it belongs now.
    """
    kind = (kind or "").strip().lower()
    out = (output_templates_dir or "").strip()
    month = order_month_key(project_path, month)
    if kind == KIND_REFERENCE:
        dirs = [reference_templates_dir(project_path),
                output_kind_dir(out, KIND_REFERENCE)]
    elif kind == KIND_ORDER:
        dirs = [order_templates_dir(project_path, month),
                output_kind_dir(out, KIND_ORDER, month)]
    else:
        dirs = [order_templates_dir(project_path, month),
                *_every_order_dir(project_path, out),
                reference_templates_dir(project_path),
                templates_dir(project_path),
                output_kind_dir(out, KIND_ORDER, month),
                output_kind_dir(out, KIND_REFERENCE),
                out]
    # De-dupe while keeping order: with no project the kind dirs collapse to "".
    seen, kept = set(), []
    for d in dirs:
        if d and d not in seen:
            seen.add(d)
            kept.append(d)
    return kept


def save_dirs(project_path: str, kind: str, month: str = "",
              output_templates_dir: str = "") -> list[str]:
    """Where a save of this kind should go, best first: the project folder, then
    the output/templates fallback for that kind. The caller writes to the first
    that accepts it."""
    out = (output_templates_dir or "").strip()
    month = order_month_key(project_path, month)
    if kind == KIND_REFERENCE:
        primary = reference_templates_dir(project_path)
    else:
        primary = order_templates_dir(project_path, month)
    fallback = output_kind_dir(out, kind, month)
    return [d for d in (primary, fallback) if d]


def collect_checked(dirs, names):
    """(abs sheet path, prompt) pairs for every sheet of each checked template,
    in template-then-sheet order — so the Template Library can output saved
    sheets + prompts directly, no re-render. Prompts come from the saved
    sheetPrompts (empty string when a template predates prompt-saving). Unknown
    names are skipped."""
    out = []
    for nm in names or []:
        tpl = load_pack_template_dirs(dirs, nm)
        if not tpl:
            continue
        prompts = tpl.get("sheetPrompts") or []
        for i, path in enumerate(tpl.get("sheetPaths") or []):
            out.append((path, prompts[i] if i < len(prompts) else ""))
    return out


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
