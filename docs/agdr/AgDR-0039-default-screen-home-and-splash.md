---
id: AgDR-0039
timestamp: 2026-05-22T00:00:00Z
note: renumbered from AgDR-0038 — id collision with PR #35 (handoff/agdr-0038-capability-nodes, a concurrent session). PR #35 keeps 0038; this surface change took 0039.
agent: claude-code (Sonnet)
session: founder demand 2026-05-22 — "the default application opening screen should be the home screen... also rethink the splash screen... show the icon... progress...etc"
trigger: ArchHub booted straight into the most-recent session's canvas, skipping Home. Splash was a bare flash with no brand mark or progress signal.
status: executed
category: ux-surface
projects: [archhub]
extends:
  - CLAUDE.md "What ArchHub is" — Home is the session-launcher surface
---

# Default opening screen is Home; splash is the minimal mark

## Context

Two founder-facing surface complaints, 2026-05-22:

1. **Boot landed inside a session.** `StudioLM` seeded `openId` with
   the most-recent session id, and a one-time `didAutoOpenRef` effect
   jumped past Home into that session's canvas. The founder never
   chose a session — the app decided for him. He wants Home (the
   session list / launcher) every launch.

2. **Splash was a flicker.** The old `#__archhub_splash` showed for
   ~120 ms with no brand mark and no "working" signal — it read as a
   render glitch, not an intentional launch screen.

The founder picked the splash style via AskUserQuestion: **Minimal
mark** — icon only, *no wordmark* ("don't put the name... I hate how
it's written... doesn't represent an Architect at all" — wordmark
redesign tracked separately).

## Options Considered

| Option | Boot screen | Verdict |
|--------|-------------|---------|
| Keep auto-open-last | session canvas | rejected — founder demand |
| Remember last, open Home anyway | Home | adds nothing; Home already lists sessions |
| Home always, `openId=null` | Home | **chosen** — simplest, single source of truth |
| Splash: wordmark lockup | text + mark | rejected — founder hates the wordmark |
| Splash: minimal mark + progress | icon + sweep | **chosen** |

## Decision

**Home default.** `openId` is the single source of truth for the live
session; it now initialises to `null` (= Home). The session-seed and
the `didAutoOpenRef` auto-open effect are removed. A `useEffect`
mirrors `openId` into `window.__archhub_session_id` on every change so
non-React readers (`currentSid`, `saveCurrentGraph`) can never desync
— going Home clears the global too (kills the stale-`revfix`-slug bug).

**Splash = minimal mark.** `#__archhub_splash` renders `archhub.png`
(104 px, soft pulse) + a thin indeterminate sweep line on the bottom
edge. No wordmark. `SplashFader` holds a 350 ms floor so even a
cache-hit boot reads as an intentional splash, then a 320 ms fade.

## Consequences

- Every launch lands on Home; the founder picks the session.
- `window.__archhub_session_id` is `null` on Home — graph saves can't
  target a dead session.
- Splash now carries the brand mark + a live "working" signal.
- `archhub.png` is vendored into `app/web_ui/` (the splash loads
  before the JSX bundle, so it can't reach `app/assets/`).
- ArchHub wordmark redesign ("doesn't represent an Architect") is a
  separate open design item — NOT in this AgDR.

## Acceptance

1. CDP probe after a clean boot: `window.__archhub_session_id` is
   `null`; `#root` text shows the Home screen; zero Workspace tabs.
2. Splash shows the icon + sweep during boot, fades clean.
3. Founder sign-off via AskUserQuestion (splash style) — recorded.

## Verification (CDP, live, 2026-05-22)

```
session_id: null
root_text:  "HOME / NODES / SHARE / SETTINGS ... Sessions / 2 · CLICK TO OPEN ..."
tab_count:  0
splash_present: false   (faded post-boot)
openId_decl: const [openId, setOpenId] = React.useState(null)
has_didAutoOpen: false
```

## Artifacts

- This AgDR.
- `app/web_ui/studio-lm.jsx` — `openId`/`openTabs` init to
  `null`/`[]`; auto-open effect removed; `openId`→global mirror.
- `app/web_ui/index.html` — minimal-mark splash markup + CSS.
- `app/web_ui/app-boot.jsx` — `SplashFader` 350 ms floor.
- `app/web_ui/archhub.png` — vendored splash icon.
- `scripts/cdp_probe_home.py` — the live verification probe.
