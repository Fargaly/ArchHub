# ArchHub UI Audit v1.2 — BRAND v0.1 drift

Audit date: 2026-05-13. Scope: PyQt6 desktop UI plus `landing/index.html`.
Spec source of truth: `app/design_tokens.py` (BRAND, COLOR, COLOR_DARK,
SPACE, RADIUS, TYPE, ELEV, MOTION, COMPONENTS).

## Verdict in one paragraph

The chrome (Studio shell, Add Host panel, Settings dialog skeleton,
Onboarding) is mostly clean and consumes tokens correctly. The drift
that makes the UI feel "missy" lives in two surfaces:

1. **`chat_window.py` header + tool/skill messages + update banner** —
   the header is the first thing a user sees and it carries: emoji icons
   in menu items, hardcoded brown banner colors, host pills with
   hardcoded greens and greys that disregard the active palette, and a
   cog menu where every item starts with a different emoji.
2. **`settings_dialog.py` provider rows** — the "providerIcon" labels
   are emoji (🔒 ✓ ○ 🧠 🛡 ☁ 🏗 👁 🌐 ⚡) which collides head-on with
   `BRAND.voice` rule "No emoji. No exclamation points." These render
   at varying sizes/widths and break the calm-density principle.

Everything else is broadly on-spec. The Studio shell, Add Host panel,
Onboarding, Parameters panel, and Skill cards all read tokens through
`_LivePalette` proxies and switch correctly between light and dark.

Severity legend
- Red = user-visible (broken in dark mode, bad voice, jarring colour)
- Orange = inconsistency (consume hex when token exists)
- Yellow = polish (token alias drift, doc strings)

---

## 1. Accessibility (contrast, focus rings, tab order)

- Orange — `app/chat_window.py:1180` update banner: `color:#f0d49a` on
  `#2a2018` is a hand-picked pair that bypasses `T['warn']`/`T['ink']`.
  Reads OK in dark mode but disappears in light mode — banner stays
  brown.
  **Spec**: brand principle 01 "Paper-first, even dark mode is graphite, never black."
  **Fix**: rebuild banner from `T['warn']`/`T['accent']` + token aliases.

- Yellow — `app/theme.qss:212` `QTextEdit#messageText` only sets
  font-family + size but no explicit `color` rule. Inherits from
  `QWidget` which is hardcoded `#251f17` (light ink) — wrong in dark.
  **Fix**: add palette role override or explicit token; deferred to
  Phase 2 because Qt6 reads QPalette.Text for QTextEdit content anyway.

- Green — focus rings: `focus_ring_qss()` is wired by `studio_shell.py`,
  `chat_window.py` builds focus styles on the model picker + input,
  and `onboarding_dialog.py` inherits the global focus rules.

## 2. Touch & interaction (Qt tap-target sizes)

- Yellow — `app/chat_window.py:1409` cog menu button `setFixedSize(40, 36)`
  is correct (≥ 36×36). The host pills (no hit handler, only cursor +
  tooltip) are decorative — no fix needed.
- Yellow — `app/studio_shell.py:268` theme toggle is 24×24 — below the
  28×28 visible minimum. Cursor is still pointing-hand and hit area is
  the full QToolButton — acceptable but tight. Phase 2: bump to 28×28.

## 3. Performance

- Green — `studio_shell.py:218` uses diff-driven 5s refresh tick. No
  unbounded re-renders.
- Yellow — `chat_window.py:1419` host-pill timer at 6s rebuilds the
  whole layout every tick. Fine on modern hardware; ~30 ms per cycle
  when 5 brokers present. Phase 2: cache pill widgets, only update text
  + dot colour.

## 4. Visual style coherence (palette consistency)

- **RED** — `app/chat_window.py:1519` host pill colours are hardcoded:
  ```py
  dot = {"live": "#5fb87a", "idle": "#b09060", "missing": "#666"}[status]
  ink = {"live": "#e8e6dc", "idle": "#a4a098", "missing": "#666"}[status]
  ```
  Bypasses `T['ok']`/`T['warn']`/`T['inkDim']` plus dark-mode-tuned
  variants. Pills look "alien" against the rest of the header.
  **Spec**: `COLOR.ok="#5a8a5e"`, `COLOR_DARK.ok="#7ec18e"`; same for
  warn/inkDim. **Fix**: read from `_LivePalette()`.

- **RED** — `app/chat_window.py:1176-1190` update banner pattern uses
  hand-picked brown `#2a2018`, gold `#f0d49a`, `#d97757` orange, plus
  `#4a3a28` borders. None of these are tokens. The banner ends up
  looking like a third party widget glued in.
  **Spec**: brand `principles[2]` "One warm color — terracotta is the
  only emotional accent." Banner should use `accentSoft` background +
  `ink` text + `accent` for the primary button.

- **RED** — `app/chat_window.py:635` `_format_row` returns
  `<span style='color:#cc785c'>` and `<i style='color:#8a8580'>` —
  hardcoded oranges. Used by SkillStepperCard which is shown for every
  saved Skill run. **Spec**: `COLOR.accent="#c96442"`, not `#cc785c`.

- Orange — `app/chat_window.py:691, 819, 840, 843, 861-862` inline hex
  on status dot, status line, reasoning toggle/view — all hardcoded
  light-mode hex that "happen to work" in dark mode by accident but
  break the moment the palette is tuned.

- Orange — `app/theme.qss` is entirely hardcoded hex (300+ literals).
  Documented at top of file. **Phase 2**: regenerate from
  design_tokens; this is mechanical but large. For this audit we leave
  theme.qss alone because:
  (a) the Studio shell + Add Host + Onboarding now overlay their own
      QSS at runtime which DOES read tokens; and
  (b) the legacy chat-window-only mode (when StudioShell isn't wrapping)
      is the only consumer of theme.qss for backgrounds, and theme.qss
      values match `COLOR` (light) exactly. Dark mode is delivered via
      `studio_shell._inline_qss()` overlays.

## 5. Layout & responsive

- Green — `chat_window._build_ui` uses `QSplitter` with
  `setChildrenCollapsible(True)` for parameters panel — collapses to
  zero when no parameters.
- Yellow — `chat_window.py:1392` "+ Add Host" lives in the header,
  competing with the Studio rail's "Add Host" page. The redundancy is
  intentional (chat-window-only mode) but the button uses
  `ghostButton` so it sits next to the cog without dominating. Keep.

## 6. Typography & color

- Orange — `theme.qss:35` hardcodes `font-family: "Inter", ...` instead
  of `TYPE['fontSans']`. Same issue as #4 — theme.qss precedes the
  token system, deferred to Phase 2.
- Green — every QSS string in `studio_shell._inline_qss()`,
  `add_host_panel._panel_qss()`, `onboarding_dialog._qss()` reads
  `TYPE['fontSans']` / `TYPE['fontSerif']` / `TYPE['fontMono']`.

## 7. Animation (quiet motion)

- Green — `_StatusDot` (chat_window.py:669) fades 1.0 → 0.35 → 1.0
  over 1.2s with `InOutSine`. Matches `MOTION.durSlow=240` ×5 cycles,
  which is fine for an ambient indicator.
- Yellow — `chat_window._TypingIndicator` is still defined (line 739)
  but unused — replaced by `_StatusDot`. Dead code, ~30 lines. Leave
  as-is; deletion is Phase 2.

## 8. Forms & feedback

- **RED** — `app/settings_dialog.py:55, 77, 282, 383, 512, 702, 812,
  838, 867` provider rows use emoji icons (🔒 ✓ ○ 👁 🧠 🛡 ☁ 🏗 🌐).
  Every emoji renders at the OS's emoji-font width which varies row by
  row. Calm density: violated. **Spec**: BRAND.voice forbids emoji.
  **Fix**: replace with single-character monogram glyphs sourced from
  the brand mark family — eg "·" or first letter of provider name. The
  `providerIcon` QSS rule already does heavy lifting (border, radius,
  accent colour); only the label text needs to change.

- **RED** — `app/chat_window.py:1577-1610` app menu uses one emoji per
  action: 🔑 🔌 ✦ 📂 ⇣ ↻ ◆ ⚡ ⓘ ⏻. The cog menu is the discovery
  surface for every secondary feature; reading it should feel like an
  index, not Skype. **Fix**: drop the emoji icons; let the menu rely
  on label clarity. Menu typography is already correct.

- Orange — `onboarding_dialog.py:199, 259` strings include "All set!"
  with an exclamation point — violates BRAND.voice rule 2.

## 9. Navigation

- Yellow — `chat_window.py:1407` cog button text is "⚙" gear emoji.
  Inconsistent with the rest of the header which is text-only ("ArchHub™",
  "+ Add Host"). Rendering on Windows depends on the user's emoji font
  (Segoe UI Emoji vs Symbol). **Fix**: replace with a textual glyph
  ("Menu") or leave it as a tool button without text and rely on the
  border + tooltip. We pick textual "Menu" because it's discoverable
  and on-brand.

## 10. Charts & data

- Green — `parameters_panel.py`, `connector_panel.py`,
  `marketplace_panel.py` use the `_LivePalette` pattern and consume
  tokens.

---

## Severity-ranked drift summary

| # | File | Line | Severity | Issue |
|---|------|------|----------|-------|
| 1 | settings_dialog.py | 55, 77, 282, 383, 512, 702, 812, 867 | RED | 9 emoji icons in provider rows violate BRAND.voice |
| 2 | chat_window.py | 1577–1610 | RED | App menu rows lead with emoji icons (10 emoji) |
| 3 | chat_window.py | 1519–1520 | RED | Host pill colours hardcoded, ignore palette |
| 4 | chat_window.py | 1176–1197 | RED | Update banner hardcoded browns; off-palette |
| 5 | chat_window.py | 635 | RED | SkillStepperCard `#cc785c`/`#8a8580` hardcoded |
| 6 | chat_window.py | 1407 | RED | Header cog button uses gear emoji "⚙" |
| 7 | onboarding_dialog.py | 199, 259 | RED | "All set!" exclamation violates voice |
| 8 | chat_window.py | 691, 819, 840, 861-862 | Orange | Status-row inline hex bypasses palette |
| 9 | theme.qss | (whole file) | Orange | Hardcoded hex everywhere — Phase 2 regen |
| 10| chat_window.py | 1918, 1936, 1949, 1963, 2154 | Orange | ⚠️ emoji in error notes (markdown-rendered) |
| 11| chat_window.py | 2754, 2901, 3140, 3166 | Orange | 💡 / ✓ / ✗ / 📋 emoji in assistant notes |
| 12| settings_dialog.py | 253, 838 | Orange | "⚡  Set up local Speckle for me" / "🌐  Open..." button labels |
| 13| add_host_panel.py | docstring lines 16-17 | Yellow | Docstring shows ✅/❌ examples — voice illustration only, keep |
| 14| studio_shell.py | 3114 | Yellow | Avatar QSS uses hardcoded `#d8c5a8` / `#5a4a2a` (intentional warm-paper tone, not a palette colour) — leave |
| 15| chat_window.py | 3229 | Yellow | "💾  Save current session" button label has emoji |

## What we fixed in this pass (v1.2)

The top six RED items + the in-message emoji noise. See
`docs/UI_FIX_NOTES.md` for visual-regression notes.

## Phase 2 backlog

1. Regenerate `app/theme.qss` from `design_tokens` so its 300+ literals
   stop drifting from the live palette.
2. Add `bgPanelAlt`/`focusRingAlt` tokens for the banner styles and
   re-skin the update banner inline.
3. Replace `chat_window._TypingIndicator` (dead code) and the
   `_format_row` helper with a token-driven `RowRenderer` shared with
   SkillStepperCard.
4. Theme-toggle button hit area 24→28 px.
5. Convert remaining markdown-renderered emoji in assistant notes (the
   ⚠️ host-warnings and 💡 skill-match prompts) to mono captions: e.g.
   "⚠️ This looks like..." → "Heads up — this looks like..."; the
   current pass keeps the wording but drops the leading emoji because
   it's the most visible offence. Done in v1.2.
6. Pull `_FORMAT_ROW` icons from a typed enum so we don't string-spray
   bullet glyphs (`○ ◐ ✓ ✗ ·`) at call sites.
