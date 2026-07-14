# ABOUTME: Sheet compositing — catalog-grid template build (port of hub
# ABOUTME: template-node buildTemplate) and prefill-ref drawing, plus PNG+sidecar save.
from __future__ import annotations

import json
import os
import re

from PIL import Image

from .order_sheet import slugify
from .prefill import prefill_regions
from .texture_pack import PackSettings

IMG_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


def scan_images(root: str) -> list[str]:
    """Sorted /-separated rel paths of all images under root; dot-dirs skipped."""
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for f in filenames:
            if os.path.splitext(f)[1].lower() in IMG_EXTS and not f.startswith("."):
                rel = os.path.relpath(os.path.join(dirpath, f), root)
                out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def category_candidates(rel_paths: list[str], category: str) -> list[str]:
    """Hub's match: any path segment prefix-matches the category (either way),
    case-insensitive."""
    cat = category.strip().lower()
    if not cat:
        return []
    def matches(rel: str) -> bool:
        for seg in rel.split("/"):
            s = seg.strip().lower()
            if s and (s.startswith(cat) or cat.startswith(s)):
                return True
        return False
    return [r for r in rel_paths if matches(r)]


class _RoundRobinPicker:
    """Round-robin through candidate images preferring exact cell-size art;
    wraps around when every candidate is consumed (more assets than art)."""

    def __init__(self, root: str, candidates: list[str], cell_w: int, cell_h: int):
        self.root = root
        self.candidates = candidates
        self.cell_w = cell_w
        self.cell_h = cell_h
        self.images: list[Image.Image | None | bool] = [False] * len(candidates)
        self.used = [False] * len(candidates)
        self.used_count = 0

    def _image_at(self, idx: int) -> Image.Image | None:
        if self.images[idx] is False:
            try:
                img = Image.open(os.path.join(self.root, self.candidates[idx]))
                img.load()
                self.images[idx] = img.convert("RGBA")
            except OSError:
                self.images[idx] = None
        return self.images[idx] or None

    def _mark(self, idx: int) -> None:
        self.used[idx] = True
        self.used_count += 1

    def pick(self) -> Image.Image | None:
        for _pass in range(2):
            fallback = -1
            for idx in range(len(self.candidates)):
                if self.used[idx]:
                    continue
                img = self._image_at(idx)
                if img is None:
                    self._mark(idx)
                    continue
                if fallback < 0:
                    fallback = idx
                if img.size == (self.cell_w, self.cell_h):
                    self._mark(idx)
                    return img
            if fallback >= 0:
                self._mark(fallback)
                return self._image_at(fallback)
            if self.used_count == 0:
                return None
            self.used = [False] * len(self.candidates)
            self.used_count = 0
        return None


def build_catalog_sheet(group: dict, assets_root: str):
    """Grid sheet from existing catalog art matched to the group's category.
    Returns (PIL.Image RGBA, regions, sheet_w, sheet_h)."""
    m = re.match(r"^(\d+)\s*[xX]\s*(\d+)$", group["canvas"].strip())
    if not m:
        raise ValueError(f"Can't parse canvas size \"{group['canvas']}\" (expected WxH).")
    cell_w, cell_h = int(m.group(1)), int(m.group(2))
    n = len(group["assets"])
    if n == 0:
        raise ValueError("The picked group has no named assets.")

    candidates = category_candidates(scan_images(assets_root), group["category"])
    picker = _RoundRobinPicker(assets_root, candidates, cell_w, cell_h)

    cols = min(max(1, 1024 // cell_w), n)
    sheet_w = cols * cell_w
    rows = -(-n // cols)  # ceil
    sheet_h = rows * cell_h
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))

    regions = []
    for i, asset in enumerate(group["assets"]):
        cx = (i % cols) * cell_w
        cy = (i // cols) * cell_h
        img = picker.pick()
        if img is not None:
            sheet.alpha_composite(img.resize((cell_w, cell_h), Image.LANCZOS), (cx, cy))
        regions.append({
            "id": f"region:{asset['assetName']}",
            "spriteId": slugify(asset["assetName"]),
            "name": asset["assetName"],
            "x": cx / sheet_w,
            "y": cy / sheet_h,
            "w": cell_w / sheet_w,
            "h": cell_h / sheet_h,
            "kind": "object",
            "desc": asset.get("prompt") or "",
            "text": "",
            "zIndex": i,
            "assetType": group["category"],
        })
    return sheet, regions, sheet_w, sheet_h


def _paint_background(sheet_w: int, sheet_h: int, background: str) -> Image.Image:
    # Pillow parses "#RRGGBB" natively; "" means transparent.
    if background:
        return Image.new("RGBA", (sheet_w, sheet_h), background)
    return Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))


def _contain_fit(img: Image.Image, w: int, h: int) -> tuple[Image.Image, int, int]:
    """Contain-fit: scale (up or down) to fill the cell while preserving aspect,
    matching the hub's drawImage-at-cell-size behavior."""
    scale = min(w / img.width, h / img.height)
    fw, fh = max(1, round(img.width * scale)), max(1, round(img.height * scale))
    return img.resize((fw, fh), Image.LANCZOS), (w - fw) // 2, (h - fh) // 2


def _load_rgba(path: str) -> Image.Image | None:
    try:
        img = Image.open(path)
        img.load()
        return img.convert("RGBA")
    except OSError:
        return None


def _composite_member(sheet: Image.Image, img: Image.Image, member: dict,
                      sheet_w: int, sheet_h: int, flip: bool | None = None) -> None:
    """Draw one image into a member cell: flipX mirror, contain-fit, and clip
    to sheet bounds (oversized overflow strips can extend past the sheet).
    `flip` overrides the member's own flipX when given (dynamic pair rule)."""
    if member.get("flipX") if flip is None else flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    cw = max(1, round(member["w"] * sheet_w))
    ch = max(1, round(member["h"] * sheet_h))
    fitted, ox, oy = _contain_fit(img, cw, ch)
    paste_x = round(member["x"] * sheet_w) + ox
    paste_y = round(member["y"] * sheet_h) + oy

    if paste_x + fitted.width > sheet_w or paste_y + fitted.height > sheet_h:
        crop_left = max(0, -paste_x)
        crop_top = max(0, -paste_y)
        crop_right = min(fitted.width, sheet_w - paste_x)
        crop_bottom = min(fitted.height, sheet_h - paste_y)
        if crop_right <= crop_left or crop_bottom <= crop_top:
            return  # completely out of bounds
        fitted = fitted.crop((crop_left, crop_top, crop_right, crop_bottom))
        paste_x = max(0, paste_x)
        paste_y = max(0, paste_y)

    sheet.alpha_composite(fitted, (paste_x, paste_y))


def _draw_task_refs(sheet: Image.Image, regions: list[dict], refs_root: str,
                    sheet_w: int, sheet_h: int) -> None:
    """Draw each region's task references, honoring the editor's selection:
    checked taskRefs paths override the prefill spriteIds, and one effective
    image in a two-cell region mirrors the second cell (the pair convention —
    same rules as the editor canvas, so the queued sheet matches the edit)."""
    for region in regions:
        members = region.get("members", [])
        paths = (region.get("taskRefs") or {}).get("paths") or []
        for i, member in enumerate(members):
            flip = None  # member's own flipX
            if paths:
                if len(paths) == 1:
                    filename = paths[0].split("/")[-1]
                    flip = len(members) == 2 and i == 1
                else:
                    # Multiple checked refs are explicit per-cell art (often a
                    # pre-mirrored pair) — never apply the baked pair flip.
                    filename = paths[min(i, len(paths) - 1)].split("/")[-1]
                    flip = False
            else:
                sprite = member.get("spriteId")
                if not sprite:
                    continue
                # spriteId is "Category/AssetName/file.png"; the ref file lives
                # flat in refs_root under its basename.
                filename = sprite.split("/")[-1]
            img = _load_rgba(os.path.join(refs_root, filename))
            if img is None:
                continue  # missing ref: cell stays background for the img2img pass
            _composite_member(sheet, img, member, sheet_w, sheet_h, flip)


def build_prefill_sheet(assets: list[dict], refs_root: str, sheet_w: int,
                        sheet_h: int, settings: PackSettings, chosen=None):
    """Prefill-from-specs sheet: regions via prefill_regions, each member cell
    drawing its reference image contain-fit (flipX mirrors the single-ref pair).
    Returns (PIL.Image, regions, overflow_names)."""
    result = prefill_regions(assets, sheet_w, sheet_h, chosen=chosen,
                             settings=settings)
    sheet = _paint_background(sheet_w, sheet_h, settings.background)
    _draw_task_refs(sheet, result["regions"], refs_root, sheet_w, sheet_h)
    return sheet, result["regions"], result["overflow"]


def build_paired_sheets(assets: list[dict], refs_root: str, assets_root: str,
                        assignments: dict[str, str], sheet_w: int, sheet_h: int,
                        settings: PackSettings, chosen=None):
    """Base + task sheets sharing ONE region layout (computed once), so region i
    on the base sheet is region i on the task-reference sheet.

    The task sheet draws the client's reference images (like build_prefill_sheet).
    The base sheet draws the ASSIGNED existing-game asset for each region —
    `assignments` maps asset name -> catalog rel path under assets_root — into
    every member cell (the flip pair mirrors it). Unassigned regions stay
    background so the img2img pass invents them.

    Returns (base_sheet, task_sheet, regions, overflow_names).
    """
    result = prefill_regions(assets, sheet_w, sheet_h, chosen=chosen,
                             settings=settings)
    regions = result["regions"]

    task_sheet = _paint_background(sheet_w, sheet_h, settings.background)
    _draw_task_refs(task_sheet, regions, refs_root, sheet_w, sheet_h)

    base_sheet = _paint_background(sheet_w, sheet_h, settings.background)
    for region in regions:
        rel = (assignments or {}).get(region.get("name") or "")
        if not rel:
            continue
        img = _load_rgba(os.path.join(assets_root, rel.replace("/", os.sep)))
        if img is None:
            continue  # missing/unreadable assignment: cell stays background
        for member in region.get("members", []):
            _composite_member(base_sheet, img, member, sheet_w, sheet_h)

    return base_sheet, task_sheet, regions, result["overflow"]


def save_sheet(img: Image.Image, regions: list[dict], name: str, out_root: str,
               subdir: str = "templates", meta: dict | None = None) -> str:
    """Write the sheet PNG + JSON sidecar (regions live in the sidecar, not the
    PNG). Returns the rel key "<subdir>/<slug>.png". Re-saves overwrite."""
    stem = slugify(name) or "template"
    out_dir = os.path.join(out_root, subdir)
    os.makedirs(out_dir, exist_ok=True)
    img.save(os.path.join(out_dir, f"{stem}.png"))
    sidecar = {
        "name": stem,
        "size": {"w": img.width, "h": img.height},
        "spriteCount": len(regions),
        "regions": regions,
        **(meta or {}),
    }
    with open(os.path.join(out_dir, f"{stem}.json"), "w") as f:
        json.dump(sidecar, f, indent=1)
    return f"{subdir}/{stem}.png"
