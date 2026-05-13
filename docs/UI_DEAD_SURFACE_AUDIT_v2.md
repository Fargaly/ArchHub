# ArchHub UI Dead-Surface Audit — v2 (round 2, brutal pass)

Audit date: 2026-05-13. Scope: every visible PyQt surface, ranked by
user-visibility (top-of-screen first, status-bar last). Builds on
`docs/UI_DEAD_SURFACE_AUDIT.md` (round 1 — 10 cuts) and
`docs/UI_AUDIT_v1.2.md` (BRAND voice / palette drift).

Round 1 was "gentle". Founder feedback after round 1: "the ui still
shitty as fuck with stagnant things with no use… i don't want things
for show only". Round 2 enforces a single rule:

> A surface earns its pixels only if it (a) drives a click in the next
> 60 seconds, or (b) shows a number the user reads BEFORE acting.
> Everything else is CUT or HIDDEN behind a disclosure.

Classification legend (extended)
- USED        — has a live handler the user reaches within 60s
- REDUNDANT   — does the same thing as another visible surface
- DECORATION  — visible but doesn't drive action / doesn't show a live number
- DEAD        — entry point exists, handler is no-op / TODO / not wired
- NO-OP       — button or menu item whose handler does nothing material (new)
- PHASE-2     — useful but premature (e.g. catalog UI when 0 packs)

## 1. Chat window header — `chat_window._build_header()` (chat_window.py:1418-1500)

Severity: top-of-screen, every session. Round 2 trims width by ~40px.

| Surface | Round 1 verdict | Round 2 verdict | Action |
|---|---|---|---|
| `QLabel("ArchHub™")` wordmark | DECORATION (keep) | DECORATION | **CUT to 'A' monogram** in 24×24 plate. The OS title bar + taskbar already say ArchHub. Saves ~60px of header chrome. Revival: `QLabel("ArchHub™")` |
| Host pills row | USED | USED | Keep. Already only renders pills whose status≠missing. |
| Model picker labels (KNOWN_MODELS) | USED | DECORATION-in-label | **Trim labels**. "Claude Opus 4.7 — best reasoning" → "Claude Opus 4.7"; "OpenRouter · Claude Sonnet 4" → "Claude Sonnet 4 (OR)". Tooltips still carry context. (`app/llm_router.py:389-405`) |
| `+ Add Host` button | USED | USED | Keep. Primary CTA. |
| `Menu` button | USED | USED | Keep. |

Header now fits comfortably inside a 600px slice of a 1280-wide window.

## 2. Chat cog menu — `chat_window._build_app_menu()` (chat_window.py:1670-1720)

| Item | Round 1 | Round 2 | Action |
|---|---|---|---|
| Sign-ins… | USED | USED | Keep. |
| Connectors… | USED | **REDUNDANT** | **CUT**. Rail HOSTS section toggles every connector inline; Add Host button is the discovery surface. Revival: re-add `addAction("Connectors…")` with `_open_connectors`. |
| Skills… | USED | USED | Keep. |
| Sessions… | USED | USED | Keep. |
| Save chat as Skill… | USED | USED | Keep. |
| Updates row | USED | USED | Keep — pulses on a new release. |
| Plans & pricing… | USED | **REDUNDANT** | **CUT**. The rail's Pricing page (More disclosure) is the single source. Revival: re-add `addAction("Plans & pricing…")`. |
| About ArchHub | USED | USED | Keep — surfaces commit/version. |
| Quit | USED | USED | Keep. |

Net menu: 7 rows (was 10 after round 1's Reality-Check cut, was 11 originally).

## 3. Chat window welcome card — `chat_window._show_welcome()` (chat_window.py:1764)

Severity: first thing user sees on launch.

| Surface | Round 1 | Round 2 | Action |
|---|---|---|---|
| "What do you want to build?" h1 | USED | DECORATION | **CUT**. The input bar placeholder ("Message ArchHub…") already says it. Revival: `QLabel("What do you want to build?")` |
| Subtitle "Type what you want; ArchHub drives the tools…" | USED | DECORATION | **CUT**. Same reasoning — input placeholder + onboarding cover this. Revival: restore the subtitle QLabel. |
| Quick-start skill chips | USED | USED | Keep IFF user has saved skills. When library empty: render nothing. |

Net: the welcome card is now invisible until the user has at least one saved skill. Empty conversation area IS the welcome state.

## 4. Chat window status bar — `chat_window._build_status_bar()` (chat_window.py:1881)

Severity: bottom-of-screen footer chrome.

| Surface | Round 1 | Round 2 | Action |
|---|---|---|---|
| `status_left` label | REDUNDANT-when-empty | DECORATION (when blank, ~24px wasted) | **Make zero-height when blank**. Wrapped in `_AutoHideLabel` so `setText("")` hides the whole bar. Bar reappears only when a transient routing-note / skill-match / send-warning sets text. |
| `status_right` label | actionable nudge | actionable nudge | Keep behaviour. When no LLM, shows "Add API keys in Settings to start chatting"; rest of the time it's blank ⇒ bar hidden. |

To revive default visibility: drop the `bar.setVisible(False)` line.

## 5. Studio rail nav — `studio_shell.NAV_ITEMS` (studio_shell.py:82)

Severity: left-rail, every session.

| Item | Round 1 | Round 2 | Action |
|---|---|---|---|
| Home | USED | USED | Primary (kept). |
| Chat | USED | USED | Primary (kept). |
| Skills | USED | USED | Primary (kept). |
| Settings | USED | USED | Primary (kept). |
| Workflows | PHASE-2 (already hidden by round 1's prior pass — wait, no, still in NAV_ITEMS) | PHASE-2 | **DEMOTE to More**. 0 workflows for most users. |
| Marketplace | PHASE-2 | PHASE-2 | **DEMOTE to More**. 0 packs installed for most users. |
| Telemetry | USED | PHASE-2 | **DEMOTE to More**. Users open Telemetry only when something's broken; rail dot already signals health. |
| Pricing | USED | DECORATION | **DEMOTE to More**. Conversion surface used once. |

Net rail: 4 primary items always visible + a "More" disclosure that holds the 4 demoted ones. Keyboard shortcuts (Ctrl+1..7) still cover every page so power users don't need the disclosure. ⌘K palette enumerates all pages via `NAV_ITEMS_ALL`. Revival: copy NAV_ITEMS_MORE entries back into NAV_ITEMS.

## 6. Studio rail other surfaces

| Surface | Round 2 | Action |
|---|---|---|
| Brand + theme toggle | USED | Keep |
| ⌘K command box | USED | Keep — first-class palette access |
| HOSTS section | USED | Keep — live state per family, click-to-toggle |
| `+ Add host…` inline row | USED | Keep |
| THREADS section | USED | Keep |
| User card + cog | USED | Keep |

## 7. Studio right inspector — `studio_shell._build_inspector()` (studio_shell.py:710)

Severity: right column 304px wide, 60-80% of the time empty.

| Surface | Round 1 | Round 2 | Action |
|---|---|---|---|
| LLM ROUTER 4-row list | USED | USED (on Home/Chat) | Keep when expanded. |
| SELECTION / PARAMETERS KVs | USED | USED (on Chat) | Keep. |
| QUICK ACTIONS chevron list | USED | USED (on Chat/Home) | Keep. |
| **Whole panel on non-Home/Chat pages** | USED | DECORATION | **Collapse to 8px click strip** on Marketplace / Skills / Settings / Pricing / Telemetry. Click strip to expand. Revival: drop the `_set_inspector_collapsed` call in `_set_page`. |

## 8. Studio bottom status rule — `studio_shell._build_status_rule()` (studio_shell.py:1067)

| Item | Round 1 | Round 2 | Action |
|---|---|---|---|
| `● N/M hosts` | USED | USED | Keep — live count. |
| `tokens —` (always "—") | DECORATION | DECORATION (still hidden by round 1) | Keep hidden. |
| `spend $0.00` | USED | USED | Keep — real number. |
| Cloud usage meter | USED (conditional) | USED | Keep. |
| Healing dot | USED (conditional) | USED | Keep. |
| **Right shortcuts trio** `⌘K palette · ⌘↩ run skill · ⌘/ docs` | DECORATION (kept by round 1) | DECORATION | **CUT**. Power users learn shortcuts on day 1; day-1 users discover via the menu. Keep only `v{ver}`. Revival: paste back the trio into the right QLabel. |

## 9. Settings dialog — `app/settings_dialog.py`

Severity: opened once per setup, then weekly.

| Section | Round 1 | Round 2 | Action |
|---|---|---|---|
| Sign-ins (4 provider rows) | USED | USED | Visible always — primary CTAs. |
| Show local Ollama models | USED | USED | Visible always. |
| AI Behaviour (thinking + per-tool policies) | USED | USED | Visible always — power knobs the user adjusts. |
| Cloud sync row | USED | DECORATION-for-most | **Collapse behind "Show advanced"** master toggle. |
| Firm relay (path B) | PHASE-2 (already in round 1's `_show_relay` toggle) | PHASE-2 | Roll into the master "Show advanced". Per-section toggle removed (now nested). |
| Speckle (toggle + token + radios) | USED | PHASE-2 (most users never use) | Roll into "Show advanced". |
| Procore (token + ids) | USED | PHASE-2 | Roll into "Show advanced". |
| Appearance — HUD overlay + hotkey | PHASE-2 (already partially) | PHASE-2 | Roll into "Show advanced". |
| Privacy & crash reports (telemetry + PostHog + Sentry + Discord) | USED | PHASE-2 (off by default, configured by ~5% of users) | Roll into "Show advanced". |

Net dialog height: 720 → 560 default. The advanced wrap auto-expands when the user already has any of the wrapped surfaces configured (cloud signed in, Speckle on, Procore token set, etc.) so nobody loses their kit behind a closed door.

Revival: drop the `_adv_wrap.setVisible(False)` line and inline-add each section back outside the `_adv_wrap`.

## 10. First-run onboarding wizard — `app/onboarding.py`

Round 1: not audited. Round 2 verdict: 3-step Continue/Next layout was Continue-button chrome that wasted day-1 time.

| Surface | Round 2 | Action |
|---|---|---|
| 3-page QStackedWidget (Sign-in → Connectors → Skill) | DECORATION (the Continue button) | **CUT step-stack**. Collapse all 3 sections into ONE scrollable column with the three real CTAs. |
| 3-dot indicator `● ○ ○` | DECORATION | **CUT**. No multi-step nav left to indicate. |
| `Continue →` button | NO-OP (chrome between identical screens) | **CUT**. Single Finish button. |

Revival: restore the QStackedWidget in `OnboardingWizard.__init__`.

## 11. Onboarding dialog (technophobe) — `app/onboarding_dialog.py`

Single screen, two real CTAs (Set up Ollama / Try Cloud) + two ghost footer buttons. Already optimal — no cut.

## 12. Parameters panel — `app/parameters_panel.py`

Round 1: USED, auto-hides when empty. Round 2 verified: `_sync_empty` correctly toggles `scroll` and `empty` visibility based on `_rows` count. No regression. Keep as-is.

## 13. Connector panel modal — `app/connector_panel.py`

| Surface | Round 1 | Round 2 | Action |
|---|---|---|---|
| Modal QDialog | USED | REDUNDANT (StudioShell active) | The rail HOSTS section + per-row toggle covers 100% of what the modal does. Keep dialog FILE on disk (used by `app/onboarding.py` step 2 → "Open connector settings", and as the chat-only fallback when StudioShell fails to build). But remove the cog-menu "Connectors…" entry that pointed at it. |

## 14. Feedback widget — `app/feedback_widget.py`

| Surface | Round 1 | Round 2 | Action |
|---|---|---|---|
| Per-bubble "Helpful? yes / no" | USED | DECORATION-when-quiet | Already gated by `MessageBubble.enterEvent` / `leaveEvent` — invisible until hover. No cut needed. |

## 15. Marketplace panel — `app/marketplace_panel.py`

| Surface | Round 1 | Round 2 | Action |
|---|---|---|---|
| Card grid | PHASE-2 | PHASE-2 | Keep — install works. |
| Empty-state copy "No catalog matches your filter." | DECORATION (generic) | DECORATION | **REPLACE** with actionable copy: "Click ↻ Sync to pull the latest catalog." / "Switch to Skills tab — the catalog has 3.". No more grey-grid stub. |

## 16. Reality Check panel — `app/reality_check_panel.py`

Round 1 cut the modal cog-menu entry (REDUNDANT vs the Telemetry-page embed). The embed in Telemetry stays — no further cut. Telemetry page itself is now under the "More" disclosure (not visible by default), which feels right: users only need Reality Check when troubleshooting.

## 17. Skills panel — `app/skills_panel.py`

USED, no cuts.

## 18. Studio shell home composer chips — `studio_shell._build_home()` (~line 425)

All four chips (Sketch / Voice / Skill / Host) USED, no cuts. The `✦` `●` `@` `+` glyphs are typographic (NOT emoji per BRAND.voice).

## 19. Studio status rule `_sr_tokens`

Hidden in round 1 (no live data). Confirmed still hidden in round 2.

## 20. Studio rail brand sub-caption `STUDIO · N LIVE`

USED (real live-host count). Keep.

---

## Distribution

Total surfaces audited: 78 (extends round 1's 56 — covers onboarding wizard, model picker labels, status rule shortcut hint, settings sub-rows, marketplace empty states, inspector page-aware visibility).

- USED        : 47
- REDUNDANT   : 6
- DECORATION  : 14
- DEAD        : 0 (round 1 cleared the dead set)
- NO-OP       : 1 (Continue button between identical onboarding screens)
- PHASE-2     : 10

## Top 15 cuts shipped this round

1. `chat_window.py:1425-1444` — brand wordmark "ArchHub™" → 24×24 'A' monogram plate.
2. `llm_router.py:389-405` — KNOWN_MODELS labels trimmed (drop marketing tails + OpenRouter prefix).
3. `chat_window.py:1764-1809` — welcome card title + subtitle removed; chip row alone, hidden when no saved skills.
4. `chat_window.py:1881-1920` — status bar auto-hides when both labels blank (`_AutoHideLabel`).
5. `chat_window.py:1680-1685` — "Connectors…" cog-menu item cut (rail covers).
6. `chat_window.py:1700-1705` — "Plans & pricing…" cog-menu item cut (rail Pricing covers).
7. `studio_shell.py:82-100` — NAV_ITEMS split: 4 primary, 4 behind "More" disclosure.
8. `studio_shell.py:307-345` — rail "More" toggle wired + secondary nav rendered.
9. `studio_shell.py:710-806` — right inspector collapses to 8px strip on non-Home/Chat pages (click strip to re-expand).
10. `studio_shell.py:1071-1093` — bottom status rule shortcut-hint trio cut (only `v{ver}` remains).
11. `settings_dialog.py:120-155` — Cloud sync moved INSIDE a new master "Show advanced" wrap.
12. `settings_dialog.py:158-210` — Firm relay's own disclosure dropped; rolled into master "Show advanced".
13. `settings_dialog.py:218-318` — Speckle section nested in `adv` layout (was directly on `outer`).
14. `settings_dialog.py:320-390` — Procore + Appearance/HUD + Privacy sections nested in `adv`.
15. `onboarding.py:50-110` — OnboardingWizard collapsed from 3-step stack into ONE scrollable column; Continue button + 3-dot indicator deleted; single Finish/Skip footer.

Plus: `marketplace_panel.py:483-510` — empty-state copy replaced with actionable text.

## Disclosures added (5)

1. **Studio rail "More"** — collapses Workflows / Marketplace / Telemetry / Pricing.
2. **Studio right inspector** — collapses to 8px click strip on Marketplace / Skills / Settings / Pricing / Telemetry.
3. **Settings master "Show advanced"** — wraps Cloud sync · Speckle · Procore · Appearance/HUD · Privacy · Firm relay in one toggle.
4. **Chat window status bar** — auto-hides when both labels are blank.
5. **Chat welcome card** — renders only when saved skills exist (no decoration when library empty).

## What I held back

The model picker QComboBox still surfaces 16 rows including provider variants the user might never click. Could trim to top 4 + a "More models…" disclosure, but that's a bigger UX bet — keyboard users routinely search via type-to-complete. Decided that label-trimming (cut 2) was the right scope for round 2.

`AI Behaviour` is still visible in Settings — could be argued as another power-knob to hide. Kept it because per-tool Allow/Ask/Deny is a genuinely-clicked surface for users with sensitive hosts (Outlook send, file delete, etc.). It's a 60s-action surface, not decoration.

The Studio bottom status rule still has `● N/M hosts` + `spend $0.00` + (conditional) cloud meter + healing dot. The `spend $0.00` shows zero almost always — borderline DECORATION. Kept because it's truthful and the moment the user signs in to Cloud it flips to a live number.

---

## How to revive any deleted surface

Every cut above has a "Revival: …" line in its table cell. All deleted Python is one paste of the original code into the file at the original site (no schema changes). Run `git log -- app/<file>` to find the original block.

## Phase-2 surfaces deferred

1. **Workflows top-level rail** — promote back into NAV_ITEMS once >50% of users have a saved workflow.
2. **Marketplace top-level rail** — promote back once remote-manifest fetch is live + >0 packs ship by default.
3. **Pricing top-level rail** — promote back if conversion funnel measurement shows users get lost in the More disclosure.
4. **Inspector on settings/telemetry/marketplace** — re-expand by default if telemetry shows users repeatedly click the 8px strip to expand.
5. **Status bar persistent visibility** — re-make always-visible if we add a persistent live signal (e.g. live token count, live session step counter).
