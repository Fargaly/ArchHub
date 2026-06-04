---
id: AgDR-0034
timestamp: 2026-05-21T23:00:00Z
agent: claude-code (Sonnet)
session: founder demand 2026-05-21 — "RUN A DEEP MAINTENANCE AUDIT... SETUP A GITHUB BOT TO DO THAT AUDIT DAILY"
trigger: Recurring "still not working" bugs reaching the founder.  He wants a standing automated audit, not one-off hunts.
status: executed
category: architecture
projects: [archhub]
extends:
  - ENGINEERING MANDATE (CLAUDE.md) — fix the class, add a guard
---

# Daily maintenance-audit bot — static bug-hunt + test sweep on a cron

## Context

Bugs keep reaching the founder ("still not working").  Root cause of
the PROCESS failure: there is no standing automated check between a
commit and the founder's hands.  Founder demand: a GitHub bot that
runs a deep audit daily and surfaces findings.

## Decision

Two artifacts:

1. **`scripts/maintenance_audit.py`** — a static bug-hunter.  Scans
   the Python backend + JSX UI for the anti-pattern CLASSES that the
   2026-05-21 deep audit found recurring:
   - bare `except:` / `except Exception: pass` that swallow errors
   - blocking work (`urlopen`, `subprocess`, COM, `time.sleep`)
     inside a `@pyqtSlot` body — the Qt-main-thread-freeze class
   - `forward()`-style success-masking (`return {"status":"ok"...}`
     in an exception handler)
   - JSX `addEventListener` / bridge `.connect(` without a matching
     removal in the same function (listener-leak class)
   - JSX `bridgeJson(` whose result is used synchronously (the
     Promise-not-awaited class)
   - `TODO` / `FIXME` / `HACK` / `XXX` census
   - Python functions over 150 lines (review-risk)
   Emits a Markdown report + a JSON summary.  Exit code 0 always
   (informational); the count of CRITICAL findings is in the summary.

2. **`.github/workflows/daily-audit.yml`** — GitHub Actions cron.
   - Runs `06:00 UTC` daily + on manual `workflow_dispatch`.
   - Sets up Python, installs deps, runs the headless-safe test
     subset (`pytest --ignore=test_bridge_qt --ignore=test_ui_smoke`).
   - Runs `maintenance_audit.py`.
   - Writes both into the GitHub **job summary** + uploads the audit
     report as a build artifact.
   - On a non-zero CRITICAL count OR a test failure, opens (or
     updates) a single tracking issue titled `🔍 Daily audit —
     <date>` via `gh` so findings are not lost.

## Why static-only on CI

GitHub runners have no Revit / AutoCAD / display.  They CANNOT run
the .NET connector builds or the CDP live-app checks.  The bot does
what CI *can* do reliably: the Python test suite + static analysis.
Live-app + .NET verification stays the developer's job per the
SESSION-CLOSE MANDATE.

## Scope of the FIRST run (this commit)

The deep audit was run manually 2026-05-21 (two parallel agents over
`bridge.py` + brokers + `studio-lm.jsx`).  Findings + fixes shipped
this commit:
- FE — CanvasMenu keydown listener leak (2-min-crash class) → fixed.
- FE — version/document param dropdowns: bridgeJson Promise never
  awaited → fixed.
- FE — SearchPanel: bridge data dead + I/O in render-phase useMemo
  → fixed (debounced effect).
- BE — broker `forward()` reported non-JSON 2xx as success → fixed
  (honest `status:error`) across revit/acad/max brokers.

Deferred to the roadmap (tracked by the bot, bigger refactors):
- BE — `list_host_sessions` / `probe_connector` / `get_all_hosts` /
  `get_local_llms` block the Qt main thread — need threading.
- BE — broker `list_sessions` 16-port scan has no TTL cache.
- FE — NodeCanvas rebuilds wire/group geometry every render (no
  useMemo) — a streaming-perf optimisation.
- BE — `WorkflowRunner` shared-state concurrency.

## Acceptance

1. `python scripts/maintenance_audit.py` runs locally, prints a
   report, exits 0.
2. `.github/workflows/daily-audit.yml` is valid YAML; a manual
   `workflow_dispatch` produces a job summary + artifact.
3. `tests/test_maintenance_audit.py` pins the audit's anti-pattern
   detectors.
4. Suite green.

## Artifacts

- This AgDR.
- `scripts/maintenance_audit.py`, `.github/workflows/daily-audit.yml`,
  `tests/test_maintenance_audit.py`.
- `docs/ROADMAP.md` — the deferred-bug list appended.
