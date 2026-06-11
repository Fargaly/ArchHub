"""Shared pytest configuration for the ArchHub desktop-app test suite.

Two jobs:
  1. Put `app/` on sys.path so tests can import the app modules.
  2. Isolate `secrets_store` for EVERY test — a throwaway per-test
     APP_DIR — so no test can ever write the developer's real
     %LOCALAPPDATA%/ArchHub/settings.json or secrets.dat.

Job 2 is the structural fix for the tool-policy pollution class.
Before this, only test_ai_behaviour.py isolated `secrets_store`; any
other test that touched `secrets_store.save_setting` or
`ai_behaviour.set_tool_policy` without its own monkeypatch silently
mutated the developer's real on-disk settings — the exact way the
`tool_policies` override store ended up polluted. Founder mandate
2026-05-18: tests must not touch real machine state, and the
guarantee must be structural, not per-test discipline.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parent.parent / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

# ConnectorHealth._maybe_self_heal fires COM NETLOAD into a LIVE AutoCAD when
# acad.exe is up and :48885 is dead — a pytest run on a dev box must never
# inject commands into the founder's open AutoCAD. Module level (not a
# fixture) so it precedes every test-module import; setdefault so a box that
# deliberately set the env keeps its value.
os.environ.setdefault("ARCHHUB_NO_SELF_HEAL", "1")


@pytest.fixture(autouse=True)
def _isolate_secrets_store(tmp_path, monkeypatch):
    """Redirect `secrets_store` to a throwaway per-test directory so no
    test pollutes the real settings store. Autouse — every test in the
    suite gets it, with zero opt-in. A test that wants its own
    secrets_store path can still monkeypatch on top; this only
    guarantees the floor."""
    app_dir = tmp_path / "ArchHub"
    app_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    # cloud_client now single-sources the cloud bearer at
    # %APPDATA%/ArchHub/brain/cloud.json (the personal-sync daemon's path), so
    # APPDATA must be isolated too — otherwise set_token() in a test writes the
    # token to the developer's REAL cloud.json (polluting the live daemon) and
    # leaks across tests (e.g. test_initially_signed_out sees a stale token).
    # Same throwaway dir keeps app + daemon paths consistent under test.
    monkeypatch.setenv("APPDATA", str(tmp_path))
    try:
        import secrets_store
    except Exception:
        # secrets_store not importable in this environment — nothing to
        # isolate. (Never fatal: a test that doesn't touch it is fine.)
        return
    monkeypatch.setattr(secrets_store, "APP_DIR", app_dir, raising=False)
    monkeypatch.setattr(secrets_store, "SECRETS_FILE",
                        app_dir / "secrets.dat", raising=False)
    monkeypatch.setattr(secrets_store, "SETTINGS_FILE",
                        app_dir / "settings.json", raising=False)


@pytest.fixture(autouse=True)
def _isolate_brain_daemon(tmp_path, monkeypatch):
    """Structurally cut every test off from the developer's live brain.

    Same philosophy as `_isolate_secrets_store` above — make the
    machine-state dependency impossible, not a matter of per-test
    discipline. The class of bug this kills:

    `bridge.memory_stats()` (and the `brain_*` slots) read their
    CANONICAL counts from the brain DAEMON over HTTP — `_brain_tool`
    calls `memory_gate.BrainClient._call('brain.health', ...)` against
    `http://127.0.0.1:8473` (the ONE-SYSTEM unify,
    docs/audits/brain-unify-design-2026-05-28.md). The daemon is a
    SEPARATE long-lived process holding the developer's real
    `brain.db` (hundreds of real facts). So any test that exercises
    `memory_stats` / `brain_status` WITHOUT its own stub silently reads
    whatever that live daemon happens to hold — non-deterministic, and
    different on a CI box where no daemon runs. `test_memory_stats_*`
    and `test_brain_status_returns_ok_envelope_on_success` are exactly
    these unstubbed-or-partially-stubbed call sites.

    The floor we guarantee for EVERY test:

      1. `BrainClient._call` raises ConnectionError by default, so the
         daemon is unreachable regardless of whether one is actually
         running. `bridge._brain_tool` then hits its real
         `except → {ok:false,error:...}` path and `memory_stats` falls
         back to the staging graph — which (2) makes empty + isolated.
      2. The memory graph (`graph.sqlite`, read via
         `memory.MemoryGraph.open()` → `default_graph_path()`) is
         pinned to this test's tmp dir through BOTH the Windows
         (`LOCALAPPDATA`) and POSIX (`XDG_DATA_HOME`) env vars, so the
         fallback read is an empty per-test store, never the real
         204-node graph. (`LOCALAPPDATA` is already set by
         `_isolate_secrets_store`; we add `XDG_DATA_HOME` so the
         guarantee holds machine-independently on CI too.)
      3. `BRAIN_HTTP_URL` points at a guaranteed-closed loopback port
         so even a code path that bypasses the `_call` stub (or probes
         `is_available`) refuses instantly instead of hanging on the
         4 s daemon timeout.

    OVERRIDABLE by design: autouse fixtures run FIRST, so a per-test
    `monkeypatch.setattr(memory_gate.BrainClient, "_call", ...)` (the
    `mock_brain_call` fixture, the daemon-down ConnectionRefused stubs,
    the dataset-export fakes) is applied AFTER this and wins — pytest's
    monkeypatch is LIFO and per-test patches layer on top. Likewise a
    per-test `monkeypatch.setattr(bridge_inst, '_brain_tool', ...)`
    (the empty-store stub in `test_memory_stats_empty_graph`) overrides
    the instance method directly. Every guard is wrapped so a missing
    symbol is a safe no-op.
    """
    # (2) Pin the memory-graph dir on POSIX too (Windows already pinned
    # by the secrets fixture's LOCALAPPDATA). default_graph_path() reads
    # XDG_DATA_HOME first on POSIX; without this a CI box reads the real
    # ~/.local/share graph.
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    # (3) Belt-and-suspenders: a closed loopback endpoint. Port 1 never
    # listens, so any BrainClient that escapes the _call stub refuses
    # instantly rather than waiting out the timeout.
    monkeypatch.setenv("BRAIN_HTTP_URL", "http://127.0.0.1:1")
    # (1) The real chokepoint — neutralise the single transport method
    # every brain call funnels through. Raising here drives bridge's
    # _brain_tool into its except→fallback and MemoryGate's
    # is_available() to False, with no network I/O.
    try:
        import memory_gate
    except Exception:
        # App package not importable in this environment — no daemon
        # transport to neutralise, and the env vars above already pin
        # the graph fallback. Safe no-op.
        return

    def _no_daemon(self, tool, params, timeout=None):
        raise ConnectionError(
            "brain daemon neutralised for tests (conftest _isolate_brain_daemon)"
        )

    monkeypatch.setattr(memory_gate.BrainClient, "_call", _no_daemon,
                        raising=False)


@pytest.fixture(autouse=True)
def _stop_leaked_background_threads():
    """Structurally kill the leaked-background-thread pollution class.

    The `connector_health` monitor is a process-global daemon thread that
    polls the *shared* `urllib.request.urlopen` every few seconds. Any test
    that constructs a UI surface (the studio/workspace/settings smoke tests,
    the connector panel, Reality Check, ...) trips `connector_health.instance()`
    as a side effect, which starts that daemon. Because the instance is a
    module-level singleton and the thread is `daemon=True`, it OUTLIVES the
    test's fixture teardown and keeps hammering `urllib.request.urlopen` for
    the rest of the pytest process. A later test that monkeypatches urlopen
    onto its own MagicMock (e.g. test_status_report's digest-flush test, which
    asserts exactly one POST) then sees the leaked daemon's probes counted
    against its mock — `call_count` inflates to 9/17/20 and the test flakes.

    The fix is structural, not per-test discipline (same philosophy as the
    secrets_store isolation above): after EVERY test we stop+join the monitor
    so no background poller can ever tick into the next test's mocked state.
    Then we assert the daemon is actually gone — a guard that fails loudly if
    a new background poller of this class is ever introduced without a clean
    stop.
    """
    yield
    try:
        import connector_health
    except Exception:
        # App package not importable in this environment — nothing started,
        # nothing to stop.
        survivors = [t for t in threading.enumerate()
                     if t.name == "ConnectorHealth" and t.is_alive()]
        assert not survivors, (
            f"leaked ConnectorHealth poll thread(s) survived teardown: "
            f"{survivors}"
        )
        return
    # Stops + joins the poll thread and drops the singleton (no-op when the
    # test never started it).
    connector_health.shutdown()
    survivors = [t for t in threading.enumerate()
                 if t.name == "ConnectorHealth" and t.is_alive()]
    assert not survivors, (
        f"leaked ConnectorHealth poll thread(s) survived teardown despite "
        f"shutdown(): {survivors} — a background poller is not stopping "
        f"cleanly and will pollute later tests' urlopen mocks"
    )
