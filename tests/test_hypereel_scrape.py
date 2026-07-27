# ABOUTME: Tests the product-scrape port — asset extraction, store handling, size
# ABOUTME: scoring, SSRF guard, store-follow merge. Ports the platform's field cases.
import socket

import pytest

from _hypereel_scrape import (
    extract_product_assets,
    is_public_http_target,
    scrape_product,
)


@pytest.fixture(autouse=True)
def _pin_dns(monkeypatch):
    """is_public_http_target resolves the host before judging it, so pin DNS to
    keep these tests hermetic and off the network. The `rebind` names model a
    public hostname whose A record points inward (the 169.254.169.254.nip.io
    class a name-only guard misses); every other name resolves to a public IP."""
    rebind = {
        "169.254.169.254.nip.io": "169.254.169.254",  # public wildcard -> metadata
        "intranet.corp.test": "10.0.0.5",
    }

    def fake_getaddrinfo(host, *args, **kwargs):
        ip = rebind.get(host, "93.184.216.34")
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


GENERIC_PAGE = """
<html><head>
<title>Empire: Four Kingdoms | Goodgame</title>
<meta property="og:title" content="Empire: Four Kingdoms" />
<meta property="og:description" content="Become a king!" />
<meta property="og:image" content="/img/og_800x420.png" />
</head><body>
<img src="/assets/logo.png">
<img src="/assets/e4k_logo_timeline_476x268.png">
<img src="/shots/castle_675x900.jpg">
<img src="/shots/thumb_120x90.jpg">
<img src="/badges/app-store-badge.png">
<a href="https://apps.apple.com/us/app/empire/id123">App Store</a>
</body></html>
"""

STORE_PAGE = """
<html><head>
<meta property="og:title" content="Bakery Story" />
<meta property="og:image" content="https://is1-ssl.mzstatic.com/image/thumb/Placeholder.mig/400x400.png" />
</head><body>
https://is1-ssl.mzstatic.com/image/thumb/AppIcon-abc/230x230.png
https://is2-ssl.mzstatic.com/image/thumb/art1/ga_1286x600.jpg
https://is2-ssl.mzstatic.com/image/thumb/art1/ga_643x300.jpg
https://is3-ssl.mzstatic.com/image/thumb/art2/gb_1286x600.jpg
https://is3-ssl.mzstatic.com/image/thumb/tmpl/{w}x{h}.jpg
</body></html>
"""


class TestGenericPage:
    def test_prefers_product_token_logo_over_site_chrome(self):
        a = extract_product_assets(GENERIC_PAGE, "https://goodgame.com/e4k")
        assert "e4k_logo_timeline_476x268" in a["logo"]

    def test_screenshots_biggest_first_and_badges_filtered(self):
        a = extract_product_assets(GENERIC_PAGE, "https://goodgame.com/e4k")
        assert any("castle_675x900" in u for u in a["screenshots"])
        assert not any("badge" in u for u in a["screenshots"])
        assert a["screenshots"][0].endswith("castle_675x900.jpg")

    def test_name_and_description(self):
        a = extract_product_assets(GENERIC_PAGE, "https://goodgame.com/e4k")
        assert a["name"] == "Empire: Four Kingdoms"
        assert a["description"] == "Become a king!"

    def test_no_og_image_never_leaks_page_url(self):
        html = "<html><head><title>X</title></head><body></body></html>"
        a = extract_product_assets(html, "https://example.com/page")
        assert a["logo"] == "" and a["screenshots"] == []


class TestStorePage:
    def test_appicon_wins_as_logo_over_placeholder(self):
        a = extract_product_assets(STORE_PAGE, "https://apps.apple.com/us/app/bakery/id1")
        assert "AppIcon" in a["logo"]

    def test_variants_deduped_biggest_kept_templates_dropped(self):
        a = extract_product_assets(STORE_PAGE, "https://apps.apple.com/us/app/bakery/id1")
        assert any("ga_1286x600" in u for u in a["screenshots"])
        assert not any("ga_643x300" in u for u in a["screenshots"])  # smaller variant of same art
        assert not any("{" in u for u in a["screenshots"])  # unresolved template
        assert not any("Placeholder" in u for u in a["screenshots"])


class TestSsrfGuard:
    @pytest.mark.parametrize("bad", [
        "http://localhost/x", "http://127.0.0.1/x", "http://10.0.0.5/x",
        "http://169.254.169.254/latest/meta-data", "http://192.168.1.1/x",
        "http://172.16.0.1/x", "http://foo.internal/x", "ftp://example.com/x",
        "http://[::1]/x",
    ])
    def test_blocked(self, bad):
        assert is_public_http_target(bad) is False

    @pytest.mark.parametrize("bad", [
        "http://2130706433/x",        # decimal 127.0.0.1
        "http://0x7f000001/x",        # hex 127.0.0.1
        "http://0177.0.0.1/x",        # octal 127.0.0.1
        "http://127.1/x",             # short-form 127.0.0.1
        "http://0/x",                 # 0.0.0.0
        "http://2852039166/x",        # decimal 169.254.169.254 (metadata)
    ])
    def test_numeric_obfuscated_loopback_blocked(self, bad):
        # ipaddress.ip_address rejects these, but socket.inet_aton / the OS
        # resolver expand them to a real private IPv4 — so they must be blocked.
        assert is_public_http_target(bad) is False

    def test_public_ok(self):
        assert is_public_http_target("https://goodgame.com/e4k") is True

    @pytest.mark.parametrize("bad", [
        "http://169.254.169.254.nip.io/latest/meta-data/",  # name -> metadata IP
        "http://intranet.corp.test/x",                       # name -> private IP
    ])
    def test_hostname_resolving_inward_is_blocked(self, bad):
        # A name-only guard trusts anything that isn't an IP literal; the host
        # must be RESOLVED so a public name whose A record points at a private or
        # metadata address (the nip.io rebinding class) is rejected on the IP.
        assert is_public_http_target(bad) is False

    @pytest.mark.parametrize("bad", [
        "http://100.64.0.1/x",   # RFC 6598 CGNAT — not private, but not global
        "http://224.0.0.1/x",    # multicast
    ])
    def test_non_global_literals_blocked(self, bad):
        # The enumerated private/loopback/link-local flags miss these; testing
        # `is_global` (plus multicast) catches every non-routable class.
        assert is_public_http_target(bad) is False

    def test_unresolvable_host_is_refused(self, monkeypatch):
        # A host that resolves to nothing is refused, not waved through.
        def boom(*a, **k):
            raise socket.gaierror("name does not resolve")
        monkeypatch.setattr(socket, "getaddrinfo", boom)
        assert is_public_http_target("http://nx.example.invalid/") is False


class TestSafeGetRedirects:
    def _resp(self, status=200, location=None, url=""):
        from types import SimpleNamespace
        return SimpleNamespace(status_code=status, ok=(200 <= status < 300),
                               headers={"location": location} if location else {},
                               url=url, text="body", content=b"body")

    def test_direct_200_returns_response(self):
        from _hypereel_scrape import safe_get
        got = safe_get(lambda u: self._resp(200, url=u), "https://good.com/x")
        assert got.ok and got.url == "https://good.com/x"

    def test_redirect_to_private_is_blocked(self):
        from _hypereel_scrape import safe_get
        calls = []
        def get(u):
            calls.append(u)
            if u == "https://good.com/x":
                return self._resp(302, location="http://169.254.169.254/latest")
            return self._resp(200, url=u)
        assert safe_get(get, "https://good.com/x") is None
        # the private target is never actually fetched
        assert calls == ["https://good.com/x"]

    def test_public_redirect_chain_followed(self):
        from _hypereel_scrape import safe_get
        def get(u):
            if u == "https://good.com/a":
                return self._resp(301, location="https://good.com/b")
            return self._resp(200, url=u)
        got = safe_get(get, "https://good.com/a")
        assert got.ok and got.url == "https://good.com/b"

    def test_redirect_loop_bounded(self):
        from _hypereel_scrape import safe_get
        got = safe_get(lambda u: self._resp(302, location="https://good.com/loop"),
                       "https://good.com/loop", max_redirects=3)
        assert got is None


class TestStoreFollow:
    def test_store_shots_lead_and_appicon_wins(self):
        pages = {
            "https://goodgame.com/e4k": GENERIC_PAGE,
            "https://apps.apple.com/us/app/empire/id123": STORE_PAGE,
        }
        result = scrape_product("https://goodgame.com/e4k", fetch=pages.get)
        assert "AppIcon" in result["logo"]
        assert "mzstatic" in result["screenshots"][0]  # store promo screens lead

    def test_lookalike_store_host_not_followed(self):
        page = GENERIC_PAGE.replace("https://apps.apple.com/us/app/empire/id123",
                                    "https://apps.apple.com.evil.com/x")
        calls = []
        def fetch(u):
            calls.append(u)
            return page if u == "https://goodgame.com/e4k" else None
        scrape_product("https://goodgame.com/e4k", fetch=fetch)
        assert all("evil.com" not in u for u in calls[1:])

    def test_failed_store_fetch_keeps_page_assets(self):
        def fetch(u):
            if u == "https://goodgame.com/e4k":
                return GENERIC_PAGE
            raise RuntimeError("store down")
        result = scrape_product("https://goodgame.com/e4k", fetch=fetch)
        assert "e4k_logo" in result["logo"]

    def test_ssrf_rejected_at_entry(self):
        with pytest.raises(ValueError):
            scrape_product("http://169.254.169.254/", fetch=lambda u: "")


class TestEntityUnescape:
    def test_html_entities_decoded_in_name(self):
        html = '<html><head><title>Bakery Story &#8211; Imperia &amp; Co</title></head><body><img src="/a_logo_100x100.png"></body></html>'
        a = extract_product_assets(html, "https://x.com/p")
        assert a["name"] == "Bakery Story – Imperia & Co"


class TestPageDigest:
    HTML = """
    <html><body>
    <nav><p>Home</p><p>About</p></nav>
    <h1>Empire: Four Kingdoms</h1>
    <p>Build your own castle, create a powerful army and fight epic player versus player battles on a dynamic world map. Crush your enemies, conquer land and rise to the ruler of a mighty empire!</p>
    <p>Cookie settings</p>
    <p>Four unique kingdoms with their own resources, buildings and dangers await your armies &amp; heroes. Forge alliances, trade with other players and prove yourself in events.</p>
    <script>var x = "The developers ship paragraphs of junk in scripts sometimes and they must never appear";</script>
    </body></html>
    """

    def test_digest_keeps_real_paragraphs_skips_crumbs_and_scripts(self):
        from _hypereel_scrape import extract_page_text
        d = extract_page_text(self.HTML)
        assert "Build your own castle" in d
        assert "Forge alliances" in d
        assert "Cookie settings" not in d and "Home" not in d
        assert "junk in scripts" not in d

    def test_digest_caps_length_and_decodes_entities(self):
        from _hypereel_scrape import extract_page_text
        d = extract_page_text(self.HTML, max_chars=120)
        assert len(d) <= 120
        long = extract_page_text(self.HTML)
        assert "armies & heroes" in long

    def test_assets_carry_details(self):
        a = extract_product_assets(self.HTML + '<img src="/e_logo_100x100.png">', "https://x.com/p")
        assert "Build your own castle" in a["details"]


class TestSummaryPlatformParity:
    """build_summary must emit the platform product node's exact line — same CTA
    phrasing, and no DETAILS digest unless explicitly enabled (the platform
    engine never sends one)."""

    def test_mobile_app_matches_platform_cta_line(self):
        from _hypereel_scrape import build_summary
        s = build_summary("Empire: Four Kingdoms", "Become a king!", "mobile app")
        assert s == (
            "App (mobile app — the call to action must match: download on the "
            "App Store / Google Play): Empire: Four Kingdoms — Become a king!"
        )

    def test_desktop_app_cta_line(self):
        from _hypereel_scrape import build_summary
        s = build_summary("X", "Y", "desktop app")
        assert "desktop app — the call to action must match: get it on desktop / sign up on the web" in s

    def test_physical_product_has_no_platform_note(self):
        from _hypereel_scrape import build_summary
        s = build_summary("Empire: Four Kingdoms", "Become a king!", "physical product")
        assert s == "Product: Empire: Four Kingdoms — Become a king!"

    def test_missing_description_drops_the_dash(self):
        from _hypereel_scrape import build_summary
        assert build_summary("X", "", "physical product") == "Product: X"

    def test_details_off_by_default_on_when_asked(self):
        from _hypereel_scrape import build_summary
        d = "Build your own castle and fight epic battles."
        assert "DETAILS:" not in build_summary("X", "Y", "mobile app", details=d)
        s = build_summary("X", "Y", "mobile app", details=d, include_details=True)
        assert s.endswith("\nDETAILS: Build your own castle and fight epic battles.")
