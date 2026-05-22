---
id: AgDR-0024
timestamp: 2026-05-21T00:00:00Z
agent: claude-code (Sonnet)
session: founder approved host-node-direction-a-comfyui-v2-ecosystem.html
trigger: Founder sign-off 2026-05-21 — "agreed...go" on the 11-constraint decision block in the v2 prototype
status: approved
category: architecture
projects: [archhub]
extends:
  - AgDR-0001 SLICE A — 16 per-host master nodes (the surface this redesigns)
  - AgDR-0002 — disable verbs (pin / freeze / bypass / preview-off) reused
  - AgDR-0005 — group collapse boundary-port algorithm reused unchanged
  - AgDR-0010 — Save-as-Skill preserves promoted sockets
  - AgDR-0013 — LIBRARY-FIRST gate surfaces existing matches first
  - AgDR-0015 — Phase 2 token binding + WCAG audit
  - AgDR-0020/0021 — code_expr / ai_plan typed primitives coexist
---

# Host node v2 — Direction A + ComfyUI hover-promote + ecosystem integration

> Founder sign-off 2026-05-21 on prototype
> `docs/prototypes/host-node-direction-a-comfyui-v2-ecosystem.html`
> (4 stages: REST · HOVER+SETTINGS · ECOSYSTEM · COLLAPSED-GROUP).
> All 11 constraints accepted. JSX migration ships sub-slice by
> sub-slice behind a `localStorage.archhub.host_node_v2` feature
> flag so the current rail stays the default until parity is
> reached + founder flips the flag.

## Constraints (signed)

1. **Op grid + active-tile-expand** (Direction A base).
2. **Per-host brand stripe** — Slice A's 16 per-host masters; brand
   colour drives the node's top border (Revit orange · AutoCAD red ·
   Max purple · Excel cyan · …).
3. **MAIN ⇄ ADVANCED I/O split** — primary inputs always visible;
   advanced inputs collapsed.
4. **OUTPUT PLUCK section** — every cooked output field hover-promotes
   to a typed right-rail socket. **The big new mechanic in v2.**
5. **Type-hint pill** on hover (`element` / `number` / `bool` / `str` /
   `id` / `list<T>`) — coloured by typed-wire palette (Slice D).
6. **Floating disable-verbs bar** — pin / freeze / bypass / preview-off
   with kbd shortcuts (AgDR-0002 reuse).
7. **Promoted sockets feed Save-as-Skill I/O** (AgDR-0010 reuse).
8. **Group-collapse boundary = promoted I/O** (AgDR-0005 reuse —
   no new algorithm needed).
9. **ai.plan reads promoted-socket schema as its tool surface**
   (AgDR-0021 reuse).
10. **Library-first Cmd-K shows existing matches before "create new"**
    (AgDR-0013 reuse).
11. **Wire colours follow Slice D palette + contrast tokens pass
    WCAG audit** (Slice D + AgDR-0015 reuse).

## Sub-slice ordering

Each sub-slice ships behind the feature flag + a per-slice CDP demo.

- **S1 · REST** — Op grid on canvas + active-tile-expand + MAIN inputs
  section. NO hover, NO advanced, NO output pluck. THIS SHIP.
- **S2 · HOVER + ADVANCED + FLOATING BAR** — hover-promote markers +
  ADVANCED INPUTS collapse + floating disable-verbs bar.
- **S3 · OUTPUT PLUCK** — output rows + right-rail sockets + downstream
  consumers wire to plucked fields (adapter / share / code).
- **S4 · ECOSYSTEM INTEGRATION** — Save-as-Skill captures promoted
  I/O; ai.plan reads schema; library-first Cmd-K refinements.

Each sub-slice = its own commit + tests + founder ack before next.

## Feature flag

```js
const _readHostNodeV2 = () => {
  try {
    return (localStorage.getItem('archhub.host_node_v2') || '').toLowerCase() === 'on';
  } catch (e) { return false; }
};
const _setHostNodeV2 = (on) => {
  try { localStorage.setItem('archhub.host_node_v2', on ? 'on' : 'off'); } catch (e) {}
  try { window.dispatchEvent(new CustomEvent('archhub-host-node-v2', { detail: !!on })); } catch (e) {}
  return !!on;
};
window.__archhubHostNodeV2 = _readHostNodeV2;
window.__archhubSetHostNodeV2 = _setHostNodeV2;
```

Default OFF until founder flips. Flip is instant — no app restart.

## What ships in S1 (THIS commit)

- Feature flag (reader + writer + window globals).
- `HostNodeV2Body` — new JSX render path for connector master nodes
  when flag is on. Renders: op-grid (4-column), per-tile pill +
  time stamp, active-tile-expand with MAIN INPUTS rows (no hover,
  no advanced, no output pluck — those land in S2 + S3).
- Wired only into the canvas-side render of connector master
  nodes. Right-panel ConnectorRail unchanged (lives in S2+).
- Tests pin: flag reader + writer, HostNodeV2Body exists, dispatch
  event fires, default-off invariant, op grid renders all op ids
  the connector exposes, active-tile-expand shows MAIN INPUTS.

## What does NOT ship in S1

- Hover-promote markers (S2).
- ADVANCED INPUTS section + collapse (S2).
- Floating disable-verbs bar (S2).
- OUTPUT PLUCK rows (S3).
- Save-as-Skill integration (S4).
- ai.plan schema-reading (S4).
- Right-panel ConnectorRail rewrite (S2-S4).

## Acceptance (S1)

Flip `localStorage.archhub.host_node_v2 = 'on'`. Place a Revit
master node from palette. Canvas renders the node face with the
op grid + active list_walls tile + MAIN INPUTS rows. JSX
Babel-parse clean. Suite green. Founder confirms via CDP demo.

## Artifacts

- This AgDR.
- Pending: `app/web_ui/studio-lm.jsx` (additive — new render path
  behind flag; existing path untouched), `tests/test_host_node_v2_s1.py`
  (new).
