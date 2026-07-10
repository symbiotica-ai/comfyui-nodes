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


def _parse_color(color_str: str) -> tuple:
    """Parse hex color string to RGB tuple. Returns (0, 0, 0) for empty or invalid."""
    if not color_str:
        return (0, 0, 0)
    color_str = color_str.strip()
    if color_str.startswith("#"):
        color_str = color_str[1:]
    if len(color_str) == 6:
        try:
            r = int(color_str[0:2], 16)
            g = int(color_str[2:4], 16)
            b = int(color_str[4:6], 16)
            return (r, g, b)
        except ValueError:
            pass
    return (0, 0, 0)


def _paint_background(sheet_w: int, sheet_h: int, background: str) -> Image.Image:
    color = _parse_color(background) if background else (0, 0, 0)
    # Create as RGBA for compositing, will convert to RGB at the end
    rgba_color = color + (255,) if len(color) == 3 else color
    return Image.new("RGBA", (sheet_w, sheet_h), rgba_color)


def _contain_fit(img: Image.Image, w: int, h: int) -> tuple[Image.Image, int, int]:
    """Contain-fit: scale image to fit in cell without exceeding it, don't scale up."""
    scale = min(1.0, w / img.width, h / img.height)
    fw, fh = max(1, round(img.width * scale)), max(1, round(img.height * scale))
    return img.resize((fw, fh), Image.LANCZOS), (w - fw) // 2, (h - fh) // 2


def build_prefill_sheet(assets: list[dict], refs_root: str, sheet_w: int,
                        sheet_h: int, settings: PackSettings, chosen=None):
    """Prefill-from-specs sheet: regions via prefill_regions, each member cell
    drawing its reference image contain-fit (flipX mirrors the single-ref pair).
    Returns (PIL.Image, regions, overflow_names)."""
    result = prefill_regions(assets, sheet_w, sheet_h, chosen=chosen,
                             settings=settings)
    sheet = _paint_background(sheet_w, sheet_h, settings.background)
    for region in result["regions"]:
        for member in region.get("members", []):
            # spriteId is "Category/AssetName/file.png"; the actual ref file
            # lives flat in refs_root under its basename.
            filename = member["spriteId"].split("/")[-1]
            path = os.path.join(refs_root, filename)
            try:
                img = Image.open(path)
                img.load()
                img = img.convert("RGBA")
            except OSError:
                continue  # missing ref: cell stays background for the img2img pass
            if member.get("flipX"):
                img = img.transpose(Image.FLIP_LEFT_RIGHT)
            cw = max(1, round(member["w"] * sheet_w))
            ch = max(1, round(member["h"] * sheet_h))
            fitted, ox, oy = _contain_fit(img, cw, ch)
            paste_x = round(member["x"] * sheet_w) + ox
            paste_y = round(member["y"] * sheet_h) + oy

            # Guard against oversized overflow strips: clip fitted image to the
            # intersection with sheet bounds before compositing. The destination
            # box for alpha_composite must be within bounds.
            if paste_x + fitted.width > sheet_w or paste_y + fitted.height > sheet_h:
                # Compute intersection region
                crop_left = max(0, -paste_x)
                crop_top = max(0, -paste_y)
                crop_right = min(fitted.width, sheet_w - paste_x)
                crop_bottom = min(fitted.height, sheet_h - paste_y)

                if crop_right > crop_left and crop_bottom > crop_top:
                    fitted = fitted.crop((crop_left, crop_top, crop_right, crop_bottom))
                    paste_x = max(0, paste_x)
                    paste_y = max(0, paste_y)
                else:
                    continue  # Completely out of bounds

            sheet.alpha_composite(fitted, (paste_x, paste_y))
    # Convert to RGB for the final result (alpha handling done during compositing)
    return sheet.convert("RGB"), result["regions"], result["overflow"]


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
