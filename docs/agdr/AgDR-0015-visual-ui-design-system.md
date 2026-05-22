---
id: AgDR-0015
timestamp: 2026-05-20T00:00:00Z
agent: claude-code (Sonnet)
session: node-redesign-loop · /design:design-system audit
trigger: founder `/design:design-system` (second invocation) — audit the VISUAL UI design system in studio-lm.jsx, complementing the library taxonomy audit in AgDR-0014
status: proposed
category: architecture
projects: [archhub]
---

# Visual UI design system audit + scale-token + accessibility floor

> In the context of the founder's second `/design:design-system` invocation
> (after AgDR-0014 audited the LIBRARY as a design system), I audited the
> VISUAL UI design system in `app/web_ui/studio-lm.jsx` (8 596 lines) and
> found it **partially tokenised** — colour + typography-family + category
> tokens are real and well-used (1 146 `LM.*` references, ~23 color tokens,
> 3 font-family tokens, 12 CAT tokens), but **scale tokens are absent** (no
> `LM.size` / `LM.font` / `LM.radius` / `LM.shadow` / `LM.motion`), leading
> to 328 inline `fontSize: N`, 223 inline `padding/margin: N`, 173 inline
> `borderRadius: N`, 30 ad-hoc `boxShadow` strings, 9 ad-hoc `transition`
> strings, and **0 `aria-*` attributes** across the whole UI — a CRITICAL
> accessibility failure for a tool aimed at enterprise AEC professionals.
> Decided: extend the existing `LM` object with `LM.size` / `LM.font` /
> `LM.radius` / `LM.shadow` / `LM.motion` scale tokens; introduce an
> accessibility floor (every interactive element gets `aria-label` and
> visible focus ring); migrate IN-PLACE (additive, non-breaking) and lock
> the scale into the **ReactFlow M1.a scaffold from day one** so the
> migration to ReactFlow is built atop a token system, not into another
> magic-number sprawl. Accepting: ~2 weeks of refactor effort to migrate
> existing magic numbers to scale tokens during M3 polish; legacy
> half-pixel sizes (8.5, 9.5, 10.5) round to the nearest scale step;
> ARIA labels need a one-pass sweep before any A11Y compliance claim.

## Context

- Founder invoked `/design:design-system` twice. First pass produced
  AgDR-0014 (library taxonomy). Second pass demands the VISUAL side.
- ArchHub markets to enterprise AEC professionals. Enterprise procurement
  expects WCAG 2.1 AA. Today's `0` aria-* attributes is a procurement
  blocker, not a polish item.
- Direction X (AgDR-0012) commits ArchHub to a ReactFlow canvas migration
  (M1.a). The migration is the right moment to introduce scale tokens —
  retrofitting them later means migrating twice.
- Existing token surface in `studio-lm.jsx:13-23`:
  ```
  const LM = {
    bg:'#0e0e11', bgPanel:'#15151a', bgSoft:'#1c1c23', bgHover:'#22222a',
    bgDeep:'#0a0a0d', bgCanvas:'#101015', bgInk:'#18181e',
    ink:'#ece8e0', inkSoft:'#9b938a', inkMuted:'#5e574f', inkDim:'#3a3530',
    line:'#26262e', lineSoft:'#1e1e24', lineHair:'#1a1a20',
    accent:'#d97757', accentSoft:'#3a2018', accentDim:'#2a1812', accentHi:'#e8896a',
    ok:'#7ec18e', warn:'#e5b25a', err:'#e6705f', cyan:'#5fb3b3',
    purple:'#a98cd6', blue:'#7898d6',
    serif:"'Instrument Serif', Georgia, serif",
    sans:"'Inter', system-ui, sans-serif",
    mono:"'JetBrains Mono', ui-monospace, monospace",
  };
  ```
  This is well-formed for what it covers; gap is in scale + brand
  extensions + accessibility.

## Audit

### Summary

| Surface | Tokens defined | Token usage | Score |
|---|---|---|---|
| Color (background / ink / line / accent / status) | 23 | 1146 LM.* references | ✅ 9/10 |
| Color (host-brand: Speckle, Dropbox, Teams…) | 0 (inline hex) | ~20 inline hex (`#0696D7`, `#0061ff`, …) | ⚠ 4/10 |
| Color (wire by port type) | 0 (semi-tokenised) | 30 entries in `WIRE` map; ~6 inline hex | ⚠ 6/10 |
| Typography family | 3 (serif / sans / mono) | 279 fontFamily declarations | ✅ 9/10 |
| Typography scale (font-size) | 0 | 328 inline `fontSize: N` across 15+ unique sizes (incl. half-pixel: 8.5, 9.5, 10.5, 11.5, 12.5) | ❌ 1/10 |
| Spacing (padding / margin) | 0 | 223 inline magic numbers | ❌ 1/10 |
| Border radius | 0 | 173 inline magic numbers across 10+ unique sizes (2, 3, 4, 5, 6, 7, 8, 9, 10, 999) | ❌ 2/10 |
| Shadow | 0 | 30 inline boxShadow strings | ❌ 2/10 |
| Motion (transition / animation) | 0 | 9 inline transition strings (very low animation coverage) | ⚠ 3/10 |
| Accessibility (aria-*, role, focus ring) | 0 aria-* / 11 role+tabIndex+onKeyDown | catastrophically low | ❌ 0/10 |

**Overall score: ≈ 45/100.** Existing token surface is honest; missing
half is structural.

### Naming consistency

| Issue | Where | Recommendation |
|---|---|---|
| Wire colors mix LM refs + hex literals (`'#e3b950'`, `'#6a9bcc'`, …) | `studio-lm.jsx:50-64` | Promote wire colors onto `LM.wire.<port_type>` so they share the color system |
| Host-brand colors inline (~20 `#XXXXXX`) | `studio-lm.jsx:673-691` | Promote to `LM.brand.<host>` (speckle, dropbox, teams, …) |
| Some category colors duplicate LM (e.g. `#9b59b6` ≈ `LM.purple`) | `studio-lm.jsx:61-64, 271-276` | Replace with `LM.purple` reference |
| Half-pixel font sizes (8.5, 9.5, 10.5, 11.5, 12.5) | ~80 occurrences | Round to scale step (10, 11, 13, 15) — half-pixels are blurry on non-Retina displays |
| `LM.serif`'s "Instrument Serif" font may not be installed on user machines | `studio-lm.jsx:20` | Verify font loading; document fallback chain |

### Component completeness

| Component | States | Variants | Token-driven | Score |
|---|---|---|---|---|
| `NodeRail` / `ConnectorRail` | focus, selected, bypassed, frozen, pinned | per-host badge mode | partial (colour ✓, spacing ✗) | 6/10 |
| `WatchBody` (list / table / json / image / view / model) | empty, loaded | 6 render modes | partial | 7/10 |
| `NoteBody` (markdown subset) | edit / display | — | partial | 7/10 |
| `NodeLibrary` modal | open / closed, search match / no-match | 4 entry points | partial | 6/10 |
| `WirePromotePalette` (AddNodeSearch) | autocomplete focused | prefix-grammar modes | partial | 7/10 |
| `SaveSkillDialog` | mode-pair toggle | shared / private | partial | 6/10 |
| `GroupDialog` | open / closed | 6 style pills | partial | 7/10 |
| `LM-toolbar` / panel chrome | hover / active | per-tool | partial | 5/10 |
| `ApprovalGate` (USER-AGENCY) | not built yet | Plan / Auto / YOLO modes | — | 0/10 (M3) |

### Priority issues

1. **CRITICAL — 0 aria-* across 8 596 lines.** Every button, input,
   modal, dialog, dropdown needs `aria-label` / `aria-labelledby`. No
   enterprise can buy this until WCAG 2.1 AA is plausible.
2. **328 magic font-sizes across 15+ unique values.** Reads as
   typographic noise; ReactFlow nodes inherit, but per-component inline
   styles override and drift further. Migration to a 4-step scale halves
   the noise.
3. **No focus ring system.** Keyboard navigation is invisible. The 11
   `tabIndex` / `onKeyDown` hits show some keyboard work, but no
   consistent visible focus state.
4. **30 boxShadow strings handwritten.** Inconsistent elevation. Affects
   panel/modal/dialog/tooltip; elevation hierarchy is unclear.
5. **No motion vocabulary.** 9 ad-hoc transitions = animation
   inconsistency. Composer streaming UX (M3) needs motion tokens.

## Decision — design-system extension

### Token 1 — `LM.size` (spacing scale, 4-step base)

```js
LM.size = {
  0: 0,      // collapse
  1: 4,      // tight (icon padding)
  2: 8,      // standard small
  3: 12,     // standard
  4: 16,     // section break
  5: 20,     // panel padding
  6: 28,     // hero
  7: 40,     // dialog
};
```

Maps every existing `padding: N` / `margin: N` magic number to the
nearest scale step. Half-pixel values disappear.

### Token 2 — `LM.font` (type scale, 4-step)

```js
LM.font = {
  xs: 10,    // metadata, footnote
  sm: 11,    // body small
  base: 13,  // body
  md: 15,    // emphasis
  lg: 18,    // section header
  xl: 22,    // page title
};
```

15 unique font-sizes → 6 scale steps. Half-pixel sizes round up.

Eyeballing the audit data: 9px → `xs` (since most are 9-9.5px); 11-12px
→ `sm/base`; 13-14px → `base/md`; 18+ → `lg/xl`.

### Token 3 — `LM.radius` (border-radius scale)

```js
LM.radius = {
  none: 0,
  xs: 3,
  sm: 5,
  md: 8,
  lg: 12,
  pill: 999,
};
```

10 unique values → 6 scale steps. `999px` (pill) keeps as a named token.

### Token 4 — `LM.shadow` (elevation scale)

```js
LM.shadow = {
  none: 'none',
  s1: '0 1px 2px rgba(0,0,0,0.3)',     // hover lift
  s2: '0 4px 12px rgba(0,0,0,0.4)',    // panel
  s3: '0 8px 24px rgba(0,0,0,0.5)',    // dialog / popover
  s4: '0 16px 48px rgba(0,0,0,0.6)',   // command palette / modal
};
```

30 boxShadow strings → 4 elevation tiers + `none`.

### Token 5 — `LM.motion` (transition + easing)

```js
LM.motion = {
  fast:  '120ms cubic-bezier(0.4, 0.0, 0.2, 1)',   // hover, focus
  base:  '200ms cubic-bezier(0.4, 0.0, 0.2, 1)',   // expand, collapse
  slow:  '320ms cubic-bezier(0.4, 0.0, 0.2, 1)',   // dialog enter / exit
  spring:'380ms cubic-bezier(0.34, 1.56, 0.64, 1)', // emphasis pop
};
```

9 ad-hoc transitions → 4 named tokens with consistent easings.

### Token 6 — `LM.brand` (host-third-party identity)

```js
LM.brand = {
  speckle:   '#3a6acc',
  autocad:   '#E87D0D',
  revit:     '#0696D7',
  max3ds:    '#0078D4',
  rhino:     '#b8b4ab',
  blender:   '#E87D0D',
  dropbox:   '#0061ff',
  word:      '#2B579A',
  excel:     '#107C41',
  powerpoint:'#B7472A',
  outlook:   '#5b8def',
  teams:     '#5b5fc7',
  notion:    LM.ink,
  photoshop: '#31A8FF',
  illustrator:'#FF9A00',
  indesign:  '#FF3366',
  anthropic: '#cc785c',
};
```

~20 host-brand hex literals → one `LM.brand.<host>` lookup. Easy to
audit, easy to swap dark / light mode variants later.

### Token 7 — Accessibility floor (NEW — non-token)

Hard rule across the codebase, enforced by lint + code review:

| Element | Requirement |
|---|---|
| Every interactive `<button>` | `aria-label` or visible text label |
| Every `<input>` | associated `<label>` or `aria-labelledby` |
| Every modal / dialog | `role="dialog"`, `aria-labelledby`, focus trap, ESC closes |
| Every dropdown | `role="combobox"` / `listbox`, arrow-key nav |
| Every node on canvas | `role="treeitem"` or `role="button"` with `aria-label` |
| Every wire | non-color affordance (dashed dasharray) for colour-blind users — slice D already does this via shape encoding |
| Focus ring | 2 px solid `LM.accent` outline on every focusable element (`:focus-visible`) |
| Keyboard | every action reachable without mouse; Tab order matches visual |
| Reduced motion | `@media (prefers-reduced-motion)` disables `LM.motion.spring` |

Today's score on this floor: **0/9**. Migration is a one-pass sweep
across `studio-lm.jsx` — ~1 week.

## Migration plan — IN-PLACE, non-breaking

### Phase 1 — Add tokens (zero functional change)

- Add `LM.size`, `LM.font`, `LM.radius`, `LM.shadow`, `LM.motion`,
  `LM.brand` to the `LM` object.
- No existing inline styles change yet. New components use tokens
  from day one.
- Acceptance: tests still green; visual diff = 0 pixels.

### Phase 2 — ReactFlow scaffold uses tokens from day 1 (M1.a)

- Every ReactFlow node + edge + handle styled via `LM.*` tokens. No
  magic numbers in the new ReactFlow code.
- The migration's success is gated on this — if ReactFlow scaffold ships
  with magic numbers, we miss the window.

### Phase 3 — Migrate existing inline styles (during M3 polish, 1-2 wks)

- Sweep `fontSize: N` → `fontSize: LM.font.<step>`.
- Sweep `padding: N` / `margin: N` → `padding: LM.size[N]` /
  `margin: LM.size[N]`.
- Sweep `borderRadius: N` → `borderRadius: LM.radius.<step>`.
- Sweep `boxShadow: '...'` → `boxShadow: LM.shadow.<tier>`.
- Sweep host-brand hex → `LM.brand.<host>`.
- One PR per component (NodeRail, WatchBody, NodeLibrary, …).

### Phase 4 — Accessibility sweep (1 wk)

- Add `aria-label` everywhere. Add focus rings. Trap focus in modals.
- Test with `axe-core` via QtWebEngine's CDP — no manual tester.

## Consequences

### What ships in Phase 1 (this AgDR's code change)

- `LM` object extended with 6 new sub-objects.
- No JSX changes outside `LM` definition.
- New tokens documented inline in the source so the JSX reads at the
  same level of detail as the AgDR.

### What's reinforced

- "Consistency over creativity" — every visual decision now references
  a token.
- ReactFlow migration starts on a token system, not into a sprawl.
- Accessibility becomes a design-system token (the floor), not a
  per-component decision.

### Risks

- 328 fontSize replacements is mechanical but high-volume. Mistakes
  show up as 1-2 px UI drift; CDP screenshot diff catches most.
- Half-pixel rounding (8.5 → 9 or 10) shifts existing layouts by 1 px.
  Acceptable; the half-pixel was already a rendering hazard on non-
  Retina displays.
- The `LM.brand` colors need light-mode variants if/when ArchHub adds
  light theme; defer to later AgDR.

### Tests / acceptance

- Phase 1: existing 1321-test suite stays green (no functional change).
- Phase 2 (M1.a): a ReactFlow scaffold smoke test asserts every styled
  element references `LM.*` (no inline hex).
- Phase 3: per-component visual diff regression suite (CDP screenshot
  diff at 3 viewport sizes).
- Phase 4: `axe-core` automated a11y scan — 0 critical violations.

## Open forks for founder

1. **Scale-step base unit.** Token 1 uses a 4-px base (8 px steps).
   Material uses 4 px, Apple uses 8 px. Pick 4 (denser, our current
   ~50 % of inline values are at 4-8 px) or 8 (cleaner, but means more
   compression).
2. **Font scale max step.** Today's largest font-size in use is 22 px;
   the proposed scale tops at `xl: 22`. Should there be `xxl: 28` /
   `xxxl: 36` for the Composer's hero state?
3. **`LM.brand.notion` defaulted to `LM.ink`** because Notion's brand
   is greyscale. OK or specific color?
4. **Phase 3 migration** is 1-2 weeks of refactor with no new
   features. Run it serial (block features), or parallel to M3?
5. **Accessibility scope** — full WCAG 2.1 AA, or only the AAA-blocker
   subset (focus rings + aria-labels + keyboard nav)?

## Artifacts

- This AgDR.
- Audit data: 57 hex literals, 33 rgba, 328 fontSize, 223 padding/margin,
  173 borderRadius, 30 boxShadow, 9 transition, 0 aria-* — measured via
  Grep across `app/web_ui/studio-lm.jsx` 2026-05-20.
- Existing token surface: `studio-lm.jsx:13-23` (`LM`),
  `studio-lm.jsx:26-39` (`CAT`), `studio-lm.jsx:45-65` (`WIRE`).
- Phase 1 code change scheduled for the next loop iteration if founder
  signs off (additive — non-breaking).
