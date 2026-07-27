# ABOUTME: Node-level regression for HypereelProductScrape — a single unreachable
# ABOUTME: image URL must degrade to None, not crash the whole scrape.
import importlib
import sys
import types

import pytest
import requests


@pytest.fixture()
def node(monkeypatch):
    # Relative imports (from ._hypereel_scrape) need the host package; the module
    # itself pulls only torch/requests/PIL/numpy, all present in the test env.
    pkg = types.ModuleType("symbiotica")
    pkg.__path__ = ["py"]
    monkeypatch.setitem(sys.modules, "symbiotica", pkg)
    return importlib.import_module("symbiotica.hypereel_product_scrape")


def test_fetch_image_returns_none_on_network_error(node, monkeypatch):
    # A public literal passes the SSRF guard without DNS; the transport then dies
    # mid-request (a hotlink-protected CDN dropping the connection). _fetch_image
    # documents "None when the download/decode fails" — a raised ConnectTimeout
    # must not escape and abort the node's whole screenshot loop.
    def boom(url, timeout):
        raise requests.exceptions.ConnectTimeout("dead host")

    monkeypatch.setattr(node, "_get", boom)
    assert node._fetch_image("http://93.184.216.34/shot.png") is None
