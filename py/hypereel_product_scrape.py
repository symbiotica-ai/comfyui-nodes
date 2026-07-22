# ABOUTME: Hypereel product scrape node — fetches a product/app/store page and returns
# ABOUTME: logo + screenshots as IMAGE outputs plus the product summary for the script LLM.
import io

import numpy as np
import requests
import torch
from PIL import Image

from ._hypereel_scrape import build_summary, is_public_http_target, scrape_product

_UA = {"user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

_PLATFORMS = ["mobile app", "desktop app", "physical product"]


def _fetch_html(url):
    res = requests.get(url, headers=_UA, timeout=8)
    return res.text if res.ok else None


def _fetch_image(url):
    """URL -> (1,H,W,3) float tensor, or None when the download/decode fails."""
    if not is_public_http_target(url):
        return None
    try:
        res = requests.get(url, headers=_UA, timeout=10)
        if not res.ok:
            return None
        img = Image.open(io.BytesIO(res.content)).convert("RGB")
        arr = np.asarray(img, dtype=np.float32) / 255.0
        return torch.from_numpy(arr).unsqueeze(0)
    except Exception:
        return None


class HypereelProductScrape:
    """Scrapes a product page, app page, or app-store listing: follows the first
    app-store link for the curated promo screens, promotes the AppIcon to logo,
    prefers the biggest image variants, drops badges and template URLs, and
    refuses non-public targets. Outputs wire straight into the video node's
    reference slots (avatar stays image_1; logo -> image_2, screenshots -> 3+)
    and the summary feeds the script LLM's PRODUCT block."""

    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "url": ("STRING", {"default": "", "tooltip": "Product page, app page, or app-store listing."}),
                "platform": (_PLATFORMS, {"default": "mobile app",
                                          "tooltip": "Drives the CTA rule in the summary."}),
            },
            "optional": {
                "include_details": ("BOOLEAN", {"default": False,
                                                "tooltip": "Append a page-text DETAILS digest to the summary. "
                                                           "Off matches the platform engine exactly."}),
            },
        }

    RETURN_TYPES = ("STRING", "IMAGE", "IMAGE", "IMAGE", "IMAGE", "INT")
    RETURN_NAMES = ("summary", "logo", "screenshot_1", "screenshot_2", "screenshot_3", "found")
    FUNCTION = "scrape"
    CATEGORY = "Symbiotica/Hypereel"

    def scrape(self, url, platform, include_details=False):
        assets = scrape_product(url.strip(), fetch=_fetch_html)

        logo = _fetch_image(assets["logo"]) if assets["logo"] else None
        shots = []
        for u in assets["screenshots"]:
            t = _fetch_image(u)
            if t is not None:
                shots.append(t)
            if len(shots) == 3:
                break
        if logo is None and not shots:
            raise RuntimeError("scrape found image URLs but none could be downloaded")
        # Missing slots repeat the last available image (a duplicate reference is
        # harmless; an absent wire would break the graph). Logo falls back to the
        # first screenshot when the page truly has none.
        if logo is None:
            logo = shots[0]
        while len(shots) < 3:
            shots.append(shots[-1] if shots else logo)

        summary = build_summary(
            assets["name"], assets["description"], platform,
            details=assets.get("details", ""), include_details=include_details,
        )
        return (summary, logo, shots[0], shots[1], shots[2], len(assets["screenshots"]))


NODE_CLASS_MAPPINGS = {
    "HypereelProductScrape": HypereelProductScrape,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "HypereelProductScrape": "Hypereel Product Scrape (URL to references)",
}
