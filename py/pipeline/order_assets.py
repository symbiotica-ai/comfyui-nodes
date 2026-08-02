# ABOUTME: Turns an order into ONE ITEM PER ASSET, grouped by asset type, and
# ABOUTME: draws each type's style reference from <project>/dataset/<Type>/.
import os
import random

from .compose import IMG_EXTS


def assets_by_category(order):
    """The order's assets as a flat list, grouped by asset type.

    One entry per ASSET — not per reference image, and not per packed sheet. A
    rotation-2 decoration with three references is still one asset here: the
    render this feeds makes one new asset from one style reference, so splitting
    per reference would run it three times over the same brief.

    Types keep first-appearance order and assets keep their order within a type,
    so the run reads down the order sheet: every decoration, then every food.
    Assets with no name are dropped — they are spreadsheet padding.
    """
    groups: dict[str, list[dict]] = {}
    for a in (order or {}).get("assets", []) or []:
        name = str(a.get("assetName", "") or "").strip()
        if not name:
            continue
        groups.setdefault(str(a.get("category", "") or "").strip(), []).append(a)
    out = []
    for cat, items in groups.items():
        for a in items:
            out.append({
                "assetName": str(a.get("assetName", "")).strip(),
                "category": cat,
                "prompt": str(a.get("prompt", "") or ""),
                "canvas": str(a.get("canvas", "") or ""),
            })
    return out


def dataset_dir(project_path, folder="dataset"):
    """Where the per-type reference folders live, beside orders and prompts."""
    return os.path.join(project_path, folder)


class MissingDatasetsError(Exception):
    """Asset types with no usable reference folder. `missing` is
    [(category, path)], sorted, so one failure names every offender instead of
    one per re-run."""

    def __init__(self, missing):
        self.missing = missing
        width = max((len(c) for c, _ in missing), default=0)
        lines = "\n".join(f"  {c:<{width}}  ->  {p}" for c, p in missing)
        noun = "type" if len(missing) == 1 else "types"
        super().__init__(f"no reference images for {len(missing)} asset "
                         f"{noun} in this order:\n{lines}")


def list_dataset_images(directory):
    """Image files directly inside `directory`, ordered by lowercased name.

    Sorted rather than left in filesystem order because the pick below indexes
    into this list: an arbitrary enumeration order would make the same seed
    choose different images on different machines.
    """
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    imgs = [n for n in names
            if os.path.splitext(n)[1].lower() in IMG_EXTS
            and os.path.isfile(os.path.join(directory, n))]
    return sorted(imgs, key=lambda n: (n.lower(), n))


def pick_reference_per_category(project_path, categories, seed,
                                folder="dataset"):
    """One reference image path per ASSET, drawn per TYPE.

    Every asset of a type shares that type's draw: three food items render
    against one food reference, so the batch is stylistically consistent. The
    draw is seeded and derived from `(seed, category)`, so it is reproducible —
    the same seed picks the same references, and a type keeps its own pick when
    a different type is added to the order.

    Returns (paths, names), both index-aligned with `categories`.
    """
    root = dataset_dir(project_path, folder)
    chosen, missing = {}, []
    for cat in dict.fromkeys(c.strip() for c in categories):
        d = os.path.join(root, cat)
        imgs = list_dataset_images(d)
        if not imgs:
            missing.append((cat, d))
            continue
        # Seed per (seed, category): adding a type must not reshuffle the rest.
        rng = random.Random(f"{seed}:{cat}")
        chosen[cat] = os.path.join(d, rng.choice(imgs))
    if missing:
        raise MissingDatasetsError(sorted(missing))
    paths = [chosen[c.strip()] for c in categories]
    return paths, [os.path.basename(p) for p in paths]
