# ArchHub Accessibility Audit — 2026-05-26

> Track E deliverable from the Content Ecosystem wave plan
> (`docs/CONTENT-ECOSYSTEM-2026-05-26.md` §6). Honest snapshot of the
> current a11y posture + the first wave of fixes shipped this session.
> ANTI-LIE: this audit does **not** claim WCAG 2.1 AA achieved. It
> claims a starting baseline, gaps measured, and the first surfaces
> moved toward AA.

---

## 1. Current state (no-fiction inventory)

### What exists today
- **3 a11y test files** under `tests/`:
  - `tests/test_a11y_phase_4_dropdown_nav.py` — keyboard navigation
    smoke for dropdowns.
  - `tests/test_a11y_phase_4_modals.py` — focus management + ESC
    contract per modal.
  - `tests/test_a11y_phase_4_nucleus.py` — top-level nucleus + ARIA
    landmark smoke.
- **20 `aria-label=` attributes** in `app/web_ui/studio-lm.jsx`
  (12 717 LoC) — concentrated in the more-menu icons, the close
  buttons, the new-chat / new-skill buttons, and the canvas
  health-panel close.
- **6 `aria-labelledby` attributes** — every modal dialog uses one
  to link its title to the dialog landmark.
- **One `role="radiogroup"` block** for the Composer mode picker
  (lines 9735-9764) with `aria-checked` per radio.

### What is missing
- **No central a11y playbook.** Test files exist but no doc tells the
  team *which contract* every surface must hold.
- **No per-user a11y preferences.** Font size, contrast, motion,
  screen-reader-optimised — none are storable. The brain has the
  primitives (`Fragment(kind=SETUP)`) but no a11y-specific writer.
- **No WCAG 2.1 AA contrast audit doc.** The dark theme tokens in
  `app/settings_dialog.py::TOKENS` (and the JSX `LM` palette) have
  never been measured against AA 4.5:1 (text) / 3:1 (large text)
  thresholds.
- **No native PyQt accessibility tree audit.** Zero calls to
  `setAccessibleName` / `setAccessibleDescription` exist in any of
  the ~30 `QPushButton` constructors across `settings_dialog.py`.
  Screen readers on Windows (Narrator) get the button label text but
  no explicit accessible name override.

### One keyboard-only smoke per modal
Confirmed: `tests/test_a11y_phase_4_modals.py` exercises ESC + Tab +
Enter against every modal listed in `MODAL_REGISTRY`. This is the
floor — keyboard-only smoke per modal already exists. Other surfaces
(canvas, composer, settings tabs) do **not** yet have an equivalent
floor.

---

## 2. Gap counts (derived from grep, 2026-05-26)

| Surface | Clickables | aria-label / aria-labelledby | Gap |
|---------|-----------|------------------------------|-----|
| `studio-lm.jsx` `<button onClick>` (rough) | ~160 | 26 (20 + 6) | ~134 |
| `studio-lm.jsx` total `onClick=` (incl. divs) | 188 | 26 | ~162 |
| `settings_dialog.py` `QPushButton(` | 30 | 0 `setAccessibleName` | 30 |

**Reading.** The JSX has thousands of clickable surfaces but the
overwhelming majority have either a `title` attribute (showing on
hover and read by some screen readers) or a clear text label inside
the button. The hard misses are icon-only buttons (📎, 🎤, ⟲) and
divs masquerading as buttons.

PyQt is the bigger surface gap: every `QPushButton` carries its text
label, but custom controls and ones that change text-by-state (e.g.
the brain status pulse `●`) have no explicit accessible name. This is
a **multi-session** sweep, not a single-session deliverable.

---

## 3. Per-Settings-tab accessible-name status

`app/settings_dialog.py` defines 10 tabs (11 after Track E lands the
`AccessibilityTab`). For each, the table records whether the tab
currently calls `setAccessibleName` on any control:

| Tab | Has `setAccessibleName` | Notes |
|-----|------------------------|-------|
| General | No | Uses QFormLayout labels (implicit names via QLabel buddy). |
| Providers | No | Custom widget rows; provider name only in QLabel text. |
| Secrets | No | New tab from agent 3; QLineEdit + dialog buttons. |
| Hosts | No | Refresh / Detect / Connect buttons unnamed. |
| Memory | No | Stat tiles + buttons. |
| Brain | No | Status pulse `●` has no accessible name (just a glyph). |
| Permissions | No | Per-permission toggles inherit QCheckBox label. |
| Storage | No | Open-folder buttons unnamed. |
| Shortcuts | No | Read-only table; row labels via QTableWidget. |
| **Accessibility (NEW)** | **N/A — being shipped this session** | Controls *do* set `setAccessibleName` from day 1 (see §5). |
| About | No | Build / version labels in QFormLayout. |

**Target.** Every tab gets a sweep adding `setAccessibleName` on
every interactive control. Tracked as multi-session work in the
runtime queue.

---

## 4. WCAG 2.1 AA gap list

Honest status: **the audit has not yet been run.** This doc names
what must be measured; the measurement is multi-session work.

Target gates:

1. **1.4.3 Contrast (Minimum) — AA 4.5:1 / 3:1.** Tokens in
   `settings_dialog.py::TOKENS` (background `#0e0e11`, text
   `#ece8e0`, muted `#8a8a93`) must be measured. The muted-on-bg pair
   is the suspected fail — `#8a8a93` on `#0e0e11` is borderline.
2. **1.4.11 Non-text Contrast — AA 3:1.** Border tokens (`#2a2a33`)
   must clear 3:1 against `#15151a` / `#1a1a21`. Suspected close-fail.
3. **2.1.1 Keyboard — AA.** Every interactive widget reachable via
   Tab. Tracked by `test_a11y_phase_4_modals.py` for modals only;
   needs extension to canvas + composer.
4. **2.4.6 Headings and Labels — AA.** `_add_title(..., scope=…)`
   already provides h1 + scope chip per tab; passes.
5. **4.1.2 Name, Role, Value — A (foundation for AA).** This is
   where `setAccessibleName` matters. Currently failing on the 30
   `QPushButton` constructors that don't set it.

---

## 5. Target — what AA-bound surfaces look like

- **Settings → Accessibility tab** (this session): 4 user-controllable
  prefs (font size, contrast, reduce motion, screen-reader
  optimised). Persist via `brain.a11y_prefs(set, …)` → user-scope
  fragment. Cross-device via existing federation transport.
- **Per-user a11y prefs in brain** (this session): a `Fragment(kind=
  SETUP, predicate=a11y, object=<json>, scope=USER, owner_user=…)`.
  Lookup by `(predicate=a11y, owner_user=<seat>)`. Stored as one
  fragment per user (overwrite-on-set).
- **JSX aria sweep** (this session): ≥5 toolbar / nav / chip clickables
  that lacked `aria-label` get one. Conservative scope — top-level
  toolbar, rail nav, chip buttons. The full 12k-LoC JSX sweep is
  multi-session work.
- **PyQt setAccessibleName sweep** (multi-session, NOT this session):
  every `QPushButton` + custom widget gets a stable accessible name.
- **Contrast audit** (multi-session, NOT this session): run the
  WebAIM contrast checker against every TOKENS pair + LM palette pair
  and publish the matrix here.

---

## 6. What ships this session (the actual delta)

1. **This document** at `docs/ACCESSIBILITY-AUDIT-2026-05-26.md`
   (current state + gap counts + target).
2. **`AccessibilityTab`** in `app/settings_dialog.py` as the 11th
   tab (between Shortcuts and About). Mirrors BrainTab visual:
   scope chip, sections, save button.
3. **`BrainStore.a11y_prefs(mode, prefs, owner_user)`** in
   `personal-brain-mcp/src/personal_brain/storage.py`. Get-set
   primitive backed by a SETUP fragment.
4. **JSX aria sweep** in `app/web_ui/studio-lm.jsx` — added
   `aria-label` to top-level toolbar + chip + nav clickables that
   previously had only `title`. Conservative add, no logic change.
5. **`tests/test_a11y_prefs.py`** — 4 unit tests around
   `BrainStore.a11y_prefs`.
6. **`tests/test_settings_dialog_tabs.py`** — updated TABS expected
   list to length 11 with `Accessibility` at index 9.

---

## 7. What does NOT ship this session

Per ANTI-LIE: we do **not** claim "WCAG 2.1 AA achieved."

- Full PyQt `setAccessibleName` sweep — deferred (multi-session).
- Full JSX aria sweep on all 12k LoC — deferred (multi-session).
- Contrast measurement of every token pair — deferred.
- Native screen-reader smoke (Narrator on Windows) — deferred.
- `brain.a11y_prefs` MCP tool exposing the storage primitive to the
  daemon — this session adds the storage layer; the MCP wrapper +
  `BrainTab` integration is wave-2 work.

---

## 8. Brain integration (already designed in §6 of the ecosystem plan)

When the storage primitive ships, the Settings → Accessibility tab
talks to it via the same MCP wire BrainTab uses. The prefs land at
USER scope, sync cross-device via the existing federation transport
(Slice 8). Tutorial pages will read the contrast pref to auto-emit
an AAA-contrast variant; voice-over scripts will reuse the same step
list.

---

## 9. Verification

This session:

- `pytest tests/test_a11y_prefs.py` — 4 tests green.
- `pytest tests/test_settings_dialog_tabs.py` — TABS contract test
  green at length 11.
- `python -c "from settings_dialog import AccessibilityTab"` — clean
  import, no side effects.

Future sessions:

- Re-grep the JSX clickable count + aria-label count weekly. Number
  should monotonically decrease toward zero gap.
- Run `axe-core` or `Lighthouse` against the JSX at the website
  surface when Track A ships the Astro build.
- Native Narrator smoke on a fresh Windows install.

---

> Audit doc lives forever. Update this file (not a new one) every
> session that closes a measurable a11y gap.
