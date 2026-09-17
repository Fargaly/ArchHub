"""Courts for the website parity round 2 founder decisions (2026-09-17).

Decision 1: the design's interactions (hero canvas drag and wire, host picker,
self-heal timeline) ship as one static script asset, admitted by its exact
sha256. The graph document stays scriptless; the export adds the one tag, and
a page with a second or inline script, or a script file with a changed byte,
is refused. Decision 2: the pricing calculator is gone. The header and footer
follow the design, the version tag reads the released revision, and /features
and /security open with the design sections only.
"""
from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodelang.site_export as site_export  # noqa: E402
from nodelang.cell_accounts import BETA_OFFER  # noqa: E402
from nodelang.map_import import PUBLIC_MAP_PATH  # noqa: E402
from nodelang.universal_application import build_universal_application  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
# Pinned here, never borrowed from the code under court.
SITE_SCRIPT_SHA256 = "4e7a942421c969557a068fe537491b77eae7315c3890588f8c4de8596605840a"
SCRIPT_TAG = '<script src="/assets/site.js" defer></script>'
SCRIPT_FILE = REPO / "nodelang" / "data" / "website" / "site.js"
REVISION = "build-20260916-2105-b914892"
NAV = ("Features", "Connectors", "Brain", "Security", "Pricing")
OFFER = dict(BETA_OFFER)


@pytest.fixture(scope="module")
def application():
    return build_universal_application(PUBLIC_MAP_PATH)


@pytest.fixture(scope="module")
def export(application):
    store, registry = application
    return site_export.build_site_export(
        store, registry, offer=OFFER, offer_sha256=site_export.offer_digest(OFFER),
        origin="https://archhub.io",
    )


def _page(export, route):
    return export["routes"][route]["html"]


def test_the_pinned_site_script_is_admitted(export, tmp_path, application):
    data = SCRIPT_FILE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SITE_SCRIPT_SHA256
    assert export["files"]["assets/site.js"] == {
        "bytes": len(data), "sha256": SITE_SCRIPT_SHA256,
    }
    for route, record in export["routes"].items():
        page = record["html"]
        assert re.findall(r"<script\b[^>]*>", page) == [SCRIPT_TAG[:-9]], route
        assert page.count(SCRIPT_TAG) == 1, route
    store, registry = application
    site_export.write_public_site(
        store, registry, tmp_path, offer=OFFER,
        offer_sha256=site_export.offer_digest(OFFER), origin="https://archhub.io",
    )
    written = (tmp_path / "dist" / "assets" / "site.js").read_bytes()
    assert hashlib.sha256(written).hexdigest() == SITE_SCRIPT_SHA256


def test_a_changed_byte_in_the_site_script_is_refused(application, monkeypatch):
    store, registry = application
    original = site_export._brand_bytes

    def changed(name):
        data = original(name)
        if name == "assets/site.js":
            return data[:-2] + bytes([data[-2] ^ 1]) + data[-1:]
        return data

    monkeypatch.setattr(site_export, "_brand_bytes", changed)
    with pytest.raises(site_export.SiteExportError, match="site script sha256"):
        site_export.build_site_export(store, registry)
    with pytest.raises(site_export.SiteExportError):
        site_export.site_script_bytes(changed("assets/site.js"))


def test_a_second_or_inline_script_is_refused(export):
    page = _page(export, "/website")
    assert site_export.admitted_scripts(page) == page
    for forged in (
        page.replace("</body>", '<script src="/assets/other.js"></script></body>'),
        page.replace("</body>", "<script>document.title=1</script></body>"),
        page.replace("</body>", SCRIPT_TAG + "</body>"),
        page.replace(SCRIPT_TAG, ""),
        page.replace(SCRIPT_TAG, '<script src="/assets/site.js"></script>'),
        page.replace(SCRIPT_TAG, '<SCRIPT src="https://cdn.example/x.js"></SCRIPT>'),
    ):
        with pytest.raises(site_export.SiteExportError):
            site_export.admitted_scripts(forged)


def test_the_graph_document_stays_scriptless():
    document = "<html><head><style>a{}</style></head><body><script>1</script></body></html>"
    with pytest.raises(site_export.SiteExportError, match="contains a script"):
        site_export._static_document(document)


def test_the_script_is_the_design_interactions_and_reaches_nothing_outside():
    text = SCRIPT_FILE.read_text(encoding="ascii")
    for hook in ("[data-canvas]", "[data-hosts]", "[data-host-detail]", "[data-heal]"):
        assert hook in text
    for banned in ("fetch(", "XMLHttpRequest", "eval(", "import(", "localStorage",
                   "document.cookie", "WebSocket", "session #"):
        assert banned not in text, banned
    assert set(re.findall(r"https?://[^'\"\s]+", text)) == {"http://www.w3.org/2000/svg"}


def test_the_pages_carry_the_hooks_the_script_reads(export):
    home = _page(export, "/website")
    assert 'data-canvas="hero"' in home
    assert home.count('data-node="') == 3
    assert 'data-hosts="catalogue"' in home and 'data-host-detail="catalogue"' in home
    assert 'data-heal="timeline"' in home and 'data-heal-play="play"' in home
    features = _page(export, "/website/features")
    assert 'data-heal="timeline"' in features


def test_the_pricing_calculator_is_gone(export):
    for route in ("/website", "/website/pricing"):
        page = _page(export, route)
        for token in ("site-calc", "site-co-", "site-segb", 'type="range"',
                      "Per month", "Sheet sets plotted", "Automated runs"):
            assert token not in page, (route, token)
    pricing = _page(export, "/website/pricing")
    assert '<h2 class="site-sec-head-title">What it costs</h2>' in pricing
    assert '<span class="site-sec-head-sub">Free during beta</span>' in pricing
    assert "site-page-card" not in pricing
    assert "site-calc" not in export["assets"]["assets/site.css"]


def test_every_page_has_the_design_header_and_footer(export):
    for route, record in export["routes"].items():
        page = record["html"]
        nav = page[page.index('<nav class="site-nav"'):page.index("</nav>")]
        assert 'class="site-logo"' in nav, route
        labels = re.findall(r'<a class="site-nav-link"[^>]*>([^<]*)</a>', nav)
        assert tuple(labels) == NAV, route
        assert '<span class="site-ver">%s</span>' % REVISION in nav, route
        assert re.search(r'<a class="site-access"[^>]*>Sign in</a>', nav), route
        assert '<a class="site-access site-access-primary" href="/signin/">Create account</a>' in nav, route
        footer = page[page.index('<footer class="site-footer">'):]
        assert 'class="site-logo"' in footer, route
        heads = re.findall(r'<p class="site-foot-head">([^<]*)</p>', footer)
        assert heads == ["Product", "Company", "Open"], route
        assert "<span>Built from %s</span>" % REVISION in footer, route
        for untrue in ("v0.27.0", "MIT", "b11bdc8", "Discord"):
            assert untrue not in page, (route, untrue)


def test_features_and_security_open_with_the_design_sections_only(export):
    features = _page(export, "/website/features")
    main = features[features.index("<main"):features.index("</main>")]
    assert "site-page-card" not in main
    assert "Canvas. Composer. " in main and "Your CAD " in main and "A graph you can " in main
    assert '<header class="site-page-header site-sr">' in main
    security = _page(export, "/website/security")
    main = security[security.index("<main"):security.index("</main>")]
    assert "site-page-card" not in main
    assert 'class="site-boundary-section"' in main
    assert "site-heal" not in main and "site-pillar" not in main