"""The new node-native ArchHub application super-node.

This module does not import or execute the previous application. It assembles
the application, Grand Map, UI tree, state, actions, bindings, and inspector
from the strict universal node kernel.
"""
from __future__ import annotations

from .core import relation_sources, relation_targets
from .domains.cloud import build_cloud_domain
from .domains.cockpit import build_cockpit_domain
from .domains.community import build_community_domain
from .domains.connectors import build_connectors_domain
from .domains.monetization import build_monetization_domain
from .domains.models import build_models_domain
from .domains.orchestration import build_orchestration_domain
from .domains.resources import (
    bind_resource_authority,
    build_resource_domain,
    connect_resource,
)
from .domains.selfext import build_self_extension_domain
from .domains.sessions import (create_lifecycle_policy, create_session_catalog,
                               govern_existing_session, register_session,
                               registered_session_ids)
from .domains.users import build_users_domain
from .cloud_runtime import build_cloud_runtime_nodes
from .deployment_evidence import build_deployment_evidence
from .graph_api import level_view
from .governance_policy import build_desktop_launch_policy
from .laws_relation import (attach_payload, build_payload_envelope,
                            set_relation_parameter)
from .laws_surface import ui_element
from .map_import import (PUBLIC_MAP_PATH, import_grand_map,
                         load_local_authority_config, resolve_map_path)
from .ui_runtime import (connect_ui_action, connect_ui_binding, connect_ui_child,
                         connect_ui_download)
from .website import WEBSITE_CSS, build_website


# The palette is transcribed from the design system's single source of truth
# (70.HANDOFFS/archhub-design/archhub/project/tokens.jsx). Two things that file
# fixes and this one had not: ink_muted was #5e574f, which that source measures
# at 2.56:1 on our dark surfaces -- failing WCAG AA at every size it is used --
# and on_fill exists because #fff on accent #d97757 measures 3.12:1. Do not
# hand-edit a colour here; change tokens.jsx and re-transcribe.
THEME = {
    'bg': '#0e0e11',
    'bg_panel': '#15151a',
    'bg_soft': '#1c1c23',
    'bg_hover': '#22222a',
    'bg_deep': '#0a0a0d',
    'bg_canvas': '#101015',
    'bg_raised': '#1d1d22',
    'bg_ink': '#18181e',
    'ink': '#ece8e0',
    'ink_soft': '#9b938a',
    'ink_muted': '#8b837a',
    'ink_dim': '#8a837c',
    'on_fill': '#180f08',
    'line': '#26262e',
    'line_soft': '#1e1e24',
    'line_hair': '#1a1a20',
    'accent': '#d97757',
    'accent_soft': '#3a2018',
    'accent_dim': '#2a1812',
    'accent_hi': '#e8896a',
    'accent_press': '#a04832',
    'ok': '#7ec18e',
    'warn': '#e5b25a',
    'err': '#e6705f',
    'cyan': '#5fb3b3',
    'purple': '#a98cd6',
    'blue': '#7898d6',
    'l_bg': '#f7f4ee',
    'l_bg_panel': '#fbf9f4',
    'l_bg_soft': '#efeae0',
    'l_ink': '#1a1612',
    'l_ink_soft': '#6b6256',
    'l_ink_muted': '#9a9183',
    'l_line': '#e3ddd0',
    'l_accent': '#c96442',
}

APPLICATION_SCHEMA_VERSION = '2026.07.13.32'


STYLESHEET = r"""
*{box-sizing:border-box}html,body{width:100%;height:100%;margin:0;overflow:hidden;background:var(--bg);color:var(--ink);font-family:Inter,system-ui,sans-serif;font-size:13px}button,input{font:inherit;letter-spacing:0}.archhub-app{width:100vw;height:100vh;display:grid;grid-template-columns:292px minmax(0,1fr);grid-template-rows:minmax(0,1fr) 22px;background:var(--bg);overflow:hidden}.sidebar{grid-column:1;grid-row:1;display:grid;grid-template-columns:56px 236px;min-height:0;background:var(--bg-panel);border-right:1px solid var(--line)}.icon-rail{background:var(--bg-deep);border-right:1px solid var(--line);display:flex;flex-direction:column;align-items:stretch;padding:12px 0 10px;gap:2px}.rail-button{min-height:48px;border:0;background:transparent;color:var(--ink-soft);display:flex;align-items:center;justify-content:center;cursor:pointer;font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;text-transform:uppercase}.rail-button:hover{background:var(--bg-soft);color:var(--ink)}.rail-button[data-active="true"]{color:var(--accent);background:var(--accent-soft);border-left:2px solid var(--accent)}.rail-spacer{flex:1}.library-panel{display:flex;flex-direction:column;min-width:0;overflow:hidden}.panel-title{height:48px;padding:17px 14px 10px;border-bottom:1px solid var(--line);font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;letter-spacing:.18em;color:var(--ink-muted)}.library-list{overflow:auto;padding:8px}.library-row{width:100%;border:0;background:transparent;color:var(--ink-soft);padding:7px 9px;text-align:left;display:flex;align-items:center;gap:8px;border-radius:5px;cursor:pointer;font-size:12px}.library-row:hover{background:var(--bg-soft);color:var(--ink)}.library-dot{width:7px;height:7px;border-radius:50%;background:var(--accent);flex:0 0 auto}.workspace{grid-column:2;grid-row:1;min-width:0;min-height:0;display:grid;grid-template-columns:minmax(0,1fr) 320px;grid-template-rows:36px minmax(0,1fr);overflow:hidden}.workspace-header{grid-column:1/-1;grid-row:1;display:flex;align-items:center;gap:10px;height:36px;padding:0 10px;background:var(--bg-panel);border-bottom:1px solid var(--line);min-width:0}.wordmark{font-family:'Architects Daughter','Segoe Print',cursive;font-size:19px;text-transform:uppercase;color:var(--ink);background:transparent;border:0;cursor:pointer}.wordmark strong{color:var(--accent);font-weight:400}.session-tab{height:27px;border:1px solid var(--line);border-bottom-color:var(--accent);background:var(--bg-soft);color:var(--ink);padding:0 10px;border-radius:4px 4px 0 0;font-family:JetBrains Mono,ui-monospace,monospace;font-size:10px}.header-spacer{flex:1}.model-chip{border:1px solid var(--line);background:var(--bg);color:var(--ink-soft);border-radius:4px;padding:3px 8px;font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px}.canvas{grid-column:1;grid-row:2;position:relative;overflow:auto;background-color:var(--bg-canvas);background-image:radial-gradient(circle,var(--line-soft) 1px,transparent 1px);background-size:20px 20px}.canvas-stage{position:relative;width:1320px;height:760px;min-width:100%;min-height:100%}.wire-layer{position:absolute;inset:0;width:1320px;height:760px;pointer-events:none;overflow:visible}.wire-line{stroke:var(--accent);stroke-width:1.35;stroke-opacity:.42;fill:none}.graph-node{position:absolute;width:204px;height:134px;border:1px solid var(--line);border-radius:6px;background:var(--bg-panel);color:var(--ink);padding:0;display:flex;flex-direction:column;box-shadow:0 4px 14px rgba(0,0,0,.28);cursor:pointer;text-align:left;overflow:hidden}.graph-node:hover{border-color:var(--accent);transform:translateY(-1px)}.node-accent{height:3px;background:var(--accent)}.node-head{padding:9px 11px 5px;font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;color:var(--ink-muted);letter-spacing:.1em;text-transform:uppercase}.node-title{padding:0 11px;font-family:'Instrument Serif',Georgia,serif;font-size:17px;line-height:1.1;color:var(--ink)}.node-value{margin-top:auto;padding:7px 11px 8px;border-top:1px solid var(--line-soft);font-family:JetBrains Mono,ui-monospace,monospace;font-size:10px;color:var(--ok)}.canvas-heading{position:absolute;left:22px;top:18px;z-index:5;font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;letter-spacing:.18em;color:var(--ink-muted);text-transform:uppercase}.canvas-toolbar{position:sticky;left:16px;bottom:14px;z-index:8;width:max-content;border:1px solid var(--line);background:var(--bg-panel);border-radius:5px;padding:5px 8px;font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;color:var(--ink-soft)}.composer{position:sticky;left:50%;bottom:18px;transform:translateX(-50%);z-index:9;width:min(560px,calc(100% - 48px));border:1px solid var(--line);background:var(--bg-panel);border-radius:7px;padding:8px;box-shadow:0 8px 30px rgba(0,0,0,.4)}/*design-language-v1*//*node-params*/.node-params{display:flex;flex-direction:column;gap:1px;padding:2px 11px 4px}.node-param{display:flex;justify-content:space-between;gap:10px;font-family:JetBrains Mono,ui-monospace,monospace;font-size:8.5px;line-height:1.5}.node-param-k{color:var(--ink-dim);letter-spacing:.02em}.node-param-v{color:var(--ink-soft);text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:120px}.universal-library .universal-collection-row{grid-template-columns:minmax(0,1fr) 24px;gap:2px}.universal-library .library-row{min-height:40px;padding:6px 8px;border-radius:4px}.universal-library .library-row .universal-library-name{margin-top:2px;font-size:11.5px;font-weight:550}.universal-library .library-row .universal-library-fields,.universal-library .library-row .universal-library-meta{margin-top:2px;font-size:8px;line-height:1.4;color:var(--ink-dim)}.universal-collection-row .header-action{width:24px;height:24px;min-height:24px;align-self:center;border:0;background:transparent;color:var(--ink-dim);opacity:0;font-size:14px}.universal-collection-row:hover .header-action{opacity:.9}.universal-collection-row .header-action:hover{color:var(--accent);background:var(--accent-soft)}.graph-node{border-radius:5px;box-shadow:0 2px 10px rgba(0,0,0,.22)}.graph-node .node-head{height:24px;padding:6px 10px 4px;font-size:8px;letter-spacing:.14em}.graph-node .node-title{padding:8px 11px 2px;font-size:12.5px;font-weight:600;letter-spacing:.01em}.graph-node .node-value{padding:3px 11px 8px;font-family:JetBrains Mono,ui-monospace,monospace;font-size:8.5px;letter-spacing:.02em;color:var(--ink-dim)}.graph-node:hover{transform:none;border-color:var(--line)}.graph-node:hover .node-accent{height:2px}.inspector .property-input{height:30px;font-family:JetBrains Mono,ui-monospace,monospace;font-size:11px}.inspector textarea.property-input{font-family:Inter,system-ui,sans-serif}.inspector .property-label{font-size:8.5px;letter-spacing:.12em;text-transform:uppercase;color:var(--ink-dim)}.inspector .inspector-section{gap:8px;padding-top:10px}.inspector .connection-box{font-family:JetBrains Mono,ui-monospace,monospace;font-size:10px;padding:8px 10px}.composer{border-radius:6px;padding:6px;background:color-mix(in srgb,var(--bg-panel) 92%,transparent);backdrop-filter:blur(6px)}.composer-input{height:30px;font-size:12.5px}.canvas-heading::after{content:'   scroll → zoom · drag → pan · shift-drag → select';color:var(--ink-dim);letter-spacing:.06em;text-transform:none;font-size:8px}.composer-agent-status{display:block;padding:4px 8px 2px;font-family:JetBrains Mono,ui-monospace,monospace;font-size:10px;color:var(--accent)}.composer-input:disabled{opacity:.55}.composer-input{width:100%;height:34px;border:0;outline:0;background:transparent;color:var(--ink);padding:4px 7px}.inspector{grid-column:2;grid-row:2;min-height:0;overflow:auto;background:var(--bg-panel);border-left:1px solid var(--line);padding:14px 16px 20px}.inspector-panel[data-visible="False"]{display:none}.inspector-panel[data-visible="True"]{display:flex}.inspector-panel{flex-direction:column;gap:16px}.inspector-kicker{font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;color:var(--accent);letter-spacing:.18em;text-transform:uppercase}.inspector-title{font-family:'Instrument Serif',Georgia,serif;font-size:22px;line-height:1.05}.inspector-meta{font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;color:var(--ink-muted)}.inspector-section{border-top:1px solid var(--line-soft);padding-top:12px;display:flex;flex-direction:column;gap:10px}.inspector-heading{font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;color:var(--ink-muted);letter-spacing:.18em;text-transform:uppercase}.property-row{display:flex;flex-direction:column;gap:5px}.property-label{font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;color:var(--ink-muted);text-transform:uppercase;letter-spacing:.08em}.property-input{width:100%;height:30px;border:1px solid var(--line);border-radius:5px;background:var(--bg);color:var(--ink);padding:5px 8px;font-family:JetBrains Mono,ui-monospace,monospace;font-size:11px;outline:0}.property-input:focus{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent-soft)}.connection-box{border:1px solid var(--line);background:var(--bg);border-radius:6px;padding:10px 12px;font-family:JetBrains Mono,ui-monospace,monospace;font-size:10px;color:var(--ink-soft)}.status-strip{grid-column:1/-1;grid-row:2;display:flex;align-items:center;gap:16px;padding:0 9px;background:var(--bg-deep);border-top:1px solid var(--line);font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;color:var(--ink-muted)}.status-live{color:var(--ok)}@media(max-width:980px){.archhub-app{grid-template-columns:56px minmax(0,1fr)}.sidebar{grid-template-columns:56px}.library-panel{display:none}.workspace{grid-template-columns:minmax(0,1fr) 280px}}@media(max-width:720px){.workspace{grid-template-columns:1fr}.inspector{display:none}.composer{width:calc(100% - 32px)}}
.wire-layer{pointer-events:none}.wire-line{pointer-events:stroke;cursor:pointer}.wire-line:hover{stroke-opacity:1;stroke-width:2.4}.graph-node{cursor:grab}.graph-node:active{cursor:grabbing}.connection-box{overflow-wrap:anywhere}.home-surface{display:none;grid-column:2;grid-row:1;min-width:0;min-height:0;overflow:auto;background:var(--bg);padding:44px 52px 120px;position:relative}.archhub-app[data-mode="home"]{grid-template-columns:56px minmax(0,1fr)}.archhub-app[data-mode="home"] .sidebar{grid-template-columns:56px;width:56px}.archhub-app[data-mode="home"] .library-panel,.archhub-app[data-mode="home"] .workspace{display:none}.archhub-app[data-mode="home"] .home-surface{display:block}.home-masthead{display:flex;align-items:flex-end;justify-content:space-between;gap:20px;padding-bottom:24px;border-bottom:1px solid var(--line)}.home-brand{font-family:'Architects Daughter','Segoe Print',cursive;font-size:36px;text-transform:uppercase;color:var(--ink)}.home-brand strong{color:var(--accent);font-weight:400}.home-subtitle{font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;letter-spacing:.18em;color:var(--ink-muted);text-transform:uppercase}.home-section-title{margin:28px 0 12px;font-family:'Instrument Serif',Georgia,serif;font-size:22px}.home-session-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px;max-width:1040px}.home-session-card{min-height:148px;border:1px solid var(--line);border-radius:6px;background:var(--bg-panel);color:var(--ink);padding:15px;text-align:left;cursor:pointer;display:flex;flex-direction:column}.home-session-card:hover{border-color:var(--accent);background:var(--bg-soft)}.home-session-kicker{font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;letter-spacing:.14em;color:var(--accent);text-transform:uppercase}.home-session-title{font-family:'Instrument Serif',Georgia,serif;font-size:21px;margin-top:8px}.home-session-meta{margin-top:auto;font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;color:var(--ink-muted)}.home-composer{position:fixed;left:calc(56px + (100vw - 56px)/2);bottom:42px;transform:translateX(-50%);width:min(620px,calc(100vw - 100px));border:1px solid var(--line);border-radius:7px;background:var(--bg-panel);padding:9px;box-shadow:0 8px 30px rgba(0,0,0,.4)}.home-composer input{width:100%;height:36px;border:0;outline:0;background:transparent;color:var(--ink);padding:4px 8px}
"""

STYLESHEET += r"""
.cockpit-surface{display:none;grid-column:2;grid-row:1;min-width:0;min-height:0;overflow:auto;background:var(--bg);padding:28px 34px 60px}.archhub-app[data-mode="cockpit"]{grid-template-columns:56px minmax(0,1fr)}.archhub-app[data-mode="cockpit"] .sidebar{grid-template-columns:56px;width:56px}.archhub-app[data-mode="cockpit"] .library-panel,.archhub-app[data-mode="cockpit"] .workspace,.archhub-app[data-mode="cockpit"] .home-surface{display:none}.archhub-app[data-mode="cockpit"] .cockpit-surface{display:block}.cockpit-header{display:flex;align-items:center;gap:16px;padding-bottom:18px;border-bottom:1px solid var(--line)}.cockpit-title{font-family:'Instrument Serif',Georgia,serif;font-size:26px}.cockpit-subtitle{font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;color:var(--ink-muted);letter-spacing:.14em}.cockpit-spacer{flex:1}.cockpit-run{border:1px solid var(--accent);border-radius:5px;background:var(--accent-soft);color:var(--accent);padding:7px 11px;cursor:pointer;font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;text-transform:uppercase}.cockpit-command{display:grid;grid-template-columns:minmax(0,1fr) auto auto;align-items:center;gap:8px;margin-top:18px;padding:10px;border:1px solid var(--line);border-radius:6px;background:var(--bg-panel)}.cockpit-command-input{height:34px;border:1px solid var(--line);border-radius:4px;background:var(--bg);color:var(--ink);padding:6px 9px;outline:0}.cockpit-command-input:focus{border-color:var(--accent)}.cockpit-command-route{font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;color:var(--cyan);text-transform:uppercase;min-width:72px;text-align:center}.cockpit-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin-top:18px}.cockpit-card{min-height:118px;border:1px solid var(--line);border-radius:6px;background:var(--bg-panel);padding:12px;display:flex;flex-direction:column;gap:8px}.cockpit-label{font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;letter-spacing:.12em;color:var(--ink-muted);text-transform:uppercase}.cockpit-value{font-family:JetBrains Mono,ui-monospace,monospace;font-size:11px;color:var(--ink);overflow-wrap:anywhere}.cockpit-domain-section{margin-top:24px}.cockpit-domain-grid{display:grid;grid-template-columns:repeat(3,minmax(220px,1fr));gap:1px;border:1px solid var(--line);background:var(--line)}.cockpit-domain-row{display:flex;align-items:center;justify-content:space-between;gap:12px;background:var(--bg-panel);padding:8px 10px}.cockpit-domain-name{font-size:12px}.cockpit-domain-value{font-family:JetBrains Mono,ui-monospace,monospace;font-size:10px;color:var(--ok)}@media(max-width:1100px){.cockpit-grid{grid-template-columns:repeat(2,minmax(180px,1fr))}.cockpit-domain-grid{grid-template-columns:1fr}}@media(max-width:720px){.cockpit-command{grid-template-columns:1fr}.cockpit-command-route{text-align:left}}
"""

STYLESHEET += r"""
.wire-line{fill:none}.canvas-stage{transform-origin:0 0}.canvas-toolbar{display:flex;align-items:center;gap:6px}.node-select{position:absolute;right:6px;top:7px;width:18px;height:18px;border:1px solid var(--line);border-radius:3px;background:var(--bg);color:transparent;cursor:pointer;z-index:3}.node-select[data-active="True"]{border-color:var(--accent);background:var(--accent);color:white}.node-select[data-active="True"]::before{content:"\2713";font-size:11px}.node-ports{margin-top:auto;border-top:1px solid var(--line-soft);display:grid;grid-template-columns:1fr 1fr}.node-port{height:25px;border:0;background:transparent;color:var(--ink-muted);font-family:JetBrains Mono,ui-monospace,monospace;font-size:8px;cursor:pointer;position:relative}.node-port:hover{color:var(--accent);background:var(--bg-soft)}.node-port-in{text-align:left;padding-left:18px}.node-port-out{text-align:right;padding-right:18px}.node-port::before{content:"";position:absolute;top:9px;width:7px;height:7px;border:1px solid currentColor;border-radius:50%;background:var(--bg-panel)}.node-port-in::before{left:5px}.node-port-out::before{right:5px}.node-port[data-pending="True"]{color:var(--accent);background:var(--accent-soft)}
"""

STYLESHEET += r"""
.create-surface{display:none;grid-column:2;grid-row:1;min-width:0;min-height:0;background:var(--bg);padding:28px 34px;overflow:auto}.archhub-app[data-mode="create"]{grid-template-columns:56px minmax(0,1fr)}.archhub-app[data-mode="create"] .sidebar{grid-template-columns:56px;width:56px}.archhub-app[data-mode="create"] .library-panel,.archhub-app[data-mode="create"] .workspace,.archhub-app[data-mode="create"] .home-surface,.archhub-app[data-mode="create"] .cockpit-surface,.archhub-app[data-mode="create"] .brain-surface,.archhub-app[data-mode="create"] .settings-surface{display:none}.archhub-app[data-mode="create"] .create-surface{display:block}.create-form{width:min(620px,100%);margin:36px auto 0}.create-kinds{display:flex;flex-wrap:wrap;gap:6px;margin:18px 0}.create-kind{height:30px;padding:0 10px;border:1px solid var(--line);border-radius:4px;background:var(--bg-panel);color:var(--ink-soft);cursor:pointer}.create-kind[data-active="True"]{border-color:var(--accent);background:var(--accent-soft);color:var(--accent)}.create-field{display:flex;flex-direction:column;gap:6px;margin:14px 0}.create-input{width:100%;height:36px;border:1px solid var(--line);border-radius:5px;background:var(--bg-panel);color:var(--ink);padding:6px 9px;outline:0}.create-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:22px}.new-node-button{margin:8px;height:32px;border:1px solid var(--accent);border-radius:5px;background:var(--accent-soft);color:var(--accent);cursor:pointer}
"""

STYLESHEET += r"""
.brain-surface{display:none;grid-column:2;grid-row:1;min-width:0;min-height:0;overflow:auto;background:var(--bg);padding:28px 34px 60px}.archhub-app[data-mode="brain"]{grid-template-columns:56px minmax(0,1fr)}.archhub-app[data-mode="brain"] .sidebar{grid-template-columns:56px;width:56px}.archhub-app[data-mode="brain"] .library-panel,.archhub-app[data-mode="brain"] .workspace,.archhub-app[data-mode="brain"] .home-surface,.archhub-app[data-mode="brain"] .cockpit-surface{display:none}.archhub-app[data-mode="brain"] .brain-surface{display:block}.brain-header{display:flex;align-items:center;gap:14px;padding-bottom:18px;border-bottom:1px solid var(--line)}.brain-title{font-family:'Instrument Serif',Georgia,serif;font-size:26px}.brain-sync{margin-left:auto;border:1px solid var(--cyan);background:var(--bg-soft);color:var(--cyan);border-radius:5px;padding:7px 11px;cursor:pointer;font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;text-transform:uppercase}.brain-grid{display:grid;grid-template-columns:repeat(2,minmax(280px,1fr));gap:10px;margin-top:18px}.brain-panel{border:1px solid var(--line);border-radius:6px;background:var(--bg-panel);padding:13px;display:flex;flex-direction:column;gap:8px;min-height:132px}.brain-panel-wide{grid-column:1/-1}.brain-label{font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;letter-spacing:.14em;color:var(--ink-muted);text-transform:uppercase}.brain-value{font-family:JetBrains Mono,ui-monospace,monospace;font-size:10px;line-height:1.55;color:var(--ink-soft);white-space:pre-wrap;overflow-wrap:anywhere}@media(max-width:900px){.brain-grid{grid-template-columns:1fr}.brain-panel-wide{grid-column:auto}}
"""

STYLESHEET += r"""
.library-panel[data-visible="False"]{display:none}.library-panel[data-visible="True"]{display:flex}.rail-button{flex-direction:column;gap:3px}.rail-button::before{font-size:17px;line-height:17px}.rail-home::before{content:"\2302"}.rail-search::before{content:"\2315"}.rail-share::before{content:"\221e"}.rail-settings::before{content:"\2699"}.sidebar-search{padding:10px;border-bottom:1px solid var(--line)}.sidebar-search-input{width:100%;height:31px;border:1px solid var(--line);border-radius:5px;background:var(--bg);color:var(--ink);padding:5px 8px;outline:0}.sidebar-search-input:focus{border-color:var(--accent)}.search-scope{padding:10px 12px 4px;font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;color:var(--ink-muted);letter-spacing:.14em}.search-result[data-visible="False"]{display:none}.share-copy{padding:10px 12px;color:var(--ink-soft);font-size:11px;line-height:1.5}.share-row{margin:4px 8px;padding:9px;border:1px solid var(--line);border-radius:5px;background:var(--bg);color:var(--ink);text-align:left;cursor:pointer}.share-row:hover{border-color:var(--accent)}.settings-surface{display:none;grid-column:2;grid-row:1;min-width:0;min-height:0;overflow:auto;background:var(--bg);padding:28px 34px 60px}.archhub-app[data-mode="settings"]{grid-template-columns:56px minmax(0,1fr)}.archhub-app[data-mode="settings"] .sidebar{grid-template-columns:56px;width:56px}.archhub-app[data-mode="settings"] .library-panel,.archhub-app[data-mode="settings"] .workspace,.archhub-app[data-mode="settings"] .home-surface,.archhub-app[data-mode="settings"] .cockpit-surface,.archhub-app[data-mode="settings"] .brain-surface{display:none}.archhub-app[data-mode="settings"] .settings-surface{display:block}.settings-header{display:flex;align-items:center;gap:12px;padding-bottom:18px;border-bottom:1px solid var(--line)}.settings-back{width:28px;height:28px;border:1px solid var(--line);border-radius:5px;background:var(--bg-panel);color:var(--ink);cursor:pointer}.settings-back::before{content:"\2190"}.settings-title{font-family:'Instrument Serif',Georgia,serif;font-size:26px}.settings-grid{display:grid;grid-template-columns:minmax(220px,360px) minmax(280px,560px);gap:32px;margin-top:24px}.settings-nav{border-right:1px solid var(--line);padding-right:22px}.settings-section{padding-bottom:22px}.settings-heading{font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;letter-spacing:.16em;color:var(--ink-muted);text-transform:uppercase;margin-bottom:12px}.settings-row{display:grid;grid-template-columns:minmax(0,1fr) 130px;align-items:center;gap:18px;min-height:42px;border-bottom:1px solid var(--line-soft)}.settings-label{color:var(--ink-soft);font-size:12px}.settings-color{width:100%;height:28px;border:1px solid var(--line);border-radius:4px;background:var(--bg);padding:2px}.header-action{height:26px;padding:4px 8px;border:1px solid var(--line);border-radius:4px;background:var(--bg-panel);color:var(--ink);font-size:11px;cursor:pointer}.header-action:hover{background:var(--bg-hover)}.header-primary{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}@media(max-width:800px){.settings-grid{grid-template-columns:1fr}.settings-nav{border-right:0;border-bottom:1px solid var(--line);padding:0 0 18px}}
"""


STYLESHEET += r"""
.court-evidence{margin-top:7px;border-left:2px solid var(--ok);padding:6px 0 2px 9px}.court-evidence summary{cursor:pointer;color:var(--ok)}.court-evidence .connection-box{margin-top:7px;font-size:8px}.court-check{padding:4px 2px;border-bottom:1px solid var(--line-soft);font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;color:var(--ink-soft)}
"""
STYLESHEET += '.wire-line[data-hidden="True"]{display:none}'
STYLESHEET += r"""
.archhub-app[data-sync="working"]{cursor:progress}.archhub-app[data-sync="settled"] .status-live{animation:runtime-settle .36s ease-out}.graph-node[data-focused="True"]{border-color:var(--accent);box-shadow:0 0 0 1px var(--accent),0 8px 24px rgba(0,0,0,.38)}.wire-line[data-focused="True"]{stroke-opacity:1;stroke-width:2.5}.wire-preview{stroke:var(--accent);stroke-width:2;stroke-dasharray:6 5;stroke-opacity:.9;fill:none;pointer-events:none}.node-port.wire-target-ready{color:var(--ok);background:rgba(126,193,142,.14)}.graph-node.is-moving{z-index:20;box-shadow:0 12px 34px rgba(0,0,0,.5)}@keyframes runtime-settle{0%{color:var(--accent)}100%{color:var(--ok)}}
.graph-node[data-visible="False"],.wire-line[data-visible="False"]{display:none}
.history-undo,.history-redo{width:28px;padding:0;font-size:0}.history-undo::before{content:"\21b6";font-size:15px}.history-redo::before{content:"\21b7";font-size:15px}
.container-back{width:28px;padding:0;font-size:0}.container-back::before{content:"\2190";font-size:15px}
.session-tab{max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
"""
STYLESHEET += r"""
.canvas{overflow:hidden;touch-action:none;cursor:crosshair;--grid-size:20px;--grid-x:0px;--grid-y:0px;background-position:var(--grid-x) var(--grid-y);background-size:var(--grid-size) var(--grid-size)}
.canvas.is-panning{cursor:grabbing}.canvas.is-selecting{cursor:crosshair}.canvas-stage{will-change:transform;contain:layout style}.wire-layer{overflow:visible}
.wire-line{stroke-linecap:round;stroke-opacity:.82;transition:stroke-opacity .08s linear,stroke-width .08s linear}.wire-line:hover{stroke-opacity:1}.wire-line[data-focused="True"]{stroke-opacity:1;filter:drop-shadow(0 0 3px var(--accent))}.wire-arrow{fill:var(--accent)}
.graph-node{--node-color:var(--ink-soft);border-width:2px 1px 1px;border-style:solid;border-color:var(--node-color) var(--line) var(--line);border-radius:9px;box-shadow:0 2px 8px rgba(0,0,0,.35);transition:border-color .08s linear,box-shadow .08s linear,opacity .12s linear;background:var(--bg-panel);overflow:visible;will-change:left,top}.graph-node[data-node-kind="value"],.graph-node[data-node-kind="param"]{--node-color:var(--blue)}.graph-node[data-node-kind="op"]{--node-color:var(--cyan)}.graph-node[data-node-kind="group"],.graph-node[data-node-kind="session"]{--node-color:var(--purple)}.graph-node[data-node-kind="wire"]{--node-color:var(--accent)}.graph-node[data-node-kind="ui"]{--node-color:var(--warn)}.graph-node[data-node-kind="proposal"]{--node-color:var(--ok)}.graph-node[data-node-kind="secret_ref"]{--node-color:var(--err)}.graph-node:hover{transform:none;box-shadow:0 6px 18px rgba(0,0,0,.42)}.graph-node[data-selected="True"]{border-right-color:var(--cyan);border-bottom-color:var(--cyan);border-left-color:var(--cyan);box-shadow:0 0 0 2px color-mix(in srgb,var(--cyan) 72%,transparent),0 4px 16px rgba(0,0,0,.42)}.graph-node[data-focused="True"]{border-right-color:var(--accent);border-bottom-color:var(--accent);border-left-color:var(--accent);box-shadow:0 0 0 3px var(--accent-soft),0 8px 24px rgba(0,0,0,.44)}
.node-accent{position:absolute;left:0;right:0;top:0;height:1px;background:var(--node-color);border-radius:8px 8px 0 0;pointer-events:none}.node-head{height:30px;padding:8px 11px 7px;border-bottom:1px solid var(--line-soft);border-radius:8px 8px 0 0;background:transparent;color:var(--node-color);font-size:8.5px;line-height:13px;letter-spacing:.18em}.node-head::before{content:"";display:inline-block;width:7px;height:7px;margin-right:8px;border:1px solid currentColor;border-radius:2px;vertical-align:-1px;background:color-mix(in srgb,currentColor 22%,transparent)}.node-title{padding:10px 12px 3px;font-family:Inter,system-ui,sans-serif;font-size:13px;font-weight:500;line-height:1.2;letter-spacing:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.node-value{padding:4px 12px 10px;border-top:0;font-size:9px;line-height:1.35;color:var(--ink-muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.node-select{display:none}.node-ports{position:absolute;inset:0;height:auto;border:0;display:block;pointer-events:none}.node-port{position:absolute;top:56px;width:22px;height:22px;padding:0;border:0;background:transparent;color:var(--node-color);font-size:0;pointer-events:auto;overflow:visible}.node-port:hover{background:transparent;color:var(--node-color)}.node-port-in{left:-11px}.node-port-out{right:-11px}.node-port::before{top:5px;left:5px;right:auto;width:10px;height:10px;border:1.5px solid currentColor;border-radius:50%;box-shadow:0 0 0 2px var(--bg-canvas);transition:transform .08s linear,box-shadow .08s linear}.node-port-in::before{left:5px;background:var(--bg-panel)}.node-port-out::before{right:auto;background:currentColor}.node-port:hover::before,.node-port.wire-target-ready::before{transform:scale(1.25);box-shadow:0 0 0 2px var(--bg-canvas),0 0 0 4px color-mix(in srgb,currentColor 26%,transparent)}
.selection-box{position:absolute;z-index:30;display:none;pointer-events:none;border:1px solid var(--cyan);background:color-mix(in srgb,var(--cyan) 13%,transparent)}.selection-box[data-mode="crossing"]{border-color:var(--ok);border-style:dashed;background:color-mix(in srgb,var(--ok) 13%,transparent)}
.canvas-selection-value{min-width:64px;color:var(--ink-muted)}
.status-message{margin-left:auto;max-width:min(52vw,720px);overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink-soft)}.status-message[hidden],.status-message[data-visible="False"]{display:none}.status-message[data-tone="error"]{color:var(--err)}
"""
STYLESHEET += r"""
.composer[hidden]{display:none!important}.universal-library{display:flex;flex-direction:column;gap:3px}.universal-library-primitive{width:100%;margin:2px 0 9px;padding:10px;border:1px solid var(--accent);border-radius:5px;background:var(--accent-soft);color:var(--ink);text-align:left;cursor:pointer}.universal-library-primitive[data-active="true"]{box-shadow:0 0 0 1px var(--accent)}.universal-library-kicker,.universal-library-section{font-family:JetBrains Mono,ui-monospace,monospace;font-size:8px;color:var(--ink-muted);letter-spacing:.14em}.universal-library-name{margin-top:6px;color:var(--ink);font-size:12px}.universal-library-fields,.universal-library-meta{margin-top:5px;color:var(--ink-muted);font-family:JetBrains Mono,ui-monospace,monospace;font-size:8px;line-height:1.5}.universal-library-section{padding:8px 8px 4px}.universal-library-definition{min-height:48px;align-items:flex-start;flex-direction:column;gap:1px}.universal-library .library-row[data-active="true"]{background:var(--bg-soft);color:var(--accent)}.universal-wire{opacity:.16;stroke-opacity:1}.universal-wire[data-context="True"],.universal-wire[data-hover-context="True"]{opacity:.85}.universal-wire:hover{opacity:1}.universal-wire-preview{stroke:var(--accent);stroke-width:2;stroke-dasharray:6 5;stroke-opacity:.9}.universal-graph-node[data-universal-wire-candidate="true"]{border-color:var(--ok);box-shadow:0 0 0 2px color-mix(in srgb,var(--ok) 30%,transparent),0 6px 18px rgba(0,0,0,.36)}.universal-graph-node .node-value{color:var(--ink-muted)}.universal-zoom-value{min-width:38px;text-align:center}.universal-collection-row{display:grid;grid-template-columns:minmax(0,1fr) repeat(3,28px);gap:4px}.universal-collection-row:last-child{grid-template-columns:minmax(0,1fr) 28px}.universal-collection-row .header-action{width:28px;padding:0}.inspector-tabs{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:2px;margin:14px 0 8px;padding:3px;border:1px solid var(--line);border-radius:6px;background:var(--bg)}.inspector-tab{height:29px;min-width:0;border:0;border-radius:4px;background:transparent;color:var(--ink-muted);font-size:10px;cursor:pointer}.inspector-tab:hover{background:var(--bg-soft);color:var(--ink)}.inspector-tab[data-active="true"]{background:var(--bg-hover);color:var(--ink);box-shadow:inset 0 -2px 0 var(--accent)}.inspector-tab:focus-visible{outline:1px solid var(--accent);outline-offset:1px}[data-inspector-section][hidden]{display:none!important}.inspector-section>summary{cursor:pointer;list-style:none}.property-input[type="color"]{padding:3px}.property-input option{background:var(--bg-panel);color:var(--ink)}@media(max-width:980px){.archhub-app .sidebar>.library-panel{display:none!important}}@media(max-width:720px){.workspace-header .model-chip,.workspace-header .header-action:not(.container-back){display:none}.workspace-header{padding:0 6px;gap:6px}.wordmark{font-size:16px}.session-tab{max-width:120px}}
"""
STYLESHEET += r"""
.property-create{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:6px;padding-top:10px;border-top:1px solid var(--line-soft)}.property-create-button{grid-column:1/-1;height:32px}.property-create .property-input{min-width:0}
.interface-create{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:6px;padding-top:10px;border-top:1px solid var(--line-soft)}.interface-create>[data-universal-relation-form-field="name"],.interface-create>[data-universal-relation-form-submit]{grid-column:1/-1}.interface-create>[data-universal-relation-form-submit]{width:100%;height:32px}.interface-create .property-input{min-width:0}
"""
STYLESHEET += ('*{scrollbar-width:thin;scrollbar-color:var(--line) var(--bg-deep)}'
               '*::-webkit-scrollbar{width:10px;height:10px}'
               '*::-webkit-scrollbar-track{background:var(--bg-deep)}'
               '*::-webkit-scrollbar-thumb{background:var(--line);border:2px solid var(--bg-deep);border-radius:4px}'
               '*::-webkit-scrollbar-corner{background:var(--bg-deep)}')


STYLESHEET += r"""
.lifecycle-head{display:flex;flex-direction:column;gap:6px}.lifecycle-head-meta{color:var(--ink-muted);font-size:8px;line-height:1.45}.lifecycle-divergence{border:1px solid var(--accent);background:var(--accent-soft);border-radius:5px;padding:8px 10px;color:var(--accent);font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;line-height:1.45}
.operational-current{color:var(--ok);border-color:var(--ok)}.operational-action{min-height:30px;border:1px solid var(--accent);border-radius:5px;background:var(--accent-soft);color:var(--accent);font-family:JetBrains Mono,ui-monospace,monospace;font-size:9px;text-transform:uppercase;cursor:pointer}.operational-action:disabled{border-color:var(--line);background:var(--bg);color:var(--ink-muted);cursor:not-allowed}
.connection-link{width:100%;text-align:left;cursor:pointer}.connection-link:hover,.connection-link:focus-visible{border-color:var(--accent);color:var(--accent);outline:0}
"""

STYLESHEET += r"""
.workspace{grid-template-columns:minmax(0,1fr) 360px}.workspace-header{height:42px;padding:0 14px}.wordmark{font-family:Inter,system-ui,sans-serif;font-size:15px;font-weight:650;text-transform:none}.session-tab{height:29px;font-family:Inter,system-ui,sans-serif;font-size:11px}.model-chip{font-size:10px}
.graph-node{width:220px;min-height:112px;height:auto;border-width:1px;border-color:var(--line);border-radius:6px;background:var(--bg-panel);box-shadow:0 3px 12px rgba(0,0,0,.28)}.graph-node:hover{border-color:color-mix(in srgb,var(--node-color) 65%,var(--line));box-shadow:0 6px 18px rgba(0,0,0,.36)}.graph-node:focus-visible{outline:2px solid var(--accent);outline-offset:3px}.graph-node[data-selected="True"]{border-color:var(--cyan);box-shadow:0 0 0 1px var(--cyan),0 5px 18px rgba(0,0,0,.36)}.graph-node[data-focused="True"]{border-color:var(--accent);box-shadow:0 0 0 2px var(--accent-soft),0 7px 22px rgba(0,0,0,.4)}
.node-accent{height:2px;border-radius:5px 5px 0 0}.node-head{height:27px;padding:7px 10px 6px;border-radius:5px 5px 0 0;font-family:Inter,system-ui,sans-serif;font-size:9px;font-weight:650;letter-spacing:0}.node-head::before{width:6px;height:6px;margin-right:7px;border-radius:1px}.node-title{padding:10px 12px 2px;font-size:13px;font-weight:650;line-height:1.25}.node-value{padding:3px 12px 9px;font-family:Inter,system-ui,sans-serif;font-size:10px;line-height:1.35}
.node-port{width:94px;height:20px;padding:0 17px;border-radius:3px;color:var(--ink-muted);font-family:Inter,system-ui,sans-serif;font-size:9px;line-height:20px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.node-port-in{left:-8px;text-align:left}.node-port-out{right:-8px;text-align:right}.node-port:hover{background:var(--bg-hover);color:var(--ink)}.node-port::before{top:5px;width:9px;height:9px;box-shadow:0 0 0 2px var(--bg-canvas)}.node-port-in::before{left:3px}.node-port-out::before{left:auto;right:3px}
.universal-wire{opacity:.14}.universal-wire[data-context="True"],.universal-wire[data-hover-context="True"],.universal-wire[data-focused="True"]{opacity:.96}.wire-line{stroke-width:1.5}.node-summary{padding:2px 12px 0;font-family:Inter,system-ui,sans-serif;font-size:10px;line-height:1.35;color:var(--ink-soft);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.node-value{text-transform:none}.node-head{text-transform:none;letter-spacing:.02em}
.canvas-toolbar{bottom:12px;min-height:34px;padding:4px 6px;border-radius:5px;box-shadow:0 4px 16px rgba(0,0,0,.28);font-family:Inter,system-ui,sans-serif;font-size:10px}.canvas-scope-item{display:contents}.canvas-heading{left:18px;top:15px;font-family:Inter,system-ui,sans-serif;font-size:10px;font-weight:600;letter-spacing:0;color:var(--ink-muted);text-transform:none}
.inspector{padding:16px 18px 24px}.inspector-panel{gap:8px}.inspector-kicker{font-family:Inter,system-ui,sans-serif;font-size:10px;font-weight:650;letter-spacing:0;color:var(--node-color,var(--accent))}.inspector-title{font-family:Inter,system-ui,sans-serif;font-size:17px;font-weight:650;line-height:1.3}.inspector-lenses{display:flex;align-items:center;gap:12px;min-height:28px;margin-top:4px;border-bottom:1px solid var(--line-soft)}.inspector-lens-button{height:28px;padding:0;border:0;border-bottom:2px solid transparent;background:transparent;color:var(--ink-muted);font-family:Inter,system-ui,sans-serif;font-size:9px;cursor:pointer}.inspector-lens-button:hover{color:var(--ink)}.inspector-lens-button[data-active="true"]{border-bottom-color:var(--accent);color:var(--ink)}.inspector-tabs{display:flex;grid-template-columns:none;gap:2px;margin:10px 0;padding:2px;border-radius:5px;overflow-x:auto}.inspector-tab{flex:1 0 auto;height:32px;min-width:72px;border-radius:3px;padding:0 10px;font-family:Inter,system-ui,sans-serif;font-size:10px;font-weight:550}.inspector-tab[data-active="true"]{background:var(--bg-hover);box-shadow:inset 0 -2px 0 var(--accent)}.inspector-tabpanel{display:flex;flex-direction:column;gap:14px}.inspector-tabpanel[hidden]{display:none}.inspector-section{padding-top:13px;gap:9px}.inspector-heading{font-family:Inter,system-ui,sans-serif;font-size:10px;font-weight:650;letter-spacing:0}.property-row{gap:6px}.property-label{font-family:Inter,system-ui,sans-serif;font-size:10px;letter-spacing:0;text-transform:none}.property-input{height:34px;border-radius:4px;padding:6px 9px;font-family:Inter,system-ui,sans-serif;font-size:12px}.connection-box{border-radius:4px;padding:9px 10px;font-family:Inter,system-ui,sans-serif;font-size:11px;line-height:1.45}.presentation-source{font-size:10px;color:var(--ink-muted);overflow-wrap:anywhere}.presentation-reset{align-self:flex-start;height:28px;border:1px solid var(--line);border-radius:4px;background:transparent;color:var(--ink-soft);padding:0 9px;font-size:9px;cursor:pointer}.presentation-reset:hover{border-color:var(--accent);color:var(--ink)}.inspector-meta{font-size:9px}
.relation-group{margin:0;border-top:1px solid var(--line-soft);padding:0}.relation-group-summary{min-height:36px;margin-left:14px;padding:0 2px;display:list-item;line-height:36px;color:var(--ink-soft);font-size:10px;font-weight:650;cursor:pointer;list-style-position:outside}.relation-group-summary:hover{color:var(--ink)}.relation-group[open]>.relation-group-summary{color:var(--ink)}.relation-group>.property-row{display:grid;grid-template-columns:72px minmax(0,1fr);align-items:center;gap:8px;padding:4px 2px}.relation-group>.property-row:last-child{padding-bottom:10px}.relation-group .connection-box{min-width:0;overflow-wrap:anywhere}.relation-group-connections>.relation-connection-row{grid-template-columns:minmax(0,1fr);padding:3px 2px}.relation-group-connections>.relation-connection-row>.property-label{display:none}.relation-group-connections .connection-box{min-height:34px;display:flex;align-items:center}.relation-authority-summary{display:flex;flex-direction:column;gap:8px}.relation-flow-summary{font-weight:550}
.panel-title{height:44px;padding:15px 13px 10px;font-family:Inter,system-ui,sans-serif;font-size:10px;font-weight:650;letter-spacing:0}.universal-library-kicker,.universal-library-section,.universal-library-fields,.universal-library-meta{font-family:Inter,system-ui,sans-serif;letter-spacing:0}.universal-library-primitive{border-radius:4px}.universal-library-group{display:flex;flex-direction:column;gap:3px}.universal-library-group+.universal-library-group{margin-top:8px}.universal-library-entry{display:grid;grid-template-columns:minmax(0,1fr) 30px;gap:4px;align-items:stretch}.universal-library-definition{min-width:0;min-height:54px;border-radius:4px}.library-definition-place{width:30px;min-width:30px;min-height:54px;padding:0;border:1px solid var(--line);border-radius:4px;background:var(--bg-panel);color:var(--ink-muted);font-family:Inter,system-ui,sans-serif;font-size:18px;line-height:1;cursor:pointer}.library-definition-place:hover{border-color:var(--accent);background:var(--bg-hover);color:var(--ink)}.library-definition-place:focus-visible{outline:2px solid var(--accent);outline-offset:1px}.universal-library-name{font-size:12px;font-weight:550}
@media(max-width:1100px){.workspace{grid-template-columns:minmax(0,1fr) 320px}}
"""

# The browser receives these variables from graph-held component bindings.
# Fallbacks keep recovery documents readable if a projection is interrupted.
STYLESHEET += r"""
html,body{font-family:var(--component-card-font,Inter,system-ui,sans-serif);font-size:var(--component-card-font-size,13px)}
.canvas{background-color:var(--component-canvas-background,var(--bg-canvas));background-image:radial-gradient(circle,var(--component-canvas-grid,var(--line-soft)) 1px,transparent 1px);--grid-size:var(--component-canvas-grid-size,20px)}
.graph-node{width:var(--component-card-width,220px);border-radius:var(--component-card-radius,6px);background:var(--component-card-background,var(--bg-panel));color:var(--component-card-text,var(--ink));font-family:var(--component-card-font,Inter,system-ui,sans-serif)}
.node-port{min-height:var(--component-socket-target-size,24px)}
/* The design's own principle is screen-constant affordances (the handoff:
   'type is screen-constant, not world-scaled'), and its target-min token
   says 24px. A 24px CSS socket at fit zoom 0.82 measures 19.7 screen px --
   below its own floor. Counter-scale the hit targets by the inverse zoom
   so a socket is always the token's size ON SCREEN at any zoom. */
.canvas .node-port{transform:scale(var(--inv-zoom,1));transform-origin:center}
.canvas .node-port-in{transform-origin:left center}
.canvas .node-port-out{transform-origin:right center}

.node-port-in::before{background:var(--component-socket-surface,var(--bg-panel))}
.node-port-out::before{background:var(--component-socket-control,currentColor)}
.node-port.node-port-exact{width:var(--component-socket-target-size,24px);height:var(--component-socket-target-size,24px);min-height:var(--component-socket-target-size,24px);padding:0;border-radius:0;background:transparent;font-size:0;line-height:var(--component-socket-target-size,24px);overflow:visible;opacity:.68}
.node-port-exact.node-port-in{left:-12px}.node-port-exact.node-port-out{right:-12px}
.node-port-exact::before{top:7px;width:9px;height:9px}
.node-port-exact::after{content:attr(data-interface-label);display:none;position:absolute;top:-2px;z-index:30;width:max-content;max-width:210px;min-height:24px;padding:4px 7px;border:1px solid var(--line);border-radius:3px;background:var(--bg-deep);color:var(--ink);font-family:Inter,system-ui,sans-serif;font-size:10px;line-height:14px;white-space:normal;box-shadow:0 4px 14px rgba(0,0,0,.36);pointer-events:none}
.node-port-exact.node-port-in::after{left:22px;text-align:left}.node-port-exact.node-port-out::after{right:22px;text-align:right}
.node-port-exact:hover{opacity:1}.node-port-exact:hover::after,.node-port-exact:focus-visible::after{display:block}
.node-port-exact[data-context="False"]{opacity:0;pointer-events:none}
.graph-node[data-selected="True"] .node-port-exact[data-context="False"],.graph-node:hover .node-port-exact[data-context="False"]{opacity:.68;pointer-events:auto}
.graph-node[data-universal-openable="True"] .node-title{cursor:zoom-in}
.node-port.node-port-exact.wire-target-ready{opacity:1;pointer-events:auto}
.node-port[data-selected="True"]{color:var(--accent);opacity:1;filter:drop-shadow(0 0 3px var(--accent))}
.universal-wire[data-context="False"]:not([data-focused="True"]):not([data-hover-context="True"]){visibility:hidden;pointer-events:none}
.universal-wire[data-context="True"]{opacity:.62}
.wire-hit{fill:none;stroke:rgba(0,0,0,.001);stroke-width:14;vector-effect:non-scaling-stroke;pointer-events:stroke;cursor:pointer}
.wire-hit[data-context="False"]:not([data-focused="True"]):not([data-hover-context="True"]){visibility:hidden;pointer-events:none}
.wire-hit:hover+.universal-wire,.wire-hit[data-focused="True"]+.universal-wire{opacity:1;stroke-opacity:1}
.universal-wire{pointer-events:none}
.wire-endpoint{opacity:0;pointer-events:none;fill:var(--bg-panel);stroke:var(--accent);stroke-width:2;vector-effect:non-scaling-stroke;cursor:grab;transition:opacity .08s linear,stroke-width .08s linear}.wire-endpoint[data-focused="True"]{opacity:1;pointer-events:all}.wire-endpoint:hover,.wire-endpoint[data-dragging="True"]{stroke-width:3;cursor:grabbing}.node-port.wire-reconnect-ready{color:var(--ok);opacity:1;pointer-events:auto;filter:drop-shadow(0 0 3px var(--ok))}
.canvas-toolbar{background:var(--component-toolbar-background,var(--bg-panel));border-color:var(--component-toolbar-border,var(--line));border-radius:var(--component-toolbar-radius,4px);transition-duration:var(--component-toolbar-motion,80ms)}
.inspector-tab[data-active="true"]{box-shadow:inset 0 -2px 0 var(--component-tab-set-active,var(--accent))}
.inspector-tab{color:var(--component-tab-set-text,var(--ink-muted));font-family:var(--component-tab-set-font,Inter,system-ui,sans-serif);font-size:var(--component-tab-set-font-size,10px)}
.property-input{background:var(--component-properties-row-background,var(--bg));color:var(--component-card-text,var(--ink));border-radius:var(--component-toolbar-radius,4px)}
.library-row{background:var(--component-library-row-background,transparent)}
.library-row:hover{background:var(--component-library-row-hover,var(--bg-hover))}
.status-live{color:var(--component-status-success,var(--ok))}
"""

STYLESHEET += r"""
.rail-button::before{content:none!important}.graph-icon{display:block;flex:0 0 auto;overflow:visible;pointer-events:none}.control-label{display:block;line-height:1}.rail-button .graph-icon{width:17px;height:17px}.header-action.icon-only{width:28px;min-width:28px;padding:0;display:inline-flex;align-items:center;justify-content:center}.header-action.icon-only .graph-icon{width:15px;height:15px}.library-definition-place.icon-only{display:inline-flex;align-items:center;justify-content:center;font-size:0}.library-definition-place.icon-only .graph-icon{width:16px;height:16px}
"""


def _param(store, title, value):
    return store.add('param', title, floor={'op': 'value', 'value': value})


def _reference_param(store, title, target):
    return store.add('param', title, floor={'op': 'reference', 'target': target})


def _el(store, tag, title, *, text=None, cls=None, attrs=None, style=None):
    return ui_element(store, tag, text=text, title=title, cls=cls,
                      attrs=attrs, style=style)


def _children(store, parent, *children):
    for order, child in enumerate(children):
        connect_ui_child(store, parent, child, order=order)


def _set_owned_param(store, node_id, name, value):
    pid = _param(store, name, value)
    params = dict(store.nodes[node_id]['params'])
    params[name] = pid
    store.edit(node_id, ['params'], params)
    return pid


def _label_param(store, node_id):
    node = store.nodes[node_id]
    existing = node['params'].get('label')
    if existing in store.nodes:
        return existing
    pid = _set_owned_param(store, node_id, 'label', node['title'] or node_id)
    store.nodes[pid]['meta']['role'] = 'presentation_label'
    return pid


def _action(store, ui_id, operation, title, *, event='activate'):
    action = store.add('op', title, floor={'op': 'value', 'value': operation})
    connect_ui_action(store, ui_id, action, event=event)
    return action


def _bind_container_visibility(store, ui_id, container_param, container_id):
    candidate = store.add(
        'value', 'Container candidate: ' + container_id,
        floor={'op': 'value', 'value': container_id})
    visible = store.add(
        'op', 'Visible in container: ' + container_id,
        floor={'op': 'compare', 'cmp': '=='})
    store.wire(container_param, visible)
    store.wire(candidate, visible)
    connect_ui_binding(store, visible, ui_id, 'attr.data-visible')
    return visible


def _math_offset(store, source, amount, title):
    constant = store.add('value', title + ' offset', floor={'op': 'value', 'value': amount})
    output = store.add('op', title, floor={'op': 'math', 'fn': '+'})
    store.wire(source, output)
    store.wire(constant, output)
    return output


def _inspector_panel(store, inspector, focus, node_id, order):
    """Project one graph node into the right rail through relation bindings."""
    node = store.nodes[node_id]
    label_param = _label_param(store, node_id)
    display_title = node['title'] or (
        'Relation ' + node_id if node['kind'] == 'wire' else node_id)
    panel = _el(store, 'section', 'Inspector: ' + display_title,
                cls='inspector-panel', attrs={'data-inspected-node': node_id})
    selected_id = store.add('value', 'selected id',
                            floor={'op': 'value', 'value': node_id})
    selected = store.add('op', 'is selected', floor={'op': 'compare', 'cmp': '=='})
    store.wire(focus, selected)
    store.wire(selected_id, selected)
    connect_ui_binding(store, selected, panel, 'attr.data-visible')
    kicker = _el(store, 'div', 'Inspector role', text=node['kind'],
                 cls='inspector-kicker')
    panel_title = _el(store, 'h1', 'Inspector title', cls='inspector-title')
    connect_ui_binding(store, label_param, panel_title, 'text')
    meta = _el(store, 'div', 'Inspector identity',
               text='%s / %d relations' % (node_id, len(node['relations'])),
               cls='inspector-meta')
    connections = _el(store, 'section', 'Connections section', cls='inspector-section')
    connections_heading = _el(store, 'div', 'Connections heading', text='CONNECTIONS',
                              cls='inspector-heading')
    connection_box = _el(store, 'div', 'Connection summary',
                         text='%d relation nodes attached' % len(node['relations']),
                         cls='connection-box')
    _children(store, connections, connections_heading, connection_box)
    properties = _el(store, 'section', 'Properties panel', cls='inspector-section')
    properties_heading = _el(store, 'div', 'Properties heading', text='PROPERTIES',
                             cls='inspector-heading')
    connect_ui_child(store, properties, properties_heading, order=0)
    input_ids = {}
    prop_order = 1
    for name, pid in node['params'].items():
        floor = store.nodes[pid]['body'].get('floor', {})
        current = floor.get('value', '') if floor.get('op') == 'value' else ''
        if name.startswith(('endpoint:', 'stage:')) and isinstance(current, dict):
            row = _el(store, 'div', 'Relation parameter: ' + name, cls='property-row')
            label = _el(store, 'span', 'Relation parameter label: ' + name,
                        text='%s / %s' % (name, current.get('role', 'stage')),
                        cls='property-label')
            participant = _el(store, 'input', 'Endpoint participant: ' + name,
                              cls='property-input', attrs={'type': 'text'})
            connect_ui_binding(store, pid, participant, 'value.node_id')
            children = [label, participant]
            if 'port_id' in current:
                port = _el(store, 'input', 'Endpoint port: ' + name,
                           cls='property-input', attrs={'type': 'text'})
                connect_ui_binding(store, pid, port, 'value.port_id')
                children.append(port)
                input_ids[name + '.port_id'] = port
            _children(store, row, *children)
            connect_ui_child(store, properties, row, order=prop_order)
            prop_order += 1
            input_ids[name + '.node_id'] = participant
            continue
        editable = floor.get('op') == 'value' and not isinstance(current, (dict, list))
        if isinstance(current, bool):
            input_type = 'checkbox'
        elif isinstance(current, (int, float)):
            input_type = 'number'
        elif isinstance(current, str) and current.startswith('#') and len(current) in (4, 7):
            input_type = 'color'
        else:
            input_type = 'text'
        row = _el(store, 'label', 'Property: ' + name, cls='property-row')
        label = _el(store, 'span', 'Property label: ' + name,
                    text=name.replace('_', ' '), cls='property-label')
        if editable:
            field = _el(store, 'input', 'Property input: ' + name,
                        cls='property-input', attrs={'type': input_type})
            connect_ui_binding(store, pid, field, 'value')
        elif floor.get('op') == 'reference':
            field = _el(store, 'div', 'Property reference: ' + name,
                        text='-> ' + str(floor.get('target', '')),
                        cls='connection-box')
        else:
            field = _el(store, 'div', 'Property value: ' + name, cls='connection-box')
            connect_ui_binding(store, pid, field, 'text')
        _children(store, row, label, field)
        connect_ui_child(store, properties, row, order=prop_order)
        prop_order += 1
        if editable:
            input_ids[name] = field
    panel_children = [kicker, panel_title, meta, connections]
    if node['kind'] == 'wire':
        transport = _el(store, 'section', 'Relation transport actions',
                        cls='inspector-section')
        transport_heading = _el(store, 'div', 'Transport heading',
                                text='TRANSPORT', cls='inspector-heading')
        encrypt = _el(store, 'button', 'Encode and encrypt relation',
                      text='Encode + encrypt', cls='header-action',
                      attrs={'type': 'button'})
        decrypt = _el(store, 'button', 'Decrypt and decode relation',
                      text='Decrypt + decode', cls='header-action',
                      attrs={'type': 'button'})
        _action(store, encrypt, {
            'op': 'command', 'capability': 'relation.transport.encrypt',
            'args': {'relation_id': node_id}}, 'Add encrypted relation transport')
        _action(store, decrypt, {
            'op': 'command', 'capability': 'relation.transport.decrypt',
            'args': {'relation_id': node_id}}, 'Add decrypted relation transport')
        _children(store, transport, transport_heading, encrypt, decrypt)
        panel_children.append(transport)
    panel_children.append(properties)
    _children(store, panel, *panel_children)
    connect_ui_child(store, inspector, panel, order=order)
    return panel, input_ids


def _one_titled(store, kind, title):
    found = [nid for nid, node in store.nodes.items()
             if node['kind'] == kind and node['title'] == title]
    if len(found) != 1:
        raise ValueError('expected one %s titled %r, found %d'
                         % (kind, title, len(found)))
    return found[0]


def _relation_projection(store, relation_id, wire_layer, focus, *, inspector=None,
                         order=0, container_param=None, container_id=None):
    relation = store.nodes[relation_id]
    sources = relation_sources(store.nodes, relation)
    targets = relation_targets(store.nodes, relation)
    if not sources or not targets:
        raise ValueError('relation %s has no projectable endpoints' % relation_id)
    source_id = sources[0]['node_id']
    target_id = targets[0]['node_id']
    for name, value in (('color', '#d97757'), ('width', 2.1),
                        ('dash', ''), ('hidden', False),
                        ('encoding', 'identity'), ('encryption', 'none')):
        if name not in relation['params']:
            set_relation_parameter(store, relation_id, name, value)
    if 'payload' not in relation['params']:
        payload = build_payload_envelope(store, {
            'logical_type': 'urn:archhub:type:any',
            'media_type': 'application/x-archhub-value',
            'mode': 'inline', 'value_ref': source_id,
        }, title='Relation payload')
        attach_payload(store, relation_id, payload)
    source = store.nodes[source_id]
    target = store.nodes[target_id]
    required = ('position_x', 'position_y')
    if not all(name in source['params'] and name in target['params'] for name in required):
        return None
    x1 = _math_offset(store, source['params']['position_x'], 204, 'cable source x')
    y1 = _math_offset(store, source['params']['position_y'], 67, 'cable source y')
    x2 = target['params']['position_x']
    y2 = _math_offset(store, target['params']['position_y'], 67, 'cable target y')
    c1 = _math_offset(store, x1, 80, 'cable control one x')
    c2 = _math_offset(store, x2, -80, 'cable control two x')
    path_value = store.add(
        'op', 'Cable Bezier geometry',
        floor={'op': 'format',
               'template': 'M {} {} C {} {}, {} {}, {} {}'})
    for value_id in (x1, y1, c1, y1, c2, y2, x2, y2):
        store.wire(value_id, path_value)
    path = _el(store, 'path', 'Cable projection', cls='wire-line',
               attrs={'data-relation': relation_id,
                      'data-source-node': source_id,
                      'data-target-node': target_id,
                      'marker-end': 'url(#archhub-wire-arrow)'})
    connect_ui_binding(store, path_value, path, 'attr.d')
    focused_id = store.add('value', 'Focused relation candidate',
                           floor={'op': 'value', 'value': relation_id})
    focused = store.add('op', 'Relation is focused',
                        floor={'op': 'compare', 'cmp': '=='})
    store.wire(focus, focused)
    store.wire(focused_id, focused)
    connect_ui_binding(store, focused, path, 'attr.data-focused')
    if container_param is not None and container_id is not None:
        _bind_container_visibility(store, path, container_param, container_id)
    presentation_ports = {
        'color': 'style.stroke', 'width': 'style.stroke_width',
        'dash': 'style.stroke_dasharray', 'hidden': 'attr.data-hidden',
    }
    for name, port in presentation_ports.items():
        if name in relation['params']:
            connect_ui_binding(store, relation['params'][name], path, port)
    connect_ui_child(store, wire_layer, path, order=order)
    _action(store, path, {'op': 'set', 'id': focus,
                          'path': ['body', 'floor', 'value'],
                          'value': relation_id}, 'Select relation')
    panel = inputs = None
    if inspector is not None:
        panel, inputs = _inspector_panel(store, inspector, focus, relation_id, order)
    return {'ui': path, 'authority': relation_id, 'panel': panel, 'inputs': inputs}


def project_relation_on_canvas(store, relation_id):
    """Add a disposable cable and inspector projection for a new relation node."""
    wire_layer = _one_titled(store, 'ui', 'Wire projection layer')
    inspector = _one_titled(store, 'ui', 'Properties inspector')
    app = _one_titled(store, 'session', 'ArchHub Application')
    focus = store.nodes[app]['params']['focus']
    container = store.nodes[app]['params']['container']
    container_id = store.pull(container)
    return _relation_projection(store, relation_id, wire_layer, focus,
                                inspector=inspector, order=len(store.nodes),
                                container_param=container, container_id=container_id)


def _projection_match(store, *, graph_node=None, container_id=None, relation_id=None):
    for ui_id, ui_node in store.nodes.items():
        if ui_node['kind'] != 'ui' or 'attrs' not in ui_node['params']:
            continue
        attrs = store.pull(ui_node['params']['attrs'])
        if not isinstance(attrs, dict):
            continue
        if graph_node is not None and attrs.get('data-graph-node') != graph_node:
            continue
        if relation_id is not None and attrs.get('data-relation') != relation_id:
            continue
        if container_id is not None and attrs.get('data-container-id') != container_id:
            continue
        return ui_id
    return None


def project_node_on_canvas(store, node_id, *, container_id=None, order=None):
    """Project a newly created universal node into every live app lens."""
    app = _one_titled(store, 'session', 'ArchHub Application')
    focus = store.nodes[app]['params']['focus']
    container = store.nodes[app]['params']['container']
    container_id = container_id or store.pull(container)
    existing = _projection_match(store, graph_node=node_id, container_id=container_id)
    if existing:
        return {'card': existing, 'existing': True}
    wire_source = store.nodes[app]['params']['wire_source']
    selection = store.nodes[app]['params']['selection']
    stage = _one_titled(store, 'ui', 'Canvas stage')
    inspector = _one_titled(store, 'ui', 'Properties inspector')
    library_list = _one_titled(store, 'ui', 'Node library list')
    search_results = _one_titled(store, 'ui', 'Search results')
    search_query = store.nodes[app]['params']['search_query']
    node = store.nodes[node_id]
    if 'position_x' not in node['params'] or 'position_y' not in node['params']:
        index = int(order or 0)
        params = dict(node['params'])
        params['position_x'] = _param(store, 'position_x', 80 + (index % 5) * 232)
        params['position_y'] = _param(store, 'position_y', 92 + (index // 5) * 164)
        store.edit(node_id, ['params'], params, actor='canvas-projection')
    label_param = _label_param(store, node_id)
    card = _el(store, 'div', 'Canvas node: ' + node['title'], cls='graph-node',
               attrs={'data-graph-node': node_id,
                      'data-node-kind': node['kind'],
                      'data-container-id': container_id,
                      'data-draggable': 'true'})
    _bind_container_visibility(store, card, container, container_id)
    focused_id = store.add('value', 'Focused node candidate: ' + node_id,
                           floor={'op': 'value', 'value': node_id})
    focused = store.add('op', 'Node is focused: ' + node_id,
                        floor={'op': 'compare', 'cmp': '=='})
    store.wire(focus, focused)
    store.wire(focused_id, focused)
    connect_ui_binding(store, focused, card, 'attr.data-focused')
    accent = _el(store, 'div', 'Node accent', cls='node-accent')
    kind = _el(store, 'div', 'Node kind', text=node['kind'], cls='node-head')
    title = _el(store, 'div', 'Node title', cls='node-title')
    connect_ui_binding(store, label_param, title, 'text')
    value = _el(store, 'div', 'Node live value', cls='node-value')
    select = _el(store, 'button', 'Select for grouping: ' + node_id,
                 cls='node-select', attrs={'type': 'button',
                                           'title': 'Toggle multi-selection'})
    _action(store, select, {'op': 'command', 'capability': 'selection.toggle',
                            'args': {'selection_param': selection,
                                     'node_id': node_id}}, 'Toggle node selection')
    selected_id = store.add('value', 'Selection candidate: ' + node_id,
                            floor={'op': 'value', 'value': node_id})
    selected = store.add('op', 'Node is in selection: ' + node_id,
                         floor={'op': 'compare', 'cmp': 'contains'})
    store.wire(selection, selected)
    store.wire(selected_id, selected)
    connect_ui_binding(store, selected, select, 'attr.data-active')
    display_source = node['params'].get('health') or node['params'].get('readiness') \
        or node['params'].get('lifecycle') or node_id
    connect_ui_binding(store, display_source, value, 'text')
    connect_ui_binding(store, node['params']['position_x'], card,
                       'style.left', suffix='px')
    connect_ui_binding(store, node['params']['position_y'], card,
                       'style.top', suffix='px')
    port_row = _el(store, 'div', 'Node ports', cls='node-ports')
    input_port = _el(store, 'button', 'Input port: ' + node_id, text='value',
                     cls='node-port node-port-in', attrs={'type': 'button'})
    output_port = _el(store, 'button', 'Output port: ' + node_id, text='value',
                      cls='node-port node-port-out', attrs={'type': 'button'})
    _children(store, port_row, input_port, output_port)
    source_value = {'node_id': node_id, 'port_id': 'value'}
    _action(store, output_port,
            {'op': 'set', 'id': wire_source, 'path': ['body', 'floor', 'value'],
             'value': source_value}, 'Start relation')
    expected_source = store.add('value', 'Expected wire source: ' + node_id,
                                floor={'op': 'value', 'value': source_value})
    pending = store.add('op', 'Wire source is pending: ' + node_id,
                        floor={'op': 'compare', 'cmp': '=='})
    store.wire(wire_source, pending)
    store.wire(expected_source, pending)
    connect_ui_binding(store, pending, output_port, 'attr.data-pending')
    _action(store, input_port, {
        'op': 'command', 'capability': 'relation.create',
        'args': {'source_param': wire_source, 'target_node': node_id,
                 'target_port': 'value'}}, 'Complete relation')
    _children(store, card, select, accent, kind, title, value, port_row)
    connect_ui_child(store, stage, card, order=len(store.nodes))
    _action(store, card, {'op': 'set', 'id': focus,
                          'path': ['body', 'floor', 'value'], 'value': node_id},
            'Select canvas node')
    if 'inner' in node['body']:
        _action(store, card, {
            'op': 'command', 'capability': 'container.open',
            'args': {'container_id': node_id}},
            'Open node container', event='double_activate')
    existing_panel = next((ui_id for ui_id, ui_node in store.nodes.items()
                           if ui_node['kind'] == 'ui' and 'attrs' in ui_node['params']
                           and store.pull(ui_node['params']['attrs']).get(
                               'data-inspected-node') == node_id), None)
    if existing_panel:
        panel, inputs = existing_panel, {}
    else:
        panel, inputs = _inspector_panel(store, inspector, focus, node_id, len(store.nodes))

    library_row = _el(store, 'button', 'Library row: ' + node['title'],
                      cls='library-row', attrs={'type': 'button'})
    connect_ui_binding(store, label_param, library_row, 'text')
    _action(store, library_row, {'op': 'set', 'id': focus,
                                 'path': ['body', 'floor', 'value'], 'value': node_id},
            'Select node')
    connect_ui_child(store, library_list, library_row, order=len(store.nodes))

    match = store.add('op', 'Search match: ' + node_id,
                      floor={'op': 'compare', 'cmp': 'icontains'})
    store.wire(label_param, match)
    store.wire(search_query, match)
    search_row = _el(store, 'button', 'Search result: ' + node_id,
                     cls='library-row search-result',
                     attrs={'type': 'button'})
    connect_ui_binding(store, label_param, search_row, 'text')
    connect_ui_binding(store, match, search_row, 'attr.data-visible')
    _action(store, search_row, {'op': 'set', 'id': focus,
                                'path': ['body', 'floor', 'value'], 'value': node_id},
            'Open search result')
    connect_ui_child(store, search_results, search_row, order=len(store.nodes))
    return {'card': card, 'select': select,
            'ports': {'input': input_port, 'output': output_port},
            'panel': panel, 'inputs': inputs, 'library_row': library_row,
            'search_row': search_row}


def _set_container_navigation(store, container_id, *, push=True):
    app = _one_titled(store, 'session', 'ArchHub Application')
    params = store.nodes[app]['params']
    container_param = params['container']
    focus = params['focus']
    stack_param = params['container_stack']
    title_param = params['container_title']
    current = store.pull(container_param)
    stack = list(store.pull(stack_param) or [])
    if push:
        if not stack:
            stack = [current]
        if container_id in stack:
            stack = stack[:stack.index(container_id) + 1]
        elif stack[-1] != container_id:
            stack.append(container_id)
    else:
        stack = [container_id]
    for node_id, value in (
            (container_param, container_id), (focus, container_id),
            (stack_param, stack), (title_param, store.nodes[container_id]['title'])):
        store.edit(node_id, ['body', 'floor', 'value'], value,
                   actor='container-navigation')
    return container_id


def navigate_container_back(store):
    app = _one_titled(store, 'session', 'ArchHub Application')
    stack_param = store.nodes[app]['params']['container_stack']
    stack = list(store.pull(stack_param) or [])
    if len(stack) <= 1:
        return store.pull(store.nodes[app]['params']['container'])
    stack.pop()
    target = stack[-1]
    _set_container_navigation(store, target, push=False)
    store.edit(stack_param, ['body', 'floor', 'value'], stack,
               actor='container-navigation')
    return target


def navigate_container_root(store):
    root = _one_titled(store, 'session', 'ArchHub Operating Graph')
    return _set_container_navigation(store, root, push=False)


def project_container_on_canvas(store, container_id):
    """Lazily materialize one open container as node UI projections."""
    container_node = store.nodes.get(container_id)
    if not container_node or 'inner' not in container_node['body']:
        raise ValueError('container.open requires an openable node')
    app = _one_titled(store, 'session', 'ArchHub Application')
    container_param = store.nodes[app]['params']['container']
    focus = store.nodes[app]['params']['focus']
    wire_layer = _one_titled(store, 'ui', 'Wire projection layer')
    inspector = _one_titled(store, 'ui', 'Properties inspector')
    children = list(dict.fromkeys(container_node['body']['inner']))
    projected = []
    for index, node_id in enumerate(children):
        projected.append(project_node_on_canvas(
            store, node_id, container_id=container_id, order=index))
    child_set = set(children)
    relation_ids = set()
    for node_id in children:
        relation_ids.update(store.nodes[node_id]['relations'])
    for index, relation_id in enumerate(sorted(relation_ids)):
        relation = store.nodes.get(relation_id)
        if not relation or relation['kind'] != 'wire':
            continue
        sources = {item['node_id'] for item in relation_sources(store.nodes, relation)}
        targets = {item['node_id'] for item in relation_targets(store.nodes, relation)}
        if not sources <= child_set or not targets <= child_set:
            continue
        if _projection_match(store, relation_id=relation_id, container_id=container_id):
            continue
        _relation_projection(
            store, relation_id, wire_layer, focus, inspector=inspector,
            order=index, container_param=container_param, container_id=container_id)
    _set_container_navigation(store, container_id, push=True)
    return [item['card'] for item in projected]


def build_archhub_application(store=None):
    from .core import Store

    store = store or Store()
    resolved_map_path = resolve_map_path()
    grand = import_grand_map(store)
    models = build_models_domain(store)
    connectors = build_connectors_domain(store, connectors=[
        {
            'key': 'brain-mcp', 'title': 'Brain MCP',
            'capabilities': ['read', 'governed-effect'],
            'endpoint': {'transport': 'http', 'address': 'http://127.0.0.1:8473/mcp',
                         'enabled': True, 'timeout_ms': 8000},
            'configuration': {'protocol': 'mcp', 'scope': 'personal'},
        },
        {
            'key': 'node-runtime', 'title': 'Node runtime',
            'capabilities': ['graph-read', 'graph-edit', 'projection'],
            'endpoint': {'transport': 'http', 'address': 'http://127.0.0.1:8482',
                         'enabled': True, 'timeout_ms': 8000},
            'configuration': {'protocol': 'archhub-node-graph-v1', 'scope': 'local'},
        },
    ])
    orchestration = build_orchestration_domain(store)
    selfext = build_self_extension_domain(store)
    monetization = build_monetization_domain(store)
    users = build_users_domain(store, users=[{
        'id': 'founder', 'display_name': 'Founder', 'email': '',
        'role': 'owner', 'entitlements': ['workspace'],
        'auth': {
            'capability_ref': 'op://archhub/auth/founder',
            'evidence': {
                'provider': 'external', 'method': 'not-connected',
                'verified': False, 'verified_at': '', 'subject_ref': '',
            },
        },
    }], sessions=[{
        'id': 'archhub-application', 'title': 'ArchHub Application Access',
        'owner': 'founder', 'privacy_scope': 'INTERNAL',
    }])
    cloud = build_cloud_domain(store)
    community = build_community_domain(store)
    resources = build_resource_domain(store)
    cloud_runtime = build_cloud_runtime_nodes(
        store, cloud, users=users, monetization=monetization,
        community=community)
    publication = build_deployment_evidence(
        store, None if resolved_map_path != PUBLIC_MAP_PATH else {
            'status': 'not-connected', 'visibility': 'private',
        })
    lifecycle_policy = create_lifecycle_policy(store)
    session_catalog = create_session_catalog(
        store, lifecycle_policy=lifecycle_policy)
    policy = build_desktop_launch_policy(store)
    brain_url = _param(store, 'Brain MCP endpoint', 'http://127.0.0.1:8473/mcp')
    brain_owner = _param(store, 'Brain owner', 'founder')
    brain_args = _param(store, 'Compliance report arguments', {'owner_user': 'founder'})
    brain_report_source = store.add(
        'op', 'Live Brain compliance report',
        floor={'op': 'mcp', 'url': {'$param': 'url'},
               'tool': 'brain.compliance_report', 'args': {'$param': 'args'},
               'effectful': False, 'timeout': 8.0},
        params={'url': brain_url, 'args': brain_args})
    brain_report_result = _param(store, 'Brain compliance snapshot', {
        'ok': False, 'status': 'NOT RUN', 'active_cde': {}, 'work': {},
        'hook_coverage': {}, 'history': {}, 'last_gate_decision': {},
        'run_reports': {},
    })
    brain_fields = {}
    for key in ('active_cde', 'work', 'hook_coverage', 'history',
                'last_gate_decision', 'run_reports'):
        field = store.add('op', 'Brain field: ' + key,
                          floor={'op': 'field', 'path': key, 'default': {}})
        store.wire(brain_report_result, field)
        brain_fields[key] = field
    authority_config = load_local_authority_config()
    grand_map_path_value = (
        str(resolved_map_path) if resolved_map_path != PUBLIC_MAP_PATH else '')
    cde_overlay_path_value = str(
        authority_config.get('cde_overlay_path') or '').strip()
    grand_map_path = _param(store, 'Grand Map authority path', grand_map_path_value)
    cde_overlay_path = _param(store, 'Node-native CDE overlay path',
                              cde_overlay_path_value)
    brain_sync_args = _param(store, 'Grand Map sync arguments', {
        'grand_map_path': grand_map_path_value,
        'overlay_path': cde_overlay_path_value,
        'owner_user': 'founder', 'dry_run': False,
    })
    brain_work_sync = store.add(
        'op', 'Sync Grand Map work into Brain',
        floor={'op': 'mcp', 'url': {'$param': 'url'},
               'tool': 'brain.grand_map_work_sync', 'args': {'$param': 'args'},
               'effectful': True, 'timeout': 60.0},
        params={'url': brain_url, 'args': brain_sync_args}, frozen=True)
    brain_work_sync_result = _param(store, 'Grand Map work sync result',
                                    {'status': 'NOT RUN'})
    brain_claim_args = _param(store, 'Brain work claim arguments', {
        'runtime': 'archhub-app', 'fit': ['test', 'python'],
        'owner_user': 'founder', 'agent_id': 'archhub-application',
        'wrap': False, 'write': True,
    })
    brain_work_claim = store.add(
        'op', 'Claim governed work from Brain',
        floor={'op': 'mcp', 'url': {'$param': 'url'},
               'tool': 'brain.work_assigned_block', 'args': {'$param': 'args'},
               'effectful': True, 'timeout': 30.0},
        params={'url': brain_url, 'args': brain_claim_args}, frozen=True)
    brain_work_claim_result = _param(store, 'Brain work claim result',
                                     {'status': 'NOT RUN'})
    brain = store.add(
        'session', 'Brain',
        inner=[policy['probes'][0], policy['probe_scores'][0],
               policy['probes'][1], policy['probe_scores'][1],
               brain_report_source, brain_report_result,
               brain_work_sync, brain_work_sync_result,
               brain_work_claim, brain_work_claim_result] + list(brain_fields.values()),
        params={'endpoint': brain_url, 'owner': brain_owner,
                'compliance_snapshot': brain_report_result,
                'work_sync_result': brain_work_sync_result,
                'work_claim_result': brain_work_claim_result},
    )
    cde_stage = _param(store, 'CDE stage', 'WIP')
    cde_scope = _param(store, 'CDE scope', '10.PRODUCT/13.NODE-LANGUAGE')
    cde_tier = _param(store, 'privacy tier', 'T1 INTERNAL')
    cde_container_id = _param(store, 'CDE container id', 'UNASSIGNED')
    cde_runtime = _param(store, 'CDE runtime', 'UNASSIGNED')
    cde = store.add('session', 'Active CDE',
                    inner=[cde_stage, cde_scope, cde_tier, cde_container_id, cde_runtime],
                    params={'stage': cde_stage, 'scope': cde_scope,
                            'privacy_tier': cde_tier,
                            'container_id': cde_container_id, 'runtime': cde_runtime})
    cockpit = build_cockpit_domain(
        store,
        founder_id='founder', role='owner', identity_verified=False,
        source_nodes={
            'users': users['session'],
            'revenue': monetization['revenue'],
            'brain': brain_report_result,
            'hooks': brain_fields['hook_coverage'],
            'governance': policy['governance_score'],
            'grand_map': grand['grand'],
            'active_cde': cde,
            'metrics_cloud': cloud['session'],
            'metrics_community': community['session'],
            'publication': publication['record'],
            'external_resources': resources['readiness'],
        },
        self_extension_node=selfext['session'],
    )
    resource_authority_relations = [
        bind_resource_authority(store, resource, cockpit['founder_verdict'])
        for resource in resources['resources'].values()
    ]
    for session_id, key, description in (
            (grand['session'], 'grand-map', 'The complete live parametric Grand Map'),
            (brain, 'brain', 'Brain, governed work and compliance'),
            (policy['session'], 'governance', 'Launch policy and independent courts'),
            (cde, 'active-cde', 'Current governed work container'),
            (models['session'], 'models', 'Provider catalog and visible routing graph'),
            (connectors['session'], 'connectors', 'Host catalog and explicit health evidence'),
            (orchestration['session'], 'orchestration',
             'Agent assignment and governed execution graph'),
            (selfext['session'], 'self-extension',
             'Proposal, court, installation and rollback graph'),
            (monetization['session'], 'monetization',
             'Plans, entitlements, quota, billing and revenue graph'),
            (users['session'], 'users', 'Identity, role, ownership and privacy graph'),
            (cloud['session'], 'cloud',
             'Cloud services, deployment, queues and synchronization graph'),
            (cloud_runtime['session'], 'cloud-runtime',
             'Node-authoritative local HTTP adapter over the Cloud graph'),
            (publication['session'], 'publication',
             'Observed publication and deployment evidence graph'),
            (resources['session'], 'resources',
             'External payload hosts under graph-owned identity, ports, policy and gates'),
            (community['session'], 'community',
             'Membership, consent, federation, moderation and marketplace graph'),
            (cockpit['session'], 'cockpit',
             'Founder gate, command routing, read tools and governed effects')):
        govern_existing_session(
            store, session_id, key, description=description,
            lifecycle_policy=lifecycle_policy)
        register_session(store, session_catalog, session_id)
    cde_fields = {}
    for name, path, default in (
            ('stage', ['active_cde', 'container', 'lifecycle_state'], 'UNASSIGNED'),
            ('scope', ['active_cde', 'container', 'allowed_paths'], []),
            ('tier', ['active_cde', 'container', 'tier'], 'UNASSIGNED'),
            ('container_id', ['active_cde', 'container', 'container_id'], 'UNASSIGNED'),
            ('runtime', ['active_cde', 'runtime'], 'UNASSIGNED')):
        field = store.add('op', 'Active CDE field: ' + name,
                          floor={'op': 'field', 'path': path, 'default': default})
        store.wire(brain_report_result, field)
        cde_fields[name] = field
    orchestration_brain_ok = store.add(
        'op', 'Orchestration Brain connection truth',
        floor={'op': 'field', 'path': ['ok'], 'default': False})
    store.wire(brain_report_result, orchestration_brain_ok)
    orchestration_hook_status = store.add(
        'op', 'Orchestration hook coverage status',
        floor={'op': 'field', 'path': ['hook_coverage', 'status'], 'default': 'missing'})
    store.wire(brain_report_result, orchestration_hook_status)
    green_status = store.add('value', 'Green hook status',
                             floor={'op': 'value', 'value': 'green'})
    orchestration_hooks_ready = store.add(
        'op', 'Orchestration hooks ready truth',
        floor={'op': 'compare', 'cmp': '=='})
    store.wire(orchestration_hook_status, orchestration_hooks_ready)
    store.wire(green_status, orchestration_hooks_ready)
    task_key = orchestration['task_order'][0]
    task_params = orchestration['task_params'][task_key]
    store.relation([
        {'role': 'source', 'direction': 'out', 'node_id': orchestration_brain_ok,
         'port_id': 'truth', 'cardinality': 'one'},
        {'role': 'target', 'direction': 'in', 'node_id': task_params['brain_connected'],
         'port_id': 'sample', 'cardinality': 'one'},
    ], title='Brain compliance drives orchestration gate')
    store.relation([
        {'role': 'source', 'direction': 'out', 'node_id': orchestration_hooks_ready,
         'port_id': 'truth', 'cardinality': 'one'},
        {'role': 'target', 'direction': 'in', 'node_id': task_params['hooks_ready'],
         'port_id': 'sample', 'cardinality': 'one'},
    ], title='Hook coverage drives orchestration gate')
    store.relation([
        {'role': 'source', 'direction': 'out', 'node_id': cde_scope,
         'port_id': 'scope', 'cardinality': 'one'},
        {'role': 'target', 'direction': 'in', 'node_id': task_params['cde_scope'],
         'port_id': 'scope', 'cardinality': 'one'},
    ], title='Active CDE scopes orchestration task')
    governance_domain = grand['domains'].get('governance') or grand['session']
    integration_relations = [
        store.relation([
            {'role': 'source', 'direction': 'out', 'node_id': brain,
             'port_id': 'compliance', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in', 'node_id': policy['session'],
             'port_id': 'brain', 'cardinality': 'one'},
        ], title='Brain governs launch policy'),
        store.relation([
            {'role': 'source', 'direction': 'out', 'node_id': policy['governance_score'],
             'port_id': 'score', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in', 'node_id': governance_domain,
             'port_id': 'compliance', 'cardinality': 'one'},
        ], title='Governance court reports to Grand Map'),
        store.relation([
            {'role': 'source', 'direction': 'out', 'node_id': cde_stage,
             'port_id': 'stage', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in', 'node_id': policy['session'],
             'port_id': 'active_cde', 'cardinality': 'one'},
        ], title='Active CDE scopes governance'),
        store.relation([
            {'role': 'source', 'direction': 'out', 'node_id': grand['report'],
             'port_id': 'requirements', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in', 'node_id': brain,
             'port_id': 'grand_map', 'cardinality': 'one'},
        ], title='Grand Map feeds Brain'),
    ]
    domain_integration_relations = [
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': cloud['session'],
             'port_id': 'cloud_authority', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in',
             'node_id': cloud_runtime['session'],
             'port_id': 'runtime_authority', 'cardinality': 'one'},
        ], title='Cloud authority drives the HTTP runtime'),
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': publication['record'],
             'port_id': 'deployment_evidence', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in', 'node_id': brain,
             'port_id': 'publication_evidence', 'cardinality': 'many'},
        ], title='Publication evidence reports to Brain'),
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': selfext['proposal_record'],
             'port_id': 'extension_request', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in',
             'node_id': orchestration['tasks'][task_key],
             'port_id': 'requested_work', 'cardinality': 'one'},
        ], title='Extension proposal enters governed orchestration'),
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': selfext['court_verdict'],
             'port_id': 'verdict', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in', 'node_id': brain,
             'port_id': 'self_extension_court', 'cardinality': 'one'},
        ], title='Self-extension court reports to Brain'),
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': users['privacy_gates']['archhub-application'],
             'port_id': 'authority_gate', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in',
             'node_id': selfext['approval'],
             'port_id': 'authority', 'cardinality': 'one'},
        ], title='Application access policy scopes extension approval'),
        store.relation([
            {'role': 'source', 'direction': 'out', 'node_id': users['session'],
             'port_id': 'identity', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in',
             'node_id': monetization['entitlements'],
             'port_id': 'account', 'cardinality': 'one'},
        ], title='Identity scopes commercial entitlements'),
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': monetization['quota_gate'],
             'port_id': 'quota', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in',
             'node_id': orchestration['governance_groups'][task_key],
             'port_id': 'commercial_gate', 'cardinality': 'one'},
        ], title='Quota state reaches governed execution'),
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': monetization['free_key'],
             'port_id': 'shared_model_capability', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in', 'node_id': models['session'],
             'port_id': 'commercial_capability', 'cardinality': 'one'},
        ], title='Free-tier capability reaches model routing'),
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': monetization['byo_key'],
             'port_id': 'credential_policy', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in',
             'node_id': connectors['session'],
             'port_id': 'credential_capability', 'cardinality': 'one'},
        ], title='BYO-key policy reaches connector credentials'),
        store.relation([
            {'role': 'source', 'direction': 'out', 'node_id': users['session'],
             'port_id': 'identity', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in',
             'node_id': cloud['services']['cloud_auth']['service'],
             'port_id': 'identity_policy', 'cardinality': 'one'},
        ], title='Identity reaches cloud authentication'),
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': monetization['billing'],
             'port_id': 'billing', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in',
             'node_id': cloud['services']['cloud_billing']['service'],
             'port_id': 'commercial_authority', 'cardinality': 'one'},
        ], title='Commercial authority reaches cloud billing'),
        store.relation([
            {'role': 'source', 'direction': 'out', 'node_id': brain,
             'port_id': 'replication', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in',
             'node_id': cloud['services']['cloud_brain_replica']['service'],
             'port_id': 'brain_state', 'cardinality': 'one'},
        ], title='Brain reaches its cloud replica'),
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': cockpit['founder_verdict'],
             'port_id': 'founder_gate', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in',
             'node_id': orchestration['governance_groups'][task_key],
             'port_id': 'founder_authority', 'cardinality': 'one'},
        ], title='Founder Cockpit gate reaches governed execution'),
        store.relation([
            {'role': 'source', 'direction': 'out', 'node_id': users['session'],
             'port_id': 'identity', 'cardinality': 'many'},
            {'role': 'target', 'direction': 'in',
             'node_id': community['community'],
             'port_id': 'membership', 'cardinality': 'many'},
        ], title='Identity reaches Community membership'),
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': community['session'],
             'port_id': 'community_knowledge', 'cardinality': 'many'},
            {'role': 'target', 'direction': 'in', 'node_id': brain,
             'port_id': 'community', 'cardinality': 'many'},
        ], title='Community knowledge reaches Brain'),
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': cloud['services']['cloud_brain_replica']['service'],
             'port_id': 'federation_transport', 'cardinality': 'many'},
            {'role': 'target', 'direction': 'in',
             'node_id': community['federation'],
             'port_id': 'transport', 'cardinality': 'many'},
        ], title='Cloud transport reaches Community federation'),
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': monetization['entitlements'],
             'port_id': 'entitlement', 'cardinality': 'many'},
            {'role': 'target', 'direction': 'in',
             'node_id': community['marketplace'],
             'port_id': 'marketplace_access', 'cardinality': 'many'},
        ], title='Entitlements reach Community marketplace'),
    ]
    resource_connections = [
        connect_resource(store, resources, 'governance-standard', policy['session'],
                         target_port='governance_rules'),
        connect_resource(store, resources, 'public-repository', selfext['session'],
                         target_port='product_tree'),
        connect_resource(store, resources, 'grand-map-authority', grand['session'],
                         target_port='map_authority'),
        connect_resource(store, resources, 'brain-daemon', brain,
                         target_port='brain_transport'),
        connect_resource(store, resources, 'application-runtime', cloud_runtime['session'],
                         target_port='local_runtime'),
        connect_resource(store, resources, 'identity-database', users['session'],
                         target_port='identity_store'),
        connect_resource(store, resources, 'application-database',
                         cloud['services']['cloud_persistent_db']['service'],
                         target_port='persistence'),
        connect_resource(store, resources, 'object-storage', cloud['session'],
                         target_port='content_store'),
        connect_resource(store, resources, 'billing-provider', monetization['billing'],
                         target_port='billing_provider'),
        connect_resource(store, resources, 'email-provider',
                         cloud['services']['cloud_email_sender']['service'],
                         target_port='message_provider'),
        connect_resource(store, resources, 'website-publication', publication['record'],
                         target_port='publication_host'),
    ]
    domain_integration_relations.extend(resource_connections)
    selected_model_id = store.add(
        'op', 'Selected model id',
        floor={'op': 'field', 'path': ['model_id'], 'default': 'NO MATCH'})
    store.wire(models['selected_candidate'], selected_model_id,
               title='Selected route drives application model display')
    visible_ids = (list(grand['domains'].values()) + [grand['grand'], brain,
                   policy['session'], cde, session_catalog, models['session'],
                   connectors['session'], orchestration['session'], selfext['session'],
                   monetization['session'], users['session'], cloud['session'],
                   cloud_runtime['session'], publication['session'],
                   community['session'], resources['session'], cockpit['session']])
    canvas_session = store.add('session', 'ArchHub Operating Graph', inner=visible_ids)
    govern_existing_session(
        store, canvas_session, 'operating-graph',
        description='Visible application operating graph',
        lifecycle_policy=lifecycle_policy)
    register_session(store, session_catalog, canvas_session)
    _set_owned_param(store, grand['session'], 'privacy_tier', 'T1 INTERNAL')
    _set_owned_param(store, canvas_session, 'privacy_tier', 'T1 INTERNAL')
    cde_display = store.add('op', 'CDE display state',
                            floor={'op': 'format', 'template': '{} / {}'})
    store.wire(cde_stage, cde_display)
    store.wire(cde_tier, cde_display)
    display_values = {
        brain: store.add('value', 'Brain display state',
                         floor={'op': 'value', 'value': 'LIVE PROBE NODES'}),
        policy['session']: store.add('value', 'Governance display state',
                                     floor={'op': 'value', 'value': '4 COURT PROBES'}),
        cde: cde_display,
        models['session']: selected_model_id,
        cloud['session']: store.add('value', 'Cloud display state',
                                    floor={'op': 'value', 'value': 'EVIDENCE REQUIRED'}),
        cloud_runtime['session']: store.add(
            'op', 'Cloud runtime display state',
            floor={'op': 'format', 'template': 'LOCAL HTTP {}:{} / ONLINE {}'}),
        publication['session']: publication['gate'],
        community['session']: store.add(
            'value', 'Community display state',
            floor={'op': 'value', 'value': 'CONSENT AND EVIDENCE REQUIRED'}),
        cockpit['session']: cockpit['selected_route'],
        session_catalog: store.add(
            'value', 'Session catalog display state',
            floor={'op': 'value',
                   'value': '%d GOVERNED SESSIONS' % len(registered_session_ids(
                       store, session_catalog))}),
        connectors['session']: store.add(
            'value', 'Connector domain display state',
            floor={'op': 'value', 'value': '2 HOST NODES / EVIDENCE REQUIRED'}),
        orchestration['session']: orchestration['safety_nodes'][task_key],
        selfext['session']: selfext['court_verdict'],
        monetization['session']: monetization['account_chip_value'],
        users['session']: users['privacy_gates']['archhub-application'],
        resources['session']: resources['readiness'],
    }
    store.wire(store.nodes[cloud_runtime['session']]['params']['listener_host'],
               display_values[cloud_runtime['session']])
    store.wire(store.nodes[cloud_runtime['session']]['params']['listener_port'],
               display_values[cloud_runtime['session']])
    store.wire(store.nodes[cloud_runtime['session']]['params']['listener_online'],
               display_values[cloud_runtime['session']])
    focus = _param(store, 'focused node', visible_ids[0])
    container = _param(store, 'open container', canvas_session)
    container_title = _param(store, 'open container title',
                             store.nodes[canvas_session]['title'])
    container_stack = _param(store, 'open container stack', [canvas_session])
    mode = _param(store, 'application mode', 'workspace')
    sidebar_panel = _param(store, 'sidebar panel', 'nodes')
    search_query = _param(store, 'global search query', '')
    wire_source = _param(store, 'pending wire source', {'node_id': '', 'port_id': ''})
    selection = _param(store, 'canvas selection', [])
    canvas_pan_x = _param(store, 'canvas pan x', 0.0)
    canvas_pan_y = _param(store, 'canvas pan y', 0.0)
    canvas_zoom = _param(store, 'canvas zoom', 1.0)
    draft_kind = _param(store, 'new node kind', 'value')
    draft_title = _param(store, 'new node title', '')
    draft_value = _param(store, 'new node value', '')
    live_refresh_enabled = _param(store, 'live refresh enabled', True)
    live_refresh_seconds = _param(store, 'live refresh seconds', 15.0)
    live_refresh_error = _param(store, 'live refresh error', '')
    schema_version = _param(store, 'application schema version', APPLICATION_SCHEMA_VERSION)
    intent = _param(store, 'composer intent', '')
    brain_result = _param(store, 'Brain health result', {'status': 'NOT RUN'})
    hook_result = _param(store, 'Hook coverage result', {'status': 'NOT RUN'})
    governance_result = _param(store, 'Governance court result', {'status': 'NOT RUN'})
    stylesheet = _param(store, 'application stylesheet', STYLESHEET + WEBSITE_CSS)
    theme_params = {name: _param(store, name, value) for name, value in THEME.items()}
    state = store.add('group', 'Application state',
                      inner=[focus, container, container_title, container_stack,
                             mode, sidebar_panel, search_query, wire_source,
                             selection,
                             canvas_pan_x, canvas_pan_y, canvas_zoom,
                             draft_kind, draft_title, draft_value,
                             live_refresh_enabled, live_refresh_seconds, live_refresh_error,
                             schema_version, intent, brain_result, hook_result,
                             governance_result])
    presentation = store.add('group', 'Application presentation',
                             inner=list(theme_params.values()) + [stylesheet],
                             params=theme_params)
    app_params = {'focus': focus, 'container': container,
                  'container_title': container_title,
                  'container_stack': container_stack, 'mode': mode,
                  'sidebar_panel': sidebar_panel, 'search_query': search_query,
                  'wire_source': wire_source,
                  'selection': selection,
                  'canvas_pan_x': canvas_pan_x, 'canvas_pan_y': canvas_pan_y,
                  'canvas_zoom': canvas_zoom,
                  'draft_kind': draft_kind, 'draft_title': draft_title,
                  'draft_value': draft_value,
                  'live_refresh_enabled': live_refresh_enabled,
                  'live_refresh_seconds': live_refresh_seconds,
                  'live_refresh_error': live_refresh_error,
                  'schema_version': schema_version, 'intent': intent,
                  'brain_result': brain_result, 'hook_result': hook_result,
                  'governance_result': governance_result,
                  'stylesheet': stylesheet}
    app_params.update({
        'brain_report_source': _reference_param(
            store, 'Brain report watcher source', brain_report_source),
        'brain_report_snapshot': brain_report_result,
        'cde_stage_target': cde_stage, 'cde_scope_target': cde_scope,
        'cde_tier_target': cde_tier, 'cde_container_target': cde_container_id,
        'cde_runtime_target': cde_runtime,
        'cde_stage_source': _reference_param(
            store, 'CDE stage watcher source', cde_fields['stage']),
        'cde_scope_source': _reference_param(
            store, 'CDE scope watcher source', cde_fields['scope']),
        'cde_tier_source': _reference_param(
            store, 'CDE tier watcher source', cde_fields['tier']),
        'cde_container_source': _reference_param(
            store, 'CDE container watcher source', cde_fields['container_id']),
        'cde_runtime_source': _reference_param(
            store, 'CDE runtime watcher source', cde_fields['runtime']),
        'governance_brain_source': _reference_param(
            store, 'Brain health watcher source', policy['probes'][0]),
        'governance_hooks_source': _reference_param(
            store, 'Hook coverage watcher source', policy['probes'][1]),
        'governance_score_source': _reference_param(
            store, 'Governance score watcher source', policy['governance_score']),
        'orchestration_brain_source': _reference_param(
            store, 'Orchestration Brain watcher source', orchestration_brain_ok),
        'orchestration_brain_target': task_params['brain_connected'],
        'orchestration_hooks_source': _reference_param(
            store, 'Orchestration hooks watcher source', orchestration_hooks_ready),
        'orchestration_hooks_target': task_params['hooks_ready'],
    })
    app_params['privacy_tier'] = _param(store, 'application privacy tier', 'T1 INTERNAL')
    app_params.update({'theme:' + name: pid for name, pid in theme_params.items()})
    app = store.add('session', 'ArchHub Application', inner=[], params=app_params)
    user_app_relation = store.relation([
        {'role': 'source', 'direction': 'out',
         'node_id': users['sessions']['archhub-application'],
         'port_id': 'access_policy', 'cardinality': 'one'},
        {'role': 'target', 'direction': 'in', 'node_id': app,
         'port_id': 'identity', 'cardinality': 'one'},
    ], title='User access policy governs application')

    positions = {}
    centers = {}
    for index, node_id in enumerate(visible_ids):
        _label_param(store, node_id)
        if node_id == grand['grand']:
            x, y = 550, 326
        else:
            col, row = index % 5, index // 5
            x, y = 60 + col * 244, 92 + row * 174
            if 410 <= x <= 720 and 250 <= y <= 450:
                y += 188
        x_param = _set_owned_param(store, node_id, 'position_x', x)
        y_param = _set_owned_param(store, node_id, 'position_y', y)
        positions[node_id] = {'x': x_param, 'y': y_param}
        centers[node_id] = {
            'x': _math_offset(store, x_param, 102, 'card center x'),
            'y': _math_offset(store, y_param, 67, 'card center y'),
        }

    root = _el(store, 'div', 'Application shell', cls='archhub-app')
    connect_ui_binding(store, mode, root, 'attr.data-mode')
    sidebar = _el(store, 'aside', 'Sidebar', cls='sidebar')
    icon_rail = _el(store, 'nav', 'Application rail', cls='icon-rail')
    library = _el(store, 'section', 'Node library', cls='library-panel')
    workspace = _el(store, 'main', 'Workspace', cls='workspace')
    header = _el(store, 'header', 'Workspace header', cls='workspace-header')
    canvas = _el(store, 'section', 'Node canvas', cls='canvas',
                 attrs={'data-pan-surface': 'true'})
    stage = _el(store, 'div', 'Canvas stage', cls='canvas-stage')
    selection_box = _el(store, 'div', 'Canvas selection window',
                        cls='selection-box',
                        attrs={'aria-hidden': 'true', 'data-mode': 'window'})
    inspector = _el(store, 'aside', 'Properties inspector', cls='inspector')
    home_surface = _el(store, 'main', 'Home surface', cls='home-surface')
    cockpit_surface = _el(store, 'main', 'Cockpit surface', cls='cockpit-surface')
    brain_surface = _el(store, 'main', 'Brain surface', cls='brain-surface')
    settings_surface = _el(store, 'main', 'Settings surface', cls='settings-surface')
    create_surface = _el(store, 'main', 'Create node surface', cls='create-surface')
    status = _el(store, 'div', 'Status strip', cls='status-strip')
    _children(store, root, sidebar, workspace, home_surface, cockpit_surface,
              brain_surface, settings_surface, create_surface, status)
    cockpit_surface_relation = store.relation([
        {'role': 'source', 'direction': 'out', 'node_id': cockpit['surface'],
         'port_id': 'presentation', 'cardinality': 'one'},
        {'role': 'target', 'direction': 'in', 'node_id': cockpit_surface,
         'port_id': 'surface', 'cardinality': 'one'},
    ], title='Cockpit authority projects the Cockpit surface')
    domain_integration_relations.append(cockpit_surface_relation)
    search_panel = _el(store, 'section', 'Global search panel', cls='library-panel')
    share_panel = _el(store, 'section', 'Share panel', cls='library-panel')
    _children(store, sidebar, icon_rail, library, search_panel, share_panel)
    _children(store, workspace, header, canvas, inspector)
    _children(store, canvas, stage, selection_box)
    canvas_transform = store.add(
        'op', 'Canvas viewport transform',
        floor={'op': 'format', 'template': 'translate({}px,{}px) scale({})'})
    store.wire(canvas_pan_x, canvas_transform)
    store.wire(canvas_pan_y, canvas_transform)
    store.wire(canvas_zoom, canvas_transform)
    connect_ui_binding(store, canvas_transform, stage, 'style.transform')
    connect_ui_binding(store, canvas_pan_x, canvas, 'view.pan_x')
    connect_ui_binding(store, canvas_pan_y, canvas, 'view.pan_y')
    connect_ui_binding(store, canvas_zoom, canvas, 'view.zoom')
    connect_ui_binding(store, selection, canvas, 'view.selection')

    home = _el(store, 'button', 'Home action', text='Home', cls='rail-button rail-home',
               attrs={'type': 'button', 'title': 'Home'})
    search = _el(store, 'button', 'Search action', text='Search',
                 cls='rail-button rail-search',
                 attrs={'type': 'button', 'title': 'Search'})
    spacer = _el(store, 'div', 'Rail spacer', cls='rail-spacer')
    share = _el(store, 'button', 'Share action', text='Share',
                cls='rail-button rail-share',
                attrs={'type': 'button', 'title': 'Share and publish'})
    settings = _el(store, 'button', 'Settings action', text='Settings',
                   cls='rail-button rail-settings',
                   attrs={'type': 'button', 'title': 'Settings'})
    _children(store, icon_rail, home, search, spacer, share, settings)
    _action(store, home, [
        {'op': 'set', 'id': mode, 'path': ['body', 'floor', 'value'], 'value': 'home'},
        {'op': 'set', 'id': sidebar_panel, 'path': ['body', 'floor', 'value'],
         'value': 'nodes'},
        {'op': 'set', 'id': focus, 'path': ['body', 'floor', 'value'],
         'value': grand['session']},
    ], 'Open Home')
    _action(store, search, [
        {'op': 'set', 'id': mode, 'path': ['body', 'floor', 'value'], 'value': 'workspace'},
        {'op': 'set', 'id': sidebar_panel, 'path': ['body', 'floor', 'value'],
         'value': 'search'},
    ], 'Open search')
    _action(store, share, [
        {'op': 'set', 'id': mode, 'path': ['body', 'floor', 'value'], 'value': 'workspace'},
        {'op': 'set', 'id': sidebar_panel, 'path': ['body', 'floor', 'value'],
         'value': 'share'},
    ], 'Open share')
    _action(store, settings, [
        {'op': 'set', 'id': mode, 'path': ['body', 'floor', 'value'], 'value': 'settings'},
        {'op': 'set', 'id': focus, 'path': ['body', 'floor', 'value'], 'value': app},
    ], 'Open settings')

    def active_when(source, expected, title):
        expected_node = store.add('value', title + ' expected',
                                  floor={'op': 'value', 'value': expected})
        result = store.add('op', title, floor={'op': 'compare', 'cmp': '=='})
        store.wire(source, result)
        store.wire(expected_node, result)
        return result

    connect_ui_binding(store, active_when(mode, 'home', 'Home is active'),
                       home, 'attr.data-active')
    connect_ui_binding(store, active_when(sidebar_panel, 'search', 'Search is active'),
                       search, 'attr.data-active')
    connect_ui_binding(store, active_when(sidebar_panel, 'share', 'Share is active'),
                       share, 'attr.data-active')
    connect_ui_binding(store, active_when(mode, 'settings', 'Settings is active'),
                       settings, 'attr.data-active')

    library_title = _el(store, 'div', 'Node library heading', text='NODES', cls='panel-title')
    new_node_button = _el(store, 'button', 'New node action', text='+ New node',
                          cls='new-node-button', attrs={'type': 'button'})
    library_list = _el(store, 'div', 'Node library list', cls='library-list')
    _children(store, library, library_title, new_node_button, library_list)
    _action(store, new_node_button,
            {'op': 'set', 'id': mode, 'path': ['body', 'floor', 'value'],
             'value': 'create'}, 'Open node creator')
    library_rows = []
    for node_id in visible_ids:
        row = _el(store, 'button', 'Library row: ' + store.nodes[node_id]['title'],
                  cls='library-row',
                  attrs={'type': 'button'})
        connect_ui_binding(store, _label_param(store, node_id), row, 'text')
        _action(store, row, {'op': 'set', 'id': focus,
                             'path': ['body', 'floor', 'value'], 'value': node_id},
                'Select node')
        connect_ui_child(store, library_list, row, order=len(library_rows))
        library_rows.append(row)

    connect_ui_binding(store, active_when(sidebar_panel, 'nodes', 'Node panel visible'),
                       library, 'attr.data-visible')
    connect_ui_binding(store, active_when(sidebar_panel, 'search', 'Search panel visible'),
                       search_panel, 'attr.data-visible')
    connect_ui_binding(store, active_when(sidebar_panel, 'share', 'Share panel visible'),
                       share_panel, 'attr.data-visible')

    search_title = _el(store, 'div', 'Search panel heading', text='SEARCH', cls='panel-title')
    search_box = _el(store, 'div', 'Search input frame', cls='sidebar-search')
    search_input = _el(store, 'input', 'Global search input', cls='sidebar-search-input',
                       attrs={'type': 'text', 'placeholder': 'everything in studio...'})
    connect_ui_binding(store, search_query, search_input, 'value')
    _children(store, search_box, search_input)
    search_scope = _el(store, 'div', 'Search scope heading', text='ALL NODES',
                       cls='search-scope')
    search_results = _el(store, 'div', 'Search results', cls='library-list')
    _children(store, search_panel, search_title, search_box, search_scope, search_results)
    search_rows = {}
    searchable_ids = visible_ids + [grand['session'], canvas_session, app]
    for order, node_id in enumerate(dict.fromkeys(searchable_ids)):
        match = store.add('op', 'Search match: ' + node_id,
                          floor={'op': 'compare', 'cmp': 'icontains'})
        label_param = _label_param(store, node_id)
        store.wire(label_param, match)
        store.wire(search_query, match)
        row = _el(store, 'button', 'Search result: ' + node_id,
                  cls='library-row search-result',
                  attrs={'type': 'button'})
        connect_ui_binding(store, label_param, row, 'text')
        connect_ui_binding(store, match, row, 'attr.data-visible')
        _action(store, row, [
            {'op': 'set', 'id': focus, 'path': ['body', 'floor', 'value'],
             'value': node_id},
            {'op': 'set', 'id': sidebar_panel, 'path': ['body', 'floor', 'value'],
             'value': 'nodes'},
        ], 'Open search result')
        connect_ui_child(store, search_results, row, order=order)
        search_rows[node_id] = row

    share_title = _el(store, 'div', 'Share panel heading', text='SHARE & PUBLISH',
                      cls='panel-title')
    share_copy = _el(store, 'div', 'Share panel summary',
                     text='SESSIONS', cls='share-copy')
    share_list = _el(store, 'div', 'Share export list', cls='library-list')
    _children(store, share_panel, share_title, share_copy, share_list)
    share_rows = {}
    for order, (label, node_id) in enumerate((
            ('Export application graph', app),
            ('Export operating session', canvas_session),
            ('Export Grand Map', grand['session']))):
        row = _el(store, 'button', 'Share: ' + label, text=label,
                  cls='share-row', attrs={'type': 'button'})
        connect_ui_download(store, node_id, row)
        connect_ui_child(store, share_list, row, order=order)
        share_rows[node_id] = row

    create_header = _el(store, 'header', 'Create node header', cls='settings-header')
    create_back = _el(store, 'button', 'Cancel node creation', cls='settings-back',
                      attrs={'type': 'button', 'title': 'Back to workspace'})
    create_title = _el(store, 'h1', 'Create node title', text='New node',
                       cls='settings-title')
    _children(store, create_header, create_back, create_title)
    _action(store, create_back,
            {'op': 'set', 'id': mode, 'path': ['body', 'floor', 'value'],
             'value': 'workspace'}, 'Cancel node creation')
    create_form = _el(store, 'section', 'Create node form', cls='create-form')
    kind_heading = _el(store, 'div', 'Node role heading', text='ROLE',
                       cls='settings-heading')
    kind_picker = _el(store, 'div', 'Node role picker', cls='create-kinds')
    kind_buttons = {}
    for order, (kind_value, label_text) in enumerate((
            ('value', 'Data'), ('op', 'Behavior'), ('group', 'Group'),
            ('param', 'Parameter'), ('session', 'Session'), ('ui', 'Interface'),
            ('proposal', 'Proposal'))):
        button = _el(store, 'button', 'Create kind: ' + kind_value,
                     text=label_text, cls='create-kind', attrs={'type': 'button'})
        _action(store, button,
                {'op': 'set', 'id': draft_kind,
                 'path': ['body', 'floor', 'value'], 'value': kind_value},
                'Choose node role')
        connect_ui_binding(store, active_when(draft_kind, kind_value,
                                              kind_value + ' draft selected'),
                           button, 'attr.data-active')
        connect_ui_child(store, kind_picker, button, order=order)
        kind_buttons[kind_value] = button
    title_field = _el(store, 'label', 'New node title field', cls='create-field')
    title_label = _el(store, 'span', 'New node title label', text='Name',
                      cls='property-label')
    title_input = _el(store, 'input', 'New node title input', cls='create-input',
                      attrs={'type': 'text'})
    connect_ui_binding(store, draft_title, title_input, 'value')
    _children(store, title_field, title_label, title_input)
    value_field = _el(store, 'label', 'New node value field', cls='create-field')
    value_label = _el(store, 'span', 'New node value label', text='Initial value',
                      cls='property-label')
    value_input = _el(store, 'input', 'New node value input', cls='create-input',
                      attrs={'type': 'text'})
    connect_ui_binding(store, draft_value, value_input, 'value')
    _children(store, value_field, value_label, value_input)
    create_actions = _el(store, 'div', 'Create node actions', cls='create-actions')
    create_cancel = _el(store, 'button', 'Cancel create node', text='Cancel',
                        cls='header-action', attrs={'type': 'button'})
    create_submit = _el(store, 'button', 'Create node command', text='Create',
                        cls='header-action header-primary', attrs={'type': 'button'})
    _action(store, create_cancel,
            {'op': 'set', 'id': mode, 'path': ['body', 'floor', 'value'],
             'value': 'workspace'}, 'Cancel create node')
    _action(store, create_submit, {
        'op': 'command', 'capability': 'node.create',
        'args': {'kind_param': draft_kind, 'title_param': draft_title,
                 'value_param': draft_value}}, 'Create universal node')
    _children(store, create_actions, create_cancel, create_submit)
    _children(store, create_form, kind_heading, kind_picker, title_field,
              value_field, create_actions)
    _children(store, create_surface, create_header, create_form)

    wordmark = _el(store, 'button', 'ArchHub wordmark', cls='wordmark',
                   attrs={'type': 'button', 'aria-label': 'ArchHub'})
    word_arch = _el(store, 'span', 'Wordmark Arch', text='Arch')
    word_hub = _el(store, 'strong', 'Wordmark Hub', text='Hub')
    _children(store, wordmark, word_arch, word_hub)
    _action(store, wordmark, [
        {'op': 'set', 'id': mode, 'path': ['body', 'floor', 'value'], 'value': 'home'},
        {'op': 'set', 'id': focus, 'path': ['body', 'floor', 'value'],
         'value': grand['session']},
    ], 'Open home')
    tab = _el(store, 'button', 'Current container tab', cls='session-tab',
              attrs={'type': 'button'})
    connect_ui_binding(store, container_title, tab, 'text')
    back = _el(store, 'button', 'Back one container', cls='header-action container-back',
               attrs={'type': 'button', 'title': 'Back', 'aria-label': 'Back'})
    _action(store, back, {
        'op': 'command', 'capability': 'container.back', 'args': {}},
        'Back one container')
    header_spacer = _el(store, 'div', 'Header spacer', cls='header-spacer')
    model = _el(store, 'span', 'Model route', cls='model-chip')
    connect_ui_binding(store, selected_model_id, model, 'text')
    undo = _el(store, 'button', 'Undo graph transaction', cls='header-action history-undo',
               attrs={'type': 'button', 'title': 'Undo', 'aria-label': 'Undo'})
    redo = _el(store, 'button', 'Redo graph transaction', cls='header-action history-redo',
               attrs={'type': 'button', 'title': 'Redo', 'aria-label': 'Redo'})
    _action(store, undo, {'op': 'command', 'capability': 'history.undo', 'args': {}},
            'Undo graph transaction')
    _action(store, redo, {'op': 'command', 'capability': 'history.redo', 'args': {}},
            'Redo graph transaction')
    save_skill = _el(store, 'button', 'Save session as skill', text='Save as skill',
                     cls='header-action', attrs={'type': 'button'})
    connect_ui_download(store, canvas_session, save_skill)
    save = _el(store, 'button', 'Save application', text='Save',
               cls='header-action header-primary', attrs={'type': 'button'})
    _action(store, save, {'op': 'command', 'capability': 'application.checkpoint',
                          'args': {}}, 'Save application checkpoint')
    _children(store, header, wordmark, back, tab, header_spacer, model, undo, redo,
              save_skill, save)
    _action(store, tab, [
        {'op': 'set', 'id': mode,
         'path': ['body', 'floor', 'value'], 'value': 'workspace'},
        {'op': 'command', 'capability': 'container.root', 'args': {}},
    ], 'Open Grand Map workspace')

    home_masthead = _el(store, 'header', 'Home masthead', cls='home-masthead')
    home_brand = _el(store, 'div', 'Home brand', cls='home-brand')
    home_brand_arch = _el(store, 'span', 'Home brand Arch', text='Arch')
    home_brand_hub = _el(store, 'strong', 'Home brand Hub', text='Hub')
    home_subtitle = _el(store, 'div', 'Home subtitle', text='NODE-NATIVE OPERATING SYSTEM',
                        cls='home-subtitle')
    _children(store, home_brand, home_brand_arch, home_brand_hub)
    _children(store, home_masthead, home_brand, home_subtitle)
    home_section_title = _el(store, 'h1', 'Home sessions heading', text='Sessions',
                             cls='home-section-title')
    home_grid = _el(store, 'section', 'Home session grid', cls='home-session-grid')
    home_composer = _el(store, 'div', 'Home composer', cls='home-composer')
    home_composer_input = _el(
        store, 'input', 'Home composer input',
        attrs={'type': 'text', 'placeholder': 'Ask ArchHub or describe an intent'})
    connect_ui_binding(store, intent, home_composer_input, 'value')
    _children(store, home_composer, home_composer_input)
    _children(store, home_surface, home_masthead, home_section_title, home_grid, home_composer)

    home_cards = {}
    home_session_ids = registered_session_ids(store, session_catalog)
    for order, focus_target in enumerate(home_session_ids):
        title_source = _label_param(store, focus_target)
        lifecycle_source = store.nodes[focus_target]['params']['lifecycle']
        meta_source = store.add('op', 'Home session metadata',
                                floor={'op': 'format', 'template': '{} / NODE GRAPH'})
        store.wire(lifecycle_source, meta_source)
        session_card = _el(store, 'button', 'Home session card',
                           cls='home-session-card', attrs={'type': 'button'})
        session_kicker = _el(store, 'div', 'Home session kind', text='SESSION',
                             cls='home-session-kicker')
        session_title = _el(store, 'div', 'Home session title',
                            cls='home-session-title')
        connect_ui_binding(store, title_source, session_title, 'text')
        session_meta = _el(store, 'div', 'Home session metadata',
                           cls='home-session-meta')
        connect_ui_binding(store, meta_source, session_meta, 'text')
        _children(store, session_card, session_kicker, session_title, session_meta)
        connect_ui_child(store, home_grid, session_card, order=order)
        _action(store, session_card, [
            {'op': 'set', 'id': mode, 'path': ['body', 'floor', 'value'],
             'value': 'workspace'},
            {'op': 'set', 'id': container, 'path': ['body', 'floor', 'value'],
             'value': canvas_session},
            {'op': 'set', 'id': focus, 'path': ['body', 'floor', 'value'],
             'value': focus_target},
        ], 'Open session')
        home_cards[focus_target] = session_card

    cockpit_header = _el(store, 'header', 'Cockpit header', cls='cockpit-header')
    cockpit_title = _el(store, 'h1', 'Cockpit title', text='Cockpit', cls='cockpit-title')
    cockpit_subtitle = _el(store, 'div', 'Cockpit subtitle',
                           text='LIVE OPERATING GRAPH / EXPLICIT COURT SAMPLES',
                           cls='cockpit-subtitle')
    cockpit_spacer = _el(store, 'div', 'Cockpit spacer', cls='cockpit-spacer')
    cockpit_run = _el(store, 'button', 'Run live court', text='Run live court',
                      cls='cockpit-run', attrs={'type': 'button'})
    _children(store, cockpit_header, cockpit_title, cockpit_subtitle,
              cockpit_spacer, cockpit_run)
    _action(store, cockpit_run, [
        {'op': 'sample', 'source': policy['probes'][0], 'target': brain_result},
        {'op': 'sample', 'source': policy['probes'][1], 'target': hook_result},
        {'op': 'sample', 'source': policy['governance_score'],
         'target': governance_result},
    ], 'Sample live governance court')
    cockpit_command_bar = _el(store, 'section', 'Cockpit command bar',
                              cls='cockpit-command')
    cockpit_command_input = _el(
        store, 'input', 'Cockpit ephemeral command input',
        cls='cockpit-command-input',
        attrs={'type': 'text', 'autocomplete': 'off',
               'placeholder': 'Direct the operating graph',
               'aria-label': 'Cockpit command'})
    cockpit_command_route = _el(store, 'span', 'Cockpit selected route',
                                cls='cockpit-command-route')
    connect_ui_binding(store, cockpit['selected_route'], cockpit_command_route, 'text')
    cockpit_command_submit = _el(
        store, 'button', 'Submit Cockpit command', text='Run command',
        cls='cockpit-run',
        attrs={'type': 'button', 'data-input-node': cockpit_command_input})
    _action(store, cockpit_command_submit,
            {'op': 'command', 'capability': 'cockpit.command.submit', 'args': {}},
            'Submit command through Cockpit policy')
    cockpit_command_relation = store.relation([
        {'role': 'source', 'direction': 'out', 'node_id': cockpit_command_input,
         'port_id': 'ephemeral_value', 'cardinality': 'one'},
        {'role': 'target', 'direction': 'in', 'node_id': cockpit_command_submit,
         'port_id': 'command_value', 'cardinality': 'one'},
    ], title='Ephemeral Cockpit input reaches governed submission')
    domain_integration_relations.append(cockpit_command_relation)
    _children(store, cockpit_command_bar, cockpit_command_input,
              cockpit_command_route, cockpit_command_submit)
    cockpit_grid = _el(store, 'section', 'Cockpit metrics', cls='cockpit-grid')

    def cockpit_metric(title_text, source_id, value_format=''):
        card = _el(store, 'section', 'Cockpit metric: ' + title_text, cls='cockpit-card')
        label = _el(store, 'div', 'Cockpit metric label', text=title_text,
                    cls='cockpit-label')
        value = _el(store, 'div', 'Cockpit metric value', cls='cockpit-value')
        connect_ui_binding(store, source_id, value, 'text', value_format=value_format)
        _children(store, card, label, value)
        return card

    metric_cards = [
        cockpit_metric('Brain health', brain_result),
        cockpit_metric('Hook coverage', hook_result),
        cockpit_metric('Governance court', governance_result),
        cockpit_metric('Active CDE scope', cde_scope),
        cockpit_metric('Grand Map progress', grand['grand'], 'percent'),
        cockpit_metric('Founder gate', cockpit['founder_verdict']),
        cockpit_metric('Command route', cockpit['selected_route']),
        cockpit_metric('Secret withheld', cockpit['redacted']),
    ]
    _children(store, cockpit_grid, *metric_cards)
    domain_section = _el(store, 'section', 'Cockpit domain section', cls='cockpit-domain-section')
    domain_title = _el(store, 'h2', 'Cockpit domain title', text='Domains',
                       cls='home-section-title')
    domain_grid = _el(store, 'div', 'Cockpit domain grid', cls='cockpit-domain-grid')
    _children(store, domain_section, domain_title, domain_grid)
    for order, (key, domain_id) in enumerate(grand['domains'].items()):
        row = _el(store, 'div', 'Cockpit domain: ' + key, cls='cockpit-domain-row')
        name = _el(store, 'span', 'Cockpit domain name', text=key,
                   cls='cockpit-domain-name')
        value = _el(store, 'span', 'Cockpit domain value', cls='cockpit-domain-value')
        connect_ui_binding(store, domain_id, value, 'text', value_format='percent')
        _children(store, row, name, value)
        connect_ui_child(store, domain_grid, row, order=order)
    _children(store, cockpit_surface, cockpit_header, cockpit_command_bar,
              cockpit_grid, domain_section)

    brain_header = _el(store, 'header', 'Brain header', cls='brain-header')
    brain_title = _el(store, 'h1', 'Brain title', text='Brain', cls='brain-title')
    brain_subtitle = _el(store, 'div', 'Brain subtitle',
                         text='LIVE COMPLIANCE / WORK / CDE / HISTORY',
                         cls='cockpit-subtitle')
    brain_sync = _el(store, 'button', 'Synchronize Brain', text='Sync live report',
                     cls='brain-sync', attrs={'type': 'button'})
    brain_map_sync = _el(store, 'button', 'Synchronize Grand Map work',
                         text='Sync Grand Map', cls='brain-sync',
                         attrs={'type': 'button'})
    brain_claim = _el(store, 'button', 'Claim governed work',
                      text='Claim work', cls='brain-sync', attrs={'type': 'button'})
    _children(store, brain_header, brain_title, brain_subtitle, brain_sync,
              brain_map_sync, brain_claim)
    _action(store, brain_sync,
            {'op': 'sample', 'source': brain_report_source,
             'target': brain_report_result},
            'Synchronize Brain compliance report')
    _action(store, brain_map_sync, [
        {'op': 'unfreeze', 'id': brain_work_sync},
        {'op': 'sample', 'source': brain_work_sync, 'target': brain_work_sync_result},
        {'op': 'freeze', 'id': brain_work_sync},
        {'op': 'sample', 'source': brain_report_source, 'target': brain_report_result},
    ], 'Synchronize Grand Map work through Brain')
    _action(store, brain_claim, [
        {'op': 'unfreeze', 'id': brain_work_claim},
        {'op': 'sample', 'source': brain_work_claim, 'target': brain_work_claim_result},
        {'op': 'freeze', 'id': brain_work_claim},
        {'op': 'sample', 'source': brain_report_source, 'target': brain_report_result},
        {'op': 'sample', 'source': cde_fields['stage'], 'target': cde_stage},
        {'op': 'sample', 'source': cde_fields['scope'], 'target': cde_scope},
        {'op': 'sample', 'source': cde_fields['tier'], 'target': cde_tier},
        {'op': 'sample', 'source': cde_fields['container_id'],
         'target': cde_container_id},
        {'op': 'sample', 'source': cde_fields['runtime'], 'target': cde_runtime},
    ], 'Claim governed work and assign CDE')
    brain_grid = _el(store, 'section', 'Brain report grid', cls='brain-grid')

    def brain_panel(title_text, source_id, wide=False):
        panel = _el(store, 'section', 'Brain panel: ' + title_text,
                    cls='brain-panel' + (' brain-panel-wide' if wide else ''))
        label = _el(store, 'div', 'Brain panel label', text=title_text, cls='brain-label')
        value = _el(store, 'div', 'Brain panel value', cls='brain-value')
        connect_ui_binding(store, source_id, value, 'text')
        _children(store, panel, label, value)
        return panel

    brain_panels = [
        brain_panel('Active CDE', brain_fields['active_cde']),
        brain_panel('Assigned work', brain_fields['work']),
        brain_panel('Hook coverage', brain_fields['hook_coverage']),
        brain_panel('Compliance history', brain_fields['history']),
        brain_panel('Run reports', brain_fields['run_reports'], wide=True),
        brain_panel('Last gate decision', brain_fields['last_gate_decision'], wide=True),
        brain_panel('Grand Map sync', brain_work_sync_result, wide=True),
        brain_panel('Claimed work', brain_work_claim_result, wide=True),
        brain_panel('Live refresh error', live_refresh_error, wide=True),
        brain_panel('Full compliance snapshot', brain_report_result, wide=True),
    ]
    _children(store, brain_grid, *brain_panels)
    _children(store, brain_surface, brain_header, brain_grid)

    settings_header = _el(store, 'header', 'Settings header', cls='settings-header')
    settings_back = _el(store, 'button', 'Close settings', cls='settings-back',
                        attrs={'type': 'button', 'title': 'Back to workspace',
                               'aria-label': 'Back to workspace'})
    settings_title = _el(store, 'h1', 'Settings title', text='Settings',
                         cls='settings-title')
    _children(store, settings_header, settings_back, settings_title)
    _action(store, settings_back,
            {'op': 'set', 'id': mode, 'path': ['body', 'floor', 'value'],
             'value': 'workspace'}, 'Close settings')
    settings_grid = _el(store, 'section', 'Settings grid', cls='settings-grid')
    settings_nav = _el(store, 'nav', 'Settings navigation', cls='settings-nav')
    settings_nav_heading = _el(store, 'div', 'Operations heading', text='OPERATIONS',
                               cls='settings-heading')
    settings_cockpit = _el(store, 'button', 'Cockpit action', text='Cockpit',
                           cls='library-row', attrs={'type': 'button'})
    settings_brain = _el(store, 'button', 'Brain action', text='Brain',
                         cls='library-row', attrs={'type': 'button'})
    settings_graph = _el(store, 'button', 'Settings open graph', text='Grand Map',
                         cls='library-row', attrs={'type': 'button'})
    _children(store, settings_nav, settings_nav_heading, settings_graph,
              settings_cockpit, settings_brain)
    _action(store, settings_graph,
            {'op': 'set', 'id': mode, 'path': ['body', 'floor', 'value'],
             'value': 'workspace'}, 'Open Grand Map from settings')
    _action(store, settings_cockpit,
            {'op': 'set', 'id': mode, 'path': ['body', 'floor', 'value'],
             'value': 'cockpit'}, 'Open Cockpit from settings')
    _action(store, settings_brain,
            {'op': 'set', 'id': mode, 'path': ['body', 'floor', 'value'],
             'value': 'brain'}, 'Open Brain from settings')
    settings_content = _el(store, 'section', 'Settings properties')
    appearance = _el(store, 'section', 'Appearance settings', cls='settings-section')
    appearance_heading = _el(store, 'div', 'Appearance heading', text='APPEARANCE',
                             cls='settings-heading')
    connect_ui_child(store, appearance, appearance_heading, order=0)
    settings_inputs = {}
    for order, (name, pid) in enumerate(theme_params.items(), start=1):
        row = _el(store, 'label', 'Theme setting: ' + name, cls='settings-row')
        label = _el(store, 'span', 'Theme label: ' + name,
                    text=name.replace('_', ' '), cls='settings-label')
        field = _el(store, 'input', 'Theme input: ' + name, cls='settings-color',
                    attrs={'type': 'color'})
        connect_ui_binding(store, pid, field, 'value')
        _children(store, row, label, field)
        connect_ui_child(store, appearance, row, order=order)
        settings_inputs[name] = field
    _children(store, settings_content, appearance)
    _children(store, settings_grid, settings_nav, settings_content)
    _children(store, settings_surface, settings_header, settings_grid)

    heading = _el(store, 'div', 'Canvas heading', cls='canvas-heading')
    connect_ui_binding(store, container_title, heading, 'text')
    wire_layer = _el(store, 'svg', 'Wire projection layer', cls='wire-layer',
                     attrs={'viewBox': '0 0 1320 760', 'aria-hidden': 'true'})
    wire_defs = _el(store, 'defs', 'Wire projection definitions')
    wire_marker = _el(store, 'marker', 'Wire direction marker', attrs={
        'id': 'archhub-wire-arrow', 'viewBox': '0 0 8 8',
        'refX': '7', 'refY': '4', 'markerWidth': '5', 'markerHeight': '5',
        'orient': 'auto', 'markerUnits': 'strokeWidth',
    })
    wire_arrow = _el(store, 'path', 'Wire direction arrow', cls='wire-arrow',
                     attrs={'d': 'M 0 0 L 8 4 L 0 8 z'})
    _children(store, wire_marker, wire_arrow)
    _children(store, wire_defs, wire_marker)
    connect_ui_child(store, wire_layer, wire_defs, order=-1)
    connect_ui_child(store, stage, wire_layer, order=0)
    connect_ui_child(store, stage, heading, order=1)

    level = level_view(store, canvas_session, pull_values=False)
    # level_view intentionally pulls live values. The remaining work is graph
    # construction, so discard its disposable memo before thousands of edits.
    store._memo.clear()
    wire_ui = []
    wire_authorities = []
    for index, projection in enumerate(level['wires']):
        authority = projection.get('relation') or projection['id']
        projected = _relation_projection(
            store, authority, wire_layer, focus, order=index,
            container_param=container, container_id=canvas_session)
        if projected:
            wire_ui.append(projected['ui'])
            wire_authorities.append(authority)

    cards = {}
    ports = {}
    selection_buttons = {}
    for index, node_id in enumerate(visible_ids):
        node = store.nodes[node_id]
        card = _el(store, 'div', 'Canvas node: ' + node['title'], cls='graph-node',
                   attrs={'data-graph-node': node_id,
                          'data-node-kind': node['kind'],
                          'data-container-id': canvas_session,
                          'data-draggable': 'true'})
        _bind_container_visibility(store, card, container, canvas_session)
        focused_id = store.add('value', 'Focused node candidate: ' + node_id,
                               floor={'op': 'value', 'value': node_id})
        focused = store.add('op', 'Node is focused: ' + node_id,
                            floor={'op': 'compare', 'cmp': '=='})
        store.wire(focus, focused)
        store.wire(focused_id, focused)
        connect_ui_binding(store, focused, card, 'attr.data-focused')
        accent = _el(store, 'div', 'Node accent', cls='node-accent')
        kind = _el(store, 'div', 'Node kind', text=node['kind'], cls='node-head')
        title = _el(store, 'div', 'Node title', cls='node-title')
        connect_ui_binding(store, _label_param(store, node_id), title, 'text')
        value = _el(store, 'div', 'Node live value', cls='node-value')
        select = _el(store, 'button', 'Select for grouping: ' + node_id,
                     cls='node-select', attrs={'type': 'button',
                                               'title': 'Toggle multi-selection'})
        _action(store, select, {'op': 'command', 'capability': 'selection.toggle',
                                'args': {'selection_param': selection,
                                         'node_id': node_id}},
                'Toggle node selection')
        selected_id = store.add('value', 'Selection candidate: ' + node_id,
                                floor={'op': 'value', 'value': node_id})
        selected = store.add('op', 'Node is in selection: ' + node_id,
                             floor={'op': 'compare', 'cmp': 'contains'})
        store.wire(selection, selected)
        store.wire(selected_id, selected)
        connect_ui_binding(store, selected, select, 'attr.data-active')
        connect_ui_binding(store, selected, card, 'attr.data-selected')
        port_row = _el(store, 'div', 'Node ports', cls='node-ports')
        input_port = _el(store, 'button', 'Input port: ' + node_id, text='value',
                         cls='node-port node-port-in',
                         attrs={'type': 'button', 'title': 'Connect to value input'})
        output_port = _el(store, 'button', 'Output port: ' + node_id, text='value',
                          cls='node-port node-port-out',
                          attrs={'type': 'button', 'title': 'Start value connection'})
        _children(store, port_row, input_port, output_port)
        source_value = {'node_id': node_id, 'port_id': 'value'}
        _action(store, output_port,
                {'op': 'set', 'id': wire_source,
                 'path': ['body', 'floor', 'value'], 'value': source_value},
                'Start relation')
        expected_source = store.add('value', 'Expected wire source: ' + node_id,
                                    floor={'op': 'value', 'value': source_value})
        pending = store.add('op', 'Wire source is pending: ' + node_id,
                            floor={'op': 'compare', 'cmp': '=='})
        store.wire(wire_source, pending)
        store.wire(expected_source, pending)
        connect_ui_binding(store, pending, output_port, 'attr.data-pending')
        _action(store, input_port, {
            'op': 'command', 'capability': 'relation.create',
            'args': {'source_param': wire_source, 'target_node': node_id,
                     'target_port': 'value'}}, 'Complete relation')
        value_source = display_values.get(node_id, node_id)
        connect_ui_binding(store, value_source, value, 'text',
                           value_format='' if node_id in display_values else 'percent')
        connect_ui_binding(store, positions[node_id]['x'], card, 'style.left', suffix='px')
        connect_ui_binding(store, positions[node_id]['y'], card, 'style.top', suffix='px')
        _children(store, card, select, accent, kind, title, value, port_row)
        connect_ui_child(store, stage, card, order=10 + index)
        _action(store, card, {'op': 'set', 'id': focus,
                              'path': ['body', 'floor', 'value'], 'value': node_id},
                'Select canvas node')
        if 'inner' in node['body']:
            _action(store, card, {
                'op': 'command', 'capability': 'container.open',
                'args': {'container_id': node_id}},
                'Open node container', event='double_activate')
        cards[node_id] = card
        ports[node_id] = {'input': input_port, 'output': output_port}
        selection_buttons[node_id] = select

    toolbar = _el(store, 'div', 'Canvas toolbar', cls='canvas-toolbar')
    zoom_out = _el(store, 'button', 'Zoom out', text='-', cls='header-action',
                   attrs={'type': 'button', 'title': 'Zoom out'})
    zoom_value = _el(store, 'span', 'Canvas zoom value')
    zoom_hundred = store.add('value', 'Zoom percent multiplier',
                             floor={'op': 'value', 'value': 100})
    zoom_percent = store.add('op', 'Canvas zoom percent',
                             floor={'op': 'math', 'fn': '*'})
    store.wire(canvas_zoom, zoom_percent)
    store.wire(zoom_hundred, zoom_percent)
    connect_ui_binding(store, zoom_percent, zoom_value, 'text', value_format='percent')
    zoom_in = _el(store, 'button', 'Zoom in', text='+', cls='header-action',
                  attrs={'type': 'button', 'title': 'Zoom in'})
    fit = _el(store, 'button', 'Fit canvas', text='Fit', cls='header-action',
              attrs={'type': 'button', 'title': 'Fit canvas'})
    selection_value = _el(store, 'span', 'Canvas selection value',
                          cls='canvas-selection-value')
    selection_count = store.add('op', 'Canvas selection count',
                                floor={'op': 'reduce', 'mode': 'count'})
    selection_label = store.add('op', 'Canvas selection label',
                                floor={'op': 'format',
                                       'template': '{} selected'})
    store.wire(selection, selection_count)
    store.wire(selection_count, selection_label)
    connect_ui_binding(store, selection_label, selection_value, 'text')
    group_selection = _el(store, 'button', 'Group selection', text='Group',
                          cls='header-action', attrs={'type': 'button',
                                                     'title': 'Group selected nodes'})
    _children(store, toolbar, zoom_out, zoom_value, zoom_in, fit,
              selection_value, group_selection)
    _action(store, zoom_out, {'op': 'command', 'capability': 'canvas.zoom',
                              'args': {'zoom_param': canvas_zoom, 'delta': -0.1}},
            'Zoom canvas out')
    _action(store, zoom_in, {'op': 'command', 'capability': 'canvas.zoom',
                             'args': {'zoom_param': canvas_zoom, 'delta': 0.1}},
            'Zoom canvas in')
    _action(store, fit, {'op': 'command', 'capability': 'canvas.fit',
                         'args': {'zoom_param': canvas_zoom,
                                  'pan_x_param': canvas_pan_x,
                                  'pan_y_param': canvas_pan_y}}, 'Fit canvas')
    _action(store, group_selection, {
        'op': 'command', 'capability': 'selection.group',
        'args': {'selection_param': selection}}, 'Group selected nodes')
    composer = _el(store, 'div', 'Canvas composer', cls='composer')
    composer_input = _el(store, 'input', 'Composer input', cls='composer-input',
                         attrs={'type': 'text', 'placeholder': 'Ask ArchHub or describe an intent'})
    connect_ui_binding(store, intent, composer_input, 'value')
    _children(store, composer, composer_input)
    connect_ui_child(store, canvas, toolbar, order=100)
    connect_ui_child(store, canvas, composer, order=101)

    inspector_nodes = visible_ids + [grand['session'], canvas_session, app] \
        + list(dict.fromkeys(wire_authorities))
    inspector_panels = {}
    property_inputs = {}
    for panel_index, node_id in enumerate(inspector_nodes):
        panel, input_ids = _inspector_panel(
            store, inspector, focus, node_id, panel_index)
        inspector_panels[node_id] = panel
        property_inputs[node_id] = input_ids

    status_left = _el(store, 'span', 'Runtime status', text='NODE RUNTIME', cls='status-live')
    status_table = _el(store, 'span', 'Table status', text='ONE TABLE')
    status_relation = _el(store, 'span', 'Relation status', text='RELATIONS AUTHORITATIVE')
    status_count = _el(store, 'span', 'Graph status', text='LIVE GRAPH')
    status_message = _el(
        store,
        'span',
        'Interaction status message',
        cls='status-message',
        attrs={'hidden': 'hidden', 'role': 'status', 'aria-live': 'polite'},
    )
    _children(store, status, status_left, status_table, status_relation, status_count,
              status_message)

    website = build_website(store, grand=grand, mode_param=mode,
                            focus_param=focus, app_id=app)
    website_resource_relation = connect_resource(
        store, resources, 'website-publication', website['session'],
        target_port='published_site')
    domain_integration_relations.append(website_resource_relation)
    publication_website_relation = store.relation([
        {'role': 'source', 'direction': 'out',
         'node_id': publication['record'],
         'port_id': 'deployment_evidence', 'cardinality': 'one'},
        {'role': 'target', 'direction': 'in',
         'node_id': website['session'],
         'port_id': 'publication', 'cardinality': 'one'},
    ], title='Deployment evidence proves website publication')
    domain_integration_relations.append(publication_website_relation)
    website_signin_relation = store.relation([
        {'role': 'source', 'direction': 'out',
         'node_id': website['route_pages']['/website/signin']['page'],
         'port_id': 'signin_gateway', 'cardinality': 'one'},
        {'role': 'target', 'direction': 'in', 'node_id': users['session'],
         'port_id': 'identity', 'cardinality': 'one'},
    ], title='Website sign-in gateway enters users domain')
    monetization_surface_relations = [
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': monetization['billing'],
             'port_id': 'checkout', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in',
             'node_id': website['route_pages']['/website/pricing']['page'],
             'port_id': 'billing', 'cardinality': 'one'},
        ], title='Billing plan reaches website pricing'),
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': monetization['revenue'],
             'port_id': 'commercial_metrics', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in', 'node_id': cockpit_surface,
             'port_id': 'metrics', 'cardinality': 'one'},
        ], title='Revenue ledger reaches Founder Cockpit'),
    ]
    domain_integration_relations.append(store.relation([
        {'role': 'source', 'direction': 'out',
         'node_id': selfext['session'],
         'port_id': 'release_evidence', 'cardinality': 'one'},
        {'role': 'target', 'direction': 'in',
         'node_id': website['route_pages']['/website/changelog']['page'],
         'port_id': 'changelog', 'cardinality': 'one'},
    ], title='Self-extension release evidence feeds website changelog'))
    domain_integration_relations.extend([
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': website['session'],
             'port_id': 'public_routes', 'cardinality': 'many'},
            {'role': 'target', 'direction': 'in',
             'node_id': cloud['services']['cloud_fly_app']['service'],
             'port_id': 'website', 'cardinality': 'one'},
        ], title='Website routes reach the cloud application host'),
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': website['route_pages']['/website/signin']['page'],
             'port_id': 'signin', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in',
             'node_id': cloud['services']['cloud_auth']['service'],
             'port_id': 'signin', 'cardinality': 'one'},
        ], title='Website sign-in reaches cloud authentication'),
        store.relation([
            {'role': 'source', 'direction': 'out',
             'node_id': website['route_pages']['/website/community']['page'],
             'port_id': 'community_route', 'cardinality': 'one'},
            {'role': 'target', 'direction': 'in',
             'node_id': community['community'],
             'port_id': 'public_surface', 'cardinality': 'one'},
        ], title='Website Community route reaches Community authority'),
    ])
    website_preview = _el(store, 'button', 'Share: Preview website',
                          text='Preview website', cls='share-row',
                          attrs={'type': 'button', 'data-navigate': '/website'})
    _action(store, website_preview,
            {'op': 'set', 'id': focus, 'path': ['body', 'floor', 'value'],
             'value': website['session']}, 'Preview website')
    connect_ui_child(store, share_list, website_preview, order=3)
    website_export = _el(store, 'button', 'Share: Export website graph',
                         text='Export website graph', cls='share-row',
                         attrs={'type': 'button'})
    connect_ui_download(store, website['session'], website_export)
    connect_ui_child(store, share_list, website_export, order=4)
    share_rows[website['session']] = website_export
    ui_root_param = store.add('param', 'UI root', floor={'op': 'reference', 'target': root})
    app_params = dict(store.nodes[app]['params'])
    app_params['ui_root'] = ui_root_param
    app_params['website_root'] = store.nodes[website['session']]['params']['ui_root']
    store.edit(app, ['params'], app_params)
    store.edit(app, ['body', 'inner'], [grand['session'], canvas_session, brain,
                                       policy['session'], cde, session_catalog,
                                       lifecycle_policy, models['session'], website['session'],
                                       connectors['session'], orchestration['session'],
                                       selfext['session'], monetization['session'],
                                       users['session'], cloud['session'],
                                       cloud_runtime['session'], publication['session'],
                                       community['session'], resources['session'],
                                       cockpit['session'],
                                       user_app_relation, website_signin_relation] +
                                      integration_relations + resource_authority_relations +
                                      domain_integration_relations +
                                      monetization_surface_relations + [
                                       state, presentation, root])

    return store, {
        'app': app, 'ui_root': root, 'focus': focus, 'container': container,
        'container_title': container_title, 'container_stack': container_stack,
        'container_back': back,
        'mode': mode, 'sidebar_panel': sidebar_panel, 'search_query': search_query,
        'canvas_view': {'pan_x': canvas_pan_x, 'pan_y': canvas_pan_y,
                        'zoom': canvas_zoom},
        'intent': intent, 'grand': grand, 'state': state, 'presentation': presentation,
        'brain': brain, 'governance': policy, 'cde': cde,
        'models': models, 'selected_model_id': selected_model_id,
        'connectors': connectors, 'orchestration': orchestration,
        'selfext': selfext,
        'monetization': monetization,
        'cloud': cloud,
        'cloud_runtime': cloud_runtime,
        'publication': publication,
        'community': community,
        'resources': resources,
        'resource_authority_relations': resource_authority_relations,
        'cockpit_domain': cockpit,
        'users': users, 'user_app_relation': user_app_relation,
        'website_signin_relation': website_signin_relation,
        'monetization_surface_relations': monetization_surface_relations,
        'session_catalog': session_catalog, 'lifecycle_policy': lifecycle_policy,
        'canvas_session': canvas_session, 'integration_relations': integration_relations,
        'domain_integration_relations': domain_integration_relations,
        'positions': positions, 'cards': cards, 'ports': ports,
        'selection_box': selection_box,
        'selection_buttons': selection_buttons,
        'selection_count': selection_count, 'selection_label': selection_label,
        'group_selection': group_selection, 'wire_ui': wire_ui,
        'wire_authorities': wire_authorities,
        'inspector': inspector, 'inspector_panels': inspector_panels,
        'property_inputs': property_inputs, 'composer_input': composer_input,
        'home': home_surface, 'home_cards': home_cards,
        'home_composer_input': home_composer_input,
        'search_panel': search_panel, 'search_input': search_input,
        'search_rows': search_rows, 'share_panel': share_panel,
        'share_rows': share_rows,
        'create_surface': create_surface, 'new_node_button': new_node_button,
        'create_submit': create_submit, 'draft_kind': draft_kind,
        'draft_title': draft_title, 'draft_value': draft_value,
        'kind_buttons': kind_buttons,
        'cockpit': cockpit_surface, 'cockpit_run': cockpit_run,
        'cockpit_command_bar': cockpit_command_bar,
        'cockpit_command_input': cockpit_command_input,
        'cockpit_command_submit': cockpit_command_submit,
        'cockpit_command_relation': cockpit_command_relation,
        'cockpit_surface_relation': cockpit_surface_relation,
        'cockpit_results': {'brain': brain_result, 'hooks': hook_result,
                            'governance': governance_result},
        'brain_surface': brain_surface, 'brain_sync': brain_sync,
        'brain_map_sync': brain_map_sync, 'brain_claim': brain_claim,
        'brain_work_sync': brain_work_sync,
        'brain_work_sync_result': brain_work_sync_result,
        'brain_work_claim': brain_work_claim,
        'brain_work_claim_result': brain_work_claim_result,
        'brain_report_source': brain_report_source,
        'brain_report_result': brain_report_result, 'brain_fields': brain_fields,
        'cde_fields': cde_fields,
        'settings': settings_surface, 'settings_inputs': settings_inputs,
        'website': website,
    }

# With nothing selected, the map's wires are a faint weave -- the cards
# read first; a selected or hovered card lights its own wires. 1.4 showed
# wires per focus; 330 wires at .62 was a hairball.
STYLESHEET += (
    '.canvas[data-selection="[]"] .universal-wire[data-context="True"]'
    ':not([data-focused="True"]):not([data-hover-context="True"]){opacity:.18}'
    '.canvas[data-selection="[]"] .graph-node:hover ~ .wire-layer .universal-wire{opacity:.18}'
)

# The 1.4 palette, on the one graph: category colours drive the card's
# accent (top border, head, sockets) exactly as the 1.4 category map did;
# declared sockets stack down the card edges; head reads the category.
STYLESHEET += (
    '.graph-node[data-node-category="Input"]{--node-color:var(--blue)}'
    '.graph-node[data-node-category="Output"]{--node-color:var(--ok)}'
    '.graph-node[data-node-category="Watch"]{--node-color:var(--cyan)}'
    '.graph-node[data-node-category="Trigger"]{--node-color:var(--warn)}'
    '.graph-node[data-node-category="Logic"]{--node-color:var(--purple)}'
    '.graph-node[data-node-category="Shape"]{--node-color:var(--warn)}'
    '.graph-node[data-node-category="AI"]{--node-color:var(--purple)}'
    '.graph-node[data-node-category="Note"]{--node-color:var(--ink-soft)}'
    '.graph-node[data-node-category="Skill"]{--node-color:var(--accent)}'
    '.node-head{text-transform:uppercase;letter-spacing:.16em;font-family:JetBrains Mono,ui-monospace,monospace;font-size:8.5px}'
    '.node-port[data-port-index="0"]{top:44px}'
    '.node-port[data-port-index="1"]{top:66px}'
    '.node-port[data-port-index="2"]{top:88px}'
    '.node-port[data-port-index="3"]{top:110px}'
    '.node-port[data-port-index="4"]{top:132px}'
    '.node-port[data-port-index="5"]{top:154px}'
    '.graph-node:hover .node-port,.node-port.wire-target-ready{font-size:8.5px;color:var(--ink-muted)}'
    '.node-port.wire-target-ready{color:var(--ok)}'
    '.node-port[data-interface-mode="declared"]{cursor:crosshair}'
    '.node-port[data-interface-mode="declared"]::before{border-style:solid}'
)

# Cards grow with their socket rows instead of overlapping them; the value
# line stays pinned to the bottom edge.
STYLESHEET += (
    '.graph-node:has(.node-port[data-port-index="1"]){min-height:132px}'
    '.graph-node:has(.node-port[data-port-index="2"]){min-height:154px}'
    '.graph-node:has(.node-port[data-port-index="3"]){min-height:176px}'
    '.graph-node:has(.node-port[data-port-index="4"]){min-height:198px}'
    '.graph-node:has(.node-port[data-port-index="5"]){min-height:220px}'
    '.node-value{position:relative;z-index:2;background:var(--bg-panel)}'
)
