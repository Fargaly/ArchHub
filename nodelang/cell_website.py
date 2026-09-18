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
from .cell_ui import UIBuilder, UIProtocol, _external_links, render_ui
from .cell_website_meta import (
    META_ROOT,
    RELEASED,
    changelog,
    download_offers,
    downloads,
    hold_artifact,
    offer_download,
    record_release,
)
from .clean_host_catalogue_source import HOST_OPERATION_RECORDS
from .universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell, Snapshot
from .universal_map_import import UniversalMapRegistry
from .website_docs_text import DOCS_PAGES


# The pages every website graph holds. A graph built before the docs pages
# holds exactly these, and is read as it is, never rebuilt.
CORE_WEBSITE_ROUTES = (
    "/website",
    "/website/features",
    "/website/pricing",
    "/website/changelog",
    "/website/security",
    "/website/community",
    "/website/signin",
)
# One page per docs text; the public site serves /website/docs/x at /docs/x/.
DOCS_WEBSITE_ROUTES = tuple("/website/docs/%s" % key for key in DOCS_PAGES)
PUBLIC_WEBSITE_ROUTES = CORE_WEBSITE_ROUTES + DOCS_WEBSITE_ROUTES

WEBSITE_ROOT = "app:website"
WEBSITE_PROTOCOL_PREFIX = "app:website-protocol"
WEBSITE_STYLESHEET_ROOT = "app:website:stylesheet"
WEBSITE_AUDIENCE_ROOT = "app:website:audience:public"
WEBSITE_CLASSIFICATION_ROOT = "app:website:classification:t0-public"
WEBSITE_PURPOSE_ROOT = "app:website:purpose:public-projection"
WEBSITE_SOURCE_ROOT = "app:website:source:universal-lens-decision"

# The repository, and the installer of each download the graph offers, are the
# only addresses outside the site a page may link to; the renderer refuses every
# other external link.
REPOSITORY_URL = "https://github.com/Fargaly/ArchHub"

# The Windows build a new website graph receives. The pages link it only after
# cell_website_meta records the revision as released, holds the installer by
# this pinned address and sha256, and offers it; the address on the page is then
# read back from the graph, never from here. A persisted graph is not changed.
PUBLIC_RELEASE = MappingProxyType({
    "revision": "build-20260916-2105-b914892",
    "summary": (
        "ArchHub desktop preview for Windows, published on GitHub with the "
        "SHA-256 of its installer."
    ),
    "state": RELEASED,
    "url": (
        "https://github.com/Fargaly/ArchHub/releases/download/"
        "build-20260916-2105-b914892/ArchHub-Setup-0.exe"
    ),
    "sha256": "756863d5e6ba3eed302fbda20daea12fdb4ab3d48380ac1a277d86d2714e2daa",
})

# The public name of each host the operation catalogue can name. A host the
# catalogue gains without a label still renders under its own id, and the
# website court names the missing label.
HOST_LABELS = MappingProxyType({
    "autocad": "AutoCAD",
    "blender": "Blender",
    "excel": "Excel",
    "max": "3ds Max",
    "outlook": "Outlook",
    "powerpoint": "PowerPoint",
    "revit": "Revit",
    "rhino": "Rhino",
    "speckle": "Speckle",
    "word": "Word",
})
# The hero canvas shows one host node whose ports are real catalogue operations.
HERO_HOST = "revit"
HERO_HOST_OPERATIONS = ("revit.list_walls", "revit.list_sheets")

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
    # "card" named the home card a binding pointed at. The grid came off the
    # public home on 2026-09-17; the role stays declared so a website
    # published before that still projects from its own graph.
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
:root{--bg-deep:#0a0a0d;--bg:#0e0e11;--panel:#15151a;--soft:#1c1c23;--ink:#ece8e0;--ink-soft:#9b938a;--ink-muted:#8b837a;--line:#26262e;--line-soft:#1e1e24;--accent:#d97757;--accent-soft:#3a2018;--accent-hi:#e8896a;--on-fill:#180f08;--ok:#7ec18e;--cyan:#5fb3b3;--warn:#e5b25a;--err:#e6705f;--serif:"Instrument Serif",Georgia,serif;--sans:"Inter",system-ui,sans-serif;--mono:"JetBrains Mono",ui-monospace,monospace}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:16px;line-height:1.5}a{color:inherit;text-decoration:none}a:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
.site-shell{min-height:100vh;background:var(--bg)}
.site-nav{height:64px;padding:0 5vw;display:flex;align-items:center;gap:28px;border-bottom:1px solid var(--line-soft);background:rgba(14,14,17,.82);backdrop-filter:blur(12px);position:sticky;top:0;z-index:50}
.site-brand{font-family:var(--serif);font-size:20px;letter-spacing:.02em;text-transform:uppercase}.site-brand-mark{color:var(--accent);font-style:italic}
.site-nav-links{margin-left:auto;display:flex;align-items:center;gap:22px;list-style:none;padding:0;margin-right:22px}
.site-nav-link{display:inline-flex;min-height:40px;align-items:center;font-size:13.5px;color:var(--ink-soft);border-bottom:2px solid transparent}.site-nav-link:hover{color:var(--ink)}.site-nav-link[aria-current="page"]{color:var(--ink);border-bottom-color:var(--accent)}
.site-access{border:1px solid var(--line);border-radius:6px;padding:8px 16px;font-size:13.5px;color:var(--ink)}.site-access:hover{border-color:var(--ink-muted)}
.site-access+.site-access{margin-left:-16px}
.site-access-primary{background:var(--accent);border-color:var(--accent);color:var(--on-fill);font-weight:600}.site-access-primary:hover{background:var(--accent-hi);border-color:var(--accent-hi)}
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
.site-hero-art{display:flex;align-items:center;padding:72px 5vw 64px 0}
.site-canvas{width:100%;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden;box-shadow:0 40px 100px rgba(0,0,0,.55)}
.site-canvas-head{display:flex;align-items:center;gap:8px;padding:9px 14px;border-bottom:1px solid var(--line);background:var(--soft)}
.site-canvas-dot{width:8px;height:8px;border-radius:50%;background:var(--line)}
.site-canvas-path{flex:1;text-align:center;padding-right:40px;font-family:var(--mono);font-size:10px;letter-spacing:.08em;color:var(--ink-muted)}
.site-canvas-body{position:relative;height:372px;list-style:none;margin:0;padding:0;background-color:var(--bg-deep);background-image:radial-gradient(var(--line) 1px,transparent 1px);background-size:22px 22px}
.site-node{position:absolute;width:212px;background:var(--panel);border:1px solid var(--line);border-radius:7px;box-shadow:0 8px 24px rgba(0,0,0,.4)}
.site-node-host{left:4%;top:30px}.site-node-ai{left:54%;top:96px}.site-node-review{left:16%;top:236px}
.site-node-head{cursor:grab}.site-node-dragging{z-index:5;box-shadow:0 18px 44px rgba(0,0,0,.65)}.site-wire-ok{border-color:var(--ok)}.site-wire-no{border-color:var(--err)}
.site-node-head{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:6px 10px;border-bottom:1px solid var(--line);background:var(--soft);border-radius:7px 7px 0 0}
.site-node-kind{font-family:var(--mono);font-size:9px;letter-spacing:.16em;text-transform:uppercase;color:var(--cyan)}
.site-node-role{font-family:var(--mono);font-size:9px;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-muted)}
.site-node-body{padding:9px 10px 11px}
.site-node-title{display:block;font-size:13px;font-weight:500;color:var(--ink)}
.site-node-port{display:flex;align-items:center;justify-content:flex-end;gap:6px;margin-top:6px;font-family:var(--mono);font-size:10px;color:var(--ink-soft)}
.site-node-dot{flex:0 0 7px;height:7px;border-radius:50%;background:var(--cyan);box-shadow:0 0 0 2px var(--panel)}.site-node-port[data-out]{cursor:crosshair}.site-node-port[data-in]{flex-direction:row-reverse}
.site-node-host .site-node-kind{color:var(--cyan)}
.site-node-ai .site-node-kind{color:var(--accent)}.site-node-ai .site-node-dot{background:#a98cd6}
.site-node-review .site-node-kind{color:var(--ok)}.site-node-review .site-node-dot{background:var(--ok)}
.site-trust{border-bottom:1px solid var(--line-soft);padding:30px 0 28px}
.site-trust-top{display:flex;align-items:baseline;flex-wrap:wrap;gap:12px 24px;margin-bottom:18px}
.site-trust-fig{display:flex;align-items:baseline;flex-wrap:wrap;gap:9px;margin:0}
.site-trust-n{font-family:var(--serif);font-size:44px;line-height:1;letter-spacing:-.03em;color:var(--accent)}
.site-trust-l{font-size:14px;color:var(--ink)}
.site-trust-sep{align-self:center;width:1px;height:26px;background:var(--line);margin:0 10px}
.site-trust-note{margin:0 0 0 auto;font-family:var(--serif);font-style:italic;font-size:16px;color:var(--ink-soft)}
.site-hosts{display:flex;flex-wrap:wrap;gap:8px;list-style:none;margin:0;padding:0}
.site-host{display:inline-flex;align-items:baseline;gap:7px;padding:5px 11px;border:1px solid var(--line);border-radius:6px;font-family:var(--serif);font-size:19px;color:var(--ink-soft)}
.site-host-ops{font-family:var(--mono);font-size:10.5px;color:var(--ink-muted)}
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
.site-foot-grid{display:grid;grid-template-columns:1.6fr 1fr 1fr 1fr;gap:32px}
.site-foot-tag{font-family:var(--serif);font-style:italic;font-size:17px;color:var(--ink-soft);max-width:320px;line-height:1.4;margin:14px 0 0}
.site-foot-head{margin:0 0 12px;font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-muted)}
.site-foot-link{display:block;font-size:13.5px;color:var(--ink-soft);padding:4px 0}.site-foot-link:hover{color:var(--ink)}
.site-foot-base{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:12px 20px;margin-top:44px;padding-top:24px;border-top:1px solid var(--line-soft);font-family:var(--mono);font-size:10.5px;color:var(--ink-muted);letter-spacing:.06em;text-transform:uppercase}
.site-heal-panel{background:var(--panel);border:1px solid var(--line);border-radius:14px;overflow:hidden}
.site-heal-grid{display:grid;grid-template-columns:1.02fr 1fr}
.site-heal-left{padding:40px;border-right:1px solid var(--line)}
.site-heal-left .site-heal-title{margin:14px 0}
.site-heal-lede{font-family:var(--serif);font-style:italic;font-size:20px;color:var(--ink-soft);line-height:1.4;margin:0;max-width:460px}
.site-heal-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:28px 0 0;padding:24px 0 0;border-top:1px solid var(--line);list-style:none}
.site-heal-k{display:block;font-family:var(--serif);font-size:42px;color:var(--accent);letter-spacing:-.03em;line-height:1}
.site-heal-v{display:block;font-size:13px;color:var(--ink);margin-top:5px}
.site-heal-vs{display:block;font-family:var(--mono);font-size:9.5px;color:var(--ink-muted);letter-spacing:.08em;margin-top:2px}
.site-heal-right{padding:28px;background:var(--bg-deep)}
.site-heal-status{margin:0 0 16px;font-family:var(--mono);font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--ok)}
.site-diff{display:grid;grid-template-columns:1fr auto 1fr;gap:14px;align-items:center;margin-bottom:18px}
.site-diff-box{background:var(--soft);border:1px solid var(--line);border-radius:7px;padding:13px 15px}
.site-diff-label{display:block;font-family:var(--mono);font-size:9px;letter-spacing:.14em;margin-bottom:7px}
.site-diff-before .site-diff-label{color:var(--err)}.site-diff-after .site-diff-label{color:var(--ok)}
.site-diff-line{display:flex;justify-content:space-between;margin-top:6px;font-family:var(--mono);font-size:11px;color:var(--ink-soft)}
.site-diff-before .site-diff-value{color:var(--err)}.site-diff-after .site-diff-value{color:var(--ok)}
.site-diff-key{color:var(--ink-soft)}
.site-diff-arrow{font-family:var(--serif);font-style:italic;font-size:30px;color:var(--accent)}
.site-heal-log{background:#0b0b0e;border:1px solid var(--line-soft);border-radius:7px;padding:10px 15px;min-height:172px}
.site-heal-idle{font-family:var(--serif);font-style:italic;font-size:14px;color:var(--ink-soft);padding:12px 0;margin:0}
.site-heal-foot{margin:12px 0 0;padding:0;border-top:0;text-align:right}
.site-sec-head{display:flex;align-items:baseline;flex-wrap:wrap;gap:20px;margin-bottom:40px}
.site-sec-head-title{font-family:var(--serif);font-size:56px;line-height:1;letter-spacing:-.03em;margin:0;font-weight:400}
.site-sec-head-sub{font-family:var(--serif);font-style:italic;font-size:22px;color:var(--ink-soft)}
@media(max-width:1100px){.site-heal-grid{grid-template-columns:1fr}.site-heal-left{border-right:0;border-bottom:1px solid var(--line)}}
.site-doc-layout{display:grid;grid-template-columns:220px minmax(0,1fr);gap:56px;margin-top:54px;border-top:1px solid var(--line);padding-top:36px}
.site-doc-index{list-style:none;margin:0;padding:0}
.site-doc-nav{position:sticky;top:88px;align-self:start}
.site-doc-index-head{margin:0 0 12px;font-family:var(--mono);font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--ink-muted)}
.site-doc-link{display:block;padding:7px 0 7px 12px;border-left:2px solid var(--line);font-size:13.5px;color:var(--ink-soft)}.site-doc-link:hover{color:var(--ink)}.site-doc-link[aria-current="page"]{color:var(--ink);border-left-color:var(--accent)}
.site-doc-body{max-width:760px}
.site-doc-h2{font-family:var(--serif);font-size:32px;line-height:1.1;letter-spacing:-.02em;margin:44px 0 14px;font-weight:400}.site-doc-body>.site-doc-h2:first-child{margin-top:0}
.site-doc-p{margin:0 0 14px;font-size:15px;line-height:1.7;color:var(--ink-soft)}
.site-doc-list{margin:0 0 16px;padding:0;list-style:none}
.site-doc-item{position:relative;padding:4px 0 4px 26px;font-size:15px;line-height:1.65;color:var(--ink-soft)}
.site-doc-item::before{content:"";position:absolute;left:8px;top:16px;width:7px;height:1px;background:var(--accent)}
.site-doc-step{position:absolute;left:0;top:5px;font-family:var(--mono);font-size:11px;color:var(--accent)}
.site-doc-list-steps .site-doc-item::before{display:none}
.site-doc-code{font-family:var(--mono);font-size:12.5px;color:var(--ink);background:var(--soft);border:1px solid var(--line);border-radius:4px;padding:1px 5px}
.site-doc-table{border:1px solid var(--line);border-radius:8px;overflow:hidden;margin:0 0 18px;background:var(--panel)}
.site-doc-row{display:grid;grid-template-columns:1.1fr 1fr 1.6fr;border-top:1px solid var(--line)}.site-doc-row:first-child{border-top:0}
.site-doc-row-head{background:var(--soft)}.site-doc-row-head .site-doc-cell{font-family:var(--mono);font-size:10px;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-muted)}
.site-doc-cell{padding:10px 14px;font-size:13.5px;line-height:1.55;color:var(--ink-soft)}
@media(max-width:900px){.site-doc-layout{grid-template-columns:1fr;gap:28px}.site-doc-nav{position:static}.site-doc-row{grid-template-columns:1fr}}
.site-brand{display:inline-flex;align-items:center;gap:10px}.site-brand-word{white-space:nowrap}
.site-logo{position:relative;display:inline-block;width:26px;height:26px;flex:none}.site-logo::before{content:"";position:absolute;left:3.2px;top:3.2px;box-sizing:border-box;width:19.7px;height:19.6px;border:1.8px solid var(--accent);border-bottom:0;border-radius:10px 10px 0 0}.site-logo::after{content:"";position:absolute;left:2.4px;top:23.3px;width:21.2px;height:.7px;background:var(--accent);border-radius:1px}
.site-logo-eye{position:absolute;left:10.9px;top:6.8px;box-sizing:border-box;width:4.3px;height:4.3px;border:1px solid var(--accent);border-radius:50%;background:radial-gradient(circle,var(--accent) 0 .7px,var(--bg) .9px)}
.site-ver{font-family:var(--mono);font-size:10.5px;letter-spacing:.06em;color:var(--ink-muted);white-space:nowrap}
.site-sr{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}
.site-wires{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible}
.site-canvas-hint{position:absolute;right:14px;bottom:10px;font-family:var(--mono);font-size:10px;letter-spacing:.06em;color:var(--ink-muted);transition:opacity .3s}
.site-host{cursor:pointer}.site-host[aria-pressed="true"]{border-color:var(--accent);color:var(--ink)}.site-host:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.site-host-detail{margin-top:14px;min-height:62px;padding:12px 16px;border:1px solid var(--line-soft);border-radius:8px;background:var(--panel)}
.site-host-idle{font-family:var(--serif);font-style:italic;font-size:15px;color:var(--ink-soft)}
.site-hd-head{display:flex;align-items:baseline;gap:14px}.site-hd-name{font-family:var(--serif);font-size:22px;color:var(--ink)}.site-hd-sig{font-family:var(--mono);font-size:10.5px;color:var(--ink-muted)}
.site-hd-ops{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.site-hd-op{padding:3px 8px;border:1px solid var(--line);border-radius:4px;font-family:var(--mono);font-size:10.5px;color:var(--ink-soft)}
.site-heal-bar{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:16px}.site-heal-bar .site-heal-status{margin:0}
.site-heal-btn{padding:7px 14px;border:1px solid var(--line);border-radius:6px;background:var(--soft);color:var(--ink);font:inherit;font-size:12.5px;cursor:pointer}.site-heal-btn:disabled{opacity:.6;cursor:default}
.site-logline{display:grid;grid-template-columns:62px 68px 1fr;gap:10px;padding:5px 0;border-bottom:1px solid var(--line-soft);font-family:var(--mono);font-size:11px}.site-lt{color:var(--ink-muted)}.site-lm{color:var(--ink)}
.site-dv-bad{color:var(--err)}.site-dv-good{color:var(--ok)}.site-dv-pending{color:var(--ink-muted)}
.site-heal-footer{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-top:12px}.site-heal-clock{font-family:var(--mono);font-size:10px;letter-spacing:.08em;color:var(--ink-muted)}
.site-price-note{max-width:640px;margin:-16px 0 0;font-size:15px;line-height:1.6;color:var(--ink-soft)}
@media(max-width:1100px){.site-hero{grid-template-columns:1fr}.site-hero-art{padding:0 7vw 72px}.site-title{font-size:68px}.site-split,.site-boundary,.site-boundary-foot,.site-foot-grid{grid-template-columns:1fr}.site-boundary-gap{height:60px}.site-boundary-wire{width:2px;height:100%;background:linear-gradient(180deg,var(--ok),var(--accent))}.site-page-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}
@media(max-width:760px){.site-nav{position:static;height:auto;min-height:64px;padding:10px 18px;flex-wrap:wrap;gap:8px 12px}.site-nav-links{order:3;width:100%;flex-wrap:wrap;gap:0 18px;margin:0}.site-nav-link{white-space:nowrap}.site-access{margin-left:auto;padding:8px 12px}.site-access+.site-access{margin-left:0}.site-hero-copy{padding:72px 24px 56px}.site-title{font-size:48px}.site-lede{font-size:19px}.site-hero-art{padding:0 24px 56px}.site-canvas-body{padding:22px 16px 26px}.site-canvas-body{height:auto;padding:18px 14px}.site-node{position:relative;left:auto;top:auto;width:100%}.site-node+.site-node{margin-top:16px}.site-canvas-hint{position:static;display:block;margin-top:12px}.site-wires{display:none}.site-trust-n{font-size:36px}.site-trust-note{margin-left:0}.site-section{padding:56px 0}.site-section-title,.site-heal-title,.site-split-title{font-size:38px}.site-pillar-grid{grid-template-columns:1fr}.site-pillar{border-right:0;border-bottom:1px solid var(--line)}.site-heal{padding:24px}.site-closing{padding:72px 0}.site-closing-title{font-size:48px}.site-page-main{padding:56px 24px 70px}.site-page-grid{grid-template-columns:1fr}.site-page-card{border-right:0}.site-page-title{font-size:40px}.site-footer{padding:40px 24px 48px}}
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
    """The public website is published from this Grand Map domain.

    The home drew one card per domain until the founder read the live
    site against the design on 2026-09-17: the design carries no such
    section, so the grid came off. The binding stays, because it is
    what ties the public site to the map it is published from, and it
    is now a graph fact only - no card, nothing on any page.
    """

    root_id: str
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


def website_download(snapshot: Snapshot):
    """The download the pages link: the newest proven offer, or None.

    An offer that fails its proof links no download; the site still builds, as
    website_external_links admits no address for it.
    """
    try:
        offers = download_offers(snapshot)
    except InvalidCell:
        return None
    return offers[-1] if offers else None


def website_external_links(snapshot: Snapshot) -> frozenset[str]:
    """The addresses outside the site a page may link to, out of the graph.

    The repository, and the address of every download the graph proves. When
    an offer fails its proof no download address is admitted: a page that
    links one is refused, and a page that links none still renders.
    """
    try:
        offers = download_offers(snapshot)
    except InvalidCell:
        offers = ()
    return frozenset({REPOSITORY_URL, *(offer.url for offer in offers)})


def _record_public_release(store: CellStore, release) -> None:
    """Enter a release through the changelog and download rules of the graph."""
    if release is None:
        return
    revision = release["revision"]
    if "%s:release:%s" % (META_ROOT, revision) not in store.snapshot().cells:
        record_release(
            store, revision=revision, summary=release["summary"],
            state=release["state"],
        )
    artifact_root = "%s:artifact:%s" % (META_ROOT, revision)
    if artifact_root not in store.snapshot().cells:
        artifact_root = hold_artifact(
            store, revision=revision, url=release["url"],
            sha256=release["sha256"],
        )
    if (
        release["state"] == RELEASED
        and revision not in downloads(store.snapshot())
    ):
        offer_download(store, artifact_root=artifact_root, revision=revision)


def host_operation_counts(records=HOST_OPERATION_RECORDS):
    """Each host of the operation catalogue with its operation count, most first.

    Counted from the records, so no figure on the page is typed.
    """
    counts: dict[str, int] = {}
    for record in records:
        host = str(record.get("host") or "").strip()
        if not host:
            raise InvalidCell("a host operation record names no host")
        counts[host] = counts.get(host, 0) + 1
    return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _offered_addresses(snapshot: Snapshot) -> frozenset[str]:
    """The plain https address each offered artifact Cell holds, proven or not.

    Only the website's verification admits these. The page projection admits
    proven addresses alone, so a broken offer refuses the pages that link it,
    never the website read that opening the app depends on.
    """
    addresses: set[str] = set()
    for revision in downloads(snapshot):
        cell = snapshot.cells.get("%s:artifact:%s" % (META_ROOT, revision))
        if cell is None or cell.link0 != NULL_CELL_ID or cell.link1 != NULL_CELL_ID:
            continue
        try:
            addresses |= _external_links((bytes(cell.atom).decode("utf-8"),))
        except (UnicodeDecodeError, InvalidCell):
            continue
    return frozenset(addresses)


def _release_cards(releases):
    """One card per released revision, newest first, read from the changelog."""
    return tuple(
        ("RELEASED", note.revision, note.summary, "RELEASED REVISION")
        for note in reversed(tuple(releases))
    )


_DOC_STEP = re.compile(r"[0-9]+[.] ")
_CODE_MARK = chr(96)


def _docs_pages():
    """The docs texts a new website graph receives, keyed by page."""
    return DOCS_PAGES


def _page_specs(offer_display=OFFER_DEFAULT_DISPLAY, releases=()):
    return {
        "/website/features": (
            "One canvas. Every tool you already use.",
            "ArchHub is a graph you can read. Hosts, AI drafts, memory and permissions sit on one canvas as nodes and wires, so you can see what happened and why.",
            (),
        ),
        "/website/pricing": (
            offer_display,
            "Every shipped feature is free while the product is in beta. No plan, checkout, subscription or commercial promise is offered yet.",
            (),
        ),
        "/website/changelog": (
            "Released builds, not intentions",
            "An entry appears here only for a released revision, and a download is offered only for a released build. Work in progress stays off this page.",
            (
                *_release_cards(releases),
                ("RULE", "Released or absent", "The changelog lists released revisions only. A draft is not a public claim, and a build that is not released cannot be offered for download.", "RELEASED REVISIONS ONLY"),
                ("UPDATES", "The app checks for you", "The desktop app looks for a newer public release and checks the installer against its published checksum before staging it. An older or equal build is never staged.", "NEWER BUILDS ONLY"),
                ("WINDOWS", "Where the installer lives", "The Windows installer is published on the ArchHub releases page on GitHub, the same place the app checks for updates.", "GITHUB RELEASES"),
            ),
        ),
        "/website/security": (
            "Nothing runs without a reason you can see",
            "Every read, change and outside call has to pass a rule that lives in the graph. Anything the graph does not admit is refused.",
            (),
        ),
        "/website/community": (
            "Share with your firm, on your terms",
            "Community in ArchHub starts inside a firm: groups you join with a code, and shared brain entries that wait for your judgement before they count. A public network is not open yet.",
            (
                ("01", "Groups with single-use codes", "The owner of a group issues join codes. The graph keeps only a fingerprint of each code, and a code that has been used cannot be used again.", "OWNER ISSUES CODES"),
                ("02", "Nothing lands unreviewed", "Entries that arrive from a peer are held in quarantine with their origin attached, and stay out of your brain until a judgement admits them. A rejection is kept, so the same claim is not argued twice.", "QUARANTINE BEFORE MERGE"),
                ("STATUS", "No public network yet", "Sharing beyond your firm is not open. When it is, this page will say so.", "FIRM SHARING FIRST"),
            ),
        ),
        "/website/signin": (
            "Sign in from the desktop app",
            "Your ArchHub identity is your email account, not your machine. You sign in from the app, which opens your browser on the ArchHub cloud sign-in page.",
            (
                ("01", "Email link or Google", "Choose an email link or Google in your browser. A one-time code returns to the app that started the sign-in and is exchanged for a session using PKCE.", "BROWSER SIGN-IN"),
                ("02", "An account, not a device", "Your account is your email address, and what the app opens for you is set on that account, so a new machine signs in to the same account.", "EMAIL IS THE IDENTITY"),
                ("03", "No password on this site", "This website shows no sign-in form and keeps no session. Download the app and sign in from there.", "SIGN IN IN THE APP"),
            ),
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
    _record_public_release(store, PUBLIC_RELEASE)
    download = website_download(store.snapshot())
    host_counts = host_operation_counts()
    released = tuple(changelog(store.snapshot()))
    release_label = released[-1].revision if released else ""
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
                children=(), root_id=None, attr_roots=None):
        return ui.element(
            tag,
            class_name=class_name,
            text=text,
            text_root=text_root,
            attributes=attrs,
            attribute_roots=attr_roots,
            children=children,
            element_id=root_id,
        )

    def download_link(class_name: str) -> tuple[str, ...]:
        """The Windows download, its address read from the artifact Cell."""
        if download is None:
            return ()
        return (element(
            "a", class_name, text="Download for Windows",
            attr_roots={"href": download.artifact_root},
        ),)

    nav_labels = (
        ("Features", "/website/features"),
        ("Connectors", "/website/docs/connectors"),
        ("Brain", "/website/docs/brain"),
        ("Security", "/website/security"),
        ("Pricing", "/website/pricing"),
    )

    def brand() -> str:
        return element(
            "a", "site-brand", attrs={"href": "/website"},
            children=(
                element("span", "site-logo", attrs={"aria-hidden": "true"}, children=(
                    element("span", "site-logo-eye"),
                )),
                element("span", "site-brand-word", children=(
                    element("span", text="Arch"),
                    element("span", "site-brand-mark", text="Hub"),
                )),
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
        create = element(
            "a", "site-access site-access-primary", text="Create account",
            attrs={"href": "/website/signin"},
        )
        version = (
            (element("span", "site-ver", text=release_label),)
            if release_label else ()
        )
        return element(
            "nav", "site-nav", attrs={"aria-label": "Primary"},
            children=(brand(), nav_list, *version, access, create),
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

    def footer_column(heading: str, links, extra=()) -> str:
        return element("div", children=(
            element("p", "site-foot-head", text=heading),
            *(link("site-foot-link", label, href) for label, href in links),
            *extra,
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
                        ("Canvas", "/website/features"),
                        ("Brain", "/website/docs/brain"),
                        ("Connectors", "/website/docs/connectors"),
                        ("Pricing", "/website/pricing"),
                        ("Changelog", "/website/changelog"),
                        ("Docs", "/website/docs/getting-started"),
                    )),
                    footer_column("Company", (
                        ("Community", "/website/community"),
                        ("Security", "/website/security"),
                        ("Sign in", "/website/signin"),
                    )),
                    footer_column(
                        "Open", (("GitHub", REPOSITORY_URL),),
                        download_link("site-foot-link"),
                    ),
                )),
                element("div", "site-foot-base", children=(
                    element("span", text="\u00a9 2026 ArchHub"),
                    *(
                        (element("span", text="Built from %s" % release_label),)
                        if release_label else ()
                    ),
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
            text=(
                "One canvas wires the tools you already use: %s. The AI edits "
                "the graph; you approve the line. Your work stays local. Your "
                "knowledge stays yours."
            ) % ", ".join(HOST_LABELS.get(host, host) for host, _ in host_counts),
        ),
        element("div", "site-actions", children=(
            *download_link("site-primary"),
            link("site-secondary", "Sign in", "/website/signin"),
        )),
        element("p", "site-fineprint site-dots", children=(
            element("span", text_root=offer_root),
            element("span", text="bring your own key"),
            element("span", text="no credit card"),
            element("span", text="Windows"),
        )),
    ))

    operation_labels = {
        str(record.get("op_id")): str(record.get("label"))
        for record in HOST_OPERATION_RECORDS
    }

    def canvas_node(variant, key, kind, role, title, ports):
        return element(
            "li", "site-node site-node-" + variant, attrs={"data-node": key},
            children=(
                element("div", "site-node-head", children=(
                    element("span", "site-node-kind", text=kind),
                    element("span", "site-node-role", text=role),
                )),
                element("div", "site-node-body", children=(
                    element("strong", "site-node-title", text=title),
                    *(
                        element(
                            "span", "site-node-port",
                            text=label, attrs={direction: port, "data-sig": signal},
                            children=(element("span", "site-node-dot"),),
                        )
                        for label, direction, port, signal in ports
                    ),
                )),
            ),
        )

    host_ports = tuple(
        operation_labels[op_id]
        for op_id in HERO_HOST_OPERATIONS
        if op_id in operation_labels
    )
    hero_art = element(
        "div", "site-hero-art", children=(
            element(
                "aside", "site-canvas", attrs={"aria-label": "A node canvas"},
                children=(
                    element("div", "site-canvas-head", children=(
                        element("span", "site-canvas-dot"),
                        element("span", "site-canvas-dot"),
                        element("span", "site-canvas-dot"),
                        element(
                            "span", "site-canvas-path",
                            text="canvas, an illustration",
                        ),
                    )),
                    element(
                        "ul", "site-canvas-body",
                        attrs={
                            "data-canvas": "hero",
                            "data-wires": "host.op0>ai.source ai.proposal>review.proposal",
                        },
                        children=(
                            canvas_node(
                                "host", "host", "Host", "read",
                                HOST_LABELS.get(HERO_HOST, HERO_HOST),
                                tuple(
                                    (label, "data-out", "op%d" % index, "elements")
                                    for index, label in enumerate(host_ports)
                                ),
                            ),
                            canvas_node(
                                "ai", "ai", "AI", "Composer",
                                "Proposes an edit to the graph", (
                                    ("source", "data-in", "source", "elements"),
                                    ("proposal", "data-out", "proposal", "proposal"),
                                ),
                            ),
                            canvas_node(
                                "review", "review", "Review", "You",
                                "Approve the line", (
                                    ("proposal", "data-in", "proposal", "proposal"),
                                    ("drawn on approval", "data-out", "approved", "approval"),
                                ),
                            ),
                            element(
                                "li", "site-canvas-hint", attrs={"data-hint": "hero"},
                                text="Drag a node, or drag from an output to wire it",
                            ),
                        ),
                    ),
                ),
            ),
        ),
        root_id="app:website:hero-canvas",
    )
    complete_hero = element(
        "section", "site-hero", children=(hero_copy, hero_art),
        root_id="app:website:hero",
    )

    operation_total = sum(count for _, count in host_counts)
    host_operations: dict[str, list[str]] = {}
    for record in HOST_OPERATION_RECORDS:
        host_operations.setdefault(str(record.get("host")), []).append(
            str(record.get("label"))
        )

    def figure(count, singular, plural):
        return (
            element("span", "site-trust-n", text=str(count)),
            element(
                "span", "site-trust-l", text=singular if count == 1 else plural,
            ),
        )

    trust = element(
        "section", "site-trust", attrs={"aria-label": "Connectors"},
        children=(
            element("div", "site-wrap", children=(
                element("div", "site-trust-top", children=(
                    element("p", "site-trust-fig", children=(
                        *figure(len(host_counts), "connector", "connectors"),
                        element("span", "site-trust-sep"),
                        *figure(operation_total, "operation", "operations"),
                    )),
                    element(
                        "p", "site-trust-note",
                        text="Counted from the operations an adapter carries out today.",
                    ),
                )),
                element("ul", "site-hosts", attrs={"data-hosts": "catalogue"}, children=tuple(
                    element(
                        "li", "site-host", text=HOST_LABELS.get(host, host),
                        attrs={
                            "role": "button", "tabindex": "0",
                            "aria-pressed": "false",
                            "data-ops": "|".join(host_operations.get(host, ())),
                        },
                        children=(
                            element("span", "site-host-ops", text=str(count)),
                        ),
                    )
                    for host, count in host_counts
                )),
                element(
                    "div", "site-host-detail", attrs={"data-host-detail": "catalogue"},
                    children=(element(
                        "span", "site-host-idle",
                        text="Pick a host to see the operations its adapter carries out today.",
                    ),),
                ),
            )),
        ),
        root_id="app:website:trust",
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

    def diff_box(label: str, side: str) -> str:
        """One side of the design's before and after frame, before any break."""
        return element("div", "site-diff-box site-diff-%s" % side, children=(
            element("span", "site-diff-label", text=label),
            *(
                element("div", "site-diff-line", children=(
                    element("span", "site-diff-key", text=key),
                    element(
                        "span", "site-diff-value", text="-",
                        attrs={"data-" + side[0]: str(index)},
                    ),
                ))
                for index, key in enumerate(("handshake", "rpc port", "session"), 1)
            ),
        ))

    # The design animates a break and its recovery with a script; the export
    # admits no script, so the page holds the design's first, idle frame.
    self_heal = element(
        "section", "site-section", children=(
            element("div", "site-wrap", children=(
                element("div", "site-heal-panel", children=(
                    element("div", "site-heal-grid", children=(
                        element("div", "site-heal-left", children=(
                            element("p", "site-kicker", text="Self-healing connectors"),
                            accent_line("h2", "site-heal-title", (
                                ("Your CAD ", False), ("tells us", True),
                                (" when it breaks. We listen.", False),
                            )),
                            element(
                                "p", "site-heal-lede",
                                text='No restarts. No "please relaunch Revit." The connector watches the host, reconnects on its own, and tells you what it did.',
                            ),
                            element("ul", "site-heal-stats", children=tuple(
                                element("li", children=(
                                    element("span", "site-heal-k", text="-"),
                                    element("span", "site-heal-v", text=name),
                                    element("span", "site-heal-vs", text=window),
                                ))
                                for name, window in (
                                    ("manual restarts", "LAST 7 DAYS"),
                                    ("recovered sessions", "LAST 7 DAYS"),
                                    ("median recovery", "ALL HOSTS"),
                                )
                            )),
                        )),
                        element("div", "site-heal-right", attrs={"data-heal": "timeline"}, children=(
                            element("div", "site-heal-bar", children=(
                                element(
                                    "p", "site-heal-status", text="Connection healthy",
                                    attrs={"data-heal-status": "status"},
                                ),
                                element(
                                    "button", "site-heal-btn",
                                    text="Break the connection \u21ba",
                                    attrs={"type": "button", "data-heal-play": "play"},
                                ),
                            )),
                            element("div", "site-diff", children=(
                                diff_box("BEFORE", "before"),
                                element("span", "site-diff-arrow", text="\u2192"),
                                diff_box("AFTER", "after"),
                            )),
                            element("div", "site-heal-log", attrs={"data-heal-log": "log"}, children=(
                                element(
                                    "p", "site-heal-idle",
                                    text="Idle. The connection is nominal. Break it and watch what happens.",
                                ),
                            )),
                            element("div", "site-heal-footer", children=(
                                element(
                                    "span", "site-heal-clock", text="illustration",
                                    attrs={"data-heal-clock": "clock"},
                                ),
                                element(
                                    "span", "site-heal-kicker site-heal-foot",
                                    text="You didn't notice. That's the point.",
                                    attrs={"data-heal-kicker": "kicker"},
                                ),
                            )),
                        )),
                    )),
                )),
            )),
        ),
        root_id="app:website:self-heal",
    )

    # The founder removed the design's calculator (2026-09-17): the section
    # keeps its head and states the offer the graph holds.
    pricing = element(
        "section", "site-section", attrs={"aria-label": "Pricing"}, children=(
            element("div", "site-wrap", children=(
                element("div", "site-sec-head", children=(
                    element("h2", "site-sec-head-title", text="What it costs"),
                    element("span", "site-sec-head-sub", text_root=offer_root),
                )),
                element(
                    "p", "site-price-note",
                    text="Every shipped feature is free while the product is in beta. No plan, checkout or subscription is offered yet.",
                ),
            )),
        ),
        root_id="app:website:pricing-frame",
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
                    *download_link("site-primary"),
                    link("site-secondary", "Read the docs", "/website/docs/getting-started"),
                )),
            )),
        ),
        root_id="app:website:closing",
    )

    home_main = element(
        "main", "site-main", children=(
            complete_hero,
            trust,
            pillars,
            divider(("Self-healing connectors",)),
            self_heal,
            divider(("Every step is a node",)),
            graph_split,
            divider(("The brain", "Skills you own")),
            brain_split,
            boundary,
            pricing,
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

    releases = changelog(store.snapshot())
    for path, (title, lede, cards) in _page_specs(offer_display, releases).items():
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
        design_sections = {
            "/website/features": (pillars, self_heal, graph_split),
            "/website/pricing": (pricing,),
            "/website/security": (boundary,),
        }.get(path, ())
        page_header = element(
            "header",
            "site-page-header site-sr" if design_sections else "site-page-header",
            children=(
                element("p", "site-kicker", text="ArchHub / public lens"),
                element("h1", "site-page-title", text_root=title_root),
                element("p", "site-page-lede", text=lede),
            ),
        )
        if design_sections:
            main = element(
                "main", "site-main", children=(page_header, *design_sections),
                root_id="app:website:main:%s" % token,
            )
        else:
            main = element(
                "main", "site-page-main", children=(
                    page_header,
                    element("section", "site-page-grid", children=content_cards),
                ),
                root_id="app:website:main:%s" % token,
            )
        page_roots[path] = element(
            "div", "site-shell",
            children=(navigation(path, token), main, footer),
            root_id="app:website:page:%s" % token,
        )

    docs = _docs_pages()

    def inline(value: str) -> tuple[str, ...]:
        """Plain text and code spans, in reading order."""
        parts = value.split(_CODE_MARK)
        if len(parts) % 2 == 0:
            raise InvalidCell("docs text has an unclosed code span")
        return tuple(
            element("span", "site-doc-code" if index % 2 else "", text=part)
            for index, part in enumerate(parts)
            if part
        )

    def docs_blocks(text: str) -> tuple[str, ...]:
        """The docs text as headings, paragraphs, lists and a table."""
        lines = text.split(chr(10))
        blocks = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
            elif line.startswith("## "):
                blocks.append(element("h2", "site-doc-h2", text=line[3:]))
                index += 1
            elif line.startswith("|"):
                rows = []
                while index < len(lines) and lines[index].startswith("|"):
                    cells = [
                        cell.strip()
                        for cell in lines[index].strip().strip("|").split("|")
                    ]
                    if not all(set(cell) <= set("- :") for cell in cells):
                        rows.append(cells)
                    index += 1
                blocks.append(element(
                    "div", "site-doc-table", attrs={"role": "table"},
                    children=tuple(
                        element(
                            "div",
                            "site-doc-row site-doc-row-head" if number == 0
                            else "site-doc-row",
                            attrs={"role": "row"},
                            children=tuple(
                                element(
                                    "span", "site-doc-cell",
                                    attrs={"role": (
                                        "columnheader" if number == 0 else "cell"
                                    )},
                                    children=inline(cell),
                                )
                                for cell in row
                            ),
                        )
                        for number, row in enumerate(rows)
                    ),
                ))
            elif line.startswith("- ") or _DOC_STEP.match(line):
                steps = bool(_DOC_STEP.match(line))
                items = []
                while index < len(lines) and (
                    lines[index].startswith("- ") or _DOC_STEP.match(lines[index])
                ):
                    item = lines[index]
                    if steps:
                        number, _, body = item.partition(". ")
                        children = (
                            element("span", "site-doc-step", text=number),
                            *inline(body),
                        )
                    else:
                        children = inline(item[2:])
                    items.append(element("li", "site-doc-item", children=children))
                    index += 1
                blocks.append(element(
                    "ul",
                    "site-doc-list site-doc-list-steps" if steps else "site-doc-list",
                    children=tuple(items),
                ))
            else:
                paragraph = []
                while index < len(lines) and lines[index].strip() and not (
                    lines[index].startswith(("## ", "|", "- "))
                    or _DOC_STEP.match(lines[index])
                ):
                    paragraph.append(lines[index].strip())
                    index += 1
                blocks.append(element(
                    "p", "site-doc-p", children=inline(" ".join(paragraph)),
                ))
        return tuple(blocks)

    for key, (doc_title, description, text) in docs.items():
        path = "/website/docs/%s" % key
        token = _part(path)
        title_root = scalar("app:website:text:%s:title" % token, doc_title)
        path_root = scalar("app:website:path:%s" % token, path)
        route_title_roots[path] = title_root
        route_path_roots[path] = path_root
        index_links = []
        for other_key, (other_title, _, _) in docs.items():
            other_path = "/website/docs/%s" % other_key
            attributes = {"href": other_path}
            if other_path == path:
                attributes["aria-current"] = "page"
            index_links.append(element("li", children=(
                element("a", "site-doc-link", text=other_title, attrs=attributes),
            )))
        main = element(
            "main", "site-page-main", children=(
                element("header", "site-page-header", children=(
                    element("p", "site-kicker", text="ArchHub / docs"),
                    element("h1", "site-page-title", text_root=title_root),
                    element("p", "site-page-lede", text=description),
                )),
                element("div", "site-doc-layout", children=(
                    element(
                        "nav", "site-doc-nav", attrs={"aria-label": "Docs"},
                        children=(
                            element("p", "site-doc-index-head", text="Docs"),
                            element("ul", "site-doc-index", children=tuple(index_links)),
                        ),
                    ),
                    element("article", "site-doc-body", children=docs_blocks(text)),
                )),
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
        if path not in page_roots:
            continue
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
            (protocol.role("domain"), domain_root),
            (protocol.role("key"), key_root),
        ), relation_id=binding_root)
        domain_binding_roots[key] = WebsiteDomainBinding(
            binding_root, domain_root
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

    external_links = website_external_links(snapshot) | _offered_addresses(snapshot)
    route_roots = _many(members, protocol.role("route"))
    if len(route_roots) not in (
        len(PUBLIC_WEBSITE_ROUTES), len(CORE_WEBSITE_ROUTES),
    ):
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
        render_ui(
            snapshot, ui_protocol, page_root, budget=20_000,
            external_links=external_links,
        )
        routes[path] = route_root
        pages[path] = page_root
        cloud_routes[path] = http_root
        titles[path] = title_root
    if set(routes) not in (set(PUBLIC_WEBSITE_ROUTES), set(CORE_WEBSITE_ROUTES)):
        raise InvalidCell("website public route set drifted")

    binding_roots = _many(members, protocol.role("domain-binding"))
    domain_bindings = {}
    for binding_root in binding_roots:
        binding = read_relation(snapshot, binding_root, budget=32)
        if _one(binding, protocol.role("website"), "binding website") != root_id:
            raise InvalidCell("domain binding belongs to another website")
        key = _text(snapshot, _one(binding, protocol.role("key"), "domain key"))
        domain_root = _one(binding, protocol.role("domain"), "domain root")
        if key in domain_bindings or map_registry.domains.get(key) != domain_root:
            raise InvalidCell("website domain binding is unknown or ambiguous")
        domain_bindings[key] = WebsiteDomainBinding(binding_root, domain_root)
    if set(domain_bindings) != set(map_registry.domains):
        raise InvalidCell(
            "website does not bind every Grand Map domain; a domain "
            "binding is a graph fact and no longer has to be visible "
            "on the home page"
        )

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
    shell = render_ui(
        snapshot, verified.ui_protocol, page_root, budget=20_000,
        external_links=website_external_links(snapshot),
    )
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
    "HOST_LABELS",
    "OFFER_DEFAULT_DISPLAY",
    "PRIVACY_SENTENCE",
    "PUBLIC_RELEASE",
    "PUBLIC_WEBSITE_ROUTES",
    "REPOSITORY_URL",
    "UniversalWebsiteBuild",
    "WebsiteDomainBinding",
    "WebsiteProtocol",
    "build_universal_website",
    "ensure_universal_website",
    "host_operation_counts",
    "offer_display_text",
    "project_universal_website_document",
    "project_website_protocol",
    "read_universal_website",
    "website_download",
    "website_external_links",
]
