# Settings UI · design audit · 2026-05-26

Founder gripe Q3 comment (consolidated-signoff): *"the settings ui for instance
is a total shit that has nothing to do with the original design."*

This audit scopes the drift between current Settings UI surfaces and any signed
design source-of-truth. Output is a prioritized fix list for the polish slice
(task #25 + task #29) — NOT the slice itself.

## Inventory

### Current Settings surfaces (`app/settings_dialog.py`)
- `GeneralTab` (line 423) — Profile · Appearance · Default model · Canvas behaviour
- `ProvidersTab` (line 702)
- `HostsTab` (line 771)
- `MemoryTab` (line 913)
- `PermissionsTab` (line 1110) — Reasoning budget · Tool policies
- `StorageTab` (line 1276) — Disk usage · Open in Explorer · Backup
- `ShortcutsTab` (line 1479)
- `AboutTab` (line 1528)
- **`BrainTab` (line 1618)** — new native PyQt tab shipped 2026-05-26
  (replaces the failed JSX BrainSection per AgDR-0046 supersede)
- `AccessibilityTab` (line 2256)
- Studio-side wrapper: `app/settings_page.py` (sidebar + scroll, dedup'd to
  3 sections per Q11/§C10)

### Signed design source-of-truth
- **Brain panel only**: `docs/prototypes/signed/brain-settings-2026-05-25/`
  + `SIGNOFF.md` lists 9 pixel-anchored sections. PROTOTYPE-IS-CONTRACT
  applies — material deviation = bug.
- **No other Settings tab has a signed prototype.** General / Providers /
  Hosts / Memory / Permissions / Storage / Shortcuts / About / Accessibility
  have no design source-of-truth other than the codebase itself + token
  system (`LM_TOKENS`).

## Drift analysis — Brain tab (parity check vs signed prototype)

The signed prototype names 9 sections. Each row below is parity status of
the current `BrainTab` (settings_dialog.py:1618+).

| # | Signed section | Current state | Drift |
|---|---|---|---|
| 1 | Header — title + live status pulse | `BrainTab` has title + status row | needs verification of pulse animation parity |
| 2 | Master switch + daemon controls (Enable · Restart · Stop · View log · Autostart) | Native widget buttons present | likely button layout drift vs signed sidebar/cards |
| 3 | Live stats — 4 tiles (Skills · Facts · MCPs Wired · Uptime) | Stats present | tile grid vs signed pixel spec — verify spacing/dimensions |
| 4 | Connected agents — per-client row (logo + path + status + toggle) | Likely sparse / placeholder | LIKELY MAJOR DRIFT — agent rows may not render logos or path correctly |
| 5 | Rescan + Auto-Wire button + Preview config files | Verify present | drift unknown |
| 6 | Sync across devices — mode dropdown + folder picker + spatial-Speckle toggle | Verify present | drift unknown |
| 7 | Tuning & safety — R1 R2 R3 R4 toggles + LLM critic picker | Verify present | drift unknown |
| 8 | Privacy & secrets — secret refs only + redaction + audit log | Verify present | drift unknown |
| 9 | Danger zone — Export · Clear cache · Reset brain | Verify present | drift unknown |

**Verification action**: per row, open BrainTab at the running app + capture
a CDP/mss screenshot · cross-walk to the signed prototype · annotate the row
above with PARITY / PARTIAL / MISSING. Founder eye-check was *"design is a
total shit but for now it will do"* — confirms PARTIAL across most rows.

## Drift analysis — other tabs (no signed prototype, audit principles)

Without signed source-of-truth, judge against:
- ArchHub design tokens (`LM_TOKENS` from `studio-lm.jsx` + `app/theme.qss`)
- Consistency across tabs (no rogue colours / fonts / spacing)
- AgDR-0015 Phase 2 invariant: NO hex literals; bind to `LM.*` tokens

| Tab | Likely drift class | Severity |
|---|---|---|
| GeneralTab | Profile/Appearance/Model groups — standard QGroupBox layout · likely OK but no token-bind validation done | low |
| ProvidersTab | LARGE tab · most-used by founder · likely visual drift from any "Studio modern" baseline | high |
| HostsTab | Connector rows — should mirror NodesPanel hosts section design language | medium |
| MemoryTab | New surface · likely raw QGroupBox stack · drift from signed brain prototype's tile grid pattern | high |
| PermissionsTab | Reasoning budget + tool policies — verbose; needs UX simplification audit | medium |
| StorageTab | Disk usage chart? · Open-in-Explorer buttons OK · Backup section verify | low |
| ShortcutsTab | Probably table/grid — verify dark mode contrast | low |
| AboutTab | Static info · low risk | low |
| AccessibilityTab | Recently added · drift unknown | low-medium |

## Prioritised polish slice plan (recommended order)

1. **P0 · BrainTab parity** — rebuild to 1:1 with signed prototype.
   PROTOTYPE-IS-CONTRACT enforced. CDP visual diff per row.
   Slice = ~1-2 days. Task #25 owns this.
2. **P1 · Memory + Providers + Hosts tabs** — apply the signed-brain design
   language (sidebar + cards · tile grid for stats · per-row chrome) as the
   new house style. These are the next-most-visited tabs.
3. **P2 · GeneralTab token-bind audit** — verify no hex literals; every
   colour/font/spacing reads from `LM.*` token. Likely <1 day.
4. **P3 · Permissions + Storage + Shortcuts polish** — apply house style;
   simplify Permissions verbose layout.
5. **P4 · AboutTab + AccessibilityTab** — low priority cleanup.

## What this audit does NOT cover

- Settings sidebar layout (covered by AgDR-0047 §C10 fix + Q11 marker —
  3-section sidebar is the current state)
- Settings shortcut/keybinding wiring (separate task)
- Settings deep-link routing (separate AgDR)
- Cross-tab state propagation (e.g. theme change reflecting live in canvas)

## Next concrete action

Polish slice P0 (BrainTab parity) is task #25. This audit is its scoping
input. Founder fork picks needed:
- **Lock the signed-brain design language as the house style for ALL
  Settings tabs?** Default = yes (per the existing PROTOTYPE-IS-CONTRACT
  + founder Q3 comment); override = no (each tab gets its own design lane).

That fork goes into the next consolidated signoff page, or executes by
default if no override per FOUNDER-INTENT-CARRIES.

---

This audit lives at `docs/audits/settings-ui-design-audit-2026-05-26.md`.
Generated 2026-05-26 per Q3 founder pick scoping. Slice work tracked as
task #29 (49 UI screens + design audit).
