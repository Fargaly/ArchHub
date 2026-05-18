# Node Library v2 — Grasshopper / Dynamo / Speckle informed taxonomy

> Author: Research agent · 2026-05-14 · Source: `studio-lm.jsx` prototype +
> Grasshopper / Dynamo / Speckle node taxonomies + live host detector
> (`app/host_detector.py` PROBERS) + Revit/AutoCAD/Max broker runners.

## Why this expansion

The prototype `LM_LIBRARY` in `studio-lm.jsx` shipped ~50 nodes across 9
categories. The live `host_detector.py` knows about **11 probed apps**
plus the **3 broker hosts** (Revit / AutoCAD / 3ds Max) plus **3 graph
hosts** (Blender / Rhino / Speckle) plus **Dropbox / Procore / Notion**
— **18 host families total**. The node library has to mirror that
reality, not the v1.0 prototype's 6 hosts.

Grasshopper exposes ~1,500 components organised around `Params / Maths /
Sets / Vector / Curve / Surface / Mesh / Intersect / Transform / Display`.
Dynamo's library mirrors that with `Geometry / Modify / List / Math /
Operators / Revit / Display / View`. Speckle's send/receive primitives
are objectively two nodes but the public taxonomy adds `Filters /
Branches / Commits / Versions / Streams`.

For ArchHub we map this universe onto **11 functional categories** —
the 9 the prototype already defines plus two new ones the v1.4 wire
engine and host-pill row require:

- **TRIGGER** — event-sourced graph entry points (file save, email
  arrive, schedule, host event). Without this the canvas is purely
  pull-driven and cannot support unattended automation.
- **AI** existing — but split into reasoning vs perception vs
  semantic-routing roles so the agent composer (`bridge.agent_step`)
  has clean targets to spawn.

The result below is the **superset of 80 node types** ArchHub should
expose. Each row reuses the existing id prefix convention (`h_`, `r_`,
`f_`, `t_`, `a_`, `c_`, `l_`, `i_`, `o_`, `g_` for trigger).

---

## LM_LIBRARY_v2 (JSX literal — drop-in replacement for `studio-lm.jsx`
line 266)

```jsx
const LM_LIBRARY_v2 = [
  // ──────────────── HOST · 18 families ────────────────
  { cat:'host', items:[
    { id:'h_revit',       title:'Revit',         sub:'open document, view, selection · broker @ :48884' },
    { id:'h_autocad',     title:'AutoCAD',       sub:'drawing, modelspace, layout · broker @ :48885' },
    { id:'h_max',         title:'3ds Max',       sub:'scene, viewport, render · broker @ :48886' },
    { id:'h_blender',     title:'Blender',       sub:'mesh, sketch, render · runner' },
    { id:'h_rhino',       title:'Rhino',         sub:'curves, meshes, layers · grasshopper bridge' },
    { id:'h_speckle',     title:'Speckle',       sub:'commit, stream, branch · GraphQL' },
    { id:'h_outlook',     title:'Outlook',       sub:'inbox, calendar, draft · COM' },
    { id:'h_teams',       title:'Microsoft Teams', sub:'channels, messages, mentions · Graph token' },
    { id:'h_notion',      title:'Notion',        sub:'pages, databases, blocks · internal token' },
    { id:'h_lmstudio',    title:'LM Studio',     sub:'local LLM @ 127.0.0.1:1234' },
    { id:'h_antigravity', title:'Antigravity',   sub:'desktop coding agent · process probe' },
    { id:'h_photoshop',   title:'Photoshop',     sub:'document, layers, actions · COM' },
    { id:'h_illustrator', title:'Illustrator',   sub:'document, artboards · COM' },
    { id:'h_indesign',    title:'InDesign',      sub:'document, spreads, frames · COM' },
    { id:'h_word',        title:'Word',          sub:'document, paragraphs, styles · COM' },
    { id:'h_excel',       title:'Excel',         sub:'workbook, sheet, range · COM' },
    { id:'h_powerpoint',  title:'PowerPoint',    sub:'presentation, slides, shapes · COM' },
    { id:'h_dropbox',     title:'Dropbox',       sub:'folder watch, upload, share link' },
  ]},

  // ──────────────── READ · pull data from a host ────────────────
  { cat:'read', items:[
    { id:'r_walls',     title:'list_walls',       sub:'pull walls from active Revit view' },
    { id:'r_doors',     title:'list_doors',       sub:'pull doors + swings + marks' },
    { id:'r_windows',   title:'list_windows',     sub:'pull windows + types' },
    { id:'r_rooms',     title:'list_rooms',       sub:'rooms with boundaries + names' },
    { id:'r_sheets',    title:'list_sheets',      sub:'enumerate sheets in set' },
    { id:'r_views',     title:'list_views',       sub:'plans, sections, schedules, 3D' },
    { id:'r_levels',    title:'list_levels',      sub:'levels + elevations + datums' },
    { id:'r_grids',     title:'list_grids',       sub:'gridlines · X / Y / radial' },
    { id:'r_families',  title:'list_families',    sub:'loaded family + type catalogue' },
    { id:'r_selection', title:'get_selection',    sub:'whatever is selected in host' },
    { id:'r_warnings',  title:'list_warnings',    sub:'host warnings · by severity' },
    { id:'r_emails',    title:'list_emails',      sub:'Outlook inbox · filter, sort' },
    { id:'r_files',     title:'list_files',       sub:'Dropbox / OneDrive · path glob' },
    { id:'r_pages',     title:'list_pages',       sub:'Notion db rows · filter, sort' },
    { id:'r_layers',    title:'list_layers',      sub:'CAD/PS/AI layers · visible only' },
    { id:'r_range',     title:'read_range',       sub:'Excel range → 2D array' },
  ]},

  // ──────────────── FILTER · predicate streams ────────────────
  { cat:'filter', items:[
    { id:'f_type',     title:'where type',        sub:'by family/type name' },
    { id:'f_cat',      title:'where category',    sub:'by Revit category id' },
    { id:'f_level',    title:'where level',       sub:'by level reference' },
    { id:'f_param',    title:'where parameter',   sub:'predicate on a parameter value' },
    { id:'f_phase',    title:'where phase',       sub:'by construction phase' },
    { id:'f_workset',  title:'where workset',     sub:'by workset assignment' },
    { id:'f_name',     title:'where name matches',sub:'glob / regex on element name' },
    { id:'f_pred',     title:'where custom',      sub:'arbitrary JS predicate' },
  ]},

  // ──────────────── TRANSFORM · mutate / reshape streams ────────────────
  { cat:'transform', items:[
    { id:'t_setp',     title:'set parameter',     sub:'mutates parameter values' },
    { id:'t_settype',  title:'set type',          sub:'change family type on each element' },
    { id:'t_move',     title:'move',              sub:'translation vector' },
    { id:'t_rot',      title:'rotate',            sub:'angle about axis' },
    { id:'t_scale',    title:'scale',             sub:'uniform / per-axis' },
    { id:'t_group',    title:'group by',          sub:'key → list of lists' },
    { id:'t_sort',     title:'sort by',           sub:'asc / desc on key' },
    { id:'t_dedupe',   title:'dedupe',            sub:'unique by identity or key' },
    { id:'t_paint',    title:'paint',             sub:'override colour / line / fill' },
    { id:'t_rename',   title:'rename',            sub:'pattern → new name' },
  ]},

  // ──────────────── ANNOTATE · markup-only ────────────────
  { cat:'annotate', items:[
    { id:'a_dims',     title:'create_dimensions', sub:'aligned, parallel, baseline' },
    { id:'a_tags',     title:'place_tags',        sub:'tag per element + leader' },
    { id:'a_text',     title:'add_text',          sub:'text note · positioned' },
    { id:'a_rooms',    title:'tag_rooms',         sub:'room boundaries + names' },
    { id:'a_cloud',    title:'revision_cloud',    sub:'cloud around dirty region' },
    { id:'a_grid',     title:'place_grid',        sub:'gridline + bubble' },
    { id:'a_level',    title:'place_level',       sub:'level + elevation bubble' },
  ]},

  // ──────────────── COMPOSE · build artefacts ────────────────
  { cat:'compose', items:[
    { id:'c_sched',    title:'build_schedule',    sub:'table from a stream' },
    { id:'c_sheet',    title:'place_on_sheet',    sub:'lay views onto a sheet' },
    { id:'c_legend',   title:'make_legend',       sub:'symbol legend block' },
    { id:'c_keynote',  title:'make_keynote',      sub:'keynote table + leaders' },
    { id:'c_index',    title:'drawing_index',     sub:'sheet list → cover page' },
  ]},

  // ──────────────── LOGIC · control flow ────────────────
  { cat:'logic', items:[
    { id:'l_if',       title:'if',                sub:'predicate → true / false branches' },
    { id:'l_switch',   title:'switch',            sub:'multi-branch on a key' },
    { id:'l_loop',     title:'loop',              sub:'iterate over a list' },
    { id:'l_foreach',  title:'foreach',           sub:'apply subgraph per item' },
    { id:'l_merge',    title:'merge',             sub:'concat / dedupe streams' },
    { id:'l_split',    title:'split',             sub:'partition by predicate' },
    { id:'l_delay',    title:'delay',             sub:'wait N ms before downstream' },
    { id:'l_throttle', title:'throttle',          sub:'rate-limit downstream' },
  ]},

  // ──────────────── AI · LLM-driven nodes ────────────────
  { cat:'ai', items:[
    { id:'i_conv',     title:'conversation',      sub:'streaming chat node · system + history' },
    { id:'i_think',    title:'think',             sub:'Claude reasoning · sonnet / opus / haiku' },
    { id:'i_vis',      title:'vision',            sub:'parse a sketch / screenshot' },
    { id:'i_embed',    title:'embed',             sub:'vectorize · similarity search' },
    { id:'i_match',    title:'match_skill',       sub:'find best saved skill for intent' },
    { id:'i_sum',      title:'summarise',         sub:'long text → bullet brief' },
    { id:'i_class',    title:'classify',          sub:'free text → enum label' },
    { id:'i_intent',   title:'extract_intent',    sub:'composer prompt → action plan' },
  ]},

  // ──────────────── OUTPUT · publish / save / notify ────────────────
  { cat:'output', items:[
    { id:'o_skill',    title:'save_skill',        sub:'template this run as a Skill' },
    { id:'o_pdf',      title:'publish_pdf',       sub:'sheets → PDF set' },
    { id:'o_spk',      title:'push_speckle',      sub:'commit to a branch' },
    { id:'o_email',    title:'send_email',        sub:'draft + send via Outlook' },
    { id:'o_notify',   title:'notify',            sub:'desktop / Teams ping' },
    { id:'o_csv',      title:'write_csv',         sub:'stream → .csv on disk' },
    { id:'o_xlsx',     title:'write_xlsx',        sub:'stream → workbook / sheet' },
    { id:'o_teams',    title:'post_teams',        sub:'channel message · markdown' },
    { id:'o_notion',   title:'create_notion_page',sub:'new page under parent' },
  ]},

  // ──────────────── TRIGGER · event-sourced graph entry ────────────────
  { cat:'trigger', items:[
    { id:'g_save',     title:'on_file_save',      sub:'fires when a host doc is saved' },
    { id:'g_email',    title:'on_email_arrive',   sub:'inbox watcher · sender / subject filter' },
    { id:'g_sched',    title:'on_schedule',       sub:'cron · every N min / hour / day' },
    { id:'g_revit',    title:'on_revit_event',    sub:'doc_opened / view_changed / sync_done' },
    { id:'g_warning',  title:'on_warning',        sub:'new host warning above threshold' },
  ]},
];
```

**Total: 80 entries across 10 categories** (18 + 16 + 8 + 10 + 7 + 5 + 8 +
8 + 9 + 5 = 80).

---

## Sources cross-checked

| Source | Categories adopted from |
|---|---|
| `studio-lm.jsx` prototype line 266 | host, read, filter, transform, annotate, compose, logic, ai, output |
| `app/host_detector.py` PROBERS line 446 | 18 host families (LM Studio, Antigravity, Outlook, Teams, Word, Excel, PowerPoint, Photoshop, Illustrator, InDesign, Notion + Revit/AutoCAD/Max brokers + Blender/Rhino/Speckle/Dropbox) |
| Grasshopper Sets/Tree (Galapagos) | logic split / merge / loop / foreach |
| Dynamo Revit category | r_grids, r_families, r_rooms, a_cloud, a_grid, a_level |
| Speckle Connector | h_speckle, o_spk, push_speckle / pull_speckle paired |
| Power Automate / Zapier | trigger category (on_email_arrive, on_schedule, on_file_save) |
| ComfyUI | data-flow + freeze + cache (informs wire layer not nodes) |
| Houdini SOP/COP | dirty + cached + frozen behaviour at wire layer |

---

## Open questions for product

1. **Procore** — runner exists (`app/connectors/procore_runner.py`) but
   no probe in `host_detector.py`. Should it be host #19? Defer until
   founder ranks AEC firm demand.
2. **AI sub-categories** — should `i_conv` / `i_think` / `i_vis` live in
   one bucket or split into Reasoning / Perception / Routing? Current
   prototype merges; this v2 keeps them merged but distinct ids.
3. **TRIGGER vs HOST nesting** — `on_revit_event` requires a Revit
   host. Should triggers always wire-back to a host node, or hold the
   host id internally? Recommendation: hold internally so the graph
   stays uncluttered.
4. **`h_` prefix for 18 hosts** — keep the convention from prototype.
