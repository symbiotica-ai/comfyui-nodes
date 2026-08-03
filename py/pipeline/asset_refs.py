# ABOUTME: The client's own reference images for ONE asset of an order — the
# ABOUTME: art they sent for this thing, as opposed to the dataset's house style.
import os


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
