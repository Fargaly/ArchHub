"""Court: the public website offers Google sign-in only, and links the current build.

archhub.io still said "Email link or Google" on /signin after the email
magic-link routes were removed (4ccf7bc), because the site was exported from
a graph that kept the old copy. Every page the export writes, the 404 page and
the redirect pages included, is read here as text a visitor sees; none may
offer an email link, a magic link or any other way to sign in than Google.
The released build the pages link is pinned here, not borrowed from the code
under court.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodelang.cell_website as cell_website  # noqa: E402
import nodelang.site_export as site_export  # noqa: E402
from nodelang.cell_accounts import BETA_OFFER  # noqa: E402
from nodelang.map_import import PUBLIC_MAP_PATH  # noqa: E402
from nodelang.universal_application import build_universal_application  # noqa: E402

ORIGIN = "https://archhub.io"
OFFER = dict(BETA_OFFER)
# The GitHub release that is releases/latest on 2026-09-29, with the sha256
# GitHub publishes for its installer asset.
REVISION = "build-20261010-1534-6ac6b78"
DOWNLOAD = (
    "https://github.com/Fargaly/ArchHub/releases/download/"
    "build-20261010-1534-6ac6b78/ArchHub-Setup-0.exe"
)
DOWNLOAD_SHA256 = "57d14a353e0c2c73f47ac8d42ec9e26c397623c8af34a1c7b47f62f3b2f2200b"

# Wording that offers a sign-in other than Google.
NOT_GOOGLE = re.compile(
    r"e-?mail(?:ed)?\s+(?:sign-?in\s+|login\s+)?links?"
    r"|links?\s+(?:is\s+|are\s+)?(?:mailed|e-?mailed|sent)\s+to"
    r"|magic"
    r"|sign-?in\s+links?"
    r"|link\s+to\s+your\s+(?:e-?mail|inbox)"
    r"|passwordless",
    re.IGNORECASE,
)


def _digest(record):
    return hashlib.sha256(json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


def _visible_text(document):
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", document, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())


@pytest.fixture(scope="module")
def export():
    store, registry = build_universal_application(PUBLIC_MAP_PATH)
    return site_export.build_site_export(
        store, registry, offer=OFFER, offer_sha256=_digest(OFFER), origin=ORIGIN,
    )


def _pages(export):
    pages = {route: record["html"] for route, record in export["routes"].items()}
    for name, contents in export["assets"].items():
        if name.endswith(".html"):
            pages[name] = contents
    return pages


def test_no_public_page_offers_an_email_link_or_magic_sign_in(export):
    pages = _pages(export)
    assert "/website/signin" in pages
    found = {
        route: sorted({m.group(0) for m in NOT_GOOGLE.finditer(_visible_text(doc))})
        for route, doc in pages.items()
    }
    assert {route: hits for route, hits in found.items() if hits} == {}


def test_the_sign_in_page_offers_google_and_nothing_else(export):
    page = _visible_text(export["routes"]["/website/signin"]["html"])
    assert "Continue with Google" in page
    assert not re.search(r"\bor Google\b|\bGoogle, or\b", page), page


def test_the_copy_the_pages_are_built_from_offers_google_only():
    specs = cell_website._page_specs()
    for path, (title, lede, cards) in specs.items():
        for text in (title, lede, *(part for card in cards for part in card)):
            assert not NOT_GOOGLE.search(text), (path, text)


def test_every_page_links_the_current_release(export):
    assert export["download"] == {
        "revision": REVISION, "sha256": DOWNLOAD_SHA256, "url": DOWNLOAD,
    }
    href = 'href="%s"' % DOWNLOAD
    for route, record in export["routes"].items():
        assert href in record["html"], route
        assert "build-20260916-2105-b914892" not in record["html"], route
