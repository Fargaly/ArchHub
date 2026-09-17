"""Courts for the /docs pages and the design sections the website holds.

The founder design (ArchHub Website.html) is one landing page: hero, trust
strip, three pillars, self-healing connectors, the canvas, the brain, the
local-first boundary, what it costs, and the closing call. Its interactions
are scripts, and the export admits none, so the pages hold each interactive
section's first, idle frame. The calculator holds no figure: prices wait on a
founder decision, and the offer the graph holds is the only claim it makes.
The docs pages say what the released build does; a website graph built before
they existed is read as it is, never rebuilt, and still opens.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodelang.cell_website as cell_website  # noqa: E402
import nodelang.site_export as site_export  # noqa: E402
from nodelang.cell_accounts import BETA_OFFER  # noqa: E402
from nodelang.cell_voice import lint  # noqa: E402
from nodelang.map_import import PUBLIC_MAP_PATH  # noqa: E402
from nodelang.universal_application import build_universal_application  # noqa: E402
from nodelang.universal_cell import CellStore  # noqa: E402
from nodelang.website_docs_text import DOCS_PAGES  # noqa: E402

ORIGIN = "https://archhub.io"
OFFER = dict(BETA_OFFER)
# The five pages the retired Astro docs collection answered at, pinned here.
DOCS_KEYS = ("getting-started", "composer-canvas", "brain", "account-web", "connectors")


def _digest(record):
    return hashlib.sha256(json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


def _documents(store, registry, routes):
    return {
        path: cell_website.project_universal_website_document(
            store, registry.website, path,
            application_root=registry.application_root,
            application_member_role=registry.roles["member"],
            map_registry=registry.map,
            cloud_route_protocol=registry.cloud_route_protocol,
        )
        for path in routes
    }


@pytest.fixture(scope="module")
def application():
    return build_universal_application(PUBLIC_MAP_PATH)


@pytest.fixture(scope="module")
def documents(application):
    return _documents(*application, cell_website.PUBLIC_WEBSITE_ROUTES)


@pytest.fixture(scope="module")
def export(application):
    store, registry = application
    return site_export.build_site_export(
        store, registry, offer=OFFER, offer_sha256=_digest(OFFER), origin=ORIGIN,
    )


def test_every_docs_page_is_a_route_the_graph_holds(application):
    assert tuple(DOCS_PAGES) == DOCS_KEYS
    assert cell_website.PUBLIC_WEBSITE_ROUTES == (
        cell_website.CORE_WEBSITE_ROUTES
        + tuple("/website/docs/%s" % key for key in DOCS_KEYS)
    )
    _, registry = application
    assert set(registry.website.route_roots) == set(cell_website.PUBLIC_WEBSITE_ROUTES)


def test_every_docs_page_renders_its_title_lede_and_every_heading(documents):
    for key, (title, description, text) in DOCS_PAGES.items():
        page = documents["/website/docs/%s" % key]
        assert '<h1 class="site-page-title">%s</h1>' % title in page, key
        assert '<p class="site-page-lede">%s</p>' % description in page, key
        for heading in re.findall(r"^## (.+)$", text, re.MULTILINE):
            assert '<h2 class="site-doc-h2">%s</h2>' % heading in page, (key, heading)
        assert page.count('class="site-doc-link"') == len(DOCS_KEYS), key
        assert 'aria-current="page">%s</a>' % title in page, key
        assert "<script" not in page, key


def test_every_docs_text_is_in_voice_ascii_and_names_no_price():
    for key, (title, description, text) in DOCS_PAGES.items():
        for value in (title, description, text):
            assert value.isascii(), key
            assert "$" not in value, key
        for line in [title, description, *text.splitlines()]:
            assert lint(line) == (), (key, line)
        assert text.count(chr(96)) % 2 == 0, key


def test_the_export_serves_every_docs_page_where_the_old_site_did(export):
    assets = export["assets"]
    for key in DOCS_KEYS:
        record = export["routes"]["/website/docs/%s" % key]
        assert record["output_path"] == "docs/%s/index.html" % key
        page = record["html"]
        assert '<link rel="canonical" href="%s/docs/%s/">' % (ORIGIN, key) in page
        assert 'http-equiv="refresh"' not in page
        assert 'href="/docs/getting-started/"' in page
    assert 'url=/docs/getting-started/"' in assets["docs/index.html"]


def test_a_website_graph_built_before_the_docs_pages_still_opens(monkeypatch):
    with monkeypatch.context() as scoped:
        scoped.setattr(cell_website, "_docs_pages", lambda: {})
        store, registry = build_universal_application(PUBLIC_MAP_PATH, CellStore())
    assert set(registry.website.route_roots) == set(cell_website.CORE_WEBSITE_ROUTES)
    revision = store.revision
    verified = cell_website.ensure_universal_website(
        store,
        application_root=registry.application_root,
        application_member_role=registry.roles["member"],
        ui_protocol=registry.ui_protocol,
        cloud_route_protocol=registry.cloud_route_protocol,
        map_registry=registry.map,
        published_lifecycle_root=registry.website.lifecycle_root,
        read_action_root=registry.website.read_action_root,
    )
    assert store.revision == revision
    assert set(verified.route_roots) == set(cell_website.CORE_WEBSITE_ROUTES)
    pages = _documents(store, registry, cell_website.CORE_WEBSITE_ROUTES)
    assert set(pages) == set(cell_website.CORE_WEBSITE_ROUTES)


def test_the_home_holds_the_design_sections_in_design_order(documents):
    page = documents["/website"]
    order = [
        'class="site-hero"', 'class="site-trust"', "Canvas. Composer.",
        'class="site-heal-panel"', "A graph you can ", "Memory that grows with the ",
        'class="site-boundary-section"', 'class="site-sec-head-title">What it costs<',
        'class="site-closing"', 'class="site-footer"',
    ]
    positions = [page.index(marker) for marker in order]
    assert positions == sorted(positions)
    assert "<script" not in page


def test_the_calculator_frame_names_the_offer_and_no_price(documents):
    page = documents["/website"]
    frame = page[page.index('class="site-sec-head-title">What it costs<'):page.index('class="site-closing"')]
    assert '<span class="site-sec-head-sub">%s</span>' % BETA_OFFER["public-label"] in frame or (
        '<span class="site-sec-head-sub">%s</span>' % cell_website.OFFER_DEFAULT_DISPLAY in frame
    )
    assert "$" not in frame
    assert not re.search(r"[0-9]", re.sub(r"<[^>]+>", "", frame))


def test_the_heal_section_holds_the_idle_frame_and_no_invented_figure(documents):
    page = documents["/website"]
    start = page.index('class="site-heal-panel"')
    frame = re.sub(r"<[^>]+>", " ", page[start:page.index("A graph you can ", start)])
    assert "Idle. The connection is nominal." in frame
    assert not re.search(r"[0-9]", frame.replace("LAST 7 DAYS", ""))


def test_each_subpage_holds_the_design_section_it_names(documents):
    assert 'class="site-heal-panel"' in documents["/website/features"]
    assert "Canvas. Composer." in documents["/website/features"]
    assert 'class="site-sec-head-title">What it costs<' in documents["/website/pricing"]
    assert 'class="site-boundary-section"' in documents["/website/security"]
