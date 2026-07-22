# ABOUTME: Tests the product-scrape port — asset extraction, store handling, size
# ABOUTME: scoring, SSRF guard, store-follow merge. Ports the platform's field cases.
import pytest

from _hypereel_scrape import (
    extract_product_assets,
    is_public_http_target,
    scrape_product,
)


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

    def test_public_ok(self):
        assert is_public_http_target("https://goodgame.com/e4k") is True


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
