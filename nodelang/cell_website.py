"""Public website lens composed entirely from universal Cells and relations."""
from __future__ import annotations

from dataclasses import dataclass
import html
import re
from types import MappingProxyType
from typing import Mapping
from urllib.parse import quote

from .cell_cloud_routes import (
    CloudRouteProtocol,
    build_cloud_route,
    read_cloud_route,
)
from .cell_protocols import (
    CellBatch,
    prepare_append_relation_members,
    read_relation,
)
from .cell_ui import UIBuilder, UIProtocol, render_ui
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot
from .universal_map_import import UniversalMapRegistry


PUBLIC_WEBSITE_ROUTES = (
    "/website",
    "/website/features",
    "/website/pricing",
    "/website/changelog",
    "/website/security",
    "/website/community",
    "/website/signin",
)

WEBSITE_ROOT = "app:website"
WEBSITE_PROTOCOL_PREFIX = "app:website-protocol"
WEBSITE_STYLESHEET_ROOT = "app:website:stylesheet"
WEBSITE_AUDIENCE_ROOT = "app:website:audience:public"
WEBSITE_CLASSIFICATION_ROOT = "app:website:classification:t0-public"
WEBSITE_PURPOSE_ROOT = "app:website:purpose:public-projection"
WEBSITE_SOURCE_ROOT = "app:website:source:universal-lens-decision"

ROLE_NAMES = (
    "vocabulary-member",
    "protocol",
    "application",
    "stylesheet",
    "route",
    "website",
    "path",
    "page",
    "http-route",
    "domain-binding",
    "card",
    "domain",
    "key",
    "title",
    "interface",
    "action",
    "audience",
    "classification",
    "lifecycle-state",
    "purpose",
    "source",
)

WEBSITE_CSS = r"""
:root{--paper:#f6f7f8;--panel:#ffffff;--ink:#111214;--muted:#5f646b;--line:#d9dde2;--line-strong:#aeb4bc;--signal:#d84a2f;--signal-soft:#fff0ec;--teal:#146c72;--dark:#17191c;--dark-soft:#23262a}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--paper);color:var(--ink);font-family:"Segoe UI",Arial,sans-serif;font-size:16px;letter-spacing:0}a{color:inherit}a:focus-visible{outline:3px solid var(--signal);outline-offset:4px}.site-shell{min-height:100vh;background:var(--paper)}.site-nav{height:68px;padding:0 5vw;display:flex;align-items:center;gap:24px;border-bottom:1px solid var(--line);background:rgba(255,255,255,.96);position:relative;z-index:5}.site-brand{font-size:20px;font-weight:760;text-decoration:none}.site-brand-mark{color:var(--signal)}.site-nav-links{margin-left:auto;display:flex;align-items:center;gap:4px;list-style:none;padding:0}.site-nav-link{display:inline-flex;min-height:40px;align-items:center;padding:0 10px;text-decoration:none;color:var(--muted);font-size:14px;border-bottom:2px solid transparent}.site-nav-link:hover{color:var(--ink)}.site-nav-link[aria-current="page"]{color:var(--ink);border-bottom-color:var(--signal)}.site-access{border:1px solid var(--ink);padding:8px 12px;text-decoration:none;font-size:14px}.site-access:hover{background:var(--ink);color:#fff}.site-main{display:block}.site-hero{min-height:660px;display:grid;grid-template-columns:minmax(340px,.9fr) minmax(520px,1.1fr);border-bottom:1px solid var(--line);background:var(--panel)}.site-hero-copy{padding:112px 7vw 72px;display:flex;flex-direction:column;justify-content:center}.site-kicker{margin:0 0 18px;color:var(--signal);font-size:12px;font-weight:700;text-transform:uppercase}.site-title{font-size:72px;line-height:.94;margin:0;max-width:680px;font-weight:780}.site-lede{font-size:25px;line-height:1.35;max-width:610px;margin:28px 0 0}.site-body{font-size:16px;line-height:1.7;color:var(--muted);max-width:600px;margin:18px 0 0}.site-actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:30px}.site-primary,.site-secondary{display:inline-flex;align-items:center;min-height:46px;padding:0 16px;text-decoration:none;font-weight:650}.site-primary{background:var(--signal);color:#fff}.site-primary:hover{background:#b93a24}.site-secondary{border:1px solid var(--line-strong);background:var(--panel)}.site-release-note{margin-top:28px;padding-left:12px;border-left:3px solid var(--teal);font-size:13px;line-height:1.55;color:var(--muted);max-width:520px}.site-graph{position:relative;overflow:hidden;background:var(--dark);color:#fff;padding:96px 5vw 60px}.site-graph::before{content:"";position:absolute;inset:0;background-size:24px 24px;background-image:radial-gradient(circle,#3a3e44 1px,transparent 1px);opacity:.58}.site-graph-head,.site-domain-grid{position:relative}.site-graph-head{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:22px}.site-graph-label{font-size:12px;color:#afb6bf;text-transform:uppercase}.site-graph-state{font-size:12px;color:#83d2ce}.site-domain-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.site-domain-card{min-height:104px;border:1px solid #3c4148;background:var(--dark-soft);padding:14px;display:flex;flex-direction:column;justify-content:space-between}.site-domain-card:nth-child(3n+1){border-top-color:var(--signal)}.site-domain-card:nth-child(3n+2){border-top-color:#e0b04b}.site-domain-card:nth-child(3n){border-top-color:#57aaa9}.site-domain-kind{font-size:10px;color:#949ca6;text-transform:uppercase}.site-domain-title{font-size:16px;line-height:1.25;margin:16px 0 0}.site-principles{padding:72px 7vw 86px;background:var(--paper)}.site-section-head{display:flex;align-items:end;justify-content:space-between;gap:30px;margin-bottom:28px}.site-section-title{font-size:38px;line-height:1.08;margin:0;max-width:720px}.site-section-copy{max-width:540px;color:var(--muted);line-height:1.65;margin:0}.site-principle-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border-top:1px solid var(--line);border-left:1px solid var(--line)}.site-principle{min-height:190px;padding:24px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);background:var(--panel)}.site-principle-index{font-size:11px;color:var(--signal);font-weight:750}.site-principle-title{font-size:21px;margin:34px 0 10px}.site-principle-body{color:var(--muted);line-height:1.6;margin:0}.site-page-main{min-height:calc(100vh - 140px);padding:94px 7vw 100px}.site-page-header{max-width:900px}.site-page-title{font-size:58px;line-height:1;margin:0}.site-page-lede{font-size:22px;line-height:1.5;color:var(--muted);margin:24px 0 0;max-width:820px}.site-page-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin-top:54px;border-top:1px solid var(--line);border-left:1px solid var(--line)}.site-page-card{min-height:230px;padding:26px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);background:var(--panel)}.site-card-kicker{font-size:11px;text-transform:uppercase;color:var(--teal);font-weight:750}.site-card-title{font-size:23px;margin:36px 0 12px}.site-card-body{color:var(--muted);line-height:1.65;margin:0}.site-card-status{margin-top:24px;padding-top:12px;border-top:1px solid var(--line);font-size:12px;color:var(--signal);font-weight:700}.site-footer{min-height:72px;padding:22px 5vw;display:flex;align-items:center;justify-content:space-between;gap:20px;background:var(--dark);color:#d9dde2}.site-footer-copy{font-size:13px}.site-footer-link{font-size:13px;color:#fff}
@media(max-width:1100px){.site-hero{grid-template-columns:1fr}.site-hero-copy{min-height:610px}.site-graph{min-height:560px}.site-title{font-size:64px}.site-domain-grid{grid-template-columns:repeat(3,minmax(150px,1fr))}.site-principle-grid,.site-page-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:760px){.site-nav{height:auto;min-height:64px;padding:10px 18px;align-items:flex-start;flex-wrap:wrap;gap:8px 14px}.site-nav-links{order:3;width:100%;overflow:auto;margin:0}.site-nav-link{white-space:nowrap}.site-access{margin-left:auto}.site-hero-copy{min-height:560px;padding:78px 24px 56px}.site-title{font-size:48px}.site-lede{font-size:21px}.site-graph{padding:62px 24px 42px}.site-domain-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.site-principles,.site-page-main{padding:58px 24px 70px}.site-section-head{display:block}.site-section-copy{margin-top:16px}.site-principle-grid,.site-page-grid{grid-template-columns:1fr}.site-page-title{font-size:44px}.site-page-lede{font-size:19px}.site-footer{align-items:flex-start;flex-direction:column}}
"""

_UNSAFE_CSS = ("</style", "@import", "url(", "expression(", "javascript:")
_PRIVATE_TEXT = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"[a-z]:[\\/]+users[\\/]",
    r"(?:00\.governance|20\.clients|30\.knowledge|40\.media|50\.tooling|"
    r"60\.personal|70\.handoffs|90\.archive)",
    r"op://",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"bootstrap=|archhub-csrf|app:authorization",
))


@dataclass(frozen=True, slots=True)
class WebsiteProtocol:
    root_id: str
    roles: Mapping[str, str]

    def role(self, name: str) -> str:
        try:
            return self.roles[name]
        except KeyError as exc:
            raise InvalidCell("unknown website role %r" % name) from exc


@dataclass(frozen=True, slots=True)
class WebsiteDomainBinding:
    root_id: str
    card_root: str
    domain_root: str


@dataclass(frozen=True, slots=True)
class UniversalWebsiteBuild:
    protocol: WebsiteProtocol
    ui_protocol: UIProtocol
    root_id: str
    stylesheet_root: str
    route_roots: Mapping[str, str]
    page_roots: Mapping[str, str]
    cloud_route_roots: Mapping[str, str]
    route_title_roots: Mapping[str, str]
    domain_binding_roots: Mapping[str, WebsiteDomainBinding]
    audience_root: str
    classification_root: str
    lifecycle_root: str
    purpose_root: str
    read_action_root: str


def _terminal(root_id: str, value: str) -> Cell:
    return Cell(root_id, NULL_CELL_ID, NULL_CELL_ID, value.encode("utf-8"))


def _text(snapshot: Snapshot, root_id: str) -> str:
    cell = snapshot.cells.get(root_id)
    if cell is None or cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
        raise InvalidCell("website scalar is missing or non-terminal")
    try:
        return cell.atom.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise InvalidCell("website scalar is not UTF-8") from exc


def _one(members, role_id: str, label: str) -> str:
    values = [member.participant_id for member in members if member.role_id == role_id]
    if len(values) != 1:
        raise InvalidCell("website %s must have exactly one participant" % label)
    return values[0]


def _many(members, role_id: str) -> tuple[str, ...]:
    return tuple(
        member.participant_id for member in members if member.role_id == role_id
    )


def _part(value: str) -> str:
    return quote(value.strip("/") or "home", safe="")


def bootstrap_website_protocol(store: CellStore) -> WebsiteProtocol:
    roles = {
        name: "%s:role:%s" % (WEBSITE_PROTOCOL_PREFIX, name)
        for name in ROLE_NAMES
    }
    batch = CellBatch(store)
    for name, root_id in roles.items():
        batch.add(_terminal(root_id, name))
    root_id = WEBSITE_PROTOCOL_PREFIX + ":root"
    batch.relation(
        ((roles["vocabulary-member"], root) for root in roles.values()),
        relation_id=root_id,
    )
    batch.commit()
    return WebsiteProtocol(root_id, MappingProxyType(roles))


def project_website_protocol(snapshot: Snapshot) -> WebsiteProtocol:
    roles = {
        name: "%s:role:%s" % (WEBSITE_PROTOCOL_PREFIX, name)
        for name in ROLE_NAMES
    }
    root_id = WEBSITE_PROTOCOL_PREFIX + ":root"
    if {root_id, *roles.values()} - set(snapshot.cells):
        raise InvalidCell("website protocol is incomplete")
    members = read_relation(snapshot, root_id, budget=128)
    if (
        any(member.role_id != roles["vocabulary-member"] for member in members)
        or {member.participant_id for member in members} != set(roles.values())
    ):
        raise InvalidCell("website protocol vocabulary drifted")
    for name, role_id in roles.items():
        if _text(snapshot, role_id) != name:
            raise InvalidCell("website protocol role label drifted")
    return WebsiteProtocol(root_id, MappingProxyType(roles))


def _domain_property_value_root(
    snapshot: Snapshot,
    map_registry: UniversalMapRegistry,
    domain_root: str,
    label: str,
) -> str:
    matches = []
    for relation_root in map_registry.root_properties[domain_root]:
        members = read_relation(snapshot, relation_root, budget=16)
        labels = _many(members, map_registry.roles["label"])
        values = _many(members, map_registry.roles["value"])
        if len(labels) == 1 and _text(snapshot, labels[0]) == label:
            if len(values) != 1:
                raise InvalidCell("Grand Map domain property is ambiguous")
            matches.append(values[0])
    if len(matches) != 1:
        raise InvalidCell("Grand Map domain lacks one %s property" % label)
    return matches[0]


def _page_specs():
    return {
        "/website/features": (
            "Everything is connected through one graph",
            "The product is built from one physical Cell record and graph-held protocols, so data, logic, relations, interfaces, presentation, authority, and evidence remain inspectable at the appropriate level.",
            (
                ("01", "One universal floor", "Cell identity, two raw links, and opaque bytes are the only persisted physical shape. Familiar node types are reusable graph assemblies, not engine classes.", "IMPLEMENTED FLOOR / BROADER COURTS STILL OPEN"),
                ("02", "Relations have identity", "A connection is a selectable relation with explicit incidences, roles, gates, transforms, policy, lifecycle, and presentation. It is not a decorative line.", "RELATION PROTOCOL ACTIVE"),
                ("03", "Different views, same roots", "Use, Build, Govern, and Floor reveal increasing detail while preserving the same semantic identities. Brain, Cockpit, Grand Map, and the website are lenses.", "PROGRESSIVE DISCLOSURE IN WIP"),
            ),
        ),
        "/website/pricing": (
            "Commercial release is not active",
            "ArchHub is still in governed WIP. No plan, checkout, subscription, or commercial promise is being offered until the product, legal, security, support, and release courts are complete.",
            (("STATUS", "Not for sale yet", "Work is focused on making the application coherent, secure, recoverable, and usable before monetisation is activated.", "NO MONETARY EFFECTS ENABLED"),),
        ),
        "/website/changelog": (
            "Revision evidence, not progress theatre",
            "A public release history will be generated from signed revisions and exact passing courts. Development activity is not presented as a shipped product.",
            (
                ("WIP", "Universal Cell migration", "The normal application state and this website are moving onto one persistent universal graph while legacy regions remain migration evidence until replaced.", "NOT A SIGNED RELEASE"),
                ("EVIDENCE", "Claims stay bounded", "Local tests prove only their named environment and artifact. Cloud, packaged-browser, independent security, and operational courts remain separate.", "OPEN GAPS REMAIN VISIBLE"),
            ),
        ),
        "/website/security": (
            "Security is an authority chain",
            "Reads, changes, effects, releases, and external capabilities must resolve identity, relationship, scope, classification, lifecycle, policy, and evidence before execution.",
            (
                ("01", "Default deny", "Unknown routes, adapters, actions, policies, audiences, classifications, and malformed graph relations fail closed.", "LOCAL GATES ACTIVE"),
                ("02", "Keys stay outside ordinary Cells", "The graph stores public descriptors, policy, and evidence while private signing bytes remain in admitted operating-system or cloud custody.", "LOCAL CNG AND TPM-PROVIDER COURTS"),
                ("03", "Release boundaries remain honest", "Hardware attestation, production cloud KMS, independent witnesses, monitoring, and external security review are not yet release-green.", "EXTERNAL COURTS OPEN"),
            ),
        ),
        "/website/community": (
            "Community federation is not connected",
            "The intended community layer requires explicit identity, consent, moderation, provenance, reputation, conflict handling, and federation authority. A public network is not currently active.",
            (("STATUS", "No public federation yet", "Contributor and community claims remain disabled until their real hosts, policies, evidence, and recovery paths are connected.", "NETWORK EFFECTS DISABLED"),),
        ),
        "/website/signin": (
            "Public account access is not enabled",
            "The local identity and session authority is under active construction. No public credential form is shown until an admitted identity provider and production authorization evidence are connected.",
            (("STATUS", "Access remains closed", "The desktop founder session is not a public account service and no browser token is exposed through this website.", "PUBLIC SIGN-IN DISABLED"),),
        ),
    }


def build_universal_website(
    store: CellStore,
    *,
    application_root: str,
    application_member_role: str,
    ui_protocol: UIProtocol,
    cloud_route_protocol: CloudRouteProtocol,
    map_registry: UniversalMapRegistry,
    published_lifecycle_root: str,
    read_action_root: str,
) -> UniversalWebsiteBuild:
    """Compose the public lens, then make it reachable from the application."""
    snapshot = store.snapshot()
    if WEBSITE_ROOT in snapshot.cells:
        raise InvalidCell("universal website already exists")
    protocol = (
        project_website_protocol(snapshot)
        if WEBSITE_PROTOCOL_PREFIX + ":root" in snapshot.cells
        else bootstrap_website_protocol(store)
    )
    snapshot = store.snapshot()
    ui = UIBuilder(store, ui_protocol)
    for root_id, value in (
        (WEBSITE_STYLESHEET_ROOT, WEBSITE_CSS),
        (WEBSITE_AUDIENCE_ROOT, "Public website visitors"),
        (WEBSITE_CLASSIFICATION_ROOT, "T0 PUBLIC"),
        (WEBSITE_PURPOSE_ROOT, "Public website projection"),
        (WEBSITE_SOURCE_ROOT, "Universal website lens decision 2026-07-17"),
    ):
        ui.batch.add(_terminal(root_id, value))

    route_title_roots: dict[str, str] = {}
    route_path_roots: dict[str, str] = {}

    def scalar(root_id: str, value: str) -> str:
        ui.batch.add(_terminal(root_id, value))
        return root_id

    def element(tag, class_name="", text=None, text_root=None, attrs=None,
                children=(), root_id=None):
        return ui.element(
            tag,
            class_name=class_name,
            text=text,
            text_root=text_root,
            attributes=attrs,
            children=children,
            element_id=root_id,
        )

    nav_labels = (
        ("Product", "/website/features"),
        ("Release", "/website/pricing"),
        ("Evidence", "/website/changelog"),
        ("Security", "/website/security"),
        ("Community", "/website/community"),
    )

    def navigation(path: str, token: str) -> str:
        brand = element(
            "a", "site-brand", attrs={"href": "/website"},
            children=(
                element("span", text="Arch"),
                element("span", "site-brand-mark", text="Hub"),
            ),
        )
        links = []
        for index, (label, href) in enumerate(nav_labels):
            attributes = {"href": href}
            if path == href:
                attributes["aria-current"] = "page"
            link = element(
                "a", "site-nav-link", text=label, attrs=attributes,
            )
            links.append(element("li", children=(link,)))
        nav_list = element("ul", "site-nav-links", children=links)
        access_attributes = {"href": "/website/signin"}
        if path == "/website/signin":
            access_attributes["aria-current"] = "page"
        access = element(
            "a", "site-access", text="Access status", attrs=access_attributes,
        )
        return element(
            "nav", "site-nav", attrs={"aria-label": "Primary"},
            children=(brand, nav_list, access),
            root_id="app:website:nav:%s" % token,
        )

    footer = element(
        "footer", "site-footer", children=(
            element("span", "site-footer-copy", text="ArchHub is in governed WIP."),
            element(
                "a", "site-footer-link", text="Security and release status",
                attrs={"href": "/website/security"},
            ),
        ),
        root_id="app:website:footer",
    )

    home_title = scalar("app:website:text:home:title", "ArchHub")
    route_title_roots["/website"] = home_title
    route_path_roots["/website"] = scalar(
        "app:website:path:home", "/website"
    )
    home_nav = navigation("/website", "home")
    hero_copy = element("div", "site-hero-copy", children=(
        element("p", "site-kicker", text="One persistent operating graph"),
        element("h1", "site-title", text_root=home_title),
        element(
            "p", "site-lede",
            text="A visual graph computer for designing, governing, and operating the built environment.",
        ),
        element(
            "p", "site-body",
            text="Data, geometry, decisions, interfaces, AI work, governance, and delivery remain connected through universal Cells and explicit relation-nodes instead of separate opaque tools.",
        ),
        element("div", "site-actions", children=(
            element(
                "a", "site-primary", text="See how it works",
                attrs={"href": "/website/features"},
            ),
            element(
                "a", "site-secondary", text="Read the security status",
                attrs={"href": "/website/security"},
            ),
        )),
        element(
            "p", "site-release-note",
            text="Current state: governed work in progress. Public release and account access are not active.",
        ),
    ))

    domain_cards: dict[str, str] = {}
    card_roots = []
    for key, domain_root in map_registry.domains.items():
        title_root = _domain_property_value_root(
            snapshot, map_registry, domain_root, "title"
        )
        card_root = "app:website:domain-card:%s" % _part(key)
        card = element(
            "article", "site-domain-card", children=(
                element("span", "site-domain-kind", text="Grand Map domain"),
                element("h3", "site-domain-title", text_root=title_root),
            ),
            root_id=card_root,
        )
        domain_cards[key] = card_root
        card_roots.append(card)
    graph_panel = element(
        "section", "site-graph", attrs={"aria-label": "Connected product domains"},
        children=(
            element("div", "site-graph-head", children=(
                element("span", "site-graph-label", text="The application composition"),
                element("span", "site-graph-state", text="Same roots / different lens"),
            )),
            element("div", "site-domain-grid", children=card_roots),
        ),
        root_id="app:website:domain-graph",
    )
    complete_hero = element(
        "section", "site-hero", children=(hero_copy, graph_panel),
        root_id="app:website:hero",
    )
    principles = element(
        "section", "site-principles", children=(
            element("div", "site-section-head", children=(
                element("h2", "site-section-title", text="Simple physical floor. Visible power above it."),
                element("p", "site-section-copy", text="The user works with understandable assemblies. Govern and Floor reveal deeper authority and mechanics only when needed."),
            )),
            element("div", "site-principle-grid", children=tuple(
                element("article", "site-principle", children=(
                    element("span", "site-principle-index", text=index),
                    element("h3", "site-principle-title", text=title),
                    element("p", "site-principle-body", text=body),
                ))
                for index, title, body in (
                    ("01", "Everything has identity", "Properties, rules, wires, sessions, interfaces, and presentations remain addressable graph compositions."),
                    ("02", "Every connection is explicit", "Relations carry participants, gates, transforms, lifecycle, security, and evidence instead of magical coupling."),
                    ("03", "Every change is recoverable", "History, WIP, review, publication, effects, reconciliation, and undo remain separate and traceable."),
                )
            )),
        ),
    )
    home_main = element(
        "main", "site-main", children=(complete_hero, principles),
        root_id="app:website:main:home",
    )
    page_roots: dict[str, str] = {
        "/website": element(
            "div", "site-shell", children=(home_nav, home_main, footer),
            root_id="app:website:page:home",
        )
    }

    for path, (title, lede, cards) in _page_specs().items():
        token = _part(path)
        title_root = scalar("app:website:text:%s:title" % token, title)
        path_root = scalar("app:website:path:%s" % token, path)
        route_title_roots[path] = title_root
        route_path_roots[path] = path_root
        content_cards = []
        for index, (kicker, card_title, body, status) in enumerate(cards):
            content_cards.append(element(
                "article", "site-page-card", children=(
                    element("span", "site-card-kicker", text=kicker),
                    element("h2", "site-card-title", text=card_title),
                    element("p", "site-card-body", text=body),
                    element("p", "site-card-status", text=status),
                ),
                root_id="app:website:page-card:%s:%s" % (token, index),
            ))
        main = element(
            "main", "site-page-main", children=(
                element("header", "site-page-header", children=(
                    element("p", "site-kicker", text="ArchHub / public lens"),
                    element("h1", "site-page-title", text_root=title_root),
                    element("p", "site-page-lede", text=lede),
                )),
                element("section", "site-page-grid", children=content_cards),
            ),
            root_id="app:website:main:%s" % token,
        )
        page_roots[path] = element(
            "div", "site-shell", children=(navigation(path, token), main, footer),
            root_id="app:website:page:%s" % token,
        )
    ui.commit()

    placeholder = CellBatch(store)
    placeholder.relation((), relation_id=WEBSITE_ROOT)
    placeholder.commit()

    cloud_route_roots = {}
    for path, page_root in page_roots.items():
        cloud_route_roots[path] = build_cloud_route(
            store,
            cloud_route_protocol,
            route_id="app:website:http-route:%s" % _part(path),
            method="GET",
            path_template=path,
            action_root=read_action_root,
            object_root=page_root,
            interface_root=ui_protocol.root_id,
            purpose_root=WEBSITE_PURPOSE_ROOT,
            audience_root=WEBSITE_AUDIENCE_ROOT,
            classification_root=WEBSITE_CLASSIFICATION_ROOT,
            lifecycle_state_root=published_lifecycle_root,
            resource_lineage_roots=(application_root, WEBSITE_ROOT),
        )

    relation_batch = CellBatch(store)
    route_roots = {}
    for path in PUBLIC_WEBSITE_ROUTES:
        root_id = "app:website:route:%s" % _part(path)
        route_roots[path] = root_id
        relation_batch.relation((
            (protocol.role("website"), WEBSITE_ROOT),
            (protocol.role("path"), route_path_roots[path]),
            (protocol.role("page"), page_roots[path]),
            (protocol.role("http-route"), cloud_route_roots[path]),
            (protocol.role("title"), route_title_roots[path]),
        ), relation_id=root_id)
    domain_binding_roots = {}
    for key, domain_root in map_registry.domains.items():
        key_root = "app:website:domain-key:%s" % _part(key)
        relation_batch.add(_terminal(key_root, key))
        binding_root = "app:website:domain-binding:%s" % _part(key)
        relation_batch.relation((
            (protocol.role("website"), WEBSITE_ROOT),
            (protocol.role("card"), domain_cards[key]),
            (protocol.role("domain"), domain_root),
            (protocol.role("key"), key_root),
        ), relation_id=binding_root)
        domain_binding_roots[key] = WebsiteDomainBinding(
            binding_root, domain_cards[key], domain_root
        )
    relation_batch.commit()

    snapshot = store.snapshot()
    website_patch = prepare_append_relation_members(
        snapshot,
        WEBSITE_ROOT,
        (
            (protocol.role("protocol"), protocol.root_id),
            (protocol.role("application"), application_root),
            (protocol.role("stylesheet"), WEBSITE_STYLESHEET_ROOT),
            (protocol.role("interface"), ui_protocol.root_id),
            (protocol.role("action"), read_action_root),
            (protocol.role("audience"), WEBSITE_AUDIENCE_ROOT),
            (protocol.role("classification"), WEBSITE_CLASSIFICATION_ROOT),
            (protocol.role("lifecycle-state"), published_lifecycle_root),
            (protocol.role("purpose"), WEBSITE_PURPOSE_ROOT),
            (protocol.role("source"), WEBSITE_SOURCE_ROOT),
            *((protocol.role("route"), root) for root in route_roots.values()),
            *((protocol.role("domain-binding"), binding.root_id)
              for binding in domain_binding_roots.values()),
        ),
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=website_patch.create,
        replace=website_patch.replace,
    )

    snapshot = store.snapshot()
    application_patch = prepare_append_relation_members(
        snapshot,
        application_root,
        (
            (application_member_role, WEBSITE_ROOT),
            (application_member_role, protocol.root_id),
            *((application_member_role, root)
              for root in cloud_route_roots.values()),
        ),
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=application_patch.create,
        replace=application_patch.replace,
    )
    return read_universal_website(
        store.snapshot(), protocol, WEBSITE_ROOT,
        ui_protocol=ui_protocol,
        application_root=application_root,
        application_member_role=application_member_role,
        map_registry=map_registry,
        cloud_route_protocol=cloud_route_protocol,
        published_lifecycle_root=published_lifecycle_root,
        read_action_root=read_action_root,
    )


def _collect_ui_roots(
    snapshot: Snapshot,
    ui_protocol: UIProtocol,
    root_id: str,
    *,
    budget: int = 20_000,
) -> frozenset[str]:
    pending = [root_id]
    seen = set()
    while pending:
        if len(seen) >= budget:
            raise InvalidCell("website UI traversal exceeded its budget")
        current = pending.pop()
        if current in seen:
            raise InvalidCell("website UI tree reuses or cycles an element")
        seen.add(current)
        members = read_relation(snapshot, current, budget=256)
        pending.extend(
            member.participant_id for member in members
            if member.role_id == ui_protocol.role("child")
        )
    return frozenset(seen)


def read_universal_website(
    snapshot: Snapshot,
    protocol: WebsiteProtocol,
    root_id: str,
    *,
    ui_protocol: UIProtocol,
    application_root: str,
    application_member_role: str,
    map_registry: UniversalMapRegistry,
    cloud_route_protocol: CloudRouteProtocol,
    published_lifecycle_root: str,
    read_action_root: str,
) -> UniversalWebsiteBuild:
    """Verify and project the exact public website authority at one snapshot."""
    projected_protocol = project_website_protocol(snapshot)
    if projected_protocol.root_id != protocol.root_id:
        raise InvalidCell("website protocol identity drifted")
    members = read_relation(snapshot, root_id, budget=2_000)
    allowed = {protocol.role(name) for name in ROLE_NAMES[1:]}
    if any(member.role_id not in allowed for member in members):
        raise InvalidCell("website root contains an undeclared role")
    expected_singles = {
        "protocol": protocol.root_id,
        "application": application_root,
        "stylesheet": WEBSITE_STYLESHEET_ROOT,
        "interface": ui_protocol.root_id,
        "action": read_action_root,
        "audience": WEBSITE_AUDIENCE_ROOT,
        "classification": WEBSITE_CLASSIFICATION_ROOT,
        "lifecycle-state": published_lifecycle_root,
        "purpose": WEBSITE_PURPOSE_ROOT,
        "source": WEBSITE_SOURCE_ROOT,
    }
    for name, expected in expected_singles.items():
        if _one(members, protocol.role(name), name) != expected:
            raise InvalidCell("website %s authority drifted" % name)
    if _text(snapshot, WEBSITE_CLASSIFICATION_ROOT) != "T0 PUBLIC":
        raise InvalidCell("website is not classified T0 PUBLIC")
    if _text(snapshot, WEBSITE_AUDIENCE_ROOT) != "Public website visitors":
        raise InvalidCell("website public audience drifted")
    stylesheet = _text(snapshot, WEBSITE_STYLESHEET_ROOT)
    if any(token in stylesheet.casefold() for token in _UNSAFE_CSS):
        raise InvalidCell("website stylesheet contains an unsafe code path")

    app_members = read_relation(snapshot, application_root, budget=100_000)
    app_member_roots = {
        member.participant_id for member in app_members
        if member.role_id == application_member_role
    }
    if root_id not in app_member_roots or protocol.root_id not in app_member_roots:
        raise InvalidCell("website is not a member of the application")

    route_roots = _many(members, protocol.role("route"))
    if len(route_roots) != len(PUBLIC_WEBSITE_ROUTES):
        raise InvalidCell("website route count drifted")
    routes = {}
    pages = {}
    cloud_routes = {}
    titles = {}
    for route_root in route_roots:
        route = read_relation(snapshot, route_root, budget=32)
        if _one(route, protocol.role("website"), "route website") != root_id:
            raise InvalidCell("website route belongs to another website")
        path_root = _one(route, protocol.role("path"), "route path")
        path = _text(snapshot, path_root)
        if path not in PUBLIC_WEBSITE_ROUTES or path in routes:
            raise InvalidCell("website route path is unknown or ambiguous")
        page_root = _one(route, protocol.role("page"), "route page")
        http_root = _one(route, protocol.role("http-route"), "HTTP route")
        title_root = _one(route, protocol.role("title"), "route title")
        cloud = read_cloud_route(snapshot, cloud_route_protocol, http_root)
        if (
            cloud.method != "GET"
            or cloud.path_template != path
            or cloud.object_root != page_root
            or cloud.interface_root != ui_protocol.root_id
            or cloud.action_root != read_action_root
            or cloud.purpose_root != WEBSITE_PURPOSE_ROOT
            or cloud.audience_root != WEBSITE_AUDIENCE_ROOT
            or cloud.classification_root != WEBSITE_CLASSIFICATION_ROOT
            or cloud.lifecycle_state_root != published_lifecycle_root
            or set(cloud.resource_lineage_roots) != {application_root, root_id}
        ):
            raise InvalidCell("website route and HTTP route authority disagree")
        if http_root not in app_member_roots:
            raise InvalidCell("website HTTP route is outside the application")
        render_ui(snapshot, ui_protocol, page_root, budget=20_000)
        routes[path] = route_root
        pages[path] = page_root
        cloud_routes[path] = http_root
        titles[path] = title_root
    if set(routes) != set(PUBLIC_WEBSITE_ROUTES):
        raise InvalidCell("website public route set drifted")

    home_ui = _collect_ui_roots(
        snapshot, ui_protocol, pages["/website"], budget=20_000
    )
    binding_roots = _many(members, protocol.role("domain-binding"))
    domain_bindings = {}
    for binding_root in binding_roots:
        binding = read_relation(snapshot, binding_root, budget=32)
        if _one(binding, protocol.role("website"), "binding website") != root_id:
            raise InvalidCell("domain binding belongs to another website")
        key = _text(snapshot, _one(binding, protocol.role("key"), "domain key"))
        card_root = _one(binding, protocol.role("card"), "domain card")
        domain_root = _one(binding, protocol.role("domain"), "domain root")
        if key in domain_bindings or map_registry.domains.get(key) != domain_root:
            raise InvalidCell("website domain binding is unknown or ambiguous")
        if card_root not in home_ui:
            raise InvalidCell("website domain binding card is not visible")
        domain_bindings[key] = WebsiteDomainBinding(
            binding_root, card_root, domain_root
        )
    if set(domain_bindings) != set(map_registry.domains):
        raise InvalidCell("website does not bind every Grand Map domain")

    return UniversalWebsiteBuild(
        protocol,
        ui_protocol,
        root_id,
        WEBSITE_STYLESHEET_ROOT,
        MappingProxyType(routes),
        MappingProxyType(pages),
        MappingProxyType(cloud_routes),
        MappingProxyType(titles),
        MappingProxyType(domain_bindings),
        WEBSITE_AUDIENCE_ROOT,
        WEBSITE_CLASSIFICATION_ROOT,
        published_lifecycle_root,
        WEBSITE_PURPOSE_ROOT,
        read_action_root,
    )


def ensure_universal_website(
    store: CellStore,
    *,
    application_root: str,
    application_member_role: str,
    ui_protocol: UIProtocol,
    cloud_route_protocol: CloudRouteProtocol,
    map_registry: UniversalMapRegistry,
    published_lifecycle_root: str,
    read_action_root: str,
) -> UniversalWebsiteBuild:
    snapshot = store.snapshot()
    if WEBSITE_ROOT not in snapshot.cells:
        if any(
            root.startswith("app:website:")
            for root in snapshot.cells
        ):
            raise InvalidCell("persisted universal website is partial")
        return build_universal_website(
            store,
            application_root=application_root,
            application_member_role=application_member_role,
            ui_protocol=ui_protocol,
            cloud_route_protocol=cloud_route_protocol,
            map_registry=map_registry,
            published_lifecycle_root=published_lifecycle_root,
            read_action_root=read_action_root,
        )
    return read_universal_website(
        snapshot,
        project_website_protocol(snapshot),
        WEBSITE_ROOT,
        ui_protocol=ui_protocol,
        application_root=application_root,
        application_member_role=application_member_role,
        map_registry=map_registry,
        cloud_route_protocol=cloud_route_protocol,
        published_lifecycle_root=published_lifecycle_root,
        read_action_root=read_action_root,
    )


def project_universal_website_document(
    store: CellStore,
    website: UniversalWebsiteBuild,
    path: str,
    *,
    application_root: str,
    application_member_role: str,
    map_registry: UniversalMapRegistry,
    cloud_route_protocol: CloudRouteProtocol,
) -> str:
    snapshot = store.snapshot()
    verified = read_universal_website(
        snapshot,
        website.protocol,
        website.root_id,
        ui_protocol=website.ui_protocol,
        application_root=application_root,
        application_member_role=application_member_role,
        map_registry=map_registry,
        cloud_route_protocol=cloud_route_protocol,
        published_lifecycle_root=website.lifecycle_root,
        read_action_root=website.read_action_root,
    )
    try:
        page_root = verified.page_roots[path]
        title_root = verified.route_title_roots[path]
    except KeyError as exc:
        raise InvalidCell("unknown public website route") from exc
    shell = render_ui(snapshot, verified.ui_protocol, page_root, budget=20_000)
    stylesheet = _text(snapshot, verified.stylesheet_root)
    document = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light">'
        '<title>%s | ArchHub</title><style>%s</style></head><body>%s</body></html>'
        % (html.escape(_text(snapshot, title_root)), stylesheet, shell)
    )
    for pattern in _PRIVATE_TEXT:
        if pattern.search(document):
            raise InvalidCell("public website projection contains private text")
    return document


__all__ = [
    "PUBLIC_WEBSITE_ROUTES",
    "UniversalWebsiteBuild",
    "WebsiteDomainBinding",
    "WebsiteProtocol",
    "build_universal_website",
    "ensure_universal_website",
    "project_universal_website_document",
    "project_website_protocol",
    "read_universal_website",
]
