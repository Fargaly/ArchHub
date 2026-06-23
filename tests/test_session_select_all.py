"""Home session multi-select — "select all" robustness.

Court finding (feat/session-bulk-delete): SELECT-ALL selected NOTHING.

Root cause: studio-lm.jsx computed `visibleIds` from a `useMemo(..., [sessions])`
where `sessions` (filter == 'all') returns the module-level `LM_SESSIONS`, which
is MUTATED IN PLACE via `.splice` (refreshSessions ~L902, Home effect ~L6365).
The array reference therefore never changes → the memo never recomputes → it
stayed at its first-render (empty, pre-hydration) value → `toggleSelectAll`
produced `new Set([])`.

Fix: recompute the visible/filtered ids FRESH at click time from the live array
+ the active filter (`currentVisibleIds`), and key the render-time memo on the
`_bumpN` state that is bumped on every in-place splice.

This file has two layers:
  1. A behavioral check (`tests/select_all_logic.fixture.mjs`, run via Node)
     that reproduces the in-place-splice mechanism and asserts select-all yields
     the FULL visible set anyway — and that the OLD reference-keyed approach
     would have selected nothing.
  2. Source pins on studio-lm.jsx so the shipped code keeps the fix (the fixture
     can't silently drift from the real handler).
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
JSX = REPO / "app" / "web_ui" / "studio-lm.jsx"
COMPILED = REPO / "app" / "web_ui" / "studio-lm.compiled.js"
FIXTURE = Path(__file__).resolve().parent / "select_all_logic.fixture.mjs"


def _node() -> str | None:
    return shutil.which("node") or shutil.which("node.exe")


# ── 1. Behavioral check via Node ────────────────────────────────────


@pytest.mark.skipif(_node() is None, reason="node not on PATH")
def test_select_all_full_visible_set_under_in_place_mutation():
    """The fixture exercises the exact splice-mutation mechanism and asserts:
    select-all selects EVERY visible card, the OLD reference-keyed path would
    have selected nothing, clear-all clears, filters are respected, and
    shift-range still works."""
    proc = subprocess.run(
        [_node(), str(FIXTURE)],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    assert proc.returncode == 0, f"select-all fixture failed:\n{out}"
    assert "ALL PASS" in out
    # The headline assertions must each be present + passing (no skipped lines).
    assert "FIXED select-all yields the full visible set" in out
    assert "OLD reference-keyed select-all selects nothing" in out
    assert "FAIL:" not in out


# ── 2. Source pins — the shipped fix stays in studio-lm.jsx ─────────


def test_jsx_has_fresh_call_time_visible_ids():
    src = JSX.read_text(encoding="utf-8")
    # The pure, reference-free filter used by both render + handlers.
    assert "const filterSessions = React.useCallback(" in src
    # The fresh-at-call-time recompute over the LIVE LM_SESSIONS array.
    assert "const currentVisibleIds = React.useCallback(" in src
    assert "filterSessions(LM_SESSIONS || [], filter)" in src


def test_toggle_select_all_recomputes_fresh_not_from_stale_memo():
    src = JSX.read_text(encoding="utf-8")
    # toggleSelectAll must take its source of truth from currentVisibleIds()
    # (call-time), not from the splice-stale visibleIds memo.
    i = src.index("const toggleSelectAll = React.useCallback(")
    body = src[i:i + 600]
    assert "currentVisibleIds()" in body, (
        "toggleSelectAll must recompute the visible ids fresh at click time"
    )
    assert "new Set(vis)" in body, "select-all must select every visible id"


def test_visible_ids_memo_keyed_on_bump_state():
    """The render-time visibleIds / sessions memos must depend on the _bumpN
    state (bumped on every in-place splice) so derived render values like
    allVisibleSelected update even when the array reference is unchanged."""
    src = JSX.read_text(encoding="utf-8")
    assert "const [_bumpN, _setBump] = React.useState(0);" in src
    # both memos include _bumpN in their dep arrays
    assert "[filter, allSessions.length, _bumpN, filterSessions]" in src
    assert "[currentVisibleIds, allSessions.length, _bumpN]" in src


def test_compiled_artifact_paired_with_source():
    """compiled.js must be rebuilt from the current .jsx (sha-paired) so the
    running app ships the fix, not a stale precompiled bundle."""
    import hashlib

    src_sha = hashlib.sha256(JSX.read_bytes()).hexdigest()
    head = COMPILED.read_text(encoding="utf-8", errors="replace")[:4096]
    marker = "ARCHHUB_JSX_SRC_SHA256:"
    embedded = None
    for line in head.splitlines():
        idx = line.find(marker)
        if idx != -1:
            embedded = line[idx + len(marker):].strip()
            break
    assert embedded == src_sha, (
        "studio-lm.compiled.js is stale — run: python tools/build_jsx.py --force"
    )
