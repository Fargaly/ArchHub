"""Self-check for the static fake-gate — proves it CATCHES a re-introduced fake.

The MAKE-IT-REAL §7 requirement has TWO halves, both proven in CI:
  1. the now-wired UI PASSES the gate            → test_ui_fake_gate.py
  2. a deliberately re-introduced fake FAILS it  → THIS FILE

A gate that only ever passes is worthless — it would pass a naked shell too.
So here we feed the gate's own scanners (imported from test_ui_fake_gate) a
mutated source string with a fake INJECTED, and assert the scanner flags it.
We mutate an IN-MEMORY copy of the real studio-lm.jsx — the file on disk is
never touched, so this is safe to run concurrently with the parallel session
editing the JSX.

Each test pairs a NEGATIVE (real source → scanner clean) with a POSITIVE
(injected fake → scanner flags it). That pairing is the founder's "show both
runs": the gate distinguishes real wiring from a shell.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from test_ui_fake_gate import (
    scan_dead_end_handlers,
    scan_fabricated_strings,
    scan_dead_dispatches,
    _INTERACTION_EVENTS,
)

JSX = Path(__file__).resolve().parents[1] / "app" / "web_ui" / "studio-lm.jsx"


def _real_src() -> str:
    return JSX.read_text(encoding="utf-8")


# A real React fragment with a real, wired control — the baseline the gate
# must accept. Mirrors the shape of the actual ServerStrip / AIBody wiring.
_REAL_FRAGMENT = """
const RealPanel = ({ onClose, n }) => {
  const [v, setV] = React.useState('');
  const submit = React.useCallback(() => {
    bridgeCall('send_chat_history', currentSid(), v, JSON.stringify([]));
  }, [v]);
  return (
    <div>
      <input value={v} onChange={e => setV(e.target.value)} />
      <button onClick={submit}>Send</button>
      <button onClick={() => onClose()}>Cancel</button>
      <span>{tokFmt(usage.tokens)} tok · {costFmt(usage.tokens)}</span>
    </div>
  );
};
"""


# ───────────────────────────────────────────────────────────────────────────
# (A) NAKED INTERACTIVE DEAD-END — the "button for show"
# ───────────────────────────────────────────────────────────────────────────

# A button with a handler that does literally nothing — the founder's exact
# "buttons are for show" complaint.
_NAKED_SHELLS = (
    '<button onClick={() => {}}>Save</button>',            # empty arrow
    '<button onClick={() => null}>Save</button>',          # no-op return
    '<button onClick={() => { /* TODO wire this */ }}>Save</button>',  # comment-only
    '<button onClick={() => undefined}>Preview</button>',  # undefined
)


def test_real_fragment_has_no_dead_ends():
    """NEGATIVE: a genuinely-wired fragment trips no dead-end finding."""
    assert scan_dead_end_handlers(_REAL_FRAGMENT) == []


@pytest.mark.parametrize("shell", _NAKED_SHELLS)
def test_injected_naked_button_is_flagged(shell):
    """POSITIVE: injecting a do-nothing button into the REAL source makes the
    dead-end scanner flag exactly it. The disk file is never modified."""
    mutated = _real_src() + "\n" + shell + "\n"
    dead = scan_dead_end_handlers(mutated)
    assert dead, f"gate failed to catch a naked shell: {shell!r}"
    # The flagged body is the injected no-op, not some pre-existing handler.
    bodies = " ".join(b for _, b in dead)
    assert "{}" in bodies or "null" in bodies or "undefined" in bodies or \
           "TODO" in bodies


def test_real_source_alone_has_zero_dead_ends():
    """NEGATIVE (full file): the real, wired studio-lm.jsx has no dead-end
    handlers — so any finding in the POSITIVE case is the injection, not noise."""
    assert scan_dead_end_handlers(_real_src()) == []


# ───────────────────────────────────────────────────────────────────────────
# (B) FABRICATED CHROME STRING — hardcoded telemetry / date
# ───────────────────────────────────────────────────────────────────────────

# The literal fakes the founder kept catching, plus variants (different numbers
# must still be caught — the gate matches the SHAPE, not one constant).
_FAKE_STRINGS = (
    '<span>· 4.2k tok · $0.024 · server :7300</span>',     # the original
    '<span>1.1k tok · $0.009</span>',                       # different numbers
    "<div>{'WEDNESDAY · MAY 13'}</div>",                    # the original divider
    "<div>{'MONDAY · JUN 3'}</div>",                        # different day
    '<span>server :9223</span>',                            # hardcoded port
)


def test_real_fragment_has_no_fabricated_strings():
    """NEGATIVE: derived usage (tokFmt/costFmt templates) is not flagged."""
    assert scan_fabricated_strings(_REAL_FRAGMENT) == []


@pytest.mark.parametrize("fake", _FAKE_STRINGS)
def test_injected_fabricated_string_is_flagged(fake):
    """POSITIVE: injecting a hardcoded telemetry/date literal into the REAL
    source makes the fabricated-string scanner flag it."""
    mutated = _real_src() + "\n" + fake + "\n"
    hits = scan_fabricated_strings(mutated)
    assert hits, f"gate failed to catch a fabricated string: {fake!r}"


def test_real_source_alone_has_zero_fabricated_strings():
    """NEGATIVE (full file): the real, wired studio-lm.jsx has no fabricated
    telemetry/date literals (the old ones survive only in audit comments,
    which the scanner strips)."""
    assert scan_fabricated_strings(_real_src()) == []


def test_derived_token_label_is_not_a_false_positive():
    """A real data-derived label like `{m.tokens_out} tok` (no literal number,
    no cost) must NOT be flagged — only the literal usage+cost shape is a fake."""
    real_label = "<span>{m.tokens_in || 0} → {m.tokens_out || 0} tok</span>"
    assert scan_fabricated_strings(real_label) == []


# ───────────────────────────────────────────────────────────────────────────
# (C) DEAD DISPATCH — a load-bearing interaction event with no listener
# ───────────────────────────────────────────────────────────────────────────


def test_focus_node_dispatch_with_listener_is_clean():
    """NEGATIVE: lm-focus-node dispatched AND listened (the real, fixed state)
    is not flagged."""
    paired = (
        "window.dispatchEvent(new CustomEvent('lm-focus-node', {detail:{node_id:'n1'}}));"
        "\nwindow.addEventListener('lm-focus-node', onFocusNode);"
    )
    assert scan_dead_dispatches(paired, names=_INTERACTION_EVENTS) == []


def test_injected_dead_focus_node_dispatch_is_flagged():
    """POSITIVE: re-introduce the founder's exact bug — dispatch lm-focus-node
    with NO listener — and the scanner flags it. We simulate the regression by
    scanning a fragment that dispatches the event but never listens."""
    # A fragment that fires the load-bearing event but registers no listener.
    regressed = (
        "const Health = () => "
        "<div onClick={() => window.dispatchEvent("
        "new CustomEvent('lm-focus-node', {detail:{node_id:'n1'}}))}>issue</div>;"
    )
    orphans = scan_dead_dispatches(regressed, names=_INTERACTION_EVENTS)
    names = [n for n, _ in orphans]
    assert "lm-focus-node" in names, (
        "gate failed to catch a load-bearing interaction event dispatched "
        "with no listener (the lm-focus-node bug class)"
    )


def test_real_source_interaction_events_all_have_listeners():
    """NEGATIVE (full file): every curated interaction event dispatched by the
    real studio-lm.jsx has a listener — the gate is green on real wiring."""
    assert scan_dead_dispatches(_real_src(), names=_INTERACTION_EVENTS) == []
