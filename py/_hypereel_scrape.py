# ABOUTME: Product-page scraper — extracts name, description, logo and screenshots
# ABOUTME: from a product/app page. Port of the platform's field-hardened scrape-product.
import html as html_mod
import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlparse

# Patterns that mark an image as chrome (badges/icons), not a product asset.
NOISE = re.compile(
    r"badge|store|icon|award|apple|google|amazon|huawei|galaxy|favicon|sprite|pixel|trans\b",
    re.IGNORECASE,
)

MAX_SCREENSHOTS = 6

# "logo" as a word (logo, site-logo, logotype, logo_dark) — never a substring of
# an unrelated word: teilor.ro's "Inele_de_logodna" (engagement rings) must not
# be promoted to logo, nor "catalogo".
LOGO_WORD = re.compile(r"(?<![a-z0-9])logo(?:type|mark)?(?![a-z])", re.IGNORECASE)


def is_store_host(url):
    """Exact hostname match — a substring test is bypassable
    (apps.apple.com.evil.com) and turns the follow-up fetch into SSRF."""
    try:
        h = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return h in ("apps.apple.com", "play.google.com")


def _host_ips(host):
    """Every IP `host` denotes: the address itself for a literal (including the
    non-standard numeric forms the OS resolver expands — decimal 2130706433,
    hex 0x7f000001, octal, short 127.1 — which socket.inet_aton accepts), else
    the A/AAAA records from DNS. Empty when the host cannot be resolved."""
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        return [ipaddress.ip_address(socket.inet_aton(host))]
    except (OSError, ValueError):
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return []
    return [ipaddress.ip_address(info[4][0]) for info in infos]


def is_public_http_target(raw):
    """No SSRF into loopback / private-range / CGNAT / link-local / metadata
    endpoints or .internal/.local/localhost hosts. The host is RESOLVED before
    it is judged, so a public name whose A record points inward (e.g. the
    169.254.169.254.nip.io rebinding trick) is rejected on the resolved address
    rather than trusted for not being a literal, and every resolved IP must be
    globally routable. A DNS-rebinding TOCTOU window remains between this check
    and the caller's connect — acceptable for a best-effort scraper, not a hard
    security boundary."""
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
    ips = _host_ips(host)
    if not ips:
        return False
    return all(ip.is_global and not ip.is_multicast for ip in ips)


def safe_get(get, url, max_redirects=4):
    """Fetch `url`, following up to `max_redirects` hops and re-checking
    is_public_http_target at EVERY hop — a 3xx to a private/metadata address is
    the classic SSRF bypass of a pre-fetch-only guard. `get(u)` must NOT follow
    redirects itself; it returns a response with `.status_code`, `.headers`,
    `.ok`, `.text`/`.content`. Returns the final response, or None when a hop is
    unsafe or the redirect budget is exhausted."""
    for _ in range(max_redirects + 1):
        if not is_public_http_target(url):
            return None
        res = get(url)
        status = getattr(res, "status_code", 0)
        location = res.headers.get("location") if 300 <= status < 400 else None
        if not location:
            return res
        url = urljoin(url, location)
    return None


def _absolutize(src, base):
    # An empty src must yield None, or a missing og:image leaks the page URL.
    if not src or not src.strip():
        return None
    try:
        return urljoin(base, src.strip())
    except ValueError:
        return None


def _area(url):
    """Pixel area parsed from a WxH token in the filename (0 when unknown)."""
    m = re.search(r"(\d{2,4})x(\d{2,4})", url)
    return int(m.group(1)) * int(m.group(2)) if m else 0


def _name_tokens(name):
    return [t for t in re.split(r"[^a-z0-9]+", name.lower()) if len(t) >= 3]


def _meta(html, name):
    for pat in (
        rf"<meta[^>]+(?:property|name)=[\"']{name}[\"'][^>]+content=[\"']([^\"']+)[\"']",
        rf"<meta[^>]+content=[\"']([^\"']+)[\"'][^>]+(?:property|name)=[\"']{name}[\"']",
    ):
        m = re.search(pat, html, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def extract_product_assets(html, page_url):
    """{name, description, logo, screenshots} from raw HTML."""
    name = _meta(html, "og:title")
    if not name:
        m = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        name = (m.group(1) if m else "").strip()
    name = html_mod.unescape(name)
    description = html_mod.unescape(_meta(html, "og:description") or _meta(html, "description"))
    og_image = _absolutize(_meta(html, "og:image"), page_url) or ""

    # App-store pages: og:image is the app icon (de-facto logo); screenshots
    # live on the store image CDNs.
    if is_store_host(page_url):
        store_shots = [
            m.group(0)
            for m in re.finditer(
                r"https://(?:is\d(?:-ssl)?\.mzstatic\.com|play-lh\.googleusercontent\.com)/[^\s\"'\\<]+",
                html,
            )
            if m.group(0) != og_image
        ]
        # The store CDN serves each artwork in several size variants differing
        # only in the final path segment — keep the biggest per artwork.
        by_art = {}
        for u in sorted(store_shots, key=_area, reverse=True):
            key = re.sub(r"/[^/]*$", "", u)
            by_art.setdefault(key, u)
        shots = list(by_art.values())
        # The AppIcon artwork is the app's true logo — prefer it over og:image
        # (sometimes a Placeholder). Placeholder art is never a screenshot.
        app_icon = next((u for u in shots if re.search(r"appicon", u, re.IGNORECASE)), None)
        screenshots = [
            u for u in shots
            if not re.search(r"appicon|placeholder", u, re.IGNORECASE) and "{" not in u
        ][:MAX_SCREENSHOTS]
        logo = app_icon or ("" if re.search(r"placeholder", og_image, re.IGNORECASE) else og_image)
        host = (urlparse(page_url).hostname or "").lower()
        cands = ([logo] if logo else []) + [f"https://www.google.com/s2/favicons?domain={host}&sz=256"]
        return {"name": name, "description": description, "logo": logo,
                "logo_candidates": cands, "screenshots": screenshots,
                "details": extract_page_text(html)}

    srcs = [
        _absolutize(m.group(1), page_url)
        for m in re.finditer(r"(?:src|href)=[\"']([^\"']+\.(?:png|jpe?g|webp))(?:\?[^\"']*)?[\"']", html, re.IGNORECASE)
    ]
    unique = list(dict.fromkeys(([og_image] if og_image else []) + [u for u in srcs if u]))

    def fname(u):
        return (u.rsplit("/", 1)[-1] if "/" in u else u).lower()

    # Logo: prefer filenames sharing a product-name token (the game's own logo
    # over the studio's site chrome), then the biggest variant.
    tokens = _name_tokens(name)
    logos = sorted(
        [u for u in unique if LOGO_WORD.search(u) and not NOISE.search(fname(u))],
        key=lambda u: (any(t in fname(u) for t in tokens), _area(u)),
        reverse=True,
    )
    screenshots = sorted(
        [u for u in unique if not LOGO_WORD.search(u) and not NOISE.search(fname(u))],
        key=_area,
        reverse=True,
    )[:MAX_SCREENSHOTS]
    candidates = extract_logo_candidates(html, page_url)
    declared = _jsonld_logos(html)
    logo = ""
    if declared:
        logo = _absolutize(declared[0], page_url) or ""
    elif logos:
        logo = logos[0]
    return {
        "name": name,
        "description": description,
        "logo": logo,
        "logo_candidates": candidates,
        "screenshots": screenshots,
        "details": extract_page_text(html),
    }


def _jsonld_logos(html):
    """Logo URLs the site itself declares in JSON-LD (Organization/WebSite.logo).
    Google requires this declaration for search, so commercial sites carry it —
    and it names the real brand mark even when the filename says 'placeholder'
    (teilor.ro). Handles logo as string, ImageObject, and @graph nesting."""
    out = []
    for m in re.finditer(r"<script[^>]+application/ld\+json[^>]*>([\s\S]*?)</script>", html, re.IGNORECASE):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        nodes = data if isinstance(data, list) else [data]
        items = []
        for d in nodes:
            if isinstance(d, dict):
                items.append(d)
                if isinstance(d.get("@graph"), list):
                    items.extend(x for x in d["@graph"] if isinstance(x, dict))
        for it in items:
            logo = it.get("logo")
            if isinstance(logo, dict):
                logo = logo.get("url")
            if isinstance(logo, str) and logo.strip():
                out.append(logo.strip())
    return out


def extract_logo_candidates(html, page_url):
    """Ordered brand-logo candidates, most authoritative first: JSON-LD
    declaration, apple-touch-icon (biggest), word-boundary logo-named images,
    sized link icons (>=96px), and the Google favicon service as the final
    always-available fallback. The consumer walks the list and keeps the first
    URL that downloads and decodes at a usable size."""
    cands = []
    for u in _jsonld_logos(html):
        a = _absolutize(u, page_url)
        if a:
            cands.append(a)

    touch = []
    for m in re.finditer(r"<link[^>]+rel=[\"\'][^\"\']*apple-touch-icon[^\"\']*[\"\'][^>]*>", html, re.IGNORECASE):
        tag = m.group(0)
        href = re.search(r"href=[\"\']([^\"\']+)[\"\']", tag)
        if not href:
            continue
        s = re.search(r"sizes=[\"\'](\d+)x\d+[\"\']", tag)
        a = _absolutize(href.group(1), page_url)
        if a:
            touch.append((int(s.group(1)) if s else 180, a))
    cands.extend(u for _, u in sorted(touch, key=lambda t: t[0], reverse=True))

    def fname(u):
        return (u.rsplit("/", 1)[-1] if "/" in u else u).lower()

    for m in re.finditer(r"(?:src|href)=[\"\']([^\"\']+\.(?:png|jpe?g|webp))(?:\?[^\"\']*)?[\"\']", html, re.IGNORECASE):
        a = _absolutize(m.group(1), page_url)
        if a and LOGO_WORD.search(a) and not NOISE.search(fname(a)):
            cands.append(a)

    for m in re.finditer(r"<link[^>]+rel=[\"\'][^\"\']*\bicon\b[^\"\']*[\"\'][^>]*>", html, re.IGNORECASE):
        tag = m.group(0)
        if re.search(r"apple-touch", tag, re.IGNORECASE):
            continue
        s = re.search(r"sizes=[\"\'](\d+)x\d+[\"\']", tag)
        if not s or int(s.group(1)) < 96:
            continue
        href = re.search(r"href=[\"\']([^\"\']+)[\"\']", tag)
        a = _absolutize(href.group(1), page_url) if href else None
        if a:
            cands.append(a)

    host = (urlparse(page_url).hostname or "").lower()
    if host:
        cands.append(f"https://www.google.com/s2/favicons?domain={host}&sz=256")
    return list(dict.fromkeys(cands))


def extract_page_text(html, max_chars=900):
    """A digest of the page's real prose: paragraph/list-item text long enough to
    be content (not nav crumbs or cookie banners), scripts/styles stripped, tags
    flattened, entities decoded, capped at max_chars. Feeds the script LLM with
    actual selling points beyond the one-line og:description."""
    body = re.sub(r"<(script|style)[^>]*>[\s\S]*?</\1>", " ", html, flags=re.IGNORECASE)
    chunks = []
    for m in re.finditer(r"<(?:p|li)[^>]*>([\s\S]*?)</(?:p|li)>", body, re.IGNORECASE):
        text = html_mod.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) >= 60 and text not in chunks:
            chunks.append(text)
    out = ""
    for c in chunks:
        candidate = (out + " " + c).strip()
        if len(candidate) > max_chars:
            break
        out = candidate
    return out


# CTA note per platform choice — the exact phrasing the platform's product node
# rides along in the summary (app modes only; a physical product carries none).
_PLATFORM_NOTE = {
    "mobile app": " (mobile app — the call to action must match: download on the App Store / Google Play)",
    "desktop app": " (desktop app — the call to action must match: get it on desktop / sign up on the web)",
    "physical product": "",
}


def build_summary(name, description, platform, details="", include_details=False,
                  logo_found=True):
    """The product line the script LLM reads, byte-identical to the platform
    product node's output: `App (…CTA…): Name — Description`. The page-text
    DETAILS digest is opt-in — the platform engine never sends one."""
    kind = "Product" if platform == "physical product" else "App"
    summary = f"{kind}{_PLATFORM_NOTE.get(platform, '')}: {name}"
    if description:
        summary += f" — {description}"
    if not logo_found:
        summary += " (no logo found on the page — end the ad on the product itself)"
    if include_details and details:
        summary += f"\nDETAILS: {details}"
    return summary


def find_store_link(html):
    for m in re.finditer(r"href=[\"'](https?://[^\"']+)[\"']", html, re.IGNORECASE):
        if is_store_host(m.group(1)):
            return m.group(1)
    return None


def scrape_product(url, fetch):
    """Full scrape: the page, plus a best-effort follow of the first app-store
    link (store listings carry the curated promo screens product sites rarely
    host). `fetch(url) -> html | None` is injected; every fetch target is
    SSRF-checked. Raises ValueError for a non-public entry URL."""
    if not is_public_http_target(url):
        raise ValueError("only public http(s) URLs can be scraped")

    def safe_fetch(u):
        if not is_public_http_target(u):
            return None
        try:
            return fetch(u)
        except Exception:
            return None

    html = safe_fetch(url)
    if html is None:
        raise RuntimeError("page fetch failed")
    assets = extract_product_assets(html, url)

    # Web-app manifest icons (PWA 192/512px brand marks) join the logo cascade
    # just before the favicon-service fallback; a stub manifest with no icons
    # (teilor.ro ships a bare push-notification one) is skipped silently.
    mlink = re.search(r"<link[^>]+rel=[\"\']manifest[\"\'][^>]+href=[\"\']([^\"\']+)[\"\']", html, re.IGNORECASE)
    if mlink:
        murl = _absolutize(mlink.group(1), url)
        mtext = safe_fetch(murl) if murl else None
        if mtext:
            try:
                icons = json.loads(mtext).get("icons", [])
            except ValueError:
                icons = []
            sized = []
            for ic in icons:
                if not isinstance(ic, dict) or not ic.get("src"):
                    continue
                s = re.match(r"(\d+)x\d+", str(ic.get("sizes", "")))
                a = _absolutize(ic["src"], murl)
                if a:
                    sized.append((int(s.group(1)) if s else 0, a))
            manifest_icons = [u for _, u in sorted(sized, key=lambda t: t[0], reverse=True)]
            if manifest_icons:
                cands = assets.get("logo_candidates", [])
                assets["logo_candidates"] = list(dict.fromkeys(cands[:-1] + manifest_icons + cands[-1:]))

    store_link = find_store_link(html)
    if store_link and not is_store_host(url):
        store_html = safe_fetch(store_link)
        if store_html:
            store = extract_product_assets(store_html, store_link)
            # Store promo screens lead (splash/logo art), page shots follow.
            merged = list(dict.fromkeys(store["screenshots"] + assets["screenshots"]))
            assets["screenshots"] = merged[:MAX_SCREENSHOTS]
            # The store og:image / AppIcon is the right end-card logo for an app.
            if store["logo"]:
                assets["logo"] = store["logo"]
            # Store listings often carry the fuller description text.
            if len(store.get("details", "")) > len(assets.get("details", "")):
                assets["details"] = store["details"]

    if not assets["logo"] and not assets["screenshots"]:
        raise RuntimeError("no usable product images found on the page")
    return assets
