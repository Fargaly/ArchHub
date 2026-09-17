"""Courts for the offer-verified public export.

The one public price sentence comes from the canonical offer record of
app:users:accounts:offer, digested the way cell_accounts.published_offer
digests it, and it drives the rendered pricing page; the static site is
addressed by root paths only; nothing the exporter writes is a Worker, a
hosting record, a server or a README. These courts never import
application_server.py.
"""
from __future__ import annotations

import hashlib
import html as html_text
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodelang.cell_website_meta as website_meta  # noqa: E402
import nodelang.site_export as site_export  # noqa: E402
from nodelang.cell_accounts import (  # noqa: E402
    BETA_OFFER,
    declare_offer,
    ensure_accounts,
    published_offer,
    set_offer_field,
)
from nodelang.cell_website import OFFER_DEFAULT_DISPLAY  # noqa: E402
from nodelang.map_import import PUBLIC_MAP_PATH  # noqa: E402
from nodelang.universal_application import (  # noqa: E402
    build_universal_application,
)
from nodelang.universal_cell import CellStore  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
ORIGIN = "https://archhub.io"
FOUNDER = "ahmed.fargaly98@gmail.com"
OFFER = dict(BETA_OFFER)
ROOT_PATHS = {
    "/website": "/",
    "/website/features": "/features/",
    "/website/pricing": "/pricing/",
    "/website/changelog": "/changelog/",
    "/website/security": "/security/",
    "/website/community": "/community/",
    "/website/signin": "/signin/",
    "/website/docs/getting-started": "/docs/getting-started/",
    "/website/docs/composer-canvas": "/docs/composer-canvas/",
    "/website/docs/brain": "/docs/brain/",
    "/website/docs/account-web": "/docs/account-web/",
    "/website/docs/connectors": "/docs/connectors/",
}
WRITTEN_SITE = [
    ".gitignore", "dist/404.html", "dist/account/index.html",
    "dist/assets/fonts.css", "dist/assets/fonts/OFL-InstrumentSerif.txt",
    "dist/assets/fonts/OFL-Inter.txt", "dist/assets/fonts/OFL-JetBrainsMono.txt",
    "dist/assets/fonts/instrument-serif-italic.woff2",
    "dist/assets/fonts/instrument-serif-regular.woff2",
    "dist/assets/fonts/inter-variable.woff2",
    "dist/assets/fonts/jetbrains-mono-regular.woff2",
    "dist/assets/site.css", "dist/assets/site.js", "dist/brain/index.html",
    "dist/changelog/index.html", "dist/community/index.html",
    "dist/docs/account-web/index.html", "dist/docs/brain/index.html",
    "dist/docs/composer-canvas/index.html", "dist/docs/connectors/index.html",
    "dist/docs/getting-started/index.html", "dist/docs/index.html",
    "dist/favicon.ico", "dist/favicon.svg",
    "dist/features/index.html", "dist/gallery/index.html", "dist/index.html",
    "dist/og.png", "dist/pricing/index.html", "dist/robots.txt",
    "dist/security/index.html", "dist/signin/index.html",
    "dist/sitemap.xml", "site-export.json",
]
OG_TITLE = re.compile(r'<meta property="og:title" content="(.*?)">')


def _digest(record):
    """The digest rule pinned here, not borrowed from the code under court."""
    return hashlib.sha256(json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


def _relabelled(label):
    return dict(OFFER, **{"public-label": label})


def _title_text(store, registry, route):
    cell = store.read(registry.website.route_title_roots[route])
    return bytes(cell.atom).decode("utf-8")


@pytest.fixture
def application():
    return build_universal_application(PUBLIC_MAP_PATH)


def _export(application, **kwargs):
    store, registry = application
    return site_export.build_site_export(store, registry, **kwargs)


def _verified(application):
    return _export(
        application, offer=OFFER, offer_sha256=_digest(OFFER), origin=ORIGIN,
    )


def test_the_offer_digest_is_what_cell_accounts_publishes():
    store = CellStore()
    ensure_accounts(store, founder_email=FOUNDER)
    declare_offer(store, founder_account=FOUNDER)
    published = published_offer(store.snapshot())
    assert published["sha256"] == _digest(BETA_OFFER)
    assert site_export.offer_digest(BETA_OFFER) == published["sha256"]
    assert site_export.offer_record_from_published(published) == BETA_OFFER

    set_offer_field(
        store, "public-label", "Free while in beta", founder_account=FOUNDER,
    )
    changed = published_offer(store.snapshot())
    assert changed["sha256"] != published["sha256"]
    record = site_export.offer_record_from_published(changed)
    assert record == _relabelled("Free while in beta")
    assert site_export.offer_digest(record) == changed["sha256"]
    with pytest.raises(site_export.SiteExportError, match="sha256"):
        site_export.offer_record_from_published(
            dict(changed, sha256=published["sha256"]))
    with pytest.raises(site_export.SiteExportError, match="pricing_visible"):
        site_export.offer_record_from_published(
            dict(changed, pricing_visible="false"))


def test_the_website_offer_is_the_record_as_the_pricing_page_reads_it():
    assert site_export.website_offer(OFFER) == {
        "display": OFFER_DEFAULT_DISPLAY, "monetary": False,
    }
    visible = dict(OFFER, **{"pricing-visible": "true"})
    assert site_export.website_offer(visible)["monetary"] is True


def test_an_offer_whose_digest_does_not_match_is_refused(application):
    with pytest.raises(site_export.SiteExportError, match="sha256"):
        _export(application, offer=OFFER, offer_sha256="0" * 64, origin=ORIGIN)


def test_a_monetary_offer_is_refused(application):
    offer = dict(OFFER, **{"pricing-visible": "true"})
    with pytest.raises(site_export.SiteExportError, match="monetary"):
        _export(application, offer=offer, offer_sha256=_digest(offer),
                origin=ORIGIN)


def test_an_offer_of_another_shape_is_refused(application):
    offer = {"display": OFFER_DEFAULT_DISPLAY, "monetary": False, "revision": 7}
    with pytest.raises(
        site_export.SiteExportError,
        match="availability, pricing-visible, public-label",
    ):
        _export(application, offer=offer, offer_sha256=_digest(offer),
                origin=ORIGIN)


def test_a_record_cell_accounts_would_refuse_is_refused(application):
    """The exporter applies the same field rules cell_accounts applies when
    it declares the record; a capitalised "True" must not pass the monetary
    veto, and a shouted slug or an over-long label must not reach the site."""
    for bad in (
        dict(OFFER, **{"pricing-visible": "True"}),
        dict(OFFER, availability="FREE!!"),
        dict(OFFER, **{"public-label": "x" * 81}),
        dict(OFFER, **{"public-label": "  Free during beta  "}),
    ):
        with pytest.raises(site_export.SiteExportError, match="offer record"):
            _export(application, offer=bad, offer_sha256=_digest(bad),
                    origin=ORIGIN)


def test_a_residual_in_app_link_is_refused(application, monkeypatch):
    """A link the rewrite did not reach (an anchor, a query, a trailing slash)
    is refused instead of shipping as a dead in-app path."""
    real = site_export._root_hrefs
    monkeypatch.setattr(
        site_export, "_root_hrefs",
        lambda text: real(text) + '<a href="/website/features#top">x</a>',
    )
    with pytest.raises(site_export.SiteExportError, match="in-app path"):
        _export(application, offer=OFFER, offer_sha256=_digest(OFFER),
                origin=ORIGIN)


def test_an_offer_the_pricing_page_does_not_show_is_refused(application):
    offer = _relabelled("Paid plans from nine a month")
    with pytest.raises(site_export.SiteExportError, match="pricing page"):
        _export(application, offer=offer, offer_sha256=_digest(offer),
                origin=ORIGIN)


def test_the_offer_drives_the_pricing_page():
    offer = _relabelled("Free while in beta")
    store, registry = build_universal_application(
        PUBLIC_MAP_PATH, offer=site_export.website_offer(offer),
    )
    payload = site_export.build_site_export(
        store, registry, offer=offer, offer_sha256=_digest(offer), origin=ORIGIN,
    )
    pricing = payload["routes"]["/website/pricing"]["html"]
    assert "Free while in beta" in pricing
    assert OFFER_DEFAULT_DISPLAY not in pricing
    assert payload["offer"] == offer
    assert payload["offer_sha256"] == _digest(offer)


def test_a_non_https_origin_is_refused(application):
    with pytest.raises(site_export.SiteExportError, match="https"):
        _export(application, offer=OFFER, offer_sha256=_digest(OFFER),
                origin="http://archhub.io")


def test_the_export_carries_the_verified_offer(application):
    payload = _verified(application)
    assert payload["offer"] == OFFER
    assert payload["offer_sha256"] == _digest(OFFER)
    assert payload["origin"] == ORIGIN
    assert "offer_revision" not in payload
    assert OFFER_DEFAULT_DISPLAY in payload["routes"]["/website/pricing"]["html"]


def test_every_page_is_addressed_by_root_paths_only(application):
    store, registry = application
    payload = _verified(application)
    assert tuple(payload["routes"]) == site_export.PUBLIC_ROUTES
    for route, record in payload["routes"].items():
        root = ROOT_PATHS[route]
        expected = "index.html" if root == "/" else root.strip("/") + "/index.html"
        assert record["output_path"] == expected
        page = record["html"]
        assert 'href="/website' not in page
        assert 'href="/"' in page
        assert 'href="/features/"' in page
        assert '<link rel="canonical" href="%s%s">' % (ORIGIN, root) in page
        assert '<meta property="og:url" content="%s%s">' % (ORIGIN, root) in page
        og_title = html_text.unescape(OG_TITLE.search(page).group(1))
        assert og_title == _title_text(store, registry, route)
        assert "| ArchHub" not in og_title
    robots = payload["assets"]["robots.txt"]
    assert "User-agent: *" in robots
    assert "Sitemap: %s/sitemap.xml" % ORIGIN in robots
    sitemap = payload["assets"]["sitemap.xml"]
    assert re.findall(r"<loc>(.*?)</loc>", sitemap) == [
        ORIGIN + ROOT_PATHS[route] for route in site_export.PUBLIC_ROUTES
    ]
    assert "/website" not in sitemap
    assert "404.html" in payload["assets"]


def test_a_described_page_gets_its_canonical_from_the_graph(application):
    store, _registry = application
    website_meta.set_origin(store, ORIGIN)
    website_meta.describe_page(
        store, path="/website/features", title="One graph",
        description="Everything the product holds is one persisted shape.",
    )
    meta = website_meta.page_meta(store.snapshot(), "/website/features")
    assert meta.canonical == ORIGIN + website_meta.public_path("/website/features")
    assert meta.canonical == "https://archhub.io/features/"
    page = _verified(application)["routes"]["/website/features"]["html"]
    assert '<link rel="canonical" href="https://archhub.io/features/">' in page
    assert '<meta property="og:title" content="One graph">' in page
    assert ('<meta property="og:description" content="Everything the product '
            'holds is one persisted shape.">') in page


def test_a_described_page_exports_before_the_graph_holds_an_origin(application):
    store, _registry = application
    website_meta.describe_page(
        store, path="/website/features", title="One graph",
        description="Everything the product holds is one persisted shape.",
    )
    assert website_meta.ORIGIN_ROOT not in store.snapshot().cells
    page = _verified(application)["routes"]["/website/features"]["html"]
    assert '<link rel="canonical" href="https://archhub.io/features/">' in page
    assert '<meta property="og:title" content="One graph">' in page


def test_a_graph_origin_that_differs_from_the_export_origin_is_refused(application):
    store, _registry = application
    website_meta.set_origin(store, "https://staging.example")
    with pytest.raises(site_export.SiteExportError, match="origin"):
        _verified(application)


def test_export_without_an_offer_stays_callable_and_claims_nothing(application):
    payload = _export(application)
    assert payload["offer"] is None
    assert payload["offer_sha256"] is None
    assert payload["origin"] is None
    assert "robots.txt" not in payload["assets"]
    assert "sitemap.xml" not in payload["assets"]
    assert "canonical" not in payload["routes"]["/website"]["html"]


def test_the_written_site_has_no_worker_hosting_server_or_readme_files(
    application, tmp_path
):
    store, registry = application
    project = tmp_path / "site"
    payload = site_export.write_public_site(
        store, registry, project,
        offer=OFFER, offer_sha256=_digest(OFFER), origin=ORIGIN,
    )
    written = sorted(
        path.relative_to(project).as_posix()
        for path in project.rglob("*") if path.is_file()
    )
    assert written == WRITTEN_SITE
    for name in written:
        for forbidden in ("wrangler", ".openai", "server", "build.mjs",
                          "package.json", "README"):
            assert forbidden not in name
    assert (project / ".gitignore").read_text(encoding="utf-8") == "dist/\n"
    assert json.loads(
        (project / "site-export.json").read_text(encoding="utf-8")) == payload
    for record in payload["routes"].values():
        rendered = project / "dist" / record["output_path"]
        assert rendered.read_text(encoding="utf-8") == record["html"]
    for scaffold in ("PACKAGE_JSON", "HOSTING_JSON", "WRANGLER_JSON",
                     "BUILD_MJS", "README"):
        assert not hasattr(site_export, scaffold), scaffold


def _cli(*args):
    return subprocess.run(
        [sys.executable, "-m", "nodelang.site_export", *args],
        cwd=REPO, capture_output=True, text=True, timeout=600,
    )


def _main_args(offer_path, sha, origin, out):
    return [
        "--offer", str(offer_path), "--offer-sha256", sha,
        "--origin", origin, "--output", str(out),
    ]


def test_the_cli_refuses_to_export_without_an_offer(tmp_path):
    result = _cli("--output", str(tmp_path / "out"))
    assert result.returncode != 0
    assert "--offer" in result.stderr
    assert not (tmp_path / "out" / "site-export.json").exists()


def test_the_cli_verifies_the_offer_and_origin_before_building(
    monkeypatch, tmp_path, capsys
):
    def _never_build(offer=None):
        raise AssertionError("the application was built before verification")

    monkeypatch.setattr(site_export, "_build_public_seed_application", _never_build)
    offer_path = tmp_path / "offer.json"
    offer_path.write_text(json.dumps(OFFER), encoding="utf-8")
    out = tmp_path / "out"

    with pytest.raises(SystemExit) as refused:
        site_export.main(_main_args(offer_path, "0" * 64, ORIGIN, out))
    assert refused.value.code == 1
    assert "sha256" in capsys.readouterr().err

    with pytest.raises(SystemExit) as refused:
        site_export.main(_main_args(
            offer_path, _digest(OFFER), "http://archhub.io", out))
    assert refused.value.code == 1
    assert "https" in capsys.readouterr().err

    monetary = dict(OFFER, **{"pricing-visible": "true"})
    monetary_path = tmp_path / "monetary.json"
    monetary_path.write_text(json.dumps(monetary), encoding="utf-8")
    with pytest.raises(SystemExit) as refused:
        site_export.main(_main_args(
            monetary_path, _digest(monetary), ORIGIN, out))
    assert refused.value.code == 1
    assert "monetary" in capsys.readouterr().err

    other_shape = tmp_path / "other.json"
    other_shape.write_text(json.dumps(
        {"display": OFFER_DEFAULT_DISPLAY, "monetary": False, "revision": 7}
    ), encoding="utf-8")
    with pytest.raises(SystemExit) as refused:
        site_export.main(_main_args(
            other_shape, _digest(json.loads(other_shape.read_text())),
            ORIGIN, out))
    assert refused.value.code == 1
    assert "availability, pricing-visible, public-label" in capsys.readouterr().err
    assert not out.exists()


def test_the_cli_builds_the_seed_with_the_website_offer(
    monkeypatch, tmp_path
):
    seen = []

    def _stop_at_build(offer=None):
        seen.append(offer)
        raise SystemExit(99)

    monkeypatch.setattr(
        site_export, "_build_public_seed_application", _stop_at_build)
    offer_path = tmp_path / "offer.json"
    offer_path.write_text(json.dumps(OFFER), encoding="utf-8")
    with pytest.raises(SystemExit) as stopped:
        site_export.main(_main_args(
            offer_path, _digest(OFFER), ORIGIN, tmp_path / "out"))
    assert stopped.value.code == 99
    assert seen == [{"display": OFFER_DEFAULT_DISPLAY, "monetary": False}]


def test_the_cli_writes_the_site_from_the_offer_it_was_given(tmp_path):
    offer_path = tmp_path / "offer.json"
    offer_path.write_text(json.dumps(OFFER), encoding="utf-8")
    out = tmp_path / "out"
    result = _cli(*_main_args(offer_path, _digest(OFFER), ORIGIN, out))
    assert result.returncode == 0, result.stderr
    summary = json.loads(result.stdout.strip().splitlines()[-1])
    assert summary["offer"] == OFFER
    assert summary["offer_sha256"] == _digest(OFFER)
    assert summary["origin"] == ORIGIN
    assert summary["routes"] == 12
    written = sorted(
        path.relative_to(out).as_posix()
        for path in out.rglob("*") if path.is_file()
    )
    assert written == WRITTEN_SITE
    pricing = (out / "dist" / "pricing" / "index.html").read_text(encoding="utf-8")
    assert OFFER_DEFAULT_DISPLAY in pricing
    wrong = _cli(*_main_args(offer_path, "0" * 64, ORIGIN, tmp_path / "wrong"))
    assert wrong.returncode != 0
    assert "sha256" in wrong.stderr
    assert not (tmp_path / "wrong").exists()
