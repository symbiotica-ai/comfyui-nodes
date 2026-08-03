# ABOUTME: The client's own reference images for ONE asset of an order — the
# ABOUTME: art they sent for this thing, as opposed to the dataset's house style.
import os

# What a reference lands on when it arrives with transparency. Grey because the
# packed sheets use it: a reference shown beside a cut cell should not be the one
# image with a different backdrop.
DEFAULT_BACKGROUND = "#808080"


def parse_hex(value, fallback=(128, 128, 128)):
    """A #rgb or #rrggbb string as an RGB triple, falling back rather than
    raising — a typo in a colour widget must not take a render down."""
    text = str(value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return fallback
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return fallback


def alpha_of(image):
    """The image's alpha as an L-mode image, or None when it has none.

    Separated from the pixels because ComfyUI carries transparency as a MASK on
    its own wire, never as a fourth channel on an IMAGE — so the only way to
    hand transparency downstream is to hand back the alpha as well.
    """
    from PIL import Image
    if image.mode == "P" and "transparency" in image.info:
        image = image.convert("RGBA")
    if image.mode in ("RGBA", "LA", "PA"):
        return image.convert("RGBA").getchannel("A")
    return None


def flatten(image, background=DEFAULT_BACKGROUND):
    """One reference as RGB, composited onto `background` if it has alpha.

    `Image.convert("RGB")` alone DISCARDS alpha rather than applying it, which
    is a silent disaster on this art: these files keep real pixels underneath
    fully transparent areas, so the hidden backdrop reappears, and the
    part-transparent pixels around every edge — which are much brighter than
    the artwork they border — become fully opaque. The result reads as a glow
    around each asset. Compositing is what makes the transparency mean what it
    looks like.
    """
    from PIL import Image
    has_alpha = (image.mode in ("RGBA", "LA", "PA")
                 or (image.mode == "P" and "transparency" in image.info))
    if not has_alpha:
        return image.convert("RGB")
    image = image.convert("RGBA")
    plate = Image.new("RGBA", image.size, parse_hex(background) + (255,))
    return Image.alpha_composite(plate, image).convert("RGB")


def find_asset(order, asset_name):
    """The order's entry for `asset_name`, or None.

    Matched on the name exactly as the order sheet writes it, which is the same
    string every other node in the lane carries, so a name that came out of
    Order Assets always finds its asset here.
    """
    want = str(asset_name or "").strip()
    if not want:
        return None
    for asset in (order or {}).get("assets") or []:
        if str(asset.get("assetName", "") or "").strip() == want:
            return asset
    return None


def asset_names(order):
    """Every named asset in the order, in sheet order — used to say what IS
    available when a lookup misses."""
    return [str(a.get("assetName", "") or "").strip()
            for a in (order or {}).get("assets") or []
            if str(a.get("assetName", "") or "").strip()]


def reference_files(order, asset_name):
    """(paths, names) of the client references for one asset.

    The order already resolved which files belong to this asset — `refFiles`,
    matched by compact name and sorted, so "Spookies.png" comes before
    "Spookies_1.png". That order is meaningful: for a type packed in stages it
    runs prep, ready, serving. Kept exactly as the order gives it rather than
    re-sorted here, so this node and the packer can never disagree about which
    reference is which.

    Raises rather than returning empty, and says which of the three possible
    causes it is: no such asset, no references matched, or the folder is gone.
    """
    asset = find_asset(order, asset_name)
    if asset is None:
        have = ", ".join(asset_names(order)[:12]) or "none"
        raise ValueError(f"no asset called {str(asset_name).strip()!r} in this "
                         f"order — it has: {have}")
    names = [str(n) for n in (asset.get("refFiles") or []) if str(n).strip()]
    if not names:
        raise ValueError(
            f"{asset_name!r} has no reference images in this order — the "
            f"client sent none, or their filenames do not match the asset "
            f"name closely enough for the order to pair them")

    root = str((order or {}).get("refsRoot", "") or "").strip()
    if not root:
        raise ValueError("this order names no references folder — re-run the "
                         "Order Specs node that produced it")
    paths = [os.path.join(root, n) for n in names]
    missing = [n for n, p in zip(names, paths) if not os.path.isfile(p)]
    if missing:
        raise ValueError(f"reference files missing from {root!r}: "
                         f"{', '.join(missing)}")
    return paths, names


def pairing_note(order, asset_name, names, cells):
    """A one-line account of whether these references line up with the sheet's
    cells, for the node to show on the canvas.

    Worth saying out loud because the useful case and the broken one look
    identical downstream: three references against three cells means reference i
    IS role i and one index drives both, while two against three means the pair
    an index makes is arbitrary. Nothing here changes the data — a caller that
    silently paired them would be guessing on the user's behalf.
    """
    asset = find_asset(order, asset_name) or {}
    category = str(asset.get("category", "") or "").strip() or "?"
    roles = [str(c.get("role", "")) for c in (cells or [])]
    if roles and len(roles) == len(names):
        return (f"{asset_name}: {len(names)} references ↔ {len(roles)} cells "
                f"({category}) — reference i is role i: {', '.join(roles)}")
    if not roles:
        return (f"{asset_name}: {len(names)} references ({category}) — no "
                f"packing rule recorded for this type, so the references do "
                f"not map to cells")
    return (f"{asset_name}: {len(names)} references but {len(roles)} cells "
            f"({category}) — they do NOT line up, so an index picks a "
            f"different thing in each: {', '.join(roles)}")
