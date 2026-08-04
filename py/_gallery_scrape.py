# ABOUTME: E-commerce gallery scraper — product metadata + ordered gallery image URLs
# ABOUTME: from JSON-LD Product markup, with og:image/DOM srcset fallback.
import html as html_mod
import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlparse

# Filenames that are site chrome (badges, payment logos, banners), never gallery shots.
NOISE = re.compile(
    r"badge|icon|award|favicon|sprite|pixel|banner|payment|visa|mastercard|"
    r"anpc|placeholder|loading|blank|trans\b",
    re.IGNORECASE,
)

# "logo" as a word (logo, site-logo, logotype, logo_dark) — never a substring of
# an unrelated word: a jewelry site's "inel-de-logodna" (engagement ring) is a
# product shot, not brand chrome.
LOGO_WORD = re.compile(r"(?<![a-z0-9])logo(?:type|mark)?(?![a-z])", re.IGNORECASE)

MAX_IMAGES = 32


def _literal_ip(host):
    """The IP a host string denotes, covering the non-dotted-quad spellings
    urlparse leaves as opaque hostnames: decimal (2130706433), hex (0x7f000001)
    and octal (0177.0.0.1) all resolve to 127.0.0.1 in libc/curl."""
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        pass
    try:
        packed = socket.inet_aton(host)
    except OSError:
        return None
    return ipaddress.ip_address(packed)


def is_public_http_target(raw):
    """No SSRF into loopback / private-range / link-local / metadata endpoints
    or .internal/.local/localhost hosts.

    A pre-flight text check only: it cannot see where a DNS name resolves, so
    callers must re-check the landed URL after redirects (the nodes do)."""
    try:
        u = urlparse(raw)
    except ValueError:
        return False
    if u.scheme not in ("http", "https"):
        return False
    host = (u.hostname or "").lower()
    if not host:
        return False
    if host == "localhost" or host.endswith((".localhost", ".internal", ".local")):
        return False
    ip = _literal_ip(host)
    if ip is not None and (ip.is_private or ip.is_loopback or ip.is_link_local
                           or ip.is_reserved or ip.is_unspecified or ip.is_multicast):
        return False
    return True


def _absolutize(src, base):
    # An empty src must yield None, or a missing og:image leaks the page URL.
    if not src or not src.strip():
        return None
    try:
        return urljoin(base, src.strip())
    except ValueError:
        return None


def _meta(html, name):
    # Quotes matched pairwise ((?P=q)) — a mixed [\"'] class truncates values
    # containing the other quote ("L'amour" dies at the apostrophe).
    for pat in (
        rf"<meta[^>]+(?:property|name)=(?P<q>[\"']){name}(?P=q)[^>]+content=(?P<qc>[\"'])(?P<c>.*?)(?P=qc)",
        rf"<meta[^>]+content=(?P<qc>[\"'])(?P<c>.*?)(?P=qc)[^>]+(?:property|name)=(?P<q>[\"']){name}(?P=q)",
    ):
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return html_mod.unescape(m.group("c").strip())
    return ""


def _iter_jsonld(html):
    """Every JSON-LD object on the page, flattening lists and @graph wrappers."""
    for m in re.finditer(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>([\s\S]*?)</script>",
        html,
        re.IGNORECASE,
    ):
        try:
            data = json.loads(m.group(1).strip())
        except ValueError:
            continue
        stack = [data]
        while stack:
            node = stack.pop(0)
            if isinstance(node, list):
                stack = node + stack
            elif isinstance(node, dict):
                yield node
                graph = node.get("@graph")
                if isinstance(graph, list):
                    stack = graph + stack


def _is_product(node):
    t = node.get("@type")
    types = t if isinstance(t, list) else [t]
    return "Product" in types


def _image_urls_of(value):
    """Flatten a schema.org image value: str | ImageObject | list of either."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        u = value.get("url") or value.get("contentUrl")
        return [u] if isinstance(u, str) else []
    if isinstance(value, list):
        out = []
        for v in value:
            out.extend(_image_urls_of(v))
        return out
    return []


def _price_of(offers):
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if not isinstance(offers, dict):
        return ""
    price = offers.get("price") or offers.get("lowPrice") or ""
    currency = offers.get("priceCurrency") or ""
    return f"{price} {currency}".strip() if price else ""


def _brand_of(brand):
    if isinstance(brand, dict):
        return brand.get("name") or ""
    return brand if isinstance(brand, str) else ""


def extract_product_jsonld(html, page_url):
    """Metadata + ordered gallery URLs from the page's JSON-LD Product, or None.

    Gallery order: the `image` field leads (the merchant's hero shot), then
    additionalProperty product_image entries, then variant_image entries —
    deduplicated so variant repeats of the hero collapse away.

    Pages can carry several Product nodes (related-items widgets); the first
    one WITH images wins, an imageless first-comer only as a last resort."""
    fallback = None
    for node in _iter_jsonld(html):
        if not _is_product(node):
            continue
        urls = list(_image_urls_of(node.get("image")))
        variants = []
        for prop in node.get("additionalProperty") or []:
            if not isinstance(prop, dict):
                continue
            name = prop.get("name")
            value = prop.get("value")
            if not isinstance(value, str):
                continue
            if name == "product_image":
                urls.append(value)
            elif name == "variant_image":
                variants.append(value)
        urls = [u for u in (_absolutize(u, page_url) for u in urls + variants) if u]
        meta = {
            "name": node.get("name") or "",
            "description": node.get("description") or "",
            "brand": _brand_of(node.get("brand")),
            "sku": str(node.get("sku") or ""),
            "material": node.get("material") or "",
            "color": node.get("color") or "",
            "price": _price_of(node.get("offers")),
            "images": list(dict.fromkeys(urls))[:MAX_IMAGES],
            "source": "jsonld",
        }
        if meta["images"]:
            return meta
        if fallback is None:
            fallback = meta
    return fallback


def _srcset_best(srcset):
    """The largest-width candidate of a srcset attribute value.

    Tokenized on whitespace, not split on ',' — CDN URLs legally contain commas
    (Cloudinary's f_auto,q_80 transforms). A trailing comma ends a candidate;
    otherwise the next token is that URL's descriptor."""
    candidates = []
    url = None
    for tok in srcset.split():
        if url is None:
            stripped = tok.rstrip(",")
            if not stripped:
                continue
            if tok.endswith(","):
                candidates.append((stripped, 0))
            else:
                url = stripped
        else:
            m = re.match(r"(\d+)w,?$", tok)
            candidates.append((url, int(m.group(1)) if m else 0))
            url = None
    if url:
        candidates.append((url, 0))
    best, best_w = None, -1
    for u, w in candidates:
        if w > best_w:
            best, best_w = u, w
    return best


def extract_gallery_dom(html, page_url):
    """og:image first, then <img> tags walked from the END of the document
    (galleries typically sit in the main content after nav/header chrome),
    biggest srcset variant per tag, chrome filenames filtered out. The fallback
    when a page carries no JSON-LD Product."""
    urls = []
    og = _absolutize(_meta(html, "og:image"), page_url)
    if og:
        urls.append(og)
    for tag in reversed(list(re.finditer(r"<img\b[^>]*>", html, re.IGNORECASE))):
        t = tag.group(0)
        m = re.search(r"srcset=[\"']([^\"']+)[\"']", t, re.IGNORECASE)
        src = _srcset_best(m.group(1)) if m else None
        if not src:
            m = re.search(r"src=[\"']([^\"']+)[\"']", t, re.IGNORECASE)
            src = m.group(1) if m else None
        if not src or src.startswith("data:"):
            continue
        u = _absolutize(src, page_url)
        if not u or not re.search(r"\.(?:png|jpe?g|webp|avif)(?:\?|$)", u, re.IGNORECASE):
            continue
        fname = u.rsplit("/", 1)[-1]
        if NOISE.search(fname) or LOGO_WORD.search(fname):
            continue
        urls.append(u)
    name = _meta(html, "og:title")
    if not name:
        m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        name = html_mod.unescape((m.group(1) if m else "").strip())
    return {
        "name": name,
        "description": _meta(html, "og:description") or _meta(html, "description"),
        "brand": "",
        "sku": "",
        "material": "",
        "color": "",
        "price": "",
        "images": list(dict.fromkeys(urls))[:MAX_IMAGES],
        "source": "dom",
    }


MAX_DESCRIPTION_CHARS = 1500


def build_product_summary(meta):
    """The product line a script LLM reads: name — description, then the spec
    fields worth citing in an ad (brand, material, color, price, SKU). The
    description is soft-capped: it is scraped remote text headed for a prompt,
    and a pathological page must not balloon the graph's STRING wires."""
    summary = f"Product: {meta['name']}"
    if meta.get("description"):
        desc = meta["description"]
        if len(desc) > MAX_DESCRIPTION_CHARS:
            desc = desc[:MAX_DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"
        summary += f" — {desc}"
    specs = [
        f"{label}: {meta[key]}"
        for label, key in (
            ("Brand", "brand"),
            ("Material", "material"),
            ("Color", "color"),
            ("Price", "price"),
            ("SKU", "sku"),
        )
        if meta.get(key)
    ]
    if specs:
        summary += "\n" + " | ".join(specs)
    return summary


def scrape_gallery(url, fetch):
    """Full scrape: JSON-LD Product first, DOM fallback. `fetch(url) -> html | None`
    is injected. Raises ValueError for a non-public entry URL, RuntimeError when
    the page yields no usable gallery."""
    if not is_public_http_target(url):
        raise ValueError("only public http(s) URLs can be scraped")
    try:
        html = fetch(url)
    except Exception:
        html = None
    if html is None:
        raise RuntimeError("page fetch failed")
    # Regex passes over the page are near-linear on well-formed HTML but can go
    # quadratic on pathological input (unclosed ld+json scripts); a hard size
    # cap bounds that, and no product page carries its gallery past 2 MB.
    html = html[:2_000_000]
    meta = extract_product_jsonld(html, url)
    if meta is None or not meta["images"]:
        meta = extract_gallery_dom(html, url)
    if not meta["images"]:
        raise RuntimeError("no gallery images found on the page")
    return meta
