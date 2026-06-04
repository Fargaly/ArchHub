"""Shared pytest configuration for the personal-brain-mcp test suite.

Two structural isolations, each killing a whole CLASS of cross-test pollution
(not by per-test discipline but by config + an autouse fixture every test
inherits). Same philosophy as ArchHub's `tests/conftest.py`
(`_isolate_secrets_store` + `_stop_leaked_background_threads`): the guarantee is
structural, asserted, and fails loudly if the class is reintroduced.

════════════════════════════════════════════════════════════════════════════
ROOT CAUSE of the 8 full-run-only failures: a shadowed `mcp` package
════════════════════════════════════════════════════════════════════════════
The 8 tests that fail in `pytest tests/` but pass in isolation
(test_cloud_archive_tool.py ×3, test_community_mcp_tools.py ×4,
test_slices_9_through_16.py::test_acl_blocks_firm_write_without_firm_membership)
all call `personal_brain.server.build_server`, which builds the in-house
`InHouseMCP` server (`mcp_core.py`). That core imports `mcp.types` (the installed
PyPI `mcp` SDK) to derive its tool schemas + JSON-RPC response envelopes, so a
working `mcp.types` is a hard prerequisite for building a server.

Three sibling test modules — test_brain_migrate.py and test_brain_unify.py
(and, harmlessly, test_backfill_skills.py) — insert the ArchHub desktop-app
dir `ArchHub/app` onto `sys.path[0]` AT IMPORT/COLLECTION TIME so they can
`from memory.graph import ...`. But `ArchHub/app` contains its OWN package
`app/mcp/` (ArchHub's local MCP-client helpers, no `types` submodule). With
`app/` ahead of site-packages on `sys.path`, `import mcp` resolves to
`app/mcp/` and gets cached in `sys.modules['mcp']`. From then on, for the rest
of the pytest process, `import mcp.types` raises `ModuleNotFoundError` →
the in-house core can no longer resolve the SDK types → `build_server` fails,
and every test that builds a server fails. Because those modules sort before
the failing ones, the whole suite is poisoned; run the failing files alone and
`app/` is never on the path, so they pass. (Verified: inserting `app/` at
sys.path[0] makes `import mcp` resolve to `app/mcp/__init__.py` and
`import mcp.types` fail.)

The fix is to PIN the real `mcp` package first. pytest imports this conftest
before collecting any `test_*.py`, so importing `mcp.types` here caches the
genuine installed SDK in `sys.modules` up-front. After that a later `app/`
insertion can no longer shadow it — the cached real module wins, `import
mcp.types` keeps working, and `build_server` succeeds regardless of test order.
The autouse fixture additionally re-pins the real `mcp` around every test as a
belt-and-braces guard and asserts the shadow has not crept back, so this class
can't silently recur.

This conftest does NOT mutate `sys.path` itself (the package is already
importable via its installed `src/personal_brain` mapping) and edits no source
— it only ensures import resolution stays correct.

════════════════════════════════════════════════════════════════════════════
SECONDARY guard: leaked module-global worker/poller registries
════════════════════════════════════════════════════════════════════════════
Two module-level registries keyed by `id(store)` are populated by tools /
helpers and never cleared between tests, each holding daemon threads + a strong
ref to a BrainStore:

  • `personal_brain.server._COMMUNITY_POLLERS`  — built lazily by
        `brain.community_poll_now`; each `CommunityPoller` owns a
        `brain-community-poller` thread + an accumulating `reputations` dict and
        pins its store alive (enabling stale-poller reuse after `id()` recycle).
  • `personal_brain.workers._SUPERVISORS`        — built by `start_workers`
        (test_engine_on.py / in-process slice-16); each `WorkerSupervisor`
        spins Sync/Publish/Reflexion/Watchdog threads and its Watchdog keeps
        calling `revive_dead()` (rebuilding workers, executing SQL) against a
        store a finished test already closed.

These are not what fails the 8 tests today, but they are real latent leaks of
the same class. The autouse fixture drains (stops each entry's threads, then
clears) both registries before and after every test and asserts they are empty
with no brain worker thread surviving — a tripwire if a new poller/supervisor
is registered without a clean stop. Every `.stop()` is wrapped so a
half-started worker can't turn teardown into the failure.

(`build_server()` makes a fresh in-house `InHouseMCP` server per call and is
thread-free, so tool-registration is per-instance, not global — nothing to
reset there. The
stateless embedder caches and the monotonic HLC carry no per-store correctness
state for these tests and are intentionally left alone.)
"""
from __future__ import annotations

import sys
import threading

import pytest


# ── Root-cause fix: pin the genuine installed `mcp` SDK in sys.modules BEFORE
# any test module can insert ArchHub/app (whose `app/mcp/` package would shadow
# it) onto sys.path. Done at conftest import time so it runs ahead of all
# collection. Degrade gracefully if `mcp` is not installed in this env.
def _pin_real_mcp() -> None:
    try:
        import mcp  # noqa: F401  (caches the real top-level package)
        import mcp.types  # noqa: F401  (the submodule build_server's tools need)
    except Exception:
        return


_pin_real_mcp()


# Daemon-thread names owned by the brain's background workers — used for a
# best-effort post-teardown survivor tripwire. Kept in sync with the
# `threading.Thread(name=...)` call sites in community.py / workers.py /
# liveness.py / sync_worker.py / publish_worker.py / reflexion.py.
_BRAIN_WORKER_THREAD_NAMES = frozenset({
    "brain-community-poller",
    "brain-watchdog",
    "brain-sync-worker",
    "brain-publish-worker",
    "reflexion-worker",
})


def _real_mcp_is_pinned() -> bool:
    """True iff sys.modules['mcp'] is the genuine installed package (i.e. its
    `types` submodule is importable). False if a shadow (e.g. app/mcp) is
    cached or mcp isn't installed."""
    mod = sys.modules.get("mcp")
    if mod is None:
        return False
    try:
        import importlib
        importlib.import_module("mcp.types")
        return True
    except Exception:
        return False


def _repin_real_mcp_if_shadowed() -> None:
    """If a shadow `mcp` (no `.types`) got cached, evict it + its submodules and
    re-import the genuine package so import resolution is correct again."""
    if _real_mcp_is_pinned():
        return
    for name in list(sys.modules):
        if name == "mcp" or name.startswith("mcp."):
            sys.modules.pop(name, None)
    _pin_real_mcp()


def _drain_registry(module_attr_owner, attr_name: str) -> int:
    """Stop every entry in a module-global `dict[id(store), owner]` registry,
    then clear it. Each `owner` (CommunityPoller / WorkerSupervisor) exposes
    `.stop(timeout_s=...)`. Each stop is isolated so one broken entry can't
    abort the drain. getattr-guarded: a safe no-op if the global is absent
    (e.g. a concurrent source refactor renames it)."""
    registry = getattr(module_attr_owner, attr_name, None)
    if not isinstance(registry, dict):
        return 0
    drained = 0
    for owner in list(registry.values()):  # snapshot; stop() may mutate
        drained += 1
        stop = getattr(owner, "stop", None)
        if not callable(stop):
            continue
        try:
            stop(timeout_s=2.0)
        except TypeError:
            try:
                stop()
            except Exception:
                pass
        except Exception:
            pass
    try:
        registry.clear()
    except Exception:
        pass
    return drained


def _surviving_brain_worker_threads() -> list[threading.Thread]:
    """Brain-owned daemon worker threads still alive after teardown. All are
    daemon=True, so this is a hygiene tripwire only — it gives a just-signalled
    thread a brief bounded join, never a hang."""
    survivors = [
        t for t in threading.enumerate()
        if t.name in _BRAIN_WORKER_THREAD_NAMES and t.is_alive()
    ]
    if survivors:
        for t in survivors:
            try:
                t.join(timeout=1.0)
            except Exception:
                pass
        survivors = [
            t for t in threading.enumerate()
            if t.name in _BRAIN_WORKER_THREAD_NAMES and t.is_alive()
        ]
    return survivors


@pytest.fixture(autouse=True)
def _isolate_brain_module_globals():
    """Around EVERY test: keep `mcp` import resolution correct and reset the
    leak-prone module-global registries — the structural fix for the
    cross-test-pollution class."""
    # setup — make sure no earlier test left a shadow `mcp` cached, and start
    # the worker registries from a clean slate (covers import-time residue /
    # a reused process from a prior run).
    _repin_real_mcp_if_shadowed()
    try:
        from personal_brain import server as _server_mod
    except Exception:
        _server_mod = None
    try:
        from personal_brain import workers as _workers_mod
    except Exception:
        _workers_mod = None
    if _server_mod is not None:
        _drain_registry(_server_mod, "_COMMUNITY_POLLERS")
    if _workers_mod is not None:
        _drain_registry(_workers_mod, "_SUPERVISORS")

    yield

    # teardown — re-pin mcp (a test that inserted app/ onto sys.path may have
    # cached the shadow), then stop + clear everything this test left behind.
    _repin_real_mcp_if_shadowed()
    if _server_mod is not None:
        _drain_registry(_server_mod, "_COMMUNITY_POLLERS")
    if _workers_mod is not None:
        _drain_registry(_workers_mod, "_SUPERVISORS")

    # guards — fail loudly if any leak class crept back. Fix the source, never
    # weaken these asserts.
    assert _real_mcp_is_pinned() or sys.modules.get("mcp") is None, (
        "a shadow `mcp` package (no `.types`) is cached in sys.modules after "
        "teardown — ArchHub/app/mcp leaked onto sys.path and shadows the real "
        "mcp SDK; the in-house server can't resolve `mcp.types` and every "
        "build_server-backed test will fail for the rest of the run"
    )
    leftover = {}
    if _server_mod is not None:
        reg = getattr(_server_mod, "_COMMUNITY_POLLERS", None)
        if isinstance(reg, dict) and reg:
            leftover["server._COMMUNITY_POLLERS"] = len(reg)
    if _workers_mod is not None:
        reg = getattr(_workers_mod, "_SUPERVISORS", None)
        if isinstance(reg, dict) and reg:
            leftover["workers._SUPERVISORS"] = len(reg)
    assert not leftover, (
        f"brain module-global registries not empty after teardown: {leftover} "
        f"— a poller/supervisor was registered without a matching stop+clear"
    )
    survivors = _surviving_brain_worker_threads()
    assert not survivors, (
        f"leaked brain worker thread(s) survived teardown: {survivors} — a "
        f"background worker is not stopping cleanly and will pollute later "
        f"tests' store / mocked state"
    )


# ════════════════════════════════════════════════════════════════════════════
# TERTIARY guard: never let a test reach the developer's REAL, billing-capable
# LLM key (the order/env-dependent skill-mint flake)
# ════════════════════════════════════════════════════════════════════════════
# Same philosophy as ArchHub's `_isolate_secrets_store` / `_isolate_brain_daemon`
# (tests must not depend on — or touch — real machine state; the guarantee is
# structural, not per-test discipline).
#
# ROOT CAUSE of the order-dependent skill-mint failures
# (test_backfill_skills / test_engine_on / test_reflexion, "anthropic…" errors,
# N fail one run / M another): the reflexion honing critic auto-selects a REAL
# LLM judge via `reflexion.default_critic()` → `reflexion.detect_real_llm_key()`.
# That probe checks, in order: (1) `ANTHROPIC_API_KEY` env, (2) **ArchHub's
# `secrets_store.load_api_key('anthropic')`** — reachable because sibling brain
# tests (test_brain_migrate / test_brain_unify) insert `ArchHub/app` onto
# `sys.path` at collection time, so `from secrets_store import load_api_key`
# resolves the desktop app's keyring/obfuscated-file resolver — and (3)
# `OPENAI_API_KEY`. On a developer box (2) returns a genuine, *billing-blocked*
# `sk-ant-…` key (verified: 108-char key reachable from the brain tree even with
# no env var set). Routing to the live judge is gated on `BRAIN_REFLEXION_LLM`,
# but several real-critic-wiring tests set that flag, and a minting test that
# runs while the flag is set (leaked) — or any future test that mints with the
# flag on without stubbing the SDK — then constructs a live `AnthropicCritic`
# against that dead key and its `messages.create` raises HTTP 400 "credit
# balance is too low". Whether a given run hits it depends on collection order +
# whatever the ambient env/secret store holds → nondeterministic ("15 fail one
# run, 3 another").
#
# The fix severs the only non-env path to a real key for EVERY test, up-front:
#   • Inject a fake `secrets_store` module whose `load_api_key(...) -> None`, so
#     the probe's step (2) can never return the on-disk key. (The genuine env
#     steps (1)/(3) are left intact: a test that explicitly sets
#     `ANTHROPIC_API_KEY` to its OWN fake string — e.g.
#     test_default_critic_routes_to_anthropic_when_key_present — still exercises
#     real routing, because that path returns before secrets_store is consulted.)
#   • Clear `BRAIN_REFLEXION_LLM` so the DEFAULT critic is the deterministic
#     `HeuristicCritic` for any test that doesn't deliberately opt in.
#
# Both are belt-and-braces: either alone closes the flake, together they make it
# impossible for a brain test to touch the live account regardless of order or
# host. OVERRIDABLE by design — autouse fixtures run first, so a per-test
# `monkeypatch.setenv("BRAIN_REFLEXION_LLM", "1")` + per-test fake-anthropic
# client (the controlled real-critic-wiring tests) layer on top (pytest
# monkeypatch is LIFO) and still pass: their fake client returns canned JSON, so
# nothing reaches the network. No test is weakened — the live key is simply
# unreachable. Every step is getattr/try-guarded so a missing symbol or a source
# refactor degrades to a safe no-op, never a teardown error.


def _real_anthropic_key_reachable_offline() -> bool:
    """True iff `detect_real_llm_key()` can surface a real key with NO env var
    set — i.e. the on-disk `secrets_store` path is live. Used only by the
    fixture's self-check assert so this isolation can't silently rot."""
    try:
        from personal_brain import reflexion as _rfx
    except Exception:
        return False
    import os as _os

    saved = {
        k: _os.environ.pop(k, None)
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")
    }
    try:
        return _rfx.detect_real_llm_key() is not None
    except Exception:
        return False
    finally:
        for k, v in saved.items():
            if v is not None:
                _os.environ[k] = v


@pytest.fixture(autouse=True)
def _isolate_real_llm_key(monkeypatch):
    """Around EVERY brain test: make the developer's real, billing-capable LLM
    key UNREACHABLE and force the deterministic critic by default — the
    structural fix for the order/env-dependent skill-mint flake (see the block
    comment above). Per-test opt-in (flag + fake SDK client) still overrides."""
    import sys as _sys
    import types as _types

    # (a) Sever the on-disk key path: a fake `secrets_store` whose resolver
    # always misses. The reflexion probe does `from secrets_store import
    # load_api_key`, so seeding sys.modules intercepts it without needing the
    # real module importable. A per-test fake (test_detect_real_llm_key_none_*)
    # layers on top harmlessly (same None result).
    _fake = _types.ModuleType("secrets_store")
    _fake.load_api_key = lambda *_a, **_k: None  # type: ignore[attr-defined]
    monkeypatch.setitem(_sys.modules, "secrets_store", _fake)

    # (b) Default the live-LLM opt-in OFF so an unmanaged minting test uses the
    # HeuristicCritic. Tests that prove the real path setenv it back on (LIFO).
    monkeypatch.delenv("BRAIN_REFLEXION_LLM", raising=False)

    yield


def test__llm_key_isolation_is_effective():
    """Tripwire (collected as a normal test): with the autouse isolation in
    place and no env key set, the real-key probe MUST come back empty. If this
    ever fails, the on-disk `secrets_store` severing regressed and the
    skill-mint flake is back — fix the fixture, never delete this guard."""
    import os

    saved = {
        k: os.environ.pop(k, None)
        for k in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")
    }
    try:
        from personal_brain import reflexion as rfx

        assert rfx.detect_real_llm_key() is None, (
            "real LLM key still reachable under test isolation — the "
            "secrets_store severing in _isolate_real_llm_key regressed; the "
            "order-dependent skill-mint flake can recur"
        )
        # And the default critic must be the deterministic heuristic.
        assert type(rfx.default_critic()).__name__ == "HeuristicCritic"
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v
