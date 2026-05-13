# Changelog

All notable changes to ArchHub.
Format roughly follows [Keep a Changelog](https://keepachangelog.com/).

## [1.0.2] — 2026-05-13

The "alive again" hotfix release. Production Sentry alerts after
v1.0.1 revealed dead code paths, missing imports, and a handful of UX
gaps that made the app feel stagnant even when it was working. v1.0.2
ships the diagnosis + every fix in one shot.

### Fixed

- **Settings → Cloud Sync no longer crashes** — `_on_sync_now` raised
  `NameError: name 'QApplication' is not defined` (Sentry PYTHON-9).
  Added the missing import.
- **Transient network blips no longer kill a turn** — `llm_router`
  retries once on `APIConnectionError`, `httpx.ReadError`,
  `WinError 10054`, anthropic 529 / cloudflare 502-504 (Sentry
  PYTHON-7). Auth/quota errors still switch provider as before.

### Added

- **Per-host AI Behaviour defaults** — `ai_behaviour._FAMILY_DEFAULTS`
  maps each host family (revit / acad / max / outlook / blender / speckle
  / archhub) to its own policy table. New connectors slotted into
  `_FAMILY_DEFAULTS` get sensible defaults without touching the UI
  or the generic rules.
- **AI Behaviour panel in the legacy Settings dialog** — the section
  previously lived only in the Studio shell; users opening the gear
  from the chat window saw an empty old dialog. Settings now renders
  the dynamic per-host tool list (grouped by family, scroll-area
  capped at 260 px) plus the thinking-effort dropdown in both
  surfaces.
- **`+ Add Host` button in the chat header** — first-class entry
  point instead of being buried in the Studio sidebar / app menu.
  Routes to the Studio page when present, falls back to a modal
  `AddHostPanel` so the chat-only fallback path also gets it.
- **Live host status pills next to the brand** — one pill per
  detected host family (●green = broker reports a live session,
  ●amber = installed but no session, hidden = not detected). Probed
  every 6 s; never blocks the UI.
- **Startup self-test** — `_startup_self_test()` writes a one-block
  summary to `boot.log` on every launch: broker session counts, host
  installation paths, .NET SDK version, tool-registry breakdown by
  family. Diagnosing "nothing works" becomes a one-file lookup.
- **21 new tests** — coverage for `_FAMILY_DEFAULTS`,
  `tools_grouped_by_host()`, `host_display_label()`, and
  `_looks_like_transient_network()`. Total: 328 passing in `tests/`,
  24 in `cloud_backend/tests/`.

### Changed

- `ai_behaviour._DEFAULT_RULES` renamed to `_GENERIC_RULES` and made
  longest-pattern-first. Legacy name kept as an alias so external
  callers don't break.
- `ai_behaviour.tools_grouped_by_host()` added — single helper that
  pulls live `tool_engine.TOOLS`, applies family + suffix rules,
  groups by host, marks user overrides. UI consumes this instead of
  iterating `TOOLS` itself.
- `SettingsDialog` default size bumped 560 × 520 → 640 × 720 to fit
  the new AI Behaviour section without forcing a global scroll.

### Removed

- **Orphan files deleted** — `app/company_pets.py` (pet-strip
  decoration, no value), `app/do_build_2023.py`,
  `app/do_build_2024.py` (superseded by
  `auto_build.build_revit_connector(year)`).
- **Dangling `relay/**/*.ts` glob references scrubbed** from
  `agents/departments.py` (now `cloud_backend/**/*.py`).
- **`relay/` directory cleaned up** — `.vercel/` cache + leftover
  `node_modules/` removed (source files were deleted in v1.0.1).

## [1.0.1] — 2026-05-12

The "make it actually work" release. v1.0.0 shipped 22 features in a
single day; v1.0.1 is the bug-hunt + UX-polish sprint that followed.
30+ live-trace-driven fixes after real-world testing.

### Added

- **Settings → AI Behaviour** section
  - Extended-thinking effort: off / low / medium / high (mapped to
    Anthropic `budget_tokens`, Gemini 2.5 `thinkingBudget`, OpenAI
    o-series `reasoning_effort`)
  - Per-tool permission table: `allow` / `ask` / `deny` per registered
    tool, with sensible defaults (read-only allow, mutate ask)
  - Inline Approve / Deny buttons in chat when a tool returns
    `needs_confirmation`
- **Outlook bulk macros** to escape the per-message loop trap
  - `outlook_auto_categorize_by_sender()` — zero-arg one-shot,
    derives category from sender domain
  - `outlook_auto_categorize_by_subject_keywords(map)` — content-based
    tagging with `{keyword: category}` map
  - `outlook_set_categories_by_filter(...)` — one-call bulk apply
  - `outlook_list_distinct_senders(days)` — domains + counts for
    deriving categories
  - `outlook_list_sent_items(limit, days)` — sent-mail mirror
- **`outlook_execute_python`** — universal escape hatch. Model writes
  Python, runs in COM context with `outlook`, `ns`, `inbox`, `sent`,
  `drafts` globals injected. Pattern mirrors the existing
  `revit_execute_csharp` / `blender_execute_python`.
- **Refusal detector** — when a provider returns text matching known
  refusal patterns ("I cannot read", "I'm not able to", "my capabilities
  are limited") AND zero tool calls AND tools were available, the router
  blocks the provider for 10 min + auto-falls-through to the next.
- **Retry-without-tools** — when a provider returns empty text AND empty
  tool calls AND tools were sent, the router retries once with
  `tools=[]` + a "reply in 1-2 short sentences" suffix. Catches the
  "Gemini overwhelmed by 33 tools" failure mode.
- **Tool-schema relevance filter** — Gemini limited to ≤12 schemas per
  request, with family-keyword promotion. Stops empty responses caused
  by Gemini Flash's "too many tools" overwhelm.
- **Tool-result synthesizer** — when an LLM finishes a turn with empty
  text but successful tool calls, the router synthesizes a one-line
  summary from the most recent invocation (e.g. "Outlook: 966 inbox,
  3 unread"). No more blank bubbles after a successful tool run.
- **Procrastination detector** — local models that emit essays instead
  of calling tools get one auto-nudge ("call the tool now, no
  description") before the router gives up.
- **AUTHORITY grant** — explicit system-prompt clause telling the model
  the user already authorised tool access. Reduces refusal rate from
  models with conservative safety fine-tunes.
- **Skill-matcher host-context filter** — drops skills whose `requires`
  targets only an unrelated host family when the prompt clearly names
  a different one (e.g. "categorise emails" no longer suggests a Revit
  construction Skill).
- **Bubble reconciliation** — `_on_finished` now force-paints from
  `response.text` when the chunk signal hasn't arrived yet. Fixes the
  "1-chunk streaming race" that left bubbles blank for some providers.
- **Empty-response placeholder** — when LLM returns empty text and no
  tools fired, bubble shows clear "(empty response — provider returned
  no text. Check Settings → Providers for credit / quota issues.)"
- **Session-save four-layer guarantee**
  - `save_session` refuses to write when content is empty
  - Post-write roundtrip verification (re-read + assert counts)
  - AST guardrail script `scripts/check_session_saves.py` + pre-commit
    hook fails any call missing `messages=`
  - 9 contract tests pinning the invariants
- **Startup stub sweep** — `cleanup_empty_sessions()` runs on every
  launch so crashed-turn stubs from previous sessions don't pollute
  the THREADS rail.
- **Multi-line chat input** — Shift+Enter inserts newline, Ctrl+Enter
  also works, plain Enter submits. Input auto-grows 1..10 lines.
- **OpenRouter 409 recovery** — sign-in dialog now has "Or paste a key
  manually" button below the OAuth one. Click to flip into clipboard-
  watch mode when OpenRouter's auth-code endpoint rate-limits.
- **CHANGELOG.md** (this file).

### Changed

- **Local-model preferences re-ranked**
  - Modeling / analysis chains: `command-r7b` (Cohere tool-use
    specialist) first; `llama3.1:8b` second; coder variants as late
    fallback.
  - `deepseek-r1` removed from action chains (reasoning model burns
    1000+ tokens in `<think>` before acting). Kept in a dedicated
    `reasoning` chain for opt-in use.
  - `gemma4:latest` typo removed (model doesn't exist); replaced with
    real `gemma3` + `gemma2`.
- **System prompt softened** — old version's "ACT, do not describe"
  made Gemini emit empty turns after a tool call. New version
  explicitly says "after the tool runs, end with one or two short
  sentences. Never end a turn silently."
- **Ollama request options** — `temperature: 0.15`, `num_predict:
  4096`, `top_p: 0.9` sent on every request. Default 0.7 made models
  "explore" instead of acting on tool-use prompts.
- **Status-bar version** reads `VERSION` file dynamically; previously
  hardcoded `v0.27.6`.
- **Pricing tiers** reworked from 2 tiers (BYO/Studio @ $199) to 4
  tiers (BYO $0 / Solo $19 / Studio $79 / Firm $299+seat).
- **Saved-session filter** now requires at least one assistant message
  with non-empty content. Sessions where the LLM never replied are
  treated as stubs.
- **Schema-filter tool count** — Gemini gets ≤12 tools per request
  (previously 33+). Family promotion keeps the right ones in the slice.

### Fixed

- Sessions appearing in THREADS rail but loading as blank chats
  (autosave wrote the empty `Session` object, not `self.history`)
- Empty assistant bubble after PING OUTLOOK on Gemini Flash (33-tool
  overwhelm → no text, no tool calls)
- Gemini refusing to use Outlook tools despite AUTHORITY grant
  (refusal detector + fallback chain → Ollama command-r7b succeeds)
- Local Ollama passing placeholder `entry_id` strings like
  `"[each message in inbox]"` (sharpened tool descriptions + explicit
  bulk pattern in prompt + zero-arg macros that don't require loops)
- Typed text invisible in chat input (Fusion-style palette didn't
  apply QSS `color:` to `QPlainTextEdit`; now sets palette directly)
- Multi-line input height clipping (chrome buffer raised from 12px
  to 36px to cover QSS padding + frame + doc margin)
- Hardcoded `v0.27.6` in status bar (now reads `VERSION` file)
- Taskbar showing pythonw snake icon despite AUMID set (Windows
  needed an explicit registry entry at
  `HKCU\Software\Classes\AppUserModelId\io.archhub.studio`)
- Empty Bubble streaming race (1-chunk responses processed `finished`
  before the chunk signal landed)

### Removed

- `gemini-1.5-pro` references (Google retired model in v1beta).
- Hardcoded version string in status bar.
- 2-tier pricing model.

### Stats

- 31 commits since v1.0.0
- 300/300 tests green (started day at 29 tests)
- ~5,500 LOC added across 50+ files
- 0 production bugs reported (still pre-public-beta)

---

## [1.0.0] — 2026-05-11

Initial public release. Open-core architecture.

### Added

- Studio shell (PyQt6 desktop) with brand v0.1 (terra/graphite/ochre)
- Multi-instance `@session` routing — Revit × N, AutoCAD × N, Max × N,
  Outlook × N accounts. Chat composer parses `@<token>` to pin a turn
  to a specific session.
- Connectors for Revit (2020-2025) / AutoCAD 2024-2026 / 3ds Max
  2025-2026 / Blender 4+ / Outlook (COM) / Speckle (cloud)
- Marketplace v0.39 — signed Skills + semver-pinned install. Ed25519
  signing module with pinned trust roots.
- Workflow canvas v2 — node editor, undo/redo (100-entry stack),
  Ctrl+D duplicate, Delete to remove, arrow nudge, Ctrl+A select all,
  minimap with click-to-pan.
- Reality Check — per-host 24h sparklines on the Telemetry page,
  driven by a ring-buffer `health_history` module.
- Sectioned Settings — Providers / About / Diagnostics tabs.
- Zero-barrier onboarding — first-launch dialog offers silent Ollama
  install + qwen2.5:3b model pull for users with no AI tooling.
- ArchHub Cloud client scaffold — bearer auth, PKCE sign-in flow,
  OpenAI-compatible streaming client, status-bar quota meter. Backend
  yet to be built; spec at `docs/BACKEND_SPEC.md`.
- 4-tier pricing UI — BYO ($0) / Solo ($19) / Studio ($79) /
  Firm ($299+seat).
- Inno Setup installer script at `installer/setup.iss`.

[1.0.1]: https://github.com/archhub/archhub/releases/tag/v1.0.1
[1.0.0]: https://github.com/archhub/archhub/releases/tag/v1.0.0
