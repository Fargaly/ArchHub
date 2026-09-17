"""Deterministic T0 export of the universal website Cell lens.

The exporter is a read-only release boundary over the same website, route,
CloudRoute, UI, and stylesheet Cells served by the application.  It refuses
unsafe graph state; it does not sanitize a second website implementation into
looking public.

The application keeps serving the site under /website.  Root paths exist only
in the export output.  The --offer file is the canonical offer record of
app:users:accounts:offer as nodelang/cell_accounts.py publishes it (each
field passing cell_accounts._offer_value unchanged): a JSON object
{"availability", "pricing-visible", "public-label"}.  The exporter
recomputes the sha256 of its canonical bytes the way
cell_accounts.published_offer does, refuses unless it equals --offer-sha256,
and maps the record to the website offer {"display": public-label,
"monetary": pricing-visible == "true"} for cell_website.offer_display_text.
404.html and the redirect pages for retired addresses are the only pages typed
here, not projected from the graph.

Every written page loads the fonts the graph stylesheet names from this site,
through assets/fonts.css in its head (the stylesheet may not fetch anything
itself), and links the brand icons; no page asks another host for a font. The
brand files, the font files and their licences are copied byte for byte from
nodelang/data/website; the payload records their size and sha256, never their
bytes. The export is refused unless the graph offers a released download and
every page links it.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
from pathlib import Path

from .cell_accounts import OFFER_FIELDS, _offer_value
from .cell_protocols import read_relation
from .cell_website import (
    PUBLIC_WEBSITE_ROUTES,
    offer_display_text,
    project_universal_website_document,
    read_universal_website,
    website_download,
)
from .cell_website_meta import META_ROOT, ORIGIN_ROOT, page_texts, public_path
from .universal_cell import NULL_CELL_ID, InvalidCell


PUBLIC_ROUTES = PUBLIC_WEBSITE_ROUTES
PUBLICATION_TIER = "T0 PUBLIC"
EXPORT_FORMAT = "archhub-universal-cell-site-v2"


class SiteExportError(ValueError):
    """The graph cannot be projected into a safe public artifact."""


_PRIVATE_PATTERNS = (
    (re.compile(r"(?i)[a-z]:[\\/]+users[\\/]"), "local user path"),
    (re.compile(r"(?i)file://"), "local file URL"),
    (re.compile(
        r"(?i)(?:00\.governance|20\.clients|30\.knowledge|40\.media|"
        r"50\.tooling|60\.personal|70\.handoffs|90\.archive)"
    ), "non-public workspace area"),
    (re.compile(r"(?i)12\.production"), "legacy application path"),
    (re.compile(r"(?i)op://"), "secret capability reference"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key"),
    (re.compile(r"(?i)ARCHHUB_GRAND_MAP_PATH|authority\.json|node-native-wip"),
     "private runtime authority"),
)

_ORIGIN = re.compile(
    r"(?i)https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?"
    r"(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+(?::[0-9]{1,5})?"
)
_WEBSITE_HREF = re.compile(r'href="/website(?:/[A-Za-z0-9-]+)*"')
_LEDE = re.compile(r'<p class="site-(?:page-)?lede">(.*?)</p>', re.DOTALL)
_TAG = re.compile(r"<[^>]+>")

# The one script the site serves: the design's interactions (hero canvas drag
# and wire, host picker, self-heal timeline), a static file admitted by this
# exact sha256. The graph document stays scriptless; the export adds only this
# tag, and a page with any other script, or a script file with any other
# bytes, is refused.
SITE_SCRIPT = "assets/site.js"
SITE_SCRIPT_SOURCE = "site.js"
SITE_SCRIPT_SHA256 = (
    "4e7a942421c969557a068fe537491b77eae7315c3890588f8c4de8596605840a"
)
SITE_SCRIPT_TAG = '<script src="/assets/site.js" defer></script>'

HEAD_LINKS = (
    '<link rel="stylesheet" href="/assets/fonts.css">'
    '<link rel="stylesheet" href="/assets/site.css">'
    '<link rel="icon" href="/favicon.ico" sizes="any">'
    '<link rel="icon" href="/favicon.svg" type="image/svg+xml">'
    + SITE_SCRIPT_TAG
)

BRAND_DIR = Path(__file__).resolve().parent / "data" / "website"
BRAND_FILES = ("favicon.ico", "favicon.svg", "og.png")
SHARE_IMAGE = "og.png"

# The three families the graph stylesheet names, served from this site. Each
# woff2 is the Latin subset of an SIL Open Font License 1.1 font (Instrument
# Serif 1.000, Inter 4.001 held at opsz 14 over weights 400 to 600, JetBrains
# Mono 2.211); its licence file travels beside it.
FONT_DIR = "fonts"
FONT_FACES = (
    ("instrument-serif-regular.woff2", "Instrument Serif", "normal", "400"),
    ("instrument-serif-italic.woff2", "Instrument Serif", "italic", "400"),
    ("inter-variable.woff2", "Inter", "normal", "400 600"),
    ("jetbrains-mono-regular.woff2", "JetBrains Mono", "normal", "400"),
)
FONT_LICENCES = (
    "OFL-InstrumentSerif.txt", "OFL-Inter.txt", "OFL-JetBrainsMono.txt",
)
FONTS_CSS = "".join(
    '@font-face{font-family:"%s";font-style:%s;font-weight:%s;'
    'font-display:swap;src:url(/assets/fonts/%s) format("woff2")}\n'
    % (family, style, weight, name)
    for name, family, style, weight in FONT_FACES
)
# Every file the export copies, by its path under dist/ and its source under
# nodelang/data/website.
PUBLIC_FILES = (
    *((name, name) for name in BRAND_FILES),
    (SITE_SCRIPT, SITE_SCRIPT_SOURCE),
    *(
        ("assets/fonts/" + name, FONT_DIR + "/" + name)
        for name in (
            *(face[0] for face in FONT_FACES), *FONT_LICENCES,
        )
    ),
)
_PUBLIC_FILE_SOURCES = dict(PUBLIC_FILES)

# The addresses the retired Astro site answered at, each sent to the live page
# closest to what it held: the docs index to the first docs page (the five
# docs guides are live pages again, at the addresses they had), the brain
# portal to the security page that explains what cloud sync holds, the account
# page to sign-in, and the gallery to the community page.
RETIRED_ADDRESSES = (
    ("/docs/", "/website/docs/getting-started"),
    ("/gallery/", "/website/community"),
    ("/account/", "/website/signin"),
    ("/brain/", "/website/security"),
)
_RETIRED_PATH = re.compile(r"(?:/[a-z0-9-]+)+/")

NOT_FOUND_HTML = (
    '<!doctype html><html lang="en"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width,initial-scale=1">'
    '<meta name="color-scheme" content="light">'
    '<title>Not found | ArchHub</title>'
    + HEAD_LINKS + '</head><body>'
    '<main class="site-page-main"><h1 class="site-page-title">Not found</h1>'
    '<p class="site-page-lede">There is no page at this address.</p>'
    '<p><a class="site-nav-link" href="/">Return to ArchHub</a></p>'
    '</main></body></html>'
)


def _canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True).encode("utf-8")


def _digest_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def offer_digest(record):
    """The sha256 of the canonical offer record.

    The same bytes cell_accounts.published_offer digests: json.dumps of the
    record with sorted keys, compact separators and ASCII escapes.
    """
    return hashlib.sha256(json.dumps(
        record, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


def _offer_record(offer):
    """The canonical offer record, in field order, or a refusal."""
    if not isinstance(offer, dict):
        raise SiteExportError("offer record must be a JSON object")
    if sorted(offer) != sorted(OFFER_FIELDS):
        raise SiteExportError(
            "offer record needs exactly: " + ", ".join(OFFER_FIELDS))
    if any(not isinstance(value, str) for value in offer.values()):
        raise SiteExportError("offer record fields must be strings")
    # Every field must pass the rule cell_accounts applies when it declares
    # the record, unchanged: a record cell_accounts would refuse ("True",
    # "yes", a shouted slug, an 81-character label) must not reach the site.
    record = {}
    for field in OFFER_FIELDS:
        try:
            value = _offer_value(field, offer[field])
        except InvalidCell as exc:
            raise SiteExportError("offer record refused: %s" % exc) from exc
        if value != offer[field]:
            raise SiteExportError(
                "offer record field %r is not in the form cell_accounts stores"
                % field
            )
        record[field] = value
    return record


def website_offer(record):
    """The offer as cell_website.offer_display_text reads it."""
    record = _offer_record(record)
    return {
        "display": record["public-label"],
        "monetary": record["pricing-visible"] == "true",
    }


def offer_record_from_published(published):
    """The canonical record behind what cell_accounts.published_offer returns.

    Refused when the sha256 it carries is not the digest of that record.
    """
    try:
        visible = published["pricing_visible"]
        record = {
            "availability": str(published["availability"]),
            "pricing-visible": "true" if visible is True else "false",
            "public-label": str(published["public_label"]),
        }
        declared = str(published["sha256"]).strip().lower()
    except (KeyError, TypeError) as exc:
        raise SiteExportError(
            "published offer must carry availability, pricing_visible, "
            "public_label and sha256") from exc
    if not isinstance(visible, bool):
        raise SiteExportError("published offer pricing_visible must be a bool")
    if offer_digest(record) != declared:
        raise SiteExportError(
            "published offer sha256 does not match its record")
    return record


def _verified_offer(offer, offer_sha256):
    """The offer record, or None, after its digest and display are proven."""
    if offer is None:
        if offer_sha256 is not None:
            raise SiteExportError("offer_sha256 was given without an offer record")
        return None
    record = _offer_record(offer)
    if offer_sha256 is None:
        raise SiteExportError("an offer record needs its offer_sha256")
    expected = offer_digest(record)
    if str(offer_sha256).strip().lower() != expected:
        raise SiteExportError(
            "offer sha256 mismatch: the offer record is not the one declared"
        )
    try:
        display = offer_display_text(website_offer(record))
    except InvalidCell as exc:
        raise SiteExportError("offer record refused: %s" % exc) from exc
    return {"record": record, "display": display, "sha256": expected}


def _public_origin(origin):
    if origin is None:
        return None
    origin = str(origin).strip().rstrip("/")
    if not _ORIGIN.fullmatch(origin):
        raise SiteExportError("a public origin must be an https host, got %r" % origin)
    return origin


def _graph_origin(snapshot):
    cell = snapshot.cells.get(ORIGIN_ROOT)
    return None if cell is None else bytes(cell.atom).decode("utf-8")


def _scan_public_text(value, label):
    for pattern, description in _PRIVATE_PATTERNS:
        match = pattern.search(value)
        if match:
            raise SiteExportError(
                "%s contains %s: %s" % (label, description, match.group(0)))


def _static_document(document):
    style_matches = tuple(re.finditer(
        r"<style>(.*?)</style>", document, flags=re.DOTALL
    ))
    if len(style_matches) != 1:
        raise SiteExportError(
            "projected website document must have exactly one graph stylesheet"
        )
    if re.search(r"<script\b", document, flags=re.IGNORECASE):
        raise SiteExportError("projected website document contains a script")
    for attribute in (
        "data-action", "data-edit", "data-edit-port", "data-download",
        "data-navigate",
    ):
        if re.search(r"\s%s=\"" % re.escape(attribute), document):
            raise SiteExportError(
                "projected website document contains mutation/runtime hooks"
            )
    style_match = style_matches[0]
    stylesheet = style_match.group(1)
    html = document[:style_match.start()] + HEAD_LINKS + document[style_match.end():]
    return html, stylesheet


def admitted_scripts(document, label="page"):
    """Refuse a page unless its only script is the pinned site script tag."""
    found = re.findall(r"<script\b[^>]*>", document, flags=re.IGNORECASE)
    if found != [SITE_SCRIPT_TAG[:-len("</script>")]]:
        raise SiteExportError(
            "%s must carry exactly the pinned site script, found %d script tags"
            % (label, len(found)))
    if document.count(SITE_SCRIPT_TAG) != 1:
        raise SiteExportError("%s site script tag is not the pinned one" % label)
    return document


def site_script_bytes(data):
    """The site script, refused unless its bytes hash to the pinned sha256."""
    digest = hashlib.sha256(data).hexdigest()
    if digest != SITE_SCRIPT_SHA256:
        raise SiteExportError(
            "site script sha256 %s is not the pinned %s" % (digest, SITE_SCRIPT_SHA256))
    return data


def _root_hrefs(static_html):
    """In-app /website links become the root paths the static site serves."""
    return _WEBSITE_HREF.sub(
        lambda match: 'href="%s"' % public_path(match.group(0)[6:-1]),
        static_html,
    )


def _output_path(root_path):
    return (root_path.strip("/") + "/index.html").lstrip("/")


def _page_identity(snapshot, verified, route, static_html):
    """Title and description: the page meta held by the graph when it
    describes the page, otherwise the route title Cell and the rendered lede."""
    try:
        if "%s:page:%s" % (META_ROOT, route) in snapshot.cells:
            return page_texts(snapshot, route)
        title = _terminal_text(
            snapshot, verified.route_title_roots[route], "route title"
        )
    except InvalidCell as exc:
        raise SiteExportError(
            "page identity for %s is unusable: %s" % (route, exc)) from exc
    lede = _LEDE.search(static_html)
    return (
        title,
        html.unescape(_TAG.sub("", lede.group(1))).strip() if lede else "",
    )


def _with_head_meta(static_html, origin, root_path, title, description):
    if "</head>" not in static_html:
        raise SiteExportError("projected website document has no head")
    url = html.escape(origin + root_path, quote=True)
    tags = [
        '<link rel="canonical" href="%s">' % url,
        '<meta property="og:title" content="%s">' % html.escape(title, quote=True),
    ]
    if description:
        tags.append('<meta property="og:description" content="%s">'
                    % html.escape(description, quote=True))
    tags.append('<meta property="og:url" content="%s">' % url)
    tags.append('<meta property="og:image" content="%s">'
                % html.escape(origin + "/" + SHARE_IMAGE, quote=True))
    tags.append('<meta name="twitter:card" content="summary_large_image">')
    return static_html.replace("</head>", "".join(tags) + "</head>", 1)


def _redirect_html(origin, route):
    """A retired address answers with the live page it moved to."""
    target = public_path(route)
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        '<meta name="robots" content="noindex">'
        '<meta http-equiv="refresh" content="0; url=%s">'
        '<title>Moved | ArchHub</title>'
        '<link rel="canonical" href="%s">%s</head><body>'
        '<main class="site-page-main">'
        '<h1 class="site-page-title">This page has moved</h1>'
        '<p class="site-page-lede">It is now at '
        '<a class="site-nav-link" href="%s">%s</a>.</p>'
        '</main></body></html>'
    ) % (
        html.escape(target, quote=True),
        html.escape(origin + target, quote=True),
        HEAD_LINKS,
        html.escape(target, quote=True),
        html.escape(origin.split("://", 1)[1] + target),
    )


def _retired_pages(origin):
    """One redirect page per retired address, at the path it used to answer."""
    live = {public_path(route) for route in PUBLIC_ROUTES}
    pages = {}
    for old_path, route in RETIRED_ADDRESSES:
        if route not in PUBLIC_ROUTES:
            raise SiteExportError(
                "retired address %s points at no public route" % old_path)
        if old_path in live or not _RETIRED_PATH.fullmatch(old_path):
            raise SiteExportError(
                "retired address %s is not a free root path" % old_path)
        pages[_output_path(old_path)] = _redirect_html(origin, route)
    return pages


def _brand_bytes(name):
    try:
        return (BRAND_DIR / _PUBLIC_FILE_SOURCES[name]).read_bytes()
    except (KeyError, OSError) as exc:
        raise SiteExportError("public file %s is missing" % name) from exc


def _brand_files():
    """Size and sha256 of each copied file; svg and txt are scanned as text."""
    records = {}
    for name, _source in PUBLIC_FILES:
        data = _brand_bytes(name)
        if name == SITE_SCRIPT:
            site_script_bytes(data)
            _scan_public_text(data.decode("ascii"), name)
        elif name.endswith((".svg", ".txt")):
            try:
                _scan_public_text(data.decode("ascii"), name)
            except UnicodeDecodeError as exc:
                raise SiteExportError("%s must be ASCII" % name) from exc
        elif name.endswith(".woff2") and data[:4] != b"wOF2":
            raise SiteExportError("%s is not a woff2 font" % name)
        records[name] = {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    return records


def _robots_txt(origin):
    return "User-agent: *\nSitemap: %s/sitemap.xml\n" % origin


def _sitemap_xml(origin, root_paths):
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        + "".join(
            "  <url><loc>%s</loc></url>\n" % html.escape(origin + path, quote=True)
            for path in root_paths
        )
        + "</urlset>\n"
    )


def _cell_record(snapshot, root_id):
    try:
        cell = snapshot.cells[root_id]
    except KeyError as exc:
        raise InvalidCell("website export source Cell is missing") from exc
    return {
        "id": cell.id,
        "link0": cell.link0,
        "link1": cell.link1,
        "atom_hex": cell.atom.hex(),
    }


def _terminal_text(snapshot, root_id, label):
    record = _cell_record(snapshot, root_id)
    if record["link0"] != NULL_CELL_ID or record["link1"] != NULL_CELL_ID:
        raise InvalidCell("%s must be a terminal Cell" % label)
    try:
        return bytes.fromhex(record["atom_hex"]).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("%s must be UTF-8" % label) from exc


def _relation_record(snapshot, root_id, *, budget=2_000):
    try:
        root = snapshot.cells[root_id]
    except KeyError as exc:
        raise InvalidCell("website export relation root is missing") from exc
    return {
        "root": {
            "id": root.id,
            "atom_hex": root.atom.hex(),
        },
        "members": [
            {
                "index": index,
                "role": member.role_id,
                "participant": member.participant_id,
            }
            for index, member in enumerate(
                read_relation(snapshot, root_id, budget=budget)
            )
        ],
    }


def _source_fingerprint(snapshot, verified, route, static_html):
    source_roots = {
        "route": verified.route_roots[route],
        "page": verified.page_roots[route],
        "http_route": verified.cloud_route_roots[route],
        "stylesheet": verified.stylesheet_root,
        "title": verified.route_title_roots[route],
    }
    statement = {
        "route_relation": _relation_record(snapshot, source_roots["route"]),
        "http_route_relation": _relation_record(
            snapshot, source_roots["http_route"], budget=256
        ),
        "page_render_sha256": _digest_text(static_html),
        "page_root": source_roots["page"],
        "stylesheet_cell": _cell_record(snapshot, source_roots["stylesheet"]),
        "title_cell": _cell_record(snapshot, source_roots["title"]),
    }
    if route == "/website":
        statement["domain_bindings"] = [
            _relation_record(snapshot, binding.root_id, budget=64)
            for _, binding in sorted(verified.domain_binding_roots.items())
        ]
    return source_roots, hashlib.sha256(_canonical_bytes(statement)).hexdigest()


def _verified_website(store, registry):
    required = (
        "website", "application_root", "roles", "ui_protocol", "map",
        "cloud_route_protocol",
    )
    if any(not hasattr(registry, name) for name in required):
        raise SiteExportError(
            "site export requires the universal application registry"
        )
    try:
        return read_universal_website(
            store.snapshot(),
            registry.website.protocol,
            registry.website.root_id,
            ui_protocol=registry.ui_protocol,
            application_root=registry.application_root,
            application_member_role=registry.roles["member"],
            map_registry=registry.map,
            cloud_route_protocol=registry.cloud_route_protocol,
            published_lifecycle_root=registry.website.lifecycle_root,
            read_action_root=registry.website.read_action_root,
        )
    except (InvalidCell, KeyError, TypeError) as exc:
        raise SiteExportError(
            "universal website verification failed: %s" % exc
        ) from exc


def build_site_export(store, registry, *, offer=None, offer_sha256=None,
                      origin=None):
    """Return a sealed public payload from the verified universal website.

    With an offer record the export is refused unless the digest of the
    record equals offer_sha256, the offer is not monetary, and the rendered
    pricing page shows its public label.  With an origin every page carries
    its canonical root URL and share image, and the site carries robots.txt,
    sitemap.xml and a redirect page for each retired address; without one the
    payload is a graph projection with no address.  The brand files are
    recorded by size and sha256 either way.
    """
    verified_offer = _verified_offer(offer, offer_sha256)
    origin = _public_origin(origin)
    verified = _verified_website(store, registry)
    snapshot = store.snapshot()
    if origin is not None:
        graph_origin = _graph_origin(snapshot)
        if graph_origin is not None and graph_origin != origin:
            raise SiteExportError(
                "graph origin %s differs from export origin %s"
                % (graph_origin, origin)
            )
    try:
        download = website_download(snapshot)
    except InvalidCell as exc:
        raise SiteExportError("the offered download is refused: %s" % exc) from exc
    if download is None:
        raise SiteExportError(
            "the graph offers no released download, so the site is not exported"
        )
    download_href = 'href="%s"' % html.escape(download.url, quote=True)
    publication_tier = _terminal_text(
        snapshot, verified.classification_root, "website classification"
    ).strip().upper()
    if publication_tier != PUBLICATION_TIER:
        raise SiteExportError(
            "website publication tier must be %s, got %s"
            % (PUBLICATION_TIER, publication_tier or "EMPTY")
        )
    if set(verified.route_roots) != set(PUBLIC_ROUTES):
        raise SiteExportError(
            "website route registry must contain exactly seven public routes"
        )

    records = {}
    root_paths = []
    shared_stylesheet = None
    for route in PUBLIC_ROUTES:
        try:
            projected = project_universal_website_document(
                store,
                verified,
                route,
                application_root=registry.application_root,
                application_member_role=registry.roles["member"],
                map_registry=registry.map,
                cloud_route_protocol=registry.cloud_route_protocol,
            )
        except InvalidCell as exc:
            raise SiteExportError(
                "route %s failed universal projection: %s" % (route, exc)
            ) from exc
        static_html, stylesheet = _static_document(projected)
        if shared_stylesheet is None:
            shared_stylesheet = stylesheet
        elif shared_stylesheet != stylesheet:
            raise SiteExportError("website routes do not share one graph stylesheet")
        static_html = _root_hrefs(static_html)
        if 'href="/website' in static_html:
            raise SiteExportError(
                "route %s still links to the in-app path after rewriting" % route
            )
        if download_href not in static_html:
            raise SiteExportError(
                "route %s does not link the released download" % route
            )
        root_path = public_path(route)
        if origin is not None:
            title, description = _page_identity(
                snapshot, verified, route, static_html
            )
            static_html = _with_head_meta(
                static_html, origin, root_path, title, description
            )
        _scan_public_text(static_html, route)
        admitted_scripts(static_html, route)
        source_roots, source_fingerprint = _source_fingerprint(
            snapshot, verified, route, static_html
        )
        root_paths.append(root_path)
        records[route] = {
            "html": static_html,
            "html_sha256": _digest_text(static_html),
            "output_path": _output_path(root_path),
            "root_node": verified.page_roots[route],
            "source_fingerprint": source_fingerprint,
            "source_roots": source_roots,
        }

    if verified_offer is not None:
        pricing = records["/website/pricing"]["html"]
        display = verified_offer["display"]
        if display not in pricing and html.escape(display) not in pricing:
            raise SiteExportError(
                "the pricing page does not show the offer display %r" % display
            )

    _scan_public_text(shared_stylesheet or "", "shared stylesheet")
    assets = {
        "assets/site.css": shared_stylesheet,
        "assets/fonts.css": FONTS_CSS,
        "404.html": NOT_FOUND_HTML,
    }
    if origin is not None:
        assets["robots.txt"] = _robots_txt(origin)
        assets["sitemap.xml"] = _sitemap_xml(origin, root_paths)
        assets.update(_retired_pages(origin))
    payload = {
        "assets": assets,
        "download": {
            "revision": download.revision,
            "sha256": download.sha256,
            "url": download.url,
        },
        "files": _brand_files(),
        "format": EXPORT_FORMAT,
        "application_root": registry.application_root,
        "website_root": verified.root_id,
        "website_fingerprint": hashlib.sha256(_canonical_bytes({
            "website": _relation_record(snapshot, verified.root_id),
            "protocol": _relation_record(snapshot, verified.protocol.root_id),
            "classification": _cell_record(
                snapshot, verified.classification_root
            ),
            "lifecycle": _cell_record(snapshot, verified.lifecycle_root),
        })).hexdigest(),
        "publication_tier": PUBLICATION_TIER,
        "origin": origin,
        "offer": None if verified_offer is None else verified_offer["record"],
        "offer_sha256": (
            None if verified_offer is None else verified_offer["sha256"]
        ),
        "routes": records,
    }
    _scan_public_text(_canonical_bytes(payload).decode("ascii"), "site export")
    payload["export_sha256"] = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    return payload


def write_public_site(store, registry, project_dir, *, offer=None,
                      offer_sha256=None, origin=None):
    """Write site-export.json, .gitignore and the static site under dist/."""
    project = Path(project_dir)
    project.mkdir(parents=True, exist_ok=True)
    payload = build_site_export(
        store, registry, offer=offer, offer_sha256=offer_sha256, origin=origin,
    )
    brand = {}
    for name, record in payload["files"].items():
        if name not in _PUBLIC_FILE_SOURCES:
            raise SiteExportError("unknown public file: %s" % name)
        data = _brand_bytes(name)
        if name == SITE_SCRIPT:
            site_script_bytes(data)
        if (len(data) != record["bytes"]
                or hashlib.sha256(data).hexdigest() != record["sha256"]):
            raise SiteExportError(
                "public file %s is not the one the export sealed" % name)
        brand["dist/" + name] = data
    dist = project / "dist"
    if dist.exists():
        shutil.rmtree(dist)
    files = {
        "site-export.json": json.dumps(payload, sort_keys=True, indent=2,
                                       ensure_ascii=True) + "\n",
        ".gitignore": "dist/\n",
    }
    for relative, contents in payload["assets"].items():
        files["dist/" + relative] = contents
    for record in payload["routes"].values():
        files["dist/" + record["output_path"]] = record["html"]
    for relative, contents in files.items():
        if relative.startswith("/") or ".." in relative.split("/"):
            raise SiteExportError("unsafe export output path: %s" % relative)
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(contents, encoding="utf-8", newline="\n")
    for relative, data in brand.items():
        target = project / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return payload


def _build_public_seed_application(offer=None):
    """Build export input from the bundled T0-safe seed, never local authority.

    The website offer, when given, is what the seed's pricing page renders.
    """
    from .map_import import PUBLIC_MAP_PATH
    from .universal_application import build_universal_application

    return build_universal_application(PUBLIC_MAP_PATH, offer=offer)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Export the T0 public website as a static site from the "
                    "canonical offer record of app:users:accounts:offer.",
    )
    parser.add_argument(
        "--offer", required=True,
        help="path to the canonical offer record JSON: availability, "
             "pricing-visible, public-label",
    )
    parser.add_argument(
        "--offer-sha256", required=True,
        help="sha256 of the canonical bytes of the offer record, as "
             "cell_accounts.published_offer publishes it",
    )
    parser.add_argument(
        "--origin", required=True,
        help="public https origin, for example https://archhub.io",
    )
    parser.add_argument(
        "--output",
        default=str(Path(__file__).resolve().parents[1] / "public_site"),
    )
    args = parser.parse_args(argv)
    try:
        offer = json.loads(Path(args.offer).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        parser.error("--offer is not a readable JSON file: %s" % exc)
    try:
        verified = _verified_offer(offer, args.offer_sha256)
        origin = _public_origin(args.origin)
    except SiteExportError as exc:
        parser.exit(1, "site export refused: %s\n" % exc)
    store, registry = _build_public_seed_application(
        website_offer(verified["record"])
    )
    try:
        payload = write_public_site(
            store, registry, args.output,
            offer=verified["record"], offer_sha256=args.offer_sha256,
            origin=origin,
        )
    except SiteExportError as exc:
        parser.exit(1, "site export refused: %s\n" % exc)
    print(json.dumps({
        "format": payload["format"],
        "publication_tier": payload["publication_tier"],
        "origin": payload["origin"],
        "offer": payload["offer"],
        "offer_sha256": payload["offer_sha256"],
        "routes": len(payload["routes"]),
        "export_sha256": payload["export_sha256"],
        "output": str(Path(args.output).resolve()),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
