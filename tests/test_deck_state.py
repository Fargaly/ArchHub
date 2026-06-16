"""COMMAND DECK — GATE for the `deck_state()` bridge slot.

The founder's one comprehensive in-app view fans out (off the Qt main
thread) to REAL sources and returns ONE JSON the panel renders:

  * burndown    <- brain requirement-tree sweep (green/red/open/needs_root)
                   + the active-work ledger (who is on what).
  * brain       <- brain.health (skills / facts / wiring) + reachability.
  * code        <- a REAL git probe (branch, uncommitted count, last commit).
  * connectors  <- app/connectors honest status per host
                   (live / loaded_dead / missing / unauthorized / probing).
  * inbox       <- the outlook/gmail connector if reachable, else HONEST empty.
  * finances    <- cloud quota + REAL provider token cost, else HONEST empty.

These tests pin the CONTRACT (ANTI-LIE: every tile names a real source +
degrades to a typed empty, never fabricated data) AND the threading
invariant (the fan-out is `_cached_async`, off the Qt main thread — a slow
source must NOT block the slot return).

Like the sibling brain-bridge tests, this does NOT require ArchHub running,
the brain daemon, or QtWebEngine — the brain HTTP I/O is mocked via
monkeypatch on `memory_gate.BrainClient`. The git probe runs for REAL
against the repo this test lives in (a real checkout) — that is the
"real git" half of the gate.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))


# ─────────────────────── fixtures ────────────────────────────────────


class _StubManager:
    """Stand-in for the connector manager — the deck only needs `entries`
    + `active_families` for the non-deck slots; the deck reads connectors
    via `connectors.base.all_connectors()`, not the manager."""
    entries: list = []

    def active_families(self) -> set:
        return set()


@pytest.fixture
def bridge_inst(tmp_path, monkeypatch):
    """A bridge with no router/engine. `auto_extract_memory=False` keeps the
    deferred boot from touching the memory graph."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    import bridge as _bridge_module
    return _bridge_module.ArchHubBridge(
        manager=_StubManager(),
        auto_extract_memory=False,
    )


def _drain(bridge_inst, slot="deck_state", *, tries=300, sleep=0.1):
    """Call a `_cached_async`-backed slot until the background refresh has
    landed (cold first call returns the typed-empty placeholder instantly,
    then the pool fills the cache). Returns the parsed dict.

    The real fan-out probes every connector (`probe()` does COM / multi-port
    broker scans, several seconds total) — that slowness is the WHOLE POINT
    of routing off-thread, so the drain budget is generous (≈30 s ceiling)
    to let the real background work land. The slot itself never blocks; only
    this test waits for the asynchronously-filled cache."""
    last = {}
    for _ in range(tries):
        raw = getattr(bridge_inst, slot)()
        assert isinstance(raw, str)
        last = json.loads(raw)
        if last.get("ready"):
            return last
        time.sleep(sleep)
    return last


# ─────────────────────── slot presence / contract ───────────────────


def test_bridge_has_deck_state_slot():
    """The single new bridge slot must exist + be callable. A silent rename
    breaks the Command Deck panel wiring."""
    from bridge import ArchHubBridge
    assert hasattr(ArchHubBridge, "deck_state"), "Bridge missing deck_state"
    assert callable(ArchHubBridge.deck_state)


def test_deck_state_returns_str_annotation():
    """deck_state returns a `str` (JSON) — the QWebChannel contract."""
    import inspect
    from bridge import ArchHubBridge
    sig = inspect.signature(ArchHubBridge.deck_state)
    ann = sig.return_annotation
    assert ann is str or ann == "str", (
        f"deck_state return annotation is {ann!r}, expected str")


def test_deck_state_returns_parseable_json_instantly(bridge_inst):
    """First (cold) call returns a parseable JSON string immediately —
    never raises, never blocks waiting for a slow source."""
    raw = bridge_inst.deck_state()
    assert isinstance(raw, str)
    data = json.loads(raw)  # MUST parse
    assert isinstance(data, dict)
    # Every tile key is present even on the cold call (typed empties).
    for tile in ("burndown", "brain", "code", "connectors", "inbox",
                 "finances"):
        assert tile in data, f"deck_state missing tile '{tile}': {data}"


def test_deck_state_is_off_thread_non_blocking(bridge_inst, monkeypatch):
    """THREADING INVARIANT — the fan-out runs on the `_cached_async` pool,
    so even a source that sleeps for seconds must NOT block the slot.

    We make the brain call sleep 3s. The slot must return in well under
    that (the cold cache returns instantly; the slow work is on the pool)."""
    import memory_gate

    def slow_call(self, tool, params, timeout=None):
        time.sleep(3.0)
        return {"ok": True}
    monkeypatch.setattr(memory_gate.BrainClient, "_call", slow_call)

    t0 = time.time()
    raw = bridge_inst.deck_state()
    elapsed = time.time() - t0
    assert isinstance(raw, str)
    json.loads(raw)
    # Generous ceiling: the real fan-out is off-thread, so this is just the
    # cheap synchronous cache read. 3s sleep on the brain must not be paid.
    assert elapsed < 1.5, (
        f"deck_state blocked {elapsed:.2f}s — the fan-out is NOT off-thread "
        f"(must route through _cached_async)")


def test_deck_state_slot_not_flagged_blocking():
    """The slot body itself must carry the off-thread marker so the
    maintenance_audit blocking-in-pyqtslot guard stays green. Belt-and-
    braces with test_no_blocking_slots: assert deck_state specifically."""
    import re
    REPO = Path(__file__).resolve().parents[1]
    SCRIPTS = REPO / "scripts"
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import maintenance_audit as ma
    bridge_py = REPO / "app" / "bridge.py"
    lines = bridge_py.read_text(encoding="utf-8").splitlines()
    audit = ma.Audit()
    ma.scan_blocking_in_slot(audit, bridge_py, lines)
    offenders = []
    for f in audit.findings:
        if f.cls != "blocking-in-pyqtslot":
            continue
        m = re.search(r"slot at line (\d+)", f.detail)
        slot_line = int(m.group(1)) if m else f.line
        dm = re.match(r"\s*def\s+([A-Za-z_]\w*)\s*\(", lines[slot_line - 1])
        if dm and dm.group(1) == "deck_state":
            offenders.append(f"bridge.py:{f.line}")
    assert not offenders, (
        "deck_state flagged as blocking the Qt UI thread at "
        + ", ".join(offenders))


# ─────────────────────── real data shape (live reads) ───────────────


def test_deck_state_real_shape_from_live_bridge(bridge_inst, monkeypatch):
    """The CORE gate — drive a live ArchHubBridge with a healthy mocked
    brain + the REAL git probe + REAL connector reads, and assert the full
    typed shape. Offline halves degrade to honest typed empties."""
    import memory_gate

    # Healthy brain: route each brain.* tool to a realistic payload.
    def fake_call(self, tool, params, timeout=None):
        if tool == "brain.health":
            return {"ok": True, "version": "0.1.0", "skills": 7,
                    "facts": 42, "wiring_active": 3,
                    "owner": {"owner_user": "Fargaly", "bound": True}}
        if tool == "brain.tree_list":
            return {"ok": True, "tree_ids": ["tree-A"]}
        if tool == "brain.tree_sweep":
            return {"ok": True, "tree_id": "tree-A", "dry": False,
                    "root_green": False,
                    "counts": {"open": 4, "claimed": 1, "green": 10,
                               "red": 2, "needs_root": 1},
                    "total_leaves": 17, "green_leaves": 10,
                    "actionable_leaves": 7, "needs_root": ["n9"]}
        if tool == "brain.work_status":
            return {"ok": True, "owner_user": "Fargaly", "dry": False,
                    "exists": True,
                    "counts": {"open": 2, "claimed": 1, "done": 5,
                               "blocked": 0},
                    "total": 8, "actionable": 3, "blocked": [],
                    "iterations": 4, "cap": 50}
        if tool == "brain.work_get":
            return {"ok": True, "ledger": {"leaves": [
                {"id": "L1", "state": "claimed",
                 "claim": {"agent_id": "claude", "runtime": "claude-code"},
                 "title": "wire the deck"},
            ]}}
        return {"ok": True}
    monkeypatch.setattr(memory_gate.BrainClient, "_call", fake_call)

    data = _drain(bridge_inst)
    assert data.get("ready") is True, f"deck never became ready: {data}"
    assert isinstance(data.get("generated_at"), str) and data["generated_at"]

    # ── burndown tile ──────────────────────────────────────────────
    bd = data["burndown"]
    assert bd["source"] == "brain.tree_sweep"
    assert bd["available"] is True
    counts = bd["counts"]
    assert counts["green"] == 10 and counts["red"] == 2
    assert counts["open"] == 4 and counts["needs_root"] == 1
    # active-work ledger rides on the same tile (who is on what).
    work = bd["work"]
    assert work["available"] is True
    assert work["source"] == "brain.work_status"
    assert work["counts"]["done"] == 5
    assert isinstance(work["active"], list)
    # the claimed leaf surfaces "who is on what"
    assert any(a.get("who") for a in work["active"]), work["active"]

    # ── brain tile ─────────────────────────────────────────────────
    br = data["brain"]
    assert br["source"] == "brain.health"
    assert br["available"] is True
    assert br["skills"] == 7 and br["facts"] == 42
    assert br["wiring"] == 3

    # ── code tile (REAL git probe) ─────────────────────────────────
    code = data["code"]
    assert code["source"] == "git"
    # This test runs inside a real checkout, so git is available + reports
    # a real branch + a real short commit hash. (If git is somehow broken
    # on the runner, available=False is the honest degrade — assert the
    # typed shape either way.)
    assert "available" in code
    assert "branch" in code and "commit" in code
    assert "uncommitted" in code and isinstance(code["uncommitted"], int)
    if code["available"]:
        assert code["commit"], "available git probe must carry a commit"

    # ── connectors tile (REAL connector reads) ─────────────────────
    conn = data["connectors"]
    assert conn["source"] == "connectors"
    assert isinstance(conn["hosts"], list)
    # honest status buckets are always present (typed), counts are ints.
    for k in ("live", "loaded_dead", "missing", "unauthorized", "probing"):
        assert k in conn["counts"], conn["counts"]
        assert isinstance(conn["counts"][k], int)
    # every host row carries a host id + an honest status string.
    for h in conn["hosts"]:
        assert h.get("host")
        assert h.get("status") in (
            "live", "loaded_dead", "missing", "unauthorized", "probing")

    # ── inbox tile ─────────────────────────────────────────────────
    inbox = data["inbox"]
    assert "available" in inbox and "source" in inbox
    assert "unread" in inbox  # typed even when the source is unreachable

    # ── finances tile ──────────────────────────────────────────────
    fin = data["finances"]
    assert "available" in fin and "source" in fin
    # token cost is a real source (router-reported) — present + typed.
    assert "tokens" in fin and "cost" in fin


def test_deck_state_honest_empty_when_brain_down(bridge_inst, monkeypatch):
    """ANTI-LIE — when the brain daemon is unreachable, the brain-backed
    tiles report available=False with typed empties (never fabricated
    counts). The git + connector tiles still report their real data."""
    import memory_gate

    def dead_call(self, tool, params, timeout=None):
        raise ConnectionRefusedError("daemon down")
    monkeypatch.setattr(memory_gate.BrainClient, "_call", dead_call)
    monkeypatch.setattr(memory_gate.BrainClient, "is_available",
                        lambda self: False)

    data = _drain(bridge_inst)
    assert data.get("ready") is True

    # brain-backed tiles are honestly empty — NOT fabricated.
    assert data["brain"]["available"] is False
    assert data["brain"].get("skills") in (None, 0)
    assert data["burndown"]["available"] is False
    # counts present + zeroed (typed empty), never invented.
    assert data["burndown"]["counts"]["green"] == 0
    assert data["burndown"]["work"]["available"] is False

    # the git + connector tiles are independent of the brain → still typed.
    assert data["code"]["source"] == "git"
    assert data["connectors"]["source"] == "connectors"
    assert isinstance(data["connectors"]["hosts"], list)


def test_deck_state_connectors_status_is_honest(bridge_inst, monkeypatch):
    """The connectors tile reflects REAL connector.probe() honest statuses,
    not a hardcoded list — when a connector reports 'missing', the deck
    surfaces 'missing' (never a fake 'live')."""
    import memory_gate
    monkeypatch.setattr(memory_gate.BrainClient, "_call",
                        lambda self, t, p, timeout=None: {"ok": True})

    data = _drain(bridge_inst)
    conn = data["connectors"]
    # With no host apps running in the test env, the honest aggregate is
    # that NOTHING is fabricated as live — every status is a real probe
    # bucket. (We don't assert a specific host is down — that depends on
    # the runner — only that the statuses are the honest enum + sum.)
    total = sum(conn["counts"][k] for k in
                ("live", "loaded_dead", "missing", "unauthorized", "probing"))
    assert total == len(conn["hosts"]), (
        "connector status buckets must sum to the host count (honest, "
        "no fabricated rows)")
