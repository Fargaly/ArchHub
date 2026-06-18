"""Self-Heal Inspector — the heal-event timeline (lane SELF-HEAL-INSPECTOR).

ArchHub's differentiator is its self-healing connectors: hosts reconnect,
connector add-ins re-NETLOAD, and graph wires re-route off type-mismatched
ports WITHOUT the user restarting anything. The app already had health
INDICATORS (GraphHealthBadge, HomeGraphHealthChip, the connector_health
daemon, host_detector reconnect) — but NO heal-event TIMELINE the user could
see. This lane adds that, reading REAL events (MAKE-IT-REAL / ANTI-LIE — it
never synthesises rows).

This gate proves four things and is a real RED->GREEN check — `git stash` the
edits and the relevant parts go RED:

  1. app/self_heal_log.py — the process-wide bounded ring buffer:
     record_heal / recent / stats work, recent is NEWEST-FIRST, stats count
     by kind, and the ring CAPS at maxlen (oldest evicts). (Stashing the new
     module makes import fail → RED.)
  2. The bridge slots self_heal_recent / self_heal_stats / record_heal return
     the REAL ledger data, on a live ArchHubBridge. (Stashing bridge.py
     removes the slots → AttributeError → RED.)
  3. record_heal posted by the JSX lands in the SAME ledger (the JS-side
     graph-heal path → bridge.record_heal → self_heal_log).
  4. The JSX SelfHealInspector renders a STAT HEADER + a reverse-chron
     TIMELINE of real events + the HONEST empty state, is mounted at the
     StudioLM root, is reachable from the existing graph-health chip + badge,
     carries data-testid=self-heal-inspector, AND that wiring is present in
     the COMPILED bundle the app actually boots. (Stashing studio-lm.jsx /
     the recompiled .compiled.js makes these vanish → RED.)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parents[1] / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

_JSX_SRC = (APP_ROOT / "web_ui" / "studio-lm.jsx").read_text(encoding="utf-8")
_COMPILED = (APP_ROOT / "web_ui" / "studio-lm.compiled.js").read_text(
    encoding="utf-8")
# Comment-stripped view so an assertion can't be satisfied by a comment, and
# whitespace-flat views so spacing / line-wrap differences never break a match
# (the compiled bundle strips inter-token spaces).
_JSX_CODE = re.sub(r"//[^\n]*", "", _JSX_SRC)
_JSX_FLAT = re.sub(r"\s+", " ", _JSX_CODE)
_COMPILED_FLAT = re.sub(r"\s+", " ", _COMPILED)


def _jsx_window(anchor: str, size: int = 6000) -> str:
    i = _JSX_CODE.find(anchor)
    assert i >= 0, f"anchor not found in studio-lm.jsx: {anchor!r}"
    return _JSX_CODE[i:i + size]


# ════════════════════════════════════════════════════════════════════
# PART 1 — self_heal_log.py: the real ring buffer (record/recent/stats/cap)
# ════════════════════════════════════════════════════════════════════
@pytest.fixture
def shl():
    """The heal ledger, cleared before + after so tests are isolated and
    deterministic (the ring is a module-level singleton)."""
    import self_heal_log as _shl
    _shl.clear()
    yield _shl
    _shl.clear()


def test_record_and_recent_roundtrip_newest_first(shl):
    """record_heal stores a real event; recent returns it NEWEST FIRST with
    the full shape the inspector renders."""
    shl.record_heal(shl.KIND_RECONNECT, "revit", "listener answered on :48884")
    shl.record_heal(shl.KIND_NETLOAD, "autocad", "add-in re-loaded")
    out = shl.recent(10)
    assert isinstance(out, list) and len(out) == 2
    # newest first → autocad netload leads.
    assert out[0]["kind"] == "netload" and out[0]["target"] == "autocad"
    assert out[1]["kind"] == "reconnect" and out[1]["target"] == "revit"
    # full event shape.
    ev = out[0]
    for key in ("id", "kind", "target", "detail", "ts"):
        assert key in ev, f"missing {key} in event {ev}"
    assert isinstance(ev["ts"], float)


def test_stats_counts_by_kind_and_last(shl):
    """stats summarises the ledger for the inspector's stat header — total,
    by-kind counts, and the most-recent heal."""
    shl.record_heal(shl.KIND_RECONNECT, "revit", "a")
    shl.record_heal(shl.KIND_RECONNECT, "blender", "b")
    shl.record_heal(shl.KIND_TYPE_HEAL, "graph", "wire re-routed")
    st = shl.stats()
    assert st["total"] == 3
    assert st["by_kind"]["reconnect"] == 2
    assert st["by_kind"]["type_heal"] == 1
    assert st["by_kind"]["netload"] == 0  # untouched kinds stay zero, not absent
    assert st["last_kind"] == "type_heal" and st["last_target"] == "graph"
    assert isinstance(st["last_heal_ts"], float)
    assert st["max"] == shl.MAX_EVENTS


def test_empty_stats_is_honest_zero(shl):
    """Honest empty state: nothing healed -> all zero / None, never fake."""
    st = shl.stats()
    assert st["total"] == 0
    assert st["last_heal_ts"] is None and st["last_kind"] is None
    assert all(v == 0 for v in st["by_kind"].values())
    assert shl.recent(10) == []


def test_ring_caps_at_maxlen(shl):
    """The deque(maxlen=N) ring is BOUNDED — beyond the cap the oldest
    events evict, so a flapping host can never grow this unbounded."""
    cap = shl.MAX_EVENTS
    for i in range(cap + 50):
        shl.record_heal(shl.KIND_OTHER, f"h{i}", f"detail {i}")
    # recent() can never exceed the cap, even asked for more.
    assert len(shl.recent(cap + 999)) == cap
    assert shl.stats()["total"] == cap
    # The oldest (h0..h49) evicted; the newest survives + leads.
    newest = shl.recent(1)[0]
    assert newest["target"] == f"h{cap + 50 - 1}"
    oldest_targets = {e["target"] for e in shl.recent(cap)}
    assert "h0" not in oldest_targets


def test_unknown_kind_buckets_to_other_not_dropped(shl):
    """A producer that reports an unknown kind still gets its REAL heal
    recorded (bucketed 'other'), never silently dropped."""
    shl.record_heal("totally_made_up_kind", "x", "still real")
    out = shl.recent(1)
    assert len(out) == 1 and out[0]["kind"] == "other"
    assert out[0]["target"] == "x"


# ════════════════════════════════════════════════════════════════════
# PART 2 — bridge slots return the REAL ledger (live ArchHubBridge)
# ════════════════════════════════════════════════════════════════════
@pytest.fixture
def bridge_inst(tmp_path, monkeypatch):
    """A live ArchHubBridge (real QObject so self_heal_changed is a real
    signal). defer_boot=False so construction has no background thread."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    import bridge as _bridge_module
    import self_heal_log as _shl
    _shl.clear()
    inst = _bridge_module.ArchHubBridge(
        tools=None, defer_boot=False, auto_extract_memory=False)
    yield inst
    _shl.clear()


def test_bridge_slots_return_real_log(bridge_inst):
    """self_heal_recent + self_heal_stats read the live ledger: empty first,
    then reflect a recorded heal."""
    import self_heal_log as _shl
    # Empty ledger -> honest empty state through the slots.
    assert json.loads(bridge_inst.self_heal_recent("50")) == []
    st0 = json.loads(bridge_inst.self_heal_stats())
    assert st0["total"] == 0 and st0["last_heal_ts"] is None
    # Record a REAL heal, then the slots surface it.
    _shl.record_heal(_shl.KIND_RECONNECT, "revit", "reconnected")
    recent = json.loads(bridge_inst.self_heal_recent("50"))
    assert len(recent) == 1 and recent[0]["target"] == "revit"
    st1 = json.loads(bridge_inst.self_heal_stats())
    assert st1["total"] == 1 and st1["by_kind"]["reconnect"] == 1


def test_bridge_record_heal_slot_lands_in_ledger(bridge_inst):
    """The record_heal slot (the JSX type-heal path's sink) writes a REAL
    event into the SAME ledger the read slots serve."""
    res = json.loads(bridge_inst.record_heal(json.dumps(
        {"kind": "type_heal", "target": "graph",
         "detail": "1 wire re-routed off a type-mismatched port"})))
    assert "error" not in res, res
    assert res["kind"] == "type_heal" and res["target"] == "graph"
    # It is now visible through the read slots — same store.
    recent = json.loads(bridge_inst.self_heal_recent("50"))
    assert any(e["detail"].startswith("1 wire re-routed") for e in recent)
    assert json.loads(bridge_inst.self_heal_stats())["by_kind"]["type_heal"] == 1


def test_bridge_has_self_heal_changed_signal(bridge_inst):
    """The live-refresh signal the inspector listens on exists + is emittable
    (a heal landing nudges the UI to re-pull without polling)."""
    from PyQt6.QtCore import pyqtBoundSignal
    sig = getattr(bridge_inst, "self_heal_changed", None)
    assert isinstance(sig, pyqtBoundSignal)
    sig.emit()  # must not raise


# ════════════════════════════════════════════════════════════════════
# PART 3 — the JSX inspector: stat header + timeline + honest empty state
# ════════════════════════════════════════════════════════════════════
def test_inspector_component_exists_with_testid():
    """The panel carries data-testid=self-heal-inspector (the task's required
    handle) and is a real component, in source + compiled bundle."""
    assert "SelfHealInspector" in _JSX_CODE
    assert 'data-testid="self-heal-inspector"' in _JSX_CODE
    # Compiled bundle the app actually boots carries it too (sha-paired build).
    assert "self-heal-inspector" in _COMPILED
    assert "SelfHealInspector" in _COMPILED


def test_inspector_reads_real_slots_not_fake_data():
    """MAKE-IT-REAL / ANTI-LIE: the inspector sources its rows from the REAL
    bridge slots, never a hard-coded sample array."""
    win = _jsx_window("const SelfHealInspectorInner", 7000)
    assert "self_heal_recent" in win
    assert "self_heal_stats" in win
    # No fabricated default like the prototype's `heals: 47` seed.
    assert "47" not in win, "inspector must not ship a fabricated heal count"


def test_inspector_renders_stat_header():
    """A stat header: total heals + last-heal + by-kind counts."""
    win = _jsx_window("const SelfHealInspectorInner", 11000)
    assert 'data-testid="self-heal-stats"' in win
    # total + last-heal labels, both fed from the REAL stats payload.
    assert "self-heals" in win and "last heal" in win
    assert "total" in win and "by_kind" in win
    assert "last_heal_ts" in win


def test_inspector_renders_reverse_chron_timeline():
    """A reverse-chronological timeline of real events — each event row with
    kind icon, target, detail, relative time."""
    win = _jsx_window("const SelfHealInspectorInner", 11000)
    assert 'data-testid="self-heal-timeline"' in win
    assert 'data-testid="self-heal-event"' in win
    assert "newest first" in win  # the reverse-chron label
    # event fields rendered.
    assert "ev.target" in win and "ev.detail" in win
    assert "_selfHealRel" in win  # relative-time of the event ts


def test_inspector_has_honest_empty_state():
    """The empty state is the HONEST 'no self-heals yet — connectors healthy',
    NOT fabricated rows."""
    win = _jsx_window("const SelfHealInspectorInner", 11000)
    assert 'data-testid="self-heal-empty"' in win
    assert "No self-heals yet" in win
    assert "healthy" in win


def test_inspector_uses_canonical_tokens():
    """Calm aesthetic + canonical tokens: terracotta accent (LM.accent) +
    mono timestamps (LM.mono)."""
    win = _jsx_window("const SelfHealInspectorInner", 11000)
    assert "LM.accent" in win   # terracotta
    assert "LM.mono" in win     # mono timestamps


def test_inspector_mounted_at_root_and_reachable():
    """DEFINITION-OF-SHIPPED: mounted at the StudioLM root AND reachable from
    the existing graph-health chip + badge — a continuous UI path."""
    # Mounted at the root modal block.
    assert "<SelfHealInspector" in _JSX_CODE
    # The open event the entry points fire.
    assert "lm-self-heal-inspector-open" in _JSX_CODE
    # Home chip opens it (was a dead toast hint before).
    chip = _jsx_window("home-graph-health-chip", 1400)
    assert "lm-self-heal-inspector-open" in chip
    # Both graph-health panels expose a self-heal entry button.
    assert 'data-testid="graph-health-self-heal"' in _JSX_CODE
    assert 'data-testid="health-strip-self-heal"' in _JSX_CODE
    # And the wiring is in the COMPILED bundle.
    assert "lm-self-heal-inspector-open" in _COMPILED


def test_js_heal_paths_post_to_record_heal():
    """The in-browser graph-heal paths (the heals Python can't see on its own)
    post to bridge.record_heal so they land in the same ledger."""
    # The shared helper.
    assert "const recordHeal" in _JSX_CODE
    assert "record_heal" in _JSX_CODE
    # The type-mismatch re-route records a type_heal.
    resnap = _jsx_window("_resnapTypeMismatch = ", 2400)
    assert "recordHeal('type_heal'" in resnap or 'recordHeal("type_heal"' in resnap
    # The port-change wire re-map records a wire_remap (only on a real re-point).
    remap = _jsx_window("remapWiresForNode = ", 2400)
    assert "wire_remap" in remap
    assert "remapped" in remap  # counts only wires SAVED, not dropped


def test_compiled_bundle_is_sha_paired():
    """The compiled bundle must be rebuilt from the current JSX (sha-paired),
    so the app boots exactly this code — not a stale bundle."""
    import hashlib
    src_sha = hashlib.sha256(
        (APP_ROOT / "web_ui" / "studio-lm.jsx").read_bytes()).hexdigest()
    head = _COMPILED[:800]
    m = re.search(r"SHA256:\s*([0-9a-f]{64})", head)
    assert m, "compiled bundle missing embedded source SHA header"
    assert m.group(1) == src_sha, (
        "compiled.js is STALE vs studio-lm.jsx — run python tools/build_jsx.py")
