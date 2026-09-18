"""The public website says only what the product can prove.

Every public route is projected through the Cell website from the public
map: the one price sentence is the offer display, the privacy sentence is
verbatim on the security page and inside the home boundary, the home
draws no Grand Map domain grid because the design has none, none of the
design's unproven literals survive, and no sentence claims a
completeness the code does not prove. This court never imports
application_server.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang.cell_website import (  # noqa: E402
    OFFER_DEFAULT_DISPLAY,
    PUBLIC_WEBSITE_ROUTES,
    project_universal_website_document,
)
from nodelang.map_import import PUBLIC_MAP_PATH  # noqa: E402
from nodelang.universal_application import (  # noqa: E402
    build_universal_application,
)

PACKAGING = Path(__file__).resolve().parents[1] / "packaging" / "website"

PRIVACY_SENTENCE = (
    "When cloud sync is on, ArchHub keeps a copy of your brain on our servers "
    "so it can reach your other devices and your firm. That copy is not "
    "end-to-end encrypted, and ArchHub's systems can read it."
)
FORBIDDEN = tuple(re.compile(pattern) for pattern in (
    r"\$[0-9]",
    r"sealed by your login",
    r"refs only",
    r"only you can read",
    r"v0\.27\.0",
    r"b11bdc8",
    r"All 19",
    r"macOS",
    r"\bMIT\b",
    r"never leaves",
    r"no upload path",
    r"session #",
    r"(?i)<script",
    r"whole boundary",
    r"second place",
    r"it is gone",
))
# The two addresses outside the site a page links: the installer of the
# released build the graph offers, and the repository. Pinned here, not
# borrowed from the code under court.
INSTALLER = (
    "https://github.com/Fargaly/ArchHub/releases/download/"
    "build-20260916-2105-b914892/ArchHub-Setup-0.exe"
)
REPOSITORY = "https://github.com/Fargaly/ArchHub"
HOME_DESIGN_TEXT = (
    "Drafted, ",
    "not generated.",
    "Graph-first AI workspace for AEC",
    '<a class="site-primary" href="%s">Download for Windows</a>' % INSTALLER,
    '<a class="site-secondary" href="/website/signin">Sign in</a>',
    "bring your own key",
    "no credit card",
    "<span>Windows</span>",
    "The three pillars",
    'class="site-pillar-title">Canvas<',
    'class="site-pillar-title">Composer<',
    'class="site-pillar-title">Brain<',
    "Self-healing connectors",
    "Replayable by construction",
    "Skills you own",
    "Recall is by purpose, out of the graph",
    "Inside your machine",
    "Leaves, when a node asks",
    "Leaves, when cloud sync is on",
    "drafting table.",
)


@pytest.fixture(scope="module")
def application():
    return build_universal_application(PUBLIC_MAP_PATH)


@pytest.fixture(scope="module")
def documents(application):
    store, registry = application
    return {
        path: project_universal_website_document(
            store, registry.website, path,
            application_root=registry.application_root,
            application_member_role=registry.roles["member"],
            map_registry=registry.map,
            cloud_route_protocol=registry.cloud_route_protocol,
        )
        for path in PUBLIC_WEBSITE_ROUTES
    }


def test_the_home_is_the_founder_design(documents):
    home = documents["/website"]
    missing = [text for text in HOME_DESIGN_TEXT if text not in home]
    assert missing == []
    assert "<title>Drafted, not generated. | ArchHub</title>" in home
    assert home.count("<main") == 1
    # The design's "Create your account" waits until /website/signin opens;
    # until then the primary call is the Windows download.
    assert "Create your account" not in home


def test_the_one_price_sentence_is_the_offer_display(documents):
    assert OFFER_DEFAULT_DISPLAY == "Free during beta"
    assert OFFER_DEFAULT_DISPLAY in documents["/website/pricing"]
    assert OFFER_DEFAULT_DISPLAY in documents["/website"]


def test_the_privacy_sentence_is_verbatim_where_the_brain_is_mentioned(documents):
    assert PRIVACY_SENTENCE in documents["/website/security"]
    assert PRIVACY_SENTENCE in documents["/website"]


@pytest.mark.parametrize("path", PUBLIC_WEBSITE_ROUTES)
def test_no_unproven_design_literal_survives(documents, path):
    document = documents[path]
    found = [pattern.pattern for pattern in FORBIDDEN if pattern.search(document)]
    assert found == []


def test_the_home_draws_no_grand_map_domain_grid(application, documents):
    # The founder read the live site against the design on 2026-09-17.
    # The design has no domain grid, so the public home draws none and
    # nothing takes its place. The bindings stay in the graph, one per
    # domain, with nothing to see on any page.
    _store, registry = application
    for path, document in documents.items():
        assert "site-domain-card" not in document, path
        assert "site-domain-grid" not in document, path
        assert "site-graph" not in document, path
        assert "The Grand Map" not in document, path
        assert "Grand Map domain" not in document, path
    bindings = registry.website.domain_binding_roots
    assert set(bindings) == set(registry.map.domains)
    assert not any(hasattr(b, "card_root") for b in bindings.values())


@pytest.mark.parametrize("path", PUBLIC_WEBSITE_ROUTES)
def test_every_link_stays_inside_the_public_routes(documents, path):
    # The offered installer and the repository are the only ways out, and
    # every page offers both.
    hrefs = set(re.findall(r'href="([^"]*)"', documents[path]))
    assert hrefs
    assert hrefs - set(PUBLIC_WEBSITE_ROUTES) == {INSTALLER, REPOSITORY}


@pytest.mark.parametrize("path", PUBLIC_WEBSITE_ROUTES)
def test_every_emitted_class_is_styled(documents, path):
    document = documents[path]
    stylesheet = document[document.index("<style>"):document.index("</style>")]
    classes = {
        token
        for value in re.findall(r'class="([^"]*)"', document)
        for token in value.split()
    }
    unstyled = sorted(
        token for token in classes
        if not re.search(r"\.%s(?![A-Za-z0-9_-])" % re.escape(token), stylesheet)
    )
    assert unstyled == []


def _packaging_text(name):
    path = PACKAGING / name
    if not path.is_file():
        pytest.skip("packaging/website/%s is not in this tree yet (W4)" % name)
    return path.read_text(encoding="utf-8")


def test_the_static_site_image_serves_the_export_with_its_own_httpd_conf():
    dockerfile = _packaging_text("Dockerfile")
    assert '"-c"' in dockerfile and '"httpd.conf"' in dockerfile
    assert "site_export" in dockerfile


def test_the_httpd_conf_names_the_not_found_page():
    assert "E404:404.html" in _packaging_text("httpd.conf")


def test_the_fly_manifest_listens_on_the_httpd_port():
    assert re.search(r"internal_port\s*=\s*3000\b", _packaging_text("fly.toml"))
