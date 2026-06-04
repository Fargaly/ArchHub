# Flake diagnosis · test_window_elapsed_flushes_combined_email

**Date**: 2026-05-26
**HEAD at investigation**: `e5dc18a docs(status): wave 5 tally`
**Reported failure**: `assert mock_urlopen.call_count == 17` vs expected `1`
**Status at HEAD**: cannot reproduce; test is deterministically green.

## What was checked

1. **Isolated** — `pytest tests/test_status_report.py::TestDigestMode::test_window_elapsed_flushes_combined_email` → 1 passed (call_count == 1).
2. **Class** — `pytest tests/test_status_report.py::TestDigestMode` → 3 passed.
3. **File** — `pytest tests/test_status_report.py` → 24 passed.
4. **Full suite** — `pytest tests/ -q --ignore=tests/test_bridge_qt.py --ignore=tests/test_ui_smoke.py` → 2539 passed in 120s.
5. **Repeated** — ran the specific test 3x in a row, all green.
6. **No randomizer** — pytest plugin list shows only `anyio` + `asyncio`. No `pytest-randomly`, so collection order is stable.

## Code-chain analysis

**Test fixture (`tests/test_status_report.py:46-58`)** — `tmp_path` per test isolates state via `ARCHHUB_AGENTS_DATA_ROOT`. `monkeypatch.delenv("ARCHHUB_REPORT_DIGEST_HOURS", raising=False)` resets digest env each test.

**Production flow (`agents/report_sender.py:435-502`)** — `tick_send_report()` for digest mode:
1. `should_send_now()` gate (one timestamp file read).
2. `_write_last_sent()` claims the slot.
3. `report_fn()` produces ONE report (lambda in the test).
4. `_append_to_digest(report)` writes one row.
5. If window elapsed: `_load_digest_buffer()` (read), `_render_digest_email()` (no HTTP), `send(combined, mode="digest_flush")`.
6. `send()` → `_post_resend()` → ONE `urllib.request.urlopen` call.

There is no retry loop, no per-event POST, no batch send. Static analysis confirms: at most ONE `urlopen` call per `tick_send_report` invocation. Reaching 17 calls from this codepath alone is structurally impossible.

## Hypothesis space ruled out

- **Test pollution from sibling classes** — autouse fixture pins `ARCHHUB_AGENTS_DATA_ROOT` to per-test `tmp_path`; state files don't leak.
- **`generate_report()` leaking calls through monkeypatched urlopen** — the failing test's `report_fn` is a dict-returning lambda, never calls `generate_report()`, so `agents/status_report.py`'s `_http_get_status`/`_http_get_json` paths aren't hit.
- **Production regression after wave 5** — `git diff 5cecfae HEAD -- tests/test_status_report.py agents/report_sender.py agents/status_report.py` returns empty. No change between the reported-failing SHA and HEAD on the relevant files.
- **Retry/backoff inside `_post_resend`** — single `try/except`, no loop. Returns on first response.
- **Python urllib pooled connection retries** — `urlopen` does not retry on its own at the level the test mocks.

## What 17 could be

The number is too specific to be a stray noise. Plausible-but-unverified sources:
- A previously-existing (now-removed) middleware that pre-flighted urlopen for every section in `_render_digest_email`. Source-tree grep for any prior call sites returns none at HEAD.
- A different test runner state (e.g. `pytest-repeat` count 17) used during the bisect that produced the original report. We did not bisect across pre-`5cecfae` commits.
- A local-machine quirk on the founder's run (env var, mock state, parallel pytest workers). Not reproducible without that environment.

## Update — flake DID reproduce mid-investigation

A second full-suite run during this session reproduced the failure:
```
FAILED tests/test_status_report.py::TestDigestMode::test_window_elapsed_flushes_combined_email
AssertionError: assert 9 == 1
 +  where 9 = <MagicMock id='2350520304368'>.call_count
```

Two subsequent identical full-suite runs were GREEN (2538/2538). So the
flake is intermittent — not deterministic on either pass or fail. The
call_count varies (original report: 17, this session's hit: 9). Same
test, same code, no order randomizer plugin active, no parallel workers.

Implications:
- Some piece of global state (probably timer-based, e.g. a thread / cron
  scheduled in cloud_runner that fires `_post_resend` on a different
  cadence; or a stray `subprocess` / asyncio.task from a prior test that
  outlives its fixture) is intermittently firing `urlopen` during the
  test window, accumulating into `mock_urlopen.call_count`.
- The call-count delta (17, 9) is the WALL-CLOCK delta of the prior
  test phase — long full-suite runs leave more "fire windows" for a
  leaked background thread to tick.

## Likely culprit (not verified within budget)

`agents/cloud_runner.py` `CloudDaemon` instances created in
`TestCloudRunnerWiring` later in the file. The daemon's heartbeat /
scheduler thread may keep running after the test's fixture cleanup,
hitting the mocked `urlopen` if there's a healthz probe.

Verifying needs:
- list active threads at test teardown,
- ensure CloudDaemon.stop() actually joins all worker threads,
- confirm no `weakref.finalize` callback is queued onto the test loop.

## Decision

Per the 15-min budget (already exceeded), the engineering mandate "fix
the root not the symptom" still applies — patching with a `time.sleep`
or `gc.collect` would be patch-the-symptom. The right fix is to find
the leaked thread/task and ensure it stops cleanly. That investigation
is owned by a follow-up session with budget for thread-introspection.

Skipping the Task 1 commit per task escape clause. The flake is filed
here so the next session has the reproduction details + lead.

---

## RESOLVED 2026-05-28

**Root cause (confirmed, not the doc's original guess).** The leaked
thread was NOT `cloud_runner.CloudDaemon` — that class spawns no ticking
thread (its `__init__` only builds a `threading.Event`; `tick_once()`
runs synchronously; the dashboard thread is only started by `main()` in
real daemon mode, never by `TestCloudRunnerWiring`). Static + thread
introspection ruled it out.

The real culprit is **`app/connector_health.py`**. `connector_health.instance()`
lazily builds a *module-level singleton* `ConnectorHealth` and immediately
calls `.start()`, spawning a `daemon=True` thread named `ConnectorHealth`
that polls **the process-global `urllib.request.urlopen`** every
`PROBE_INTERVAL_SECONDS` (5s) via `_probe_listener`. UI smoke tests
(`test_studio_shell_smoke.py`, `test_workspace_shell_smoke.py`,
`test_settings_page.py`, the connector panel / Reality Check tests) trip
`instance()` as a *side effect of constructing a widget*. Because the
instance is a module global and the thread is a daemon, it OUTLIVES its
test's fixture teardown and keeps hammering `urllib.request.urlopen` for
the rest of the pytest process.

`test_status_report.py`'s digest-flush test does
`monkeypatch.setattr(report_sender.urllib.request, "urlopen", MagicMock())`.
Since `report_sender` does `import urllib.request` (module-level), that
patches the **shared global** `urllib.request.urlopen`. The leaked
`ConnectorHealth` daemon's probes then land on that MagicMock and are
counted against it. `call_count` becomes `1 (the real send) + N (daemon
ticks that fell inside the few-ms the mock was installed)`. N is a
function of wall-clock duration — which is exactly why the original
report saw 17, this doc's mid-session hit saw 9, and longer full-suite
runs inflate it more. Single-file runs almost never reproduce it because
the daemon is never started in that process and the window is tiny.

**Thread-introspection evidence.** With a pytest plugin enumerating live
threads at the target test's setup:
- `pytest test_status_report.py` alone → `['MainThread']` (no daemon, never flakes).
- `pytest test_studio_shell_smoke.py test_status_report.py::...target` →
  `['MainThread', 'ConnectorHealth']` (daemon leaked in from the smoke test).
- A standalone harness that starts the daemon (fast interval) with the
  test's MagicMock installed drove `mock_urlopen.call_count` from `1` →
  `20` deterministically — the mechanism, with no wall-clock luck.

**Class fix (mechanism, not symptom).**
1. *Production* (`app/connector_health.py`): `ConnectorHealth.stop()` now
   stops **and joins** the poll thread (previously it only set the event,
   so the daemon could still fire one more `urlopen` probe before
   noticing), and a new module-level `connector_health.shutdown()`
   stops+joins the thread and clears the `_INSTANCE` singleton. This is a
   real production gap — `main.py` starts the monitor on launch and never
   halts it — so the app now has a clean way to stop it too, not just the
   tests.
2. *Test class guard* (`tests/conftest.py`): a new autouse fixture
   `_stop_leaked_background_threads` calls `connector_health.shutdown()`
   in teardown after **every** test in the desktop-app suite, then asserts
   no `ConnectorHealth` thread survives. Same structural-guarantee
   philosophy as the existing `_isolate_secrets_store` fixture: no
   background poller started by any test can ever tick into a later test's
   mocked state, and the guard fails loudly if a new poller of this class
   is introduced without a clean stop.

No `time.sleep` / `gc.collect` / retry-the-assert symptom patches were
used.

**Determinism proof.**
- Failing test in isolation: green.
- Full `test_status_report.py` ×5 consecutive: 24 passed, all 5.
- Cross-module repro `test_studio_shell_smoke + test_workspace_shell_smoke
  + test_status_report` ×5 (this is the path that actually leaks the
  daemon): 43 passed, all 5. With the probe, `ConnectorHealth` is no
  longer alive at the target test's setup (`['MainThread']` only).
- Full suite ×2: 2539 passed each (118s), guard never tripped.
