# ABOUTME: Product gallery scrape node — fetches an e-commerce product page and returns
# ABOUTME: its gallery split into product-only / on-model / other IMAGE batches.
import io

import requests
from PIL import Image

from ._gallery_classify import DEFAULT_MODEL, classify_images, get_backend
from ._gallery_images import group_by_category, to_batch
from ._gallery_scrape import build_product_summary, is_public_http_target, scrape_gallery

_UA = {"user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}

_MAX_IMAGE_BYTES = 25 * 1024 * 1024
_MAX_IMAGE_PIXELS = 40_000_000


def _fetch_html(url):
    res = requests.get(url, headers=_UA, timeout=10)
    if not res.ok or not is_public_http_target(res.url):
        return None  # the redirect chain must land public too
    # Pages that declare charset only in <meta> arrive as ISO-8859-1 by the
    # requests default and mangle diacritics (Romanian copy) — sniff instead.
    if "charset" not in res.headers.get("content-type", "").lower():
        res.encoding = res.apparent_encoding
    return res.text


def _fetch_pil(url):
    """URL -> RGB PIL image, or None when the download/decode fails. Oversized
    payloads and decompression-bomb dimensions are dropped, not decoded."""
    if not is_public_http_target(url):
        return None
    try:
        res = requests.get(url, headers=_UA, timeout=10)
        if not res.ok or not is_public_http_target(res.url):
            return None
        if len(res.content) > _MAX_IMAGE_BYTES:
            return None
        img = Image.open(io.BytesIO(res.content))
        if img.size[0] * img.size[1] > _MAX_IMAGE_PIXELS:
            return None
        return img.convert("RGB")
    except Exception:
        return None


class ProductGalleryScrape:
    """Scrapes a product page (JSON-LD Product first, DOM fallback), downloads the
    gallery, and splits it by content — packshots of the product alone, shots of a
    person wearing/using it, and everything else (packaging, banners) — using local
    zero-shot CLIP, since e-commerce markup carries no reliable person/product
    signal (empty alts, arbitrary numbering). Empty categories emit a white
    placeholder frame; gate on the count outputs. The summary feeds a script LLM;
    the report logs every image's verdict for debugging."""

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "url": ("STRING", {"default": "", "tooltip": "Product page URL (public http/https)."}),
                "classifier": (["clip", "off"], {
                    "default": "clip",
                    "tooltip": "clip: split by content with zero-shot CLIP (downloads the model "
                               "on first run). off: everything lands in product_images.",
                }),
            },
            "optional": {
                "clip_model": ("STRING", {
                    "default": DEFAULT_MODEL,
                    "tooltip": "Hugging Face CLIP checkpoint for the classifier.",
                }),
                "max_images": ("INT", {"default": 12, "min": 1, "max": 32,
                                       "tooltip": "Cap on downloaded gallery images."}),
                "image_size": ("INT", {"default": 1024, "min": 256, "max": 4096, "step": 64,
                                       "tooltip": "Longest side per image (downscale only)."}),
            },
        }

    RETURN_TYPES = ("IMAGE", "IMAGE", "IMAGE", "STRING", "STRING", "INT", "INT", "INT")
    RETURN_NAMES = ("product_images", "on_model_images", "other_images",
                    "summary", "report", "product_count", "on_model_count", "other_count")
    FUNCTION = "scrape"
    CATEGORY = "Symbiotica/Commerce"

    def scrape(self, url, classifier, clip_model=DEFAULT_MODEL,
               max_images=12, image_size=1024):
        meta = scrape_gallery(url.strip(), fetch=_fetch_html)

        items = []
        for u in meta["images"]:
            im = _fetch_pil(u)
            if im is not None:
                items.append((im, u.rsplit("/", 1)[-1]))
            if len(items) >= max_images:
                break
        if not items:
            raise RuntimeError("gallery URLs found but no image could be downloaded")

        pils = [im for im, _ in items]
        if classifier == "clip":
            verdicts = classify_images(pils, get_backend(clip_model))
        else:
            verdicts = [{"category": "product", "confidence": 1.0, "margin": 1.0}] * len(pils)

        groups, lines = group_by_category(items, verdicts)
        header = f"source: {meta['source']}, {len(pils)} image(s), classifier: {classifier}"

        return (
            to_batch(groups["product"], image_size),
            to_batch(groups["on_model"], image_size),
            to_batch(groups["other"], image_size),
            build_product_summary(meta),
            "\n".join([header] + lines),
            len(groups["product"]),
            len(groups["on_model"]),
            len(groups["other"]),
        )


NODE_CLASS_MAPPINGS = {
    "NSProductGalleryScrape": ProductGalleryScrape,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "NSProductGalleryScrape": "Product Gallery Scrape",
}
