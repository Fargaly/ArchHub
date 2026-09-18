"""Courts for the findings of the live archhub.io review (2026-09-17).

The live site had no download, a primary call that led to a closed page,
design fonts that never loaded, retired Astro addresses answering 404, an
application link to a dead page, no favicon or share image, a phone nav cut
off mid-word, and a home whose hero, trust strip and footer had drifted from
the founder design. The rework courts hold the review of that fix: the
download is the released, pinned installer the graph offers (never a moving
latest address), the hero names only hosts the operation catalogue offers,
the fonts come from this site with their licences, the phone nav scrolls
away, and a website graph that already exists is read, never rebuilt. Every
download link is bound to the artifact Cell the graph holds, so the address a
visitor follows is the one the release rule proved. The numbers on the trust
strip are counted from the host operation catalogue here as well, never
typed; that catalogue is the install source in
nodelang/clean_host_catalogue_source.py, not Cells in the website graph.
These courts never import application_server.
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import sys
from collections import Counter
from pathlib import Path
from types import MappingProxyType

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import nodelang.cell_website as cell_website  # noqa: E402
import nodelang.site_export as site_export  # noqa: E402
from nodelang.cell_accounts import BETA_OFFER  # noqa: E402
from nodelang.cell_protocols import read_relation  # noqa: E402
from nodelang.cell_ui import UIBuilder, bootstrap_ui_protocol, render_ui  # noqa: E402
from nodelang.cell_voice import lint  # noqa: E402
import nodelang.cell_website_meta as website_meta  # noqa: E402
from nodelang.cell_website_meta import (  # noqa: E402
    DRAFT,
    META_ROOT,
    RELEASED,
    changelog,
    downloads,
    offer_download,
    public_path,
    record_release,
)
from nodelang.clean_host_catalogue_source import HOST_OPERATION_RECORDS  # noqa: E402
from nodelang.domains.cloud import GRAND_MAP_CLOUD_SERVICES  # noqa: E402
from nodelang.map_import import PUBLIC_MAP_PATH  # noqa: E402
from nodelang.universal_application import (  # noqa: E402
    build_universal_application,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
ORIGIN = "https://archhub.io"
OFFER = dict(BETA_OFFER)
# The GitHub release build-20260916-2105-b914892 as its release notes and the
# asset digest publish it, pinned here, not borrowed from the code under court.
REVISION = "build-20260916-2105-b914892"
DOWNLOAD = (
    "https://github.com/Fargaly/ArchHub/releases/download/"
    "build-20260916-2105-b914892/ArchHub-Setup-0.exe"
)
DOWNLOAD_SHA256 = "756863d5e6ba3eed302fbda20daea12fdb4ab3d48380ac1a277d86d2714e2daa"
ARTIFACT = META_ROOT + ":artifact:" + REVISION
REPOSITORY = "https://github.com/Fargaly/ArchHub"
# The old Astro site (12.PRODUCTION/web/src/pages and its docs collection),
# pinned here, not borrowed from the exporter under court.
RETIRED = {
    "/docs/": "/docs/getting-started/",
    "/gallery/": "/community/",
    "/account/": "/signin/",
    "/brain/": "/security/",
}
BRAND_FILES = ("favicon.ico", "favicon.svg", "og.png")
FONT_FAMILIES = ("Instrument Serif", "Inter", "JetBrains Mono")
# Suffixes the built-in table of BusyBox 1.35.0 types (networking/httpd.c,
# suffixTable), the httpd lipanski/docker-static-website:2.1.0 compiles; any
# other suffix the site serves needs its own line in httpd.conf.
BUSYBOX_TYPED = frozenset((
    ".txt", ".h", ".c", ".cc", ".cpp", ".htm", ".html", ".jpg", ".jpeg",
    ".gif", ".png", ".svg", ".css", ".js", ".wav", ".avi", ".qt", ".mov",
    ".mpe", ".mpeg", ".mid", ".midi", ".mp3",
))


def _digest(record):
    return hashlib.sha256(json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


def _documents(store, registry):
    return {
        path: cell_website.project_universal_website_document(
            store, registry.website, path,
            application_root=registry.application_root,
            application_member_role=registry.roles["member"],
            map_registry=registry.map,
            cloud_route_protocol=registry.cloud_route_protocol,
        )
        for path in cell_website.PUBLIC_WEBSITE_ROUTES
    }


def _ensure_again(store, registry):
    return cell_website.ensure_universal_website(
        store,
        application_root=registry.application_root,
        application_member_role=registry.roles["member"],
        ui_protocol=registry.ui_protocol,
        cloud_route_protocol=registry.cloud_route_protocol,
        map_registry=registry.map,
        published_lifecycle_root=registry.website.lifecycle_root,
        read_action_root=registry.website.read_action_root,
    )


@pytest.fixture(scope="module")
def application():
    return build_universal_application(PUBLIC_MAP_PATH)


@pytest.fixture(scope="module")
def documents(application):
    return _documents(*application)


@pytest.fixture(scope="module")
def export(application):
    store, registry = application
    return site_export.build_site_export(
        store, registry, offer=OFFER, offer_sha256=_digest(OFFER), origin=ORIGIN,
    )


def _pages(export):
    pages = {route: record["html"] for route, record in export["routes"].items()}
    pages["404"] = export["assets"]["404.html"]
    return pages


def _href_roots(snapshot, protocol, root_id):
    """Every Cell a page's href attributes read, walked through the UI tree."""
    roots, pending = [], [root_id]
    while pending:
        members = read_relation(snapshot, pending.pop(), budget=10_000)
        for member in members:
            if member.role_id == protocol.role("child"):
                pending.append(member.participant_id)
            elif member.role_id == protocol.role("attribute"):
                pair = {
                    item.role_id: item.participant_id
                    for item in read_relation(
                        snapshot, member.participant_id, budget=32
                    )
                }
                name = pair[protocol.role("attribute-name")]
                if bytes(snapshot.cells[name].atom) == b"href":
                    roots.append(pair[protocol.role("attribute-value")])
    return roots


def _section(document, class_name):
    start = document.index('<section class="%s"' % class_name)
    return document[start:document.index("</section>", start)]


# 1. No way to download the app; the rework: only the released, pinned build.
def test_finding_1_every_page_links_the_released_build_the_graph_offers(
    application, documents,
):
    store, _registry = application
    snapshot = store.snapshot()
    assert not hasattr(cell_website, "DOWNLOAD_URL")
    assert [note.revision for note in changelog(snapshot)] == [REVISION]
    assert website_meta.download_offers(snapshot) == (
        website_meta.DownloadOffer(REVISION, DOWNLOAD, DOWNLOAD_SHA256, ARTIFACT),
    )
    assert cell_website.website_download(snapshot) == website_meta.download_offers(snapshot)[0]
    for path, document in documents.items():
        assert 'href="%s"' % DOWNLOAD in document, path
        assert "/latest/" not in document, path


def test_the_export_seals_the_download_it_links(export):
    assert export["download"] == {
        "revision": REVISION, "sha256": DOWNLOAD_SHA256, "url": DOWNLOAD,
    }
    for route, record in export["routes"].items():
        assert 'href="%s"' % DOWNLOAD in record["html"], route


def test_every_download_link_reads_the_artifact_cell_and_follows_its_edit():
    # A store of its own: the conftest fork would hand back the template.
    store, registry = build_universal_application(PUBLIC_MAP_PATH, CellStore())
    snapshot = store.snapshot()
    protocol = registry.ui_protocol
    for path, page_root in registry.website.page_roots.items():
        hrefs = _href_roots(snapshot, protocol, page_root)
        assert ARTIFACT in hrefs, path
        copied = [
            root for root in hrefs
            if root != ARTIFACT
            and bytes(snapshot.cells[root].atom) == DOWNLOAD.encode("ascii")
        ]
        assert copied == [], path
    moved = DOWNLOAD.replace("ArchHub-Setup-0.exe", "ArchHub-Setup-1.exe")
    artifact = store.read(ARTIFACT)
    store.commit(store.revision, replace=(Cell(
        artifact.id, artifact.link0, artifact.link1, moved.encode("ascii"),
    ),))
    for path, document in _documents(store, registry).items():
        assert 'href="%s"' % moved in document, path
        assert DOWNLOAD not in document, path
    store.commit(store.revision, replace=(Cell(
        artifact.id, artifact.link0, artifact.link1,
        b"https://github.com/Fargaly/ArchHub/releases/latest/download/"
        b"ArchHub-Setup-0.exe",
    ),))
    assert cell_website.website_external_links(store.snapshot()) == frozenset(
        {REPOSITORY}
    )
    with pytest.raises(InvalidCell):
        _documents(store, registry)


@pytest.mark.parametrize("release", (
    "draft",
    "absent",
))
def test_a_graph_without_a_released_build_links_no_download_and_is_not_exported(
    monkeypatch, release,
):
    monkeypatch.setattr(cell_website, "PUBLIC_RELEASE", None if release == "absent"
                        else MappingProxyType(dict(cell_website.PUBLIC_RELEASE,
                                                   state=DRAFT)))
    # A store of its own: the conftest fork would hand back the template.
    store, registry = build_universal_application(PUBLIC_MAP_PATH, CellStore())
    snapshot = store.snapshot()
    assert changelog(snapshot) == ()
    assert downloads(snapshot) == ()
    assert cell_website.website_download(snapshot) is None
    assert cell_website.website_external_links(snapshot) == frozenset({REPOSITORY})
    for path, document in _documents(store, registry).items():
        assert "releases/" not in document, path
        assert "Download for Windows" not in document, path
        external = {
            href for href in re.findall(r'href="([^"]*)"', document)
            if not href.startswith("/")
        }
        assert external == {REPOSITORY}, path
    with pytest.raises(site_export.SiteExportError, match="no released download"):
        site_export.build_site_export(store, registry)


def _released_store(revision="build-x"):
    store = CellStore()
    record_release(store, revision=revision, summary="A released build.")
    return store


@pytest.mark.parametrize("url", (
    "https://github.com/Fargaly/ArchHub/releases/latest/download/ArchHub-Setup-0.exe",
    "https://github.com/Fargaly/ArchHub/releases/download/build-y/ArchHub-Setup-0.exe",
    "http://github.com/Fargaly/ArchHub/releases/download/build-x/ArchHub-Setup-0.exe",
))
def test_an_address_that_can_move_or_names_another_build_is_refused(url):
    store = _released_store()
    with pytest.raises(InvalidCell, match="name revision"):
        website_meta.hold_artifact(store, revision="build-x", url=url, sha256="a" * 64)


def test_an_artifact_is_held_with_its_sha256_and_offered_only_when_released():
    store = _released_store()
    url = "https://example.org/releases/download/build-x/setup.exe"
    with pytest.raises(InvalidCell, match="sha256"):
        website_meta.hold_artifact(store, revision="build-x", url=url, sha256="not-a-digest")
    artifact = website_meta.hold_artifact(store, revision="build-x", url=url, sha256="B" * 64)
    offer_download(store, artifact_root=artifact, revision="build-x")
    assert website_meta.download_offers(store.snapshot()) == (
        website_meta.DownloadOffer("build-x", url, "b" * 64, artifact),
    )
    record_release(store, revision="build-z", summary="A draft.", state=DRAFT)
    draft = website_meta.hold_artifact(
        store, revision="build-z",
        url="https://example.org/releases/download/build-z/setup.exe",
        sha256="c" * 64,
    )
    with pytest.raises(InvalidCell, match="not released"):
        offer_download(store, artifact_root=draft, revision="build-z")
    assert [offer.revision for offer in website_meta.download_offers(store.snapshot())] == [
        "build-x"
    ]


def test_an_offered_artifact_whose_address_was_swapped_is_refused_on_read():
    store = _released_store()
    url = "https://example.org/releases/download/build-x/setup.exe"
    artifact = website_meta.hold_artifact(store, revision="build-x", url=url, sha256="d" * 64)
    offer_download(store, artifact_root=artifact, revision="build-x")
    store.commit(store.revision, replace=(Cell(
        artifact, NULL_CELL_ID, NULL_CELL_ID,
        b"https://example.org/releases/latest/download/setup.exe",
    ),))
    with pytest.raises(InvalidCell, match="name revision"):
        website_meta.download_offers(store.snapshot())


# An existing graph: its persisted website is read, never rebuilt or changed.
def test_an_existing_website_graph_is_read_not_rebuilt(monkeypatch, application):
    with monkeypatch.context() as scoped:
        scoped.setattr(cell_website, "PUBLIC_RELEASE", None)
        persisted, registry = build_universal_application(
            PUBLIC_MAP_PATH, CellStore()
        )
    assert cell_website.PUBLIC_RELEASE["state"] == RELEASED
    revision = persisted.revision
    rebuilt = _ensure_again(persisted, registry)
    assert persisted.revision == revision
    assert rebuilt.page_roots == registry.website.page_roots
    snapshot = persisted.snapshot()
    assert "%s:release:%s" % (META_ROOT, REVISION) not in snapshot.cells
    assert downloads(snapshot) == ()
    for path, document in _documents(persisted, registry).items():
        assert "releases/" not in document, path
    with pytest.raises(site_export.SiteExportError, match="no released download"):
        site_export.build_site_export(persisted, registry)

    # The offer shape cell_website_meta admitted before artifacts were pinned:
    # any held Cell, here one that names no address. The write rule is now the
    # read rule, so the offer is refused and never stored; the pages link no
    # download and the export refuses a site with no released download.
    persisted.commit(persisted.revision, create=(Cell(
        "artifact:installer", NULL_CELL_ID, NULL_CELL_ID, b"installer",
    ),))
    record_release(
        persisted, revision="r2", summary="The canvas opens on the work.",
    )
    with pytest.raises(InvalidCell, match="artifact held for revision"):
        offer_download(
            persisted, artifact_root="artifact:installer", revision="r2",
        )
    assert downloads(persisted.snapshot()) == ()
    assert cell_website.website_download(persisted.snapshot()) is None
    assert cell_website.website_external_links(persisted.snapshot()) == frozenset(
        {REPOSITORY}
    )
    revision = persisted.revision
    _ensure_again(persisted, registry)
    assert persisted.revision == revision
    assert set(_documents(persisted, registry)) == set(
        cell_website.PUBLIC_WEBSITE_ROUTES
    )
    with pytest.raises(site_export.SiteExportError, match="no released download"):
        site_export.build_site_export(persisted, registry)

    store, current = application
    revision = store.revision
    _ensure_again(store, current)
    assert store.revision == revision
    assert website_meta.download_offers(store.snapshot())[0].url == DOWNLOAD


# 2. The main button led to a closed sign-in page.
def test_finding_2_the_primary_call_is_the_download_and_sign_in_is_secondary(
    documents,
):
    home = documents["/website"]
    primaries = re.findall(
        r'<a class="site-primary" href="([^"]*)">([^<]*)</a>', home
    )
    assert primaries
    assert all(href == DOWNLOAD for href, _ in primaries)
    assert (DOWNLOAD, "Download for Windows") in primaries
    hero = _section(home, "site-hero")
    assert '<a class="site-secondary" href="/website/signin">Sign in</a>' in hero
    assert "Create your account" not in home
    for document in documents.values():
        assert '<a class="site-primary" href="/website/signin"' not in document


# The hero lede named Rhino and Speckle, which the catalogue does not offer.
def test_the_hero_lede_names_only_hosts_the_operation_catalogue_offers(documents):
    counts = Counter(str(record["host"]) for record in HOST_OPERATION_RECORDS)
    offered = [
        cell_website.HOST_LABELS[host]
        for host, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    hero = _section(documents["/website"], "site-hero")
    lede = re.search(r'<p class="site-lede">([^<]*)</p>', hero).group(1)
    named = re.match(
        r"One canvas wires the tools you already use: ([^.]*)\. ", lede
    ).group(1).split(", ")
    assert named == offered
    for host, label in cell_website.HOST_LABELS.items():
        if host not in counts:
            assert not re.search(r"\b%s\b" % re.escape(label), hero), label


# 3. The design fonts never loaded; the rework: from this site, with licences.
def test_finding_3_every_page_loads_the_fonts_from_this_site(export):
    stylesheet = export["assets"]["assets/site.css"]
    families = re.findall(r'--(?:serif|sans|mono):"([^"]+)"', stylesheet)
    assert sorted(families) == sorted(FONT_FAMILIES)
    for token in ("url(", "@import"):
        assert token not in stylesheet
    sealed = json.dumps(export, sort_keys=True)
    for host in ("fonts.googleapis.com", "fonts.gstatic.com"):
        assert host not in sealed
    for name, page in _pages(export).items():
        fonts = page.index('<link rel="stylesheet" href="/assets/fonts.css">')
        assert fonts < page.index(
            '<link rel="stylesheet" href="/assets/site.css">'
        ), name
        # Founder decision 2026-09-17: the one script is the pinned site script.
        assert re.findall(r"<script\b[^>]*>", page) == [
            '<script src="/assets/site.js" defer>'
        ], name
        assert not re.search(
            r'<link rel="(?:stylesheet|preconnect|preload|icon)"[^>]*href="https?://',
            page,
        ), name
    faces = re.findall(
        r'@font-face\{font-family:"([^"]+)";font-style:(normal|italic);'
        r'font-weight:([0-9 ]+);font-display:swap;'
        r'src:url\(/assets/fonts/([a-z0-9-]+\.woff2)\) format\("woff2"\)\}',
        export["assets"]["assets/fonts.css"],
    )
    assert len(faces) == export["assets"]["assets/fonts.css"].count("@font-face")
    assert {family for family, *_ in faces} == set(FONT_FAMILIES)
    assert ("Instrument Serif", "italic", "400") in {face[:3] for face in faces}
    used = {int(weight) for weight in re.findall(r"font-weight:([0-9]+)", stylesheet)}
    inter = [face for face in faces if face[0] == "Inter"]
    assert len(inter) == 1
    low, high = (int(value) for value in inter[0][2].split())
    assert used and low <= min(used) and max(used) <= high
    for family, _style, _weight, name in faces:
        record = export["files"]["assets/fonts/" + name]
        data = (REPO / "nodelang" / "data" / "website" / "fonts" / name).read_bytes()
        assert data[:4] == b"wOF2", name
        assert record == {
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        }
        licence = export["files"][
            "assets/fonts/OFL-%s.txt" % family.replace(" ", "")
        ]
        text = (
            REPO / "nodelang" / "data" / "website" / "fonts"
            / ("OFL-%s.txt" % family.replace(" ", ""))
        ).read_text(encoding="ascii")
        assert licence["sha256"] == hashlib.sha256(text.encode("ascii")).hexdigest()
        assert text.startswith("Copyright ")
        assert "The %s Project Authors" % family in text.splitlines()[0]
        assert "SIL OPEN FONT LICENSE Version 1.1 - 26 February 2007" in text


def test_finding_3_the_written_site_carries_the_font_files_and_licences(
    application, tmp_path,
):
    store, registry = application
    project = tmp_path / "site"
    payload = site_export.write_public_site(
        store, registry, project,
        offer=OFFER, offer_sha256=_digest(OFFER), origin=ORIGIN,
    )
    assert (project / "dist/assets/fonts.css").read_text(encoding="utf-8") == (
        payload["assets"]["assets/fonts.css"]
    )
    fonts = REPO / "nodelang" / "data" / "website" / "fonts"
    for name in payload["files"]:
        if name.startswith("assets/fonts/"):
            assert (project / "dist" / name).read_bytes() == (
                fonts / name[len("assets/fonts/"):]
            ).read_bytes(), name


# 4. The old Astro addresses answered 404.
def test_finding_4_every_retired_address_is_a_redirect_to_a_live_page(
    export, tmp_path, application,
):
    live = {public_path(route) for route in cell_website.PUBLIC_WEBSITE_ROUTES}
    assert set(RETIRED.values()) <= live
    for old, new in RETIRED.items():
        page = export["assets"][old.strip("/") + "/index.html"]
        assert '<meta http-equiv="refresh" content="0; url=%s">' % new in page
        assert '<link rel="canonical" href="%s%s">' % (ORIGIN, new) in page
        assert '<meta name="robots" content="noindex">' in page
        assert 'href="%s"' % new in page
    store, registry = application
    project = tmp_path / "site"
    site_export.write_public_site(
        store, registry, project,
        offer=OFFER, offer_sha256=_digest(OFFER), origin=ORIGIN,
    )
    for old in RETIRED:
        assert (project / "dist" / old.strip("/") / "index.html").is_file(), old
    unaddressed = site_export.build_site_export(store, registry)
    assert not any(
        key.startswith(("docs/", "gallery/", "account/", "brain/"))
        for key in unaddressed["assets"]
    )


# 5. The application linked to https://archhub.io/brain, a dead page.
def test_finding_5_the_brain_portal_link_is_the_live_security_page(documents):
    portal = next(
        service for service in GRAND_MAP_CLOUD_SERVICES
        if service["id"] == "cloud_brain_portal"
    )
    assert portal["endpoint"]["address"] == (
        ORIGIN + public_path("/website/security")
    )
    assert cell_website.PRIVACY_SENTENCE in documents["/website/security"]


# 6. No favicon and no share image.
def test_finding_6_every_page_links_the_favicon_and_the_share_image(
    export, application, tmp_path,
):
    for name, page in _pages(export).items():
        assert '<link rel="icon" href="/favicon.ico" sizes="any">' in page, name
        assert (
            '<link rel="icon" href="/favicon.svg" type="image/svg+xml">' in page
        ), name
    for route, record in export["routes"].items():
        assert (
            '<meta property="og:image" content="%s/og.png">' % ORIGIN
        ) in record["html"], route
    brand = REPO / "nodelang" / "data" / "website"
    assert set(BRAND_FILES) <= set(export["files"])
    for name in BRAND_FILES:
        data = (brand / name).read_bytes()
        assert export["files"][name] == {
            "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        }
    assert (brand / "favicon.ico").read_bytes() == (
        REPO / "archhub.ico"
    ).read_bytes()
    og = (brand / "og.png").read_bytes()
    assert og[:8] == b"\x89PNG\r\n\x1a\n"
    assert struct.unpack(">II", og[16:24]) == (1200, 630)
    svg = (brand / "favicon.svg").read_text(encoding="ascii")
    assert svg.startswith("<svg") and "<script" not in svg
    store, registry = application
    project = tmp_path / "site"
    site_export.write_public_site(
        store, registry, project,
        offer=OFFER, offer_sha256=_digest(OFFER), origin=ORIGIN,
    )
    for name in BRAND_FILES:
        assert (project / "dist" / name).read_bytes() == (
            brand / name
        ).read_bytes()


def test_finding_6_a_brand_file_that_changed_after_export_is_refused(
    application, tmp_path, monkeypatch,
):
    store, registry = application
    payload = site_export.build_site_export(store, registry)
    forged = dict(payload, files=dict(payload["files"]))
    forged["files"]["og.png"] = dict(forged["files"]["og.png"], sha256="0" * 64)
    monkeypatch.setattr(
        site_export, "build_site_export", lambda *args, **kwargs: forged
    )
    with pytest.raises(site_export.SiteExportError, match="og.png"):
        site_export.write_public_site(store, registry, tmp_path / "site")


def test_every_suffix_the_site_serves_has_a_content_type(tmp_path, application):
    store, registry = application
    project = tmp_path / "site"
    site_export.write_public_site(
        store, registry, project,
        offer=OFFER, offer_sha256=_digest(OFFER), origin=ORIGIN,
    )
    suffixes = {
        path.suffix for path in (project / "dist").rglob("*") if path.is_file()
    }
    conf = (REPO / "packaging" / "website" / "httpd.conf").read_text(encoding="utf-8")
    typed = {
        line.split(":", 1)[0] for line in conf.splitlines()
        if re.fullmatch(r"\.[a-z0-9]+:[a-z]+/[a-z0-9.+-]+", line.strip())
    }
    assert suffixes - BUSYBOX_TYPED - typed == set()
    assert ".ico:image/x-icon" in conf.splitlines()


# 7. The phone nav cut off mid-word at 375 px, then stayed pinned over a fifth
# of the screen.
def test_finding_7_the_phone_nav_wraps_and_scrolls_away(documents):
    css = cell_website.WEBSITE_CSS
    phone = css[css.index("@media(max-width:760px){"):]
    nav = re.search(r"\{\.site-nav\{([^}]*)\}", phone).group(1)
    assert "position:static" in nav
    links = re.search(r"\.site-nav-links\{([^}]*)\}", phone).group(1)
    assert "flex-wrap:wrap" in links
    assert "overflow" not in links
    assert "width:100%" in links
    for path, document in documents.items():
        assert (
            '<a class="site-access site-access-primary" href="/website/signin">'
            "Create account</a>"
        ) in document, path


# 8. Home parity: node canvas hero, trust strip, GitHub in the footer.
def test_finding_8_the_hero_is_the_node_canvas_not_the_grand_map_grid(documents):
    home = documents["/website"]
    hero = _section(home, "site-hero")
    assert 'class="site-canvas"' in hero
    assert "site-domain-grid" not in hero
    assert hero.count('<li class="site-node') >= 3
    labels = {str(record["label"]) for record in HOST_OPERATION_RECORDS}
    ports = re.findall(r'<span class="site-node-port"[^>]*>([^<]*)<', hero)
    host_ports = ports[:2]
    assert len(host_ports) == 2
    assert set(host_ports) <= labels
    # Finding 8 moved the map out of the hero. The founder read the live
    # site against the design on 2026-09-17 and took the grid off the
    # public home altogether, so it is nowhere on the page now.
    assert "site-domain-grid" not in home


def test_finding_8_the_trust_strip_counts_the_host_operation_catalogue(documents):
    home = documents["/website"]
    hosts = Counter(str(record["host"]) for record in HOST_OPERATION_RECORDS)
    trust = _section(home, "site-trust")
    figures = re.findall(r'<span class="site-trust-n">([0-9]+)</span>', trust)
    assert figures == [str(len(hosts)), str(len(HOST_OPERATION_RECORDS))]
    chips = re.findall(
        r'<li class="site-host"[^>]*>([^<]+)'
        r'<span class="site-host-ops">([0-9]+)</span></li>',
        trust,
    )
    assert len(chips) == len(hosts)
    assert {label: int(count) for label, count in chips} == {
        cell_website.HOST_LABELS[host]: count for host, count in hosts.items()
    }
    counts = [int(count) for _, count in chips]
    assert counts == sorted(counts, reverse=True)


def test_finding_8_every_catalogue_host_has_a_declared_label():
    hosts = {str(record["host"]) for record in HOST_OPERATION_RECORDS}
    assert hosts <= set(cell_website.HOST_LABELS)


def test_finding_8_every_footer_links_github_and_no_dead_docs(documents):
    for path, document in documents.items():
        footer = document[document.index('<footer class="site-footer">'):]
        assert (
            '<a class="site-foot-link" href="%s">GitHub</a>' % REPOSITORY
        ) in footer, path
        assert (
            '<a class="site-foot-link" href="%s">Download for Windows</a>'
            % DOWNLOAD
        ) in footer, path
        assert (
            '<a class="site-foot-link" href="/website/docs/getting-started">Docs</a>'
        ) in footer, path


def test_every_external_link_the_website_emits_is_read_from_the_graph(
    application, documents,
):
    store, _registry = application
    links = cell_website.website_external_links(store.snapshot())
    assert links == frozenset({DOWNLOAD, REPOSITORY})
    for path, document in documents.items():
        external = {
            href for href in re.findall(r'href="([^"]*)"', document)
            if not href.startswith("/")
        }
        assert external == links, path


def test_the_renderer_admits_only_the_exact_external_links_it_is_given():
    store = CellStore()
    protocol = bootstrap_ui_protocol(store)
    ui = UIBuilder(store, protocol)
    allowed = ui.element("a", text="GitHub", attributes={"href": REPOSITORY})
    other = ui.element("a", attributes={"href": REPOSITORY + "/issues"})
    ui.commit()
    links = frozenset({REPOSITORY})
    snapshot = store.snapshot()
    assert render_ui(snapshot, protocol, allowed, external_links=links) == (
        '<a href="%s">GitHub</a>' % REPOSITORY
    )
    with pytest.raises(InvalidCell, match="local absolute"):
        render_ui(snapshot, protocol, allowed)
    with pytest.raises(InvalidCell, match="local absolute"):
        render_ui(snapshot, protocol, other, external_links=links)
    with pytest.raises(InvalidCell, match="https"):
        render_ui(
            snapshot, protocol, allowed,
            external_links=frozenset({"http://github.com/Fargaly/ArchHub"}),
        )


def test_a_bound_attribute_renders_the_cell_it_names_and_is_never_also_copied():
    store = CellStore()
    protocol = bootstrap_ui_protocol(store)
    store.commit(store.revision, create=(Cell(
        "link:repository", NULL_CELL_ID, NULL_CELL_ID, REPOSITORY.encode("ascii"),
    ),))
    ui = UIBuilder(store, protocol)
    with pytest.raises(InvalidCell, match="copy and bind"):
        ui.element(
            "a", attributes={"href": "/website"},
            attribute_roots={"href": "link:repository"},
        )
    bound = ui.element(
        "a", text="GitHub", attribute_roots={"href": "link:repository"},
    )
    ui.commit()
    snapshot = store.snapshot()
    assert render_ui(
        snapshot, protocol, bound, external_links=frozenset({REPOSITORY}),
    ) == '<a href="%s">GitHub</a>' % REPOSITORY
    assert _href_roots(snapshot, protocol, bound) == ["link:repository"]


# The page copy of /features /changelog /security /community /signin.
# Each page title and its card titles, as the website lane wrote the copy on
# 2026-09-17, every card citing the source that does what it says.
SUBPAGE_COPY = {
    # /features and /security open with the design sections; they hold no cards.
    "/website/features": ("One canvas. Every tool you already use.", ()),
    "/website/changelog": ("Released builds, not intentions", (
        "Released or absent", "The app checks for you",
        "Where the installer lives",
    )),
    "/website/security": ("Nothing runs without a reason you can see", ()),
    "/website/community": ("Share with your firm, on your terms", (
        "Groups with single-use codes", "Nothing lands unreviewed",
        "No public network yet",
    )),
    "/website/signin": ("Sign in from the desktop app", (
        "Email link or Google", "An account, not a device",
        "No password on this site",
    )),
}


def test_every_subpage_says_what_the_code_does_in_voice(documents):
    specs = cell_website._page_specs()
    for path, (pinned_title, card_titles) in SUBPAGE_COPY.items():
        title, lede, cards = specs[path]
        assert title == pinned_title, path
        assert tuple(card[1] for card in cards) == card_titles, path
        for card_title in card_titles:
            assert '<h2 class="site-card-title">%s</h2>' % card_title in (
                documents[path]
            ), (path, card_title)
        for text in (title, lede, *(part for card in cards for part in card)):
            assert lint(text) == (), (path, text)
            assert text.isascii(), (path, text)
        assert "<h1 class=\"site-page-title\">%s</h1>" % title in documents[path]
        for kicker, *texts in cards:
            for text in (title, lede, *texts):
                assert not re.search(r"[0-9]", text), (path, text)
                for word in (r"\bMIT\b", r"\bnever leaves\b", r"\bmagic\b",
                             r"\bprice"):
                    assert not re.search(word, text), (path, word)
    assert cell_website.PRIVACY_SENTENCE in documents["/website/security"]
    pricing = cell_website._page_specs()["/website/pricing"]
    assert pricing[0] == cell_website.OFFER_DEFAULT_DISPLAY


# The two findings of the website-live-r2 review.
def test_offer_download_refuses_an_artifact_download_offers_would_refuse():
    store = _released_store()
    url = "https://example.org/releases/download/build-x/setup.exe"
    stray = website_meta.META_ROOT + ":stray-artifact"
    store.commit(store.snapshot().revision, create=(website_meta._terminal(stray, url),))
    with pytest.raises(InvalidCell, match="artifact held for revision"):
        offer_download(store, artifact_root=stray, revision="build-x")
    assert website_meta.download_offers(store.snapshot()) == ()


def test_a_broken_offer_refuses_its_pages_but_never_the_website_read():
    # A store of its own: the conftest fork would hand back the template.
    store, registry = build_universal_application(PUBLIC_MAP_PATH, CellStore())
    artifact = store.read(ARTIFACT)
    store.commit(store.revision, replace=(Cell(
        artifact.id, artifact.link0, artifact.link1,
        b"https://github.com/Fargaly/ArchHub/releases/latest/download/"
        b"ArchHub-Setup-0.exe",
    ),))
    snapshot = store.snapshot()
    assert cell_website.website_download(snapshot) is None
    website = registry.website
    verified = cell_website.read_universal_website(
        snapshot, website.protocol, website.root_id,
        ui_protocol=registry.ui_protocol,
        application_root=registry.application_root,
        application_member_role=registry.roles["member"],
        map_registry=registry.map,
        cloud_route_protocol=registry.cloud_route_protocol,
        published_lifecycle_root=website.lifecycle_root,
        read_action_root=website.read_action_root,
    )
    assert set(verified.route_roots) == set(cell_website.PUBLIC_WEBSITE_ROUTES)
    with pytest.raises(InvalidCell):
        _documents(store, registry)


def test_finding_2_the_changelog_page_lists_the_released_build(documents):
    page = documents["/website/changelog"]
    assert REVISION in page
    assert cell_website.PUBLIC_RELEASE["summary"] in page