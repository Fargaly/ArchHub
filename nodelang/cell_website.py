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
:root{--bg-deep:#0a0a0d;--bg:#0e0e11;--panel:#15151a;--soft:#1c1c23;--ink:#ece8e0;--ink-soft:#9b938a;--ink-muted:#8b837a;--line:#26262e;--line-soft:#1e1e24;--accent:#d97757;--accent-soft:#3a2018;--accent-hi:#e8896a;--on-fill:#180f08;--ok:#7ec18e;--cyan:#5fb3b3;--serif:"Instrument Serif",Georgia,serif;--sans:"Inter",system-ui,sans-serif;--mono:"JetBrains Mono",ui-monospace,monospace}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.5}a{color:inherit;text-decoration:none}a:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.site-shell{min-height:100vh;background:var(--bg)}
.site-nav{height:64px;padding:0 5vw;display:flex;align-items:center;gap:28px;border-bottom:1px solid var(--line-soft);background:rgba(14,14,17,.82);position:sticky;top:0;z-index:50}
.site-brand{font-family:var(--serif);font-size:20px;letter-spacing:.02em;text-transform:uppercase}.site-brand-mark{color:var(--accent);font-style:italic}
.site-nav-links{margin-left:auto;display:flex;align-items:center;gap:22px;list-style:none;padding:0;margin-right:22px}
.site-nav-link{display:inline-flex;min-height:40px;align-items:center;font-size:13.5px;color:var(--ink-soft);border-bottom:2px solid transparent}.site-nav-link:hover{color:var(--ink)}.site-nav-link[aria-current="page"]{color:var(--ink);border-bottom-color:var(--accent)}
.site-access{border:1px solid var(--line);border-radius:6px;padding:8px 16px;font-size:13.5px;color:var(--ink)}.site-access:hover{border-color:var(--ink-muted)}
.site-main{display:block}
.site-wrap{max-width:1240px;margin:0 auto;padding:0 5vw}
.site-hero{display:grid;grid-template-columns:minmax(340px,1.15fr) minmax(460px,.95fr);border-bottom:1px solid var(--line-soft);background-image:radial-gradient(var(--line-soft) 1px,transparent 1px);background-size:22px 22px}
.site-hero-copy{padding:96px 7vw 72px;display:flex;flex-direction:column;justify-content:center}
.site-kicker{margin:0 0 18px;font-family:var(--mono);font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--accent)}
.site-title{font-family:var(--serif);font-size:88px;line-height:.9;letter-spacing:-.04em;margin:0;max-width:680px;font-weight:400}
.site-title-ital{display:block;font-style:italic;color:var(--accent)}
.site-ital{font-style:italic;color:var(--accent)}
.site-lede{font-family:var(--serif);font-style:italic;font-size:24px;line-height:1.38;color:var(--ink-soft);max-width:560px;margin:24px 0 0}
.site-actions{display:flex;flex-wrap:wrap;gap:12px;margin-top:32px}
.site-actions-center{justify-content:center}
.site-primary,.site-secondary{display:inline-flex;align-items:center;min-height:44px;padding:0 20px;border-radius:6px;font-size:14.5px;font-weight:500}
.site-primary{background:var(--accent);color:var(--on-fill);font-weight:600}.site-primary:hover{background:var(--accent-hi)}
.site-secondary{border:1px solid var(--line);color:var(--ink)}.site-secondary:hover{border-color:var(--ink-muted)}
.site-fineprint{margin:18px 0 0;font-family:var(--mono);font-size:11px;letter-spacing:.04em;color:var(--ink-muted)}
.site-dots>span+span::before{content:"\00B7";margin:0 .6em;color:var(--ink-muted)}
.site-graph{position:relative;background:var(--bg-deep);padding:88px 5vw 60px;border-left:1px solid var(--line-soft)}
.site-graph-head{display:flex;align-items:flex-end;justify-content:space-between;gap:24px;margin-bottom:22px}
.site-graph-label{font-family:var(--mono);font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-muted)}
.site-graph-state{font-family:var(--mono);font-size:10px;letter-spacing:.12em;color:var(--ok)}
.site-domain-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.site-domain-card{min-height:104px;border:1px solid var(--line);border-top:2px solid var(--accent);border-radius:7px;background:var(--panel);padding:14px;display:flex;flex-direction:column;justify-content:space-between}
.site-domain-card:nth-child(3n+2){border-top-color:var(--ok)}.site-domain-card:nth-child(3n){border-top-color:var(--ink-muted)}
.site-domain-kind{font-family:var(--mono);font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-muted)}
.site-domain-title{font-family:var(--serif);font-size:19px;line-height:1.25;margin:16px 0 0;font-weight:400}
.site-section{padding:88px 0}
.site-section-title{font-family:var(--serif);font-size:56px;line-height:1;letter-spacing:-.03em;margin:0 0 8px;font-weight:400;max-width:820px}
.site-dim{display:flex;align-items:center;width:100%;color:var(--ink-muted)}
.site-dim::before,.site-dim::after{content:"";flex:1;height:1px;background:var(--line)}
.site-dim-label{font-family:var(--mono);font-size:10px;letter-spacing:.16em;text-transform:uppercase;padding:0 12px;white-space:nowrap}
.site-pillar-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));border-top:1px solid var(--line);margin-top:28px}
.site-pillar{padding:28px 28px 32px;border-right:1px solid var(--line)}.site-pillar:last-child{border-right:0}
.site-pillar-index{margin:0;font-family:var(--mono);font-size:10.5px;letter-spacing:.16em;text-transform:uppercase;color:var(--ink-muted)}
.site-pillar-title{font-family:var(--serif);font-size:30px;letter-spacing:-.02em;margin:22px 0 10px;font-weight:400}
.site-pillar-body{font-size:14.5px;color:var(--ink-soft);line-height:1.6;margin:0}
.site-heal{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:40px}
.site-heal-title{font-family:var(--serif);font-size:58px;line-height:1;letter-spacing:-.035em;margin:0 0 14px;font-weight:400;max-width:760px}
.site-heal-kicker{font-family:var(--serif);font-style:italic;font-size:16px;color:var(--ink-soft);margin:28px 0 0;padding-top:24px;border-top:1px solid var(--line)}
.site-split{display:grid;grid-template-columns:1fr 1fr;gap:48px;align-items:center}
.site-split-title{font-family:var(--serif);font-size:52px;line-height:1.02;letter-spacing:-.03em;margin:0;font-weight:400}
.site-feat-list{list-style:none;padding:0;margin:24px 0 0}
.site-feat{display:flex;gap:14px;padding:16px 0;border-top:1px solid var(--line)}
.site-feat-index{font-family:var(--serif);font-style:italic;font-size:22px;color:var(--accent);min-width:30px}
.site-feat-title{display:block;font-size:15px;font-weight:600;color:var(--ink);margin-bottom:3px}
.site-feat-body{font-size:13.5px;color:var(--ink-soft);line-height:1.55}
.site-chain-card{background:var(--bg-deep);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.site-chain-head{padding:10px 14px;border-bottom:1px solid var(--line);font-family:var(--mono);font-size:10.5px;letter-spacing:.08em;color:var(--ink-muted)}
.site-chain{list-style:none;margin:0;padding:18px}
.site-chain-node{display:flex;align-items:baseline;gap:14px;padding:12px 14px;border:1px solid var(--line);border-radius:7px;background:var(--panel)}.site-chain-node+.site-chain-node{margin-top:10px}
.site-chain-kind{font-family:var(--mono);font-size:9.5px;letter-spacing:.14em;text-transform:uppercase;color:var(--accent);min-width:96px}
.site-chain-name{font-family:var(--serif);font-size:18px}
.site-skill{background:var(--bg-deep);border:1px solid var(--line);border-radius:10px;padding:20px 22px;font-family:var(--mono);font-size:12.5px;line-height:1.75;color:var(--ink-soft)}
.site-skill-line{display:block}.site-skill-line-in{padding-left:1.5em}.site-skill-line-deep{padding-left:3em}
.site-skill-key{color:var(--cyan)}.site-skill-str{color:var(--ok)}.site-skill-pun{color:var(--ink-muted)}
.site-skill-note{margin:14px 0 0;font-family:var(--mono);font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-muted)}
.site-boundary-section{background:var(--bg-deep);border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:88px 0}
.site-boundary{display:grid;grid-template-columns:1fr 96px 1fr;align-items:stretch;margin-top:30px}
.site-boundary-side{padding:22px 24px;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
.site-boundary-inside{border-color:var(--ok)}
.site-boundary-tag{margin:0 0 14px;font-family:var(--mono);font-size:9px;letter-spacing:.16em;text-transform:uppercase;color:var(--ok)}
.site-boundary-outside .site-boundary-tag{color:var(--accent)}
.site-boundary-tag-sync{margin-top:18px;padding-top:14px;border-top:1px dashed var(--line)}
.site-boundary-list{list-style:none;margin:0;padding:0}
.site-boundary-item{padding:9px 0;border-top:1px solid var(--line-soft)}.site-boundary-item:first-child{border-top:0}
.site-boundary-name{display:block;font-size:13.5px;font-weight:500;color:var(--ink)}
.site-boundary-out .site-boundary-name{color:var(--accent)}
.site-boundary-detail{display:block;font-family:var(--mono);font-size:10.5px;color:var(--ink-soft);margin-top:3px;line-height:1.5}
.site-boundary-gap{position:relative;display:grid;place-items:center}
.site-boundary-wire{position:relative;display:block;width:100%;height:2px;background:linear-gradient(90deg,var(--ok),var(--accent))}
.site-boundary-label{position:absolute;top:12px;left:50%;transform:translateX(-50%);white-space:nowrap;font-family:var(--mono);font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-muted)}
.site-boundary-foot{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-top:24px;padding-top:18px;border-top:1px solid var(--line-soft);font-size:13px;color:var(--ink-soft);line-height:1.6}
.site-boundary-foot a{color:var(--ink);border-bottom:1px solid var(--accent)}
.site-closing{padding:120px 0;text-align:center;border-top:1px solid var(--line-soft)}
.site-closing-title{font-family:var(--serif);font-size:88px;line-height:.95;letter-spacing:-.04em;margin:0 0 10px;font-weight:400}
.site-closing-copy{font-family:var(--serif);font-style:italic;font-size:22px;color:var(--ink-soft);margin:0 auto 32px;max-width:560px}
.site-page-main{min-height:calc(100vh - 136px);padding:94px 7vw 100px}
.site-page-header{max-width:900px}
.site-page-title{font-family:var(--serif);font-size:56px;line-height:1;letter-spacing:-.035em;margin:0;font-weight:400}
.site-page-lede{font-family:var(--serif);font-style:italic;font-size:21px;line-height:1.45;color:var(--ink-soft);margin:24px 0 0;max-width:820px}
.site-page-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));margin-top:54px;border-top:1px solid var(--line)}
.site-page-card{min-height:230px;padding:26px;border-right:1px solid var(--line);border-bottom:1px solid var(--line);background:var(--panel)}.site-page-card:last-child{border-right:0}
.site-card-kicker{font-family:var(--mono);font-size:10px;letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}
.site-card-title{font-family:var(--serif);font-size:23px;margin:32px 0 12px;font-weight:400}
.site-card-body{color:var(--ink-soft);font-size:14px;line-height:1.65;margin:0}
.site-card-status{margin-top:24px;padding-top:12px;border-top:1px solid var(--line);font-family:var(--mono);font-size:10px;letter-spacing:.12em;color:var(--ink-muted)}
.site-footer{padding:56px 5vw 64px;border-top:1px solid var(--line-soft);background:var(--bg-deep)}
.site-foot-grid{display:grid;grid-template-columns:1.6fr 1fr 1fr;gap:32px}
.site-foot-tag{font-family:var(--serif);font-style:italic;font-size:17px;color:var(--ink-soft);max-width:320px;line-height:1.4;margin:14px 0 0}
.site-foot-head{margin:0 0 12px;font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-muted)}
.site-foot-link{display:block;font-size:13.5px;color:var(--ink-soft);padding:4px 0}.site-foot-link:hover{color:var(--ink)}
.site-foot-base{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px 20px;margin-top:44px;padding-top:24px;border-top:1px solid var(--line-soft);font-family:var(--mono);font-size:10.5px;color:var(--ink-muted);letter-spacing:.06em;text-transform:uppercase}
@media(max-width:1100px){.site-hero{grid-template-columns:1fr}.site-graph{border-left:0;border-top:1px solid var(--line-soft)}.site-title{font-size:68px}.site-split,.site-boundary,.site-boundary-foot,.site-foot-grid{grid-template-columns:1fr}.site-boundary-gap{height:60px}.site-boundary-wire{width:2px;height:100%;background:linear-gradient(180deg,var(--ok),var(--accent))}.site-page-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:760px){.site-nav{height:auto;min-height:64px;padding:10px 18px;flex-wrap:wrap;gap:8px 14px}.site-nav-links{order:3;width:100%;overflow:auto;margin:0}.site-nav-link{white-space:nowrap}.site-access{margin-left:auto}.site-hero-copy{padding:72px 24px 56px}.site-title{font-size:48px}.site-lede{font-size:19px}.site-graph{padding:56px 24px 42px}.site-domain-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.site-section{padding:56px 0}.site-section-title,.site-heal-title,.site-split-title{font-size:38px}.site-pillar-grid{grid-template-columns:1fr}.site-pillar{border-right:0;border-bottom:1px solid var(--line)}.site-heal{padding:24px}.site-closing{padding:72px 0}.site-closing-title{font-size:48px}.site-page-main{padding:56px 24px 70px}.site-page-grid{grid-template-columns:1fr}.site-page-card{border-right:0}.site-page-title{font-size:40px}.site-footer{padding:40px 24px 48px}}
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
    if any(_root not in snapshot.cells for _root in {root_id, *roles.values()}):
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


OFFER_DEFAULT_DISPLAY = "Free during beta"

PRIVACY_SENTENCE = (
    "When cloud sync is on, ArchHub keeps a copy of your brain on our servers "
    "so it can reach your other devices and your firm. That copy is not "
    "end-to-end encrypted, and ArchHub's systems can read it."
)


def offer_display_text(offer):
    """The one public price sentence, taken from the cockpit-owned offer."""
    if offer is None:
        return OFFER_DEFAULT_DISPLAY
    try:
        display = str(offer["display"]).strip()
        monetary = bool(offer["monetary"])
    except (KeyError, TypeError) as exc:
        raise InvalidCell("offer record needs display and monetary") from exc
    if not display:
        raise InvalidCell("offer record has no display text")
    if monetary:
        raise InvalidCell("a monetary offer is not admitted on the public site")
    return display


def _page_specs(offer_display=OFFER_DEFAULT_DISPLAY):
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
            offer_display,
            "Every shipped feature is free while the product is in beta. No plan, checkout, subscription or commercial promise is offered yet.",
            ((
                "STATUS", offer_display,
                "Work is focused on making the application coherent, secure, recoverable and usable before any price is set.",
                "NO MONETARY EFFECTS ENABLED",
            ),),
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
                ("04", "What cloud sync holds", PRIVACY_SENTENCE + " Recognised API-key formats are blocked from upload. Deleting your cloud brain removes your personal copy; entries you shared with a firm are not removed.", "CLOUD SYNC IS OPT-IN"),
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
    offer=None,
) -> UniversalWebsiteBuild:
    """Compose the public lens, then make it reachable from the application."""
    offer_display = offer_display_text(offer)
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
        ("Features", "/website/features"),
        ("Pricing", "/website/pricing"),
        ("Changelog", "/website/changelog"),
        ("Security", "/website/security"),
        ("Community", "/website/community"),
    )

    def brand() -> str:
        return element(
            "a", "site-brand", attrs={"href": "/website"},
            children=(
                element("span", text="Arch"),
                element("span", "site-brand-mark", text="Hub"),
            ),
        )

    def navigation(path: str, token: str) -> str:
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
            "a", "site-access", text="Sign in", attrs=access_attributes,
        )
        return element(
            "nav", "site-nav", attrs={"aria-label": "Primary"},
            children=(brand(), nav_list, access),
            root_id="app:website:nav:%s" % token,
        )

    def link(class_name: str, text: str, href: str) -> str:
        return element("a", class_name, text=text, attrs={"href": href})

    def dots(tag: str, class_name: str, parts) -> str:
        """One mono line whose parts the stylesheet separates with a dot."""
        return element(
            tag, class_name + " site-dots",
            children=tuple(element("span", text=part) for part in parts),
        )

    def accent_line(tag: str, class_name: str, parts, accent_class="site-ital") -> str:
        """A heading whose accented words the design sets in italic."""
        return element(
            tag, class_name,
            children=tuple(
                element("span", accent_class if accent else "", text=part)
                for part, accent in parts
            ),
        )

    def divider(parts) -> str:
        return element("div", "site-wrap", children=(
            element("div", "site-dim", children=(
                dots("span", "site-dim-label", parts),
            )),
        ))

    def feature_list(items) -> str:
        return element("ul", "site-feat-list", children=tuple(
            element("li", "site-feat", children=(
                element("span", "site-feat-index", text=index),
                element("div", children=(
                    element("strong", "site-feat-title", text=title),
                    element("span", "site-feat-body", text=body),
                )),
            ))
            for index, title, body in items
        ))

    def boundary_rows(rows, item_class="site-boundary-item") -> str:
        return element("ul", "site-boundary-list", children=tuple(
            element("li", item_class, children=(
                element("strong", "site-boundary-name", text=name),
                element("span", "site-boundary-detail", text=detail),
            ))
            for name, detail in rows
        ))

    def footer_column(heading: str, links) -> str:
        return element("div", children=(
            element("p", "site-foot-head", text=heading),
            *(link("site-foot-link", label, href) for label, href in links),
        ))

    footer = element(
        "footer", "site-footer", children=(
            element("div", "site-wrap", children=(
                element("div", "site-foot-grid", children=(
                    element("div", children=(
                        brand(),
                        element("p", "site-foot-tag", text="A drafting table for AI."),
                    )),
                    footer_column("Product", (
                        ("Features", "/website/features"),
                        ("Pricing", "/website/pricing"),
                        ("Changelog", "/website/changelog"),
                    )),
                    footer_column("Company", (
                        ("Security", "/website/security"),
                        ("Community", "/website/community"),
                        ("Sign in", "/website/signin"),
                    )),
                )),
                element("div", "site-foot-base", children=(
                    element("span", text="ArchHub is in beta"),
                    element("span", text="Drafted, not generated"),
                )),
            )),
        ),
        root_id="app:website:footer",
    )

    home_title = scalar("app:website:text:home:title", "Drafted, not generated.")
    route_title_roots["/website"] = home_title
    route_path_roots["/website"] = scalar(
        "app:website:path:home", "/website"
    )
    offer_root = scalar("app:website:text:offer:display", offer_display)
    home_nav = navigation("/website", "home")
    hero_copy = element("div", "site-hero-copy", children=(
        element("p", "site-kicker", text="Graph-first AI workspace for AEC"),
        element("h1", "site-title", children=(
            element("span", text="Drafted, "),
            element("span", "site-title-ital", text="not generated."),
        )),
        element(
            "p", "site-lede",
            text="One canvas wires every tool you already use: Revit, Rhino, Speckle, Excel. The AI edits the graph; you approve the line. Your work stays local. Your knowledge stays yours.",
        ),
        element("div", "site-actions", children=(
            link("site-primary", "Sign in", "/website/signin"),
            link("site-secondary", "See how it works", "/website/features"),
        )),
        element("p", "site-fineprint site-dots", children=(
            element("span", text_root=offer_root),
            element("span", text="bring your own key"),
            element("span", text="no credit card"),
            element("span", text="Windows"),
        )),
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
        "section", "site-graph", attrs={"aria-label": "Grand Map domains"},
        children=(
            element("div", "site-graph-head", children=(
                element("span", "site-graph-label", text="The Grand Map"),
                element("span", "site-graph-state", text="Every domain is a node"),
            )),
            element("div", "site-domain-grid", children=card_roots),
        ),
        root_id="app:website:domain-graph",
    )
    complete_hero = element(
        "section", "site-hero", children=(hero_copy, graph_panel),
        root_id="app:website:hero",
    )

    pillars = element(
        "section", "site-section", children=(
            element("div", "site-wrap", children=(
                element("p", "site-kicker", text="The three pillars"),
                accent_line("h2", "site-section-title", (
                    ("Canvas. Composer. ", False), ("Brain.", True),
                )),
                element(
                    "p", "site-lede",
                    text="The whole product is three ideas, and not one of them is a chat box.",
                ),
                element("div", "site-pillar-grid", children=tuple(
                    element("article", "site-pillar", children=(
                        dots("p", "site-pillar-index", (index, role)),
                        element("h3", "site-pillar-title", text=title),
                        element("p", "site-pillar-body", text=body),
                    ))
                    for index, role, title, body in (
                        ("01", "The surface", "Canvas", "Every action is a node; every node is replayable. Drag a parameter and the chain downstream re-runs. Nothing happens that you can't see, trace, or undo."),
                        ("02", "The hand", "Composer", "Talk to the project. The AI proposes edits to the graph; you approve the line before it's drawn. Set out, don't ask out: review is the default, not an afterthought."),
                        ("03", "The memory", "Brain", "Persistent memory and reusable skills that grow with your firm. Save any thread as a skill: a graph-held assembly you own, with the work it was learned from and the evidence that earned it. No marketplace lock-in."),
                    )
                )),
            )),
        ),
        root_id="app:website:pillars",
    )

    self_heal = element(
        "section", "site-section", children=(
            element("div", "site-wrap", children=(
                element("div", "site-heal", children=(
                    element("p", "site-kicker", text="Self-healing connectors"),
                    accent_line("h2", "site-heal-title", (
                        ("Your CAD ", False), ("tells us", True),
                        (" when it breaks. We listen.", False),
                    )),
                    element(
                        "p", "site-lede",
                        text='No restarts. No "please relaunch Revit." The connector watches the host, reconnects on its own, and tells you what it did.',
                    ),
                    element(
                        "p", "site-heal-kicker",
                        text="You didn't notice. That's the point.",
                    ),
                )),
            )),
        ),
        root_id="app:website:self-heal",
    )

    graph_split = element(
        "section", "site-section", children=(
            element("div", "site-wrap", children=(
                element("div", "site-split", children=(
                    element("div", children=(
                        element("p", "site-kicker", text="The canvas"),
                        accent_line("h2", "site-split-title", (
                            ("A graph you can ", False), ("audit", True),
                            (", not a transcript you have to trust.", False),
                        )),
                        feature_list((
                            ("01", "Replayable by construction", "Re-run any node from any upstream state. The same inputs always draw the same line."),
                            ("02", "Parametric, not one-shot", "Every chat turn becomes a parameter. Nudge a slider; the chain re-runs from that node down."),
                            ("03", "Auditable wires", "Every connection is typed and logged. Hover any wire to see exactly what passed through it."),
                        )),
                    )),
                    element(
                        "aside", "site-chain-card",
                        attrs={"aria-label": "A chain of nodes"},
                        children=(
                            element("div", "site-chain-head", text="sketch to sheet set, as nodes"),
                            element("ul", "site-chain", children=tuple(
                                element("li", "site-chain-node", children=(
                                    element("span", "site-chain-kind", text=kind),
                                    element("span", "site-chain-name", text=name),
                                ))
                                for kind, name in (
                                    ("Read", "sketch.png"),
                                    ("AI", "Extract floors"),
                                    ("Transform", "Build walls"),
                                    ("Compose", "Door schedule"),
                                    ("Output", "Plot sheet set"),
                                )
                            )),
                        ),
                    ),
                )),
            )),
        ),
        root_id="app:website:graph-split",
    )

    skill_lines = (
        ("", (("pun", "{"),)),
        ("in", (("key", '"name"'), ("pun", ": "), ("str", '"Sketch to production"'), ("pun", ","))),
        ("in", (("key", '"purpose"'), ("pun", ": "), ("str", '"sketch to sheet set"'), ("pun", ","))),
        ("in", (("key", '"steps"'), ("pun", ": ["), ("str", '"read"'), ("pun", ", "), ("str", '"extract"'), ("pun", ", "), ("str", '"build"'), ("pun", ","))),
        ("deep", (("str", '"dimension"'), ("pun", ", "), ("str", '"schedule"'), ("pun", ", "), ("str", '"plot"'), ("pun", "],"))),
        ("in", (("key", '"learned_from"'), ("pun", ": "), ("str", '"Tower-A, issue 04"'), ("pun", ","))),
        ("in", (("key", '"released"'), ("pun", ": "), ("str", "true"))),
        ("", (("pun", "}"),)),
    )
    skill_card = element("div", "site-skill", children=tuple(
        element(
            "span",
            "site-skill-line" if not indent else "site-skill-line site-skill-line-" + indent,
            children=tuple(
                element("span", "site-skill-" + kind, text=text)
                for kind, text in tokens
            ),
        )
        for indent, tokens in skill_lines
    ))
    brain_split = element(
        "section", "site-section", children=(
            element("div", "site-wrap", children=(
                element("div", "site-split", children=(
                    element("div", children=(
                        skill_card,
                        dots("p", "site-skill-note", (
                            "Held in your brain", "Purpose, work and evidence",
                            "Recall is by purpose, out of the graph",
                        )),
                    )),
                    element("div", children=(
                        element("p", "site-kicker", text="The brain"),
                        accent_line("h2", "site-split-title", (
                            ("Memory that grows with the ", False), ("firm", True),
                            (", not the vendor.", False),
                        )),
                        feature_list((
                            ("01", "Skills you own", "Save any thread as a skill. Each one carries its purpose, the work it was learned from and the evidence that earned it; a skill without evidence is never promoted."),
                            ("02", "Persistent across projects", "The Brain remembers your standards, from sheet naming to dim styles to detail libraries, and reuses them on the next tower."),
                            ("03", "No marketplace lock-in", "Recall comes out of your own graph, not a marketplace. There is no index and no cache in between: the brain that holds a skill is the brain that recalls it."),
                        )),
                    )),
                )),
            )),
        ),
        root_id="app:website:brain-split",
    )

    boundary = element(
        "section", "site-boundary-section", children=(
            element("div", "site-wrap", children=(
                element("p", "site-kicker", text="Local-first by default"),
                accent_line("h2", "site-section-title", (
                    ("Your work happens here. ", False),
                    ("Your knowledge stays yours.", True),
                )),
                element(
                    "p", "site-lede",
                    text="What stays on your machine, and what crosses when a node asks or when you turn cloud sync on.",
                ),
                element("div", "site-boundary", children=(
                    element("div", "site-boundary-side site-boundary-inside", children=(
                        element("p", "site-boundary-tag", text="Inside your machine"),
                        boundary_rows((
                            ("The canvas", "sessions, nodes and wires"),
                            ("The brain", "your memory and skills, on this machine"),
                            ("Your drawings", "read in place by the connector"),
                            ("Provider keys", "the graph holds where a key lives, never the key; anything that looks like a credential is refused"),
                            ("Skills", "purpose, work and evidence you can read, diff and delete"),
                        )),
                    )),
                    element(
                        "div", "site-boundary-gap", attrs={"aria-hidden": "true"},
                        children=(
                            element("span", "site-boundary-wire", children=(
                                element("span", "site-boundary-label", text="the crossings"),
                            )),
                        ),
                    ),
                    element("div", "site-boundary-side site-boundary-outside", children=(
                        element("p", "site-boundary-tag", text="Leaves, when a node asks"),
                        boundary_rows((
                            ("One model call", "the prompt that node built, to your provider on your key"),
                        ), "site-boundary-item site-boundary-out"),
                        element(
                            "p", "site-boundary-tag site-boundary-tag-sync",
                            text="Leaves, when cloud sync is on",
                        ),
                        boundary_rows((("Your brain", PRIVACY_SENTENCE),)),
                    )),
                )),
                element("div", "site-boundary-foot", children=(
                    element(
                        "span",
                        text="If you can't read what a node does, it doesn't belong on your canvas.",
                    ),
                    element("span", children=(
                        element("span", text="Your provider invoices you directly for model calls. "),
                        link("", "Read the security page", "/website/security"),
                    )),
                )),
            )),
        ),
        root_id="app:website:boundary",
    )

    closing = element(
        "section", "site-closing", children=(
            element("div", "site-wrap", children=(
                element("p", "site-kicker", text="Plotted on Friday, not promised"),
                accent_line("h2", "site-closing-title", (
                    ("Sit down at the ", False), ("drafting table.", True),
                ), accent_class="site-title-ital"),
                element(
                    "p", "site-closing-copy",
                    text="Open the canvas. Wire your first host. Read every sentence aloud to a senior architect; if they nod, you're home.",
                ),
                element("div", "site-actions site-actions-center", children=(
                    link("site-primary", "Sign in", "/website/signin"),
                    link("site-secondary", "Read the changelog", "/website/changelog"),
                )),
            )),
        ),
        root_id="app:website:closing",
    )

    home_main = element(
        "main", "site-main", children=(
            complete_hero,
            pillars,
            divider(("Self-healing connectors",)),
            self_heal,
            divider(("Every step is a node",)),
            graph_split,
            divider(("The brain", "Skills you own")),
            brain_split,
            boundary,
            closing,
        ),
        root_id="app:website:main:home",
    )
    page_roots: dict[str, str] = {
        "/website": element(
            "div", "site-shell", children=(home_nav, home_main, footer),
            root_id="app:website:page:home",
        )
    }

    for path, (title, lede, cards) in _page_specs(offer_display).items():
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
    offer=None,
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
            offer=offer,
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
    "OFFER_DEFAULT_DISPLAY",
    "PRIVACY_SENTENCE",
    "PUBLIC_WEBSITE_ROUTES",
    "UniversalWebsiteBuild",
    "WebsiteDomainBinding",
    "WebsiteProtocol",
    "build_universal_website",
    "ensure_universal_website",
    "offer_display_text",
    "project_universal_website_document",
    "project_website_protocol",
    "read_universal_website",
]
