# ABOUTME: Turns an order into ONE ITEM PER ASSET, grouped by asset type, and
# ABOUTME: draws each type's style reference from <project>/dataset/<Type>/.
import os
import random

from .compose import IMG_EXTS


def assets_by_category(order, category="All"):
    """The order's assets as a flat list, grouped by asset type.

    `category` narrows the run to one type — "All" (or empty) keeps every type.
    Narrowing here rather than downstream is what makes it useful: the type
    lists this returns drive the architect prompt and the dataset draw, so
    picking "Food - 3 stages" leaves a run of three food assets with nothing
    else to configure.

    One entry per ASSET — not per reference image, and not per packed sheet. A
    rotation-2 decoration with three references is still one asset here: the
    render this feeds makes one new asset from one style reference, so splitting
    per reference would run it three times over the same brief.

    Types keep first-appearance order and assets keep their order within a type,
    so the run reads down the order sheet: every decoration, then every food.
    Assets with no name are dropped — they are spreadsheet padding.
    """
    want = (category or "All").strip() or "All"
    groups: dict[str, list[dict]] = {}
    for a in (order or {}).get("assets", []) or []:
        name = str(a.get("assetName", "") or "").strip()
        if not name:
            continue
        cat = str(a.get("category", "") or "").strip()
        if want != "All" and cat != want:
            continue
        groups.setdefault(cat, []).append(a)
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


def event_label(order):
    """"Mini 1 — Ghostly Goodies": the feature with its event name, the same
    label the node's own feature picker shows (web/js eventLabel). A feature
    with no event name is just the feature."""
    feature = str((order or {}).get("feature", "") or "").strip()
    event = str((order or {}).get("eventName", "") or "").strip()
    return f"{feature} — {event}" if feature and event else feature


def _segment(value):
    """One path segment from an order value.

    A separator inside a name would silently deepen the tree — an asset called
    "Sign / Board" must not become a "Sign" folder — so separators collapse to a
    space. Windows-illegal characters go too: these paths are written to a
    shared Drive folder that syncs to other machines.
    """
    out = str(value or "").strip()
    for bad in ("/", "\\", ":", "*", "?", '"', "<", ">", "|", "\n", "\r", "\t"):
        out = out.replace(bad, " ")
    return " ".join(out.split()).strip(". ")


def save_paths(order, items):
    """month/feature/category/asset for each asset, ready for a save node's
    filename prefix.

    Kept as the order sheet writes them — "Food - 3 stages", not a slug —
    because these folders are read by people looking for this month's work, and
    a slug makes the delivered tree harder to scan than the order it came from.
    Empty segments are dropped rather than left as "//", which would put the
    file at the wrong depth.
    """
    month = _segment((order or {}).get("month", ""))
    feature = _segment(event_label(order))
    out = []
    for a in items:
        parts = [p for p in (month, feature, _segment(a.get("category", "")),
                             _segment(a.get("assetName", ""))) if p]
        out.append("/".join(parts))
    return out


def dataset_dir(project_path, folder="dataset"):
    """Where the per-type reference folders live, beside orders and prompts."""
    return os.path.join(project_path, folder)


def _folder_key(name):
    """A type name reduced to what a folder and an order can agree on.

    Case and a trailing plural are the two ways the same type gets written
    twice: the order sheet says "Appliance" and the dataset folder is called
    "Appliances", which failed the whole run for a spelling.
    """
    return " ".join(str(name or "").strip().lower().split()).rstrip("s")


def category_dir(root, category):
    """The dataset folder for one asset type, or "" when none names it.

    Exact first — a folder called exactly what the order says is always the
    answer. Only when nothing matches exactly does it fall back to the loose
    key, and an ambiguous fallback (both "Chair" and "Chairs" on disk) is
    treated as no match: guessing between two real folders would silently
    reference the wrong art, and the caller's error names the path it wanted.
    """
    exact = os.path.join(root, str(category or "").strip())
    if os.path.isdir(exact):
        return exact
    key = _folder_key(category)
    if not key:
        return ""
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return ""
    hits = [n for n in names
            if _folder_key(n) == key and os.path.isdir(os.path.join(root, n))]
    return os.path.join(root, hits[0]) if len(hits) == 1 else ""


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
        d = category_dir(root, cat) or os.path.join(root, cat)
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
