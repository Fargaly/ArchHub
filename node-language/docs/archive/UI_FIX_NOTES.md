# UI fix notes — v1.2 BRAND v0.1 drift pass

Date: 2026-05-13. Author: design audit pass. Scope: surgical fixes to
the parts of the PyQt6 desktop UI that drifted from `app/design_tokens.py`.

These are the visible changes you'll notice the next time ArchHub
starts. Nothing functional moved — every change is cosmetic or
voice-only. Test suite: 543/543 passing before and after.

## Header (chat window)

- The cog button at the top right is now a **text button labelled
  "Menu"** instead of a "⚙" gear glyph. Width grew from 40 px to 64 px
  to fit the label. The bordered ghost-button style is unchanged.
- The dropdown that opens from that button is **emoji-free**. Every
  row used to start with a different glyph (🔑 🔌 ✦ 📂 ⇣ ↻ ◆ ⚡ ⓘ ⏻);
  rows now read as plain labels: "Sign-ins…", "Connectors…",
  "Skills…", "Sessions…", "Save chat as Skill…", "Plans & pricing…",
  "Reality Check", "About ArchHub", "Quit". The Updates row still
  carries the typographic "↻" because it's not an emoji.
- **Host pills** (Revit / AutoCAD / 3ds Max / Blender / Outlook) now
  use the active palette's `ok` / `warn` / `inkDim` for the leading dot
  and `ink` / `inkSoft` / `inkDim` for the label, instead of the
  hardcoded "#5fb87a" / "#b09060" / "#666" / "#e8e6dc" / "#a4a098".
  In light mode the live-green is olivey rather than spring-green,
  and the idle-amber pulls toward the brand ochre. In dark mode the
  green is a touch lighter so it doesn't disappear against the
  graphite background.

## Update banner

- The download-ready banner used to be a hand-tuned coffee-brown
  (`#2a2018` background, `#f0d49a` text, `#4a3a28` border). It is now
  built from design tokens: `accentSoft` background, `ink` text, `line`
  border, `accent` icon. In light mode this turns the banner into a
  warm clay-tinted strip that matches the rest of the chrome; in dark
  mode it stays subtle.

## Skill stepper card (inline in chat)

- The `○ ◐ ✓ ✗ ·` markers in front of each skill step used to render
  as `#cc785c` on `#8a8580`. They now pull from the live palette
  (`accent` for the icon, `inkMuted` for the trailing status). Same
  effect as the host pills — the colours track theme.

## Tool card status row

- The error preview text on a failed tool card now reads from
  `COLOR.err` (`#b8493e` light / `#e6705f` dark) instead of the
  hardcoded "#d97757". Failures look red, not coral.

## Status row (pulsing dot + italic text)

- The single fading dot during "Thinking…" pulled from a hardcoded
  `#c96442`. It now reads `accent` from the active palette, so it
  pulses at `#d97757` in dark mode (the brand's tuned dark accent).
- The italic status text beside it ("Thinking…", "Calling outlook…")
  now reads `inkMuted` from the palette instead of `#9a9183`.

## Reasoning toggle / view

- The "Reasoning" disclosure toggle's color + the body text and left
  rule of the reasoning blockquote now read from `inkMuted` / `inkSoft`
  / `line` tokens. Dark mode used to render these in dim brown on
  near-black; they're now graphite-on-graphite, which matches the
  brand's "calm density" principle.

## Settings dialog (Sign-ins, AI Behaviour, Privacy, Procore,
Cloud sync)

- Provider rows used to lead with a 🔒 emoji, swapped to ✓ when a key
  was present. Both are gone. Rows now lead with a typographic bullet
  ("·" pre-signin, "●" signed-in) inside the bordered terra
  `providerIcon` plate. Calmer, fixed row height.
- The "AI Behaviour", "Privacy & crash reports", "Cloud sync —
  Skills, Sessions", and "Procore" section icons (🧠 🛡 ☁ 🏗) are now
  two-letter typographic plates: "AI", "Pr", "CS", "Pc".
- The "👁" eye buttons next to the Speckle PAT and Procore PAT input
  fields are now text labels reading "Show" (width 56 px).
- The "Set up local Speckle for me" primary button no longer has the
  ⚡ lightning prefix. The "Open developers.procore.com" button no
  longer has the 🌐 globe prefix.
- The Cloud-sync help text used to lead pull/push gap lines with a
  ⚠ warning glyph. The lines now read plainly: "3 updates on the
  remote haven't been pulled yet."

## Onboarding dialog

- The two "All set!" sentences ("All set! You're signed in to ArchHub
  Cloud." / "All set! Your AI brain is ready.") now read:
  - "Signed in to ArchHub Cloud."
  - "Your AI brain is ready."
  BRAND.voice rule 2: "No exclamation points."

## In-chat assistant messages

- The skill-match prompt no longer begins with "💡". The clipboard
  copy confirmation no longer begins with "📋". The "Saved as
  Skill…" / "Imported Skill…" confirmations dropped their leading
  "✓". The success/failure summaries "✓ Skill complete." / "✗ Skill
  failed." now read "Skill complete." / "Skill failed.". Same for
  Workflows.
- Host-warning messages no longer begin with "⚠️". The pattern was
  "⚠️ This looks like a Revit action…" — now "Heads up — this looks
  like a Revit action…" or just the bare warning sentence. The
  `_add_assistant_note` markdown rendering already gives these notes
  visual weight via bubble chrome, so the leading emoji was redundant.
- Tool execution failures: "Error — {error}" replaces "⚠️ {error}"
  in the streaming assistant bubble.

## What is intentionally unchanged

1. `app/theme.qss` still uses 300+ hardcoded hex values. The Studio
   shell + Add Host + Onboarding + Settings rebuild their own QSS at
   runtime via tokens, so the visual surface is correct in both modes.
   theme.qss only governs the legacy "chat-window-only" mode (no
   Studio shell wrap) and its values are a 1:1 match for `COLOR`
   (light). Regenerating theme.qss from tokens is in the Phase 2 list.
2. The "Architecture: Drafting table for AI" italic-serif headings
   are unchanged.
3. The Studio shell rail, inspector, status rule, Add Host page,
   Parameters panel, Connector panel, Marketplace panel, Skills panel
   are unchanged — they were already token-driven and on spec.
4. The `_StatusDot` pulse animation timing (1.2s, InOutSine, single
   dot) is unchanged.

## How to undo if any of this looks wrong

Every change is in one of three files:

- `app/chat_window.py` (header, banner, host pills, assistant notes,
  status row, reasoning view, stepper card, tool card)
- `app/settings_dialog.py` (provider icons, AI Behaviour / Privacy /
  Cloud / Procore section icons, eye buttons, Speckle/Procore primary
  buttons, sync warning text)
- `app/onboarding_dialog.py` (two "All set!" strings)

`git diff` will show the full delta. The audit notes are in
`docs/UI_AUDIT_v1.2.md` with severity ratings and Phase 2 backlog.
