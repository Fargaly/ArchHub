"""CANVAS-UX finalize lane — REAL behaviour + wiring guards (RED→GREEN).

Two deliverables, both entirely in app/web_ui/studio-lm.jsx:

(A) SPEED — viewport culling. On the software renderer a 400+-node graph
    collapsed to ~6fps because the per-render node/wire pass was O(N) over ALL
    nodes/wires regardless of what was on screen. The fix adds three pure,
    module-scope helpers — worldViewport / bboxInViewport / cullToViewport —
    and funnels both the node map and the wire map through cullToViewport so
    only the on-screen subset (+ a margin) renders → O(visible). The headline
    test EXECUTES the real extracted functions in Node and asserts a 400-node
    graph culls to a small on-screen subset (ROMA: gate on the real artifact,
    not a re-implementation). Plus source guards that the render maps actually
    iterate the culled lists (a perf fix that isn't wired in is a fake).

(B) IN-APP VISIBILITY — three header surfaces that make working backends
    VISIBLE:
      b1 AccountChip   — cloud_status()/cloud_sign_in/cloud_sign_out, email
                         from cloud_signin_done; menu Account / dashboard / sign
                         out; signed-out → "Sign in".
      b2 Brain cold-start — "connecting to brain…" shimmer keyed on brain_ok
                         (get_runtime_info, instant) while the first stats
                         snapshot is cached-empty; offline ONLY after a warmed
                         re-pull — never an instant "offline" on cold start.
      b3 RouterStatus  — header indicator of the active/auto-routed model from
                         get_token_usage().model (real provider-reported),
                         refreshed on lm-usage-bump.

WHY THIS IS RED ON origin/main: none of the helpers, components, or wiring
exist there — the Node cull probe reports ok:false (functions not found) and
the source/compiled guards miss their markers. GREEN on this branch. Proven
via `git stash` in the task report.

The live perf + DOM proof (CDP: render a 400-node graph, read
window.__archhub_cull.rendered << total, drag at >=45fps; the account/brain/
router chips visible in the top nav) is described in the PR — it needs the
running app. Here we gate the mechanism + the wiring so a regression FAILS.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
WEB_UI = REPO / "app" / "web_ui"
JSX = WEB_UI / "studio-lm.jsx"
COMPILED = WEB_UI / "studio-lm.compiled.js"
CULL_PROBE = Path(__file__).resolve().parent / "_fixtures" / "cull_probe.cjs"


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


def _compiled() -> str:
    return COMPILED.read_text(encoding="utf-8")


# Comment-stripped + whitespace-flat views so an assertion can't be satisfied
# by a comment and is tolerant of source line-wrapping (the same hardening the
# existing JSX-guard tests use).
def _code() -> str:
    return re.sub(r"//[^\n]*", "", _src())


def _flat() -> str:
    return re.sub(r"\s+", " ", _code())


def _compiled_flat() -> str:
    return re.sub(r"\s+", " ", _compiled())


def _have_node() -> bool:
    return bool(shutil.which("node") or shutil.which("node.exe"))


def _block(anchor: str, size: int = 1400) -> str:
    code = _code()
    i = code.find(anchor)
    assert i >= 0, f"anchor not found in studio-lm.jsx: {anchor!r}"
    return code[i:i + size]


# ════════════════════════ (A) VIEWPORT CULLING ════════════════════════

# ── A1. The headline behaviour gate: run the REAL functions in Node ──────────
@pytest.mark.skipif(not _have_node(), reason="node not on PATH")
def test_cull_functions_actually_cull_a_400_node_graph():
    """Extract worldViewport / bboxInViewport / cullToViewport from the LIVE
    JSX source and execute them in Node. A 400-node graph must cull to a small
    on-screen subset; the on-screen node is kept, a far node is dropped; a null
    / degenerate viewport returns the FULL list (never hides). This is the perf
    fix proven on the real artifact — on origin/main the functions don't exist,
    so the probe reports ok:false and this FAILS."""
    assert CULL_PROBE.exists(), "cull_probe.cjs fixture missing"
    out = subprocess.run(
        ["node", str(CULL_PROBE), str(JSX)],
        capture_output=True, text=True, timeout=60,
    )
    assert out.returncode == 0, f"probe crashed: {out.stderr or out.stdout}"
    v = json.loads(out.stdout.strip().splitlines()[-1])
    assert v.get("ok") is True, (
        f"cull functions not present/usable in source: {v.get('error')}")
    # The viewport math is real.
    assert v["viewport_nonnull"] is True
    assert v["zero_size_viewport_null"] is True, (
        "an unknown viewport size must yield null (→ render all, never hide)")
    assert v["bad_zoom_viewport_null"] is True
    assert v["nullvp_returns_all"] is True, (
        "cullToViewport(items, …, null) must return the full list unchanged")
    # The headline invariant: 400 nodes → a small on-screen subset.
    assert v["total"] == 400
    assert v["visible_lt_total"] is True, "culling must drop off-screen nodes"
    assert v["visible_small"] is True, (
        f"a 400-node graph must cull to a small subset, got {v['visible_count']}")
    assert v["near_kept"] is True, "an on-screen node must be rendered"
    assert v["far_culled"] is True, "a far-corner node must be culled"
    # Panning to another region shows a different, also-small subset.
    assert v["region2_small"] is True
    assert v["region2_disjoint_ish"] is True
    # Margin behaviour kills pop-in without re-inflating the count.
    assert v["margin_keeps_edge"] is True, (
        "a node straddling the margin edge must stay mounted (no pop-in)")
    assert v["beyond_margin_dropped"] is True, (
        "a node well beyond the margin must be dropped")


# ── A2. Source guards: the helpers exist + the render maps use the culled sets
def test_cull_helpers_defined_at_module_scope():
    code = _code()
    assert re.search(r"const\s+worldViewport\s*=\s*\(", code), (
        "worldViewport (screen→world viewport) helper must exist")
    assert re.search(r"const\s+bboxInViewport\s*=\s*\(", code), (
        "bboxInViewport (AABB intersection w/ margin) helper must exist")
    assert re.search(r"const\s+cullToViewport\s*=\s*\(", code), (
        "cullToViewport (the single cull chokepoint) helper must exist")
    # A real world-px margin constant (the pop-in guard), not a literal 0.
    assert re.search(r"const\s+CULL_MARGIN\s*=\s*\d+", code)


def test_node_render_map_iterates_culled_set_not_all_nodes():
    """The node map must iterate the culled `visibleNodesSrc`, NOT `allNodes`
    directly — otherwise the O(N) pass is untouched and the perf fix is a fake.
    On origin/main the map is `(allNodes || []).map(n =>` (no cull)."""
    flat = _flat()
    assert "visibleNodesSrc.map(n =>" in flat, (
        "the node render map must iterate the viewport-culled visibleNodesSrc")
    # And the culled set is actually built from cullToViewport.
    assert "cullToViewport(allNodes" in flat or "cullToViewport((allNodes" in flat, (
        "visibleNodesSrc must be derived via cullToViewport over allNodes")


def test_wire_render_map_iterates_culled_set_not_all_wires():
    """The wire map must iterate the culled `visibleWires`, NOT the full
    `wires` memo. On origin/main it is `wires.map(w =>` (no cull)."""
    flat = _flat()
    assert "visibleWires.map(w =>" in flat, (
        "the wire render map must iterate the viewport-culled visibleWires")
    assert re.search(r"visibleWires\s*=\s*React\.useMemo\([\s\S]{0,200}cullToViewport\(\s*wires",
                     _code()), (
        "visibleWires must be derived via cullToViewport over the wires memo")


def test_cull_keeps_focused_and_selected_nodes_mounted():
    """Correctness over cull: a focused/selected node dragged off-screen must
    stay mounted (the rail inspects it; multi-drag acts on it). The cull memo
    must re-add focusId / selectedIds members the viewport test dropped."""
    block = _block("const visibleNodesSrc", size=900)
    assert "focusId" in block and "selectedIds" in block, (
        "visibleNodesSrc must always keep the focused + selected nodes mounted")


def test_cull_exposes_live_stats_for_cdp_proof():
    """A machine-readable seam for the CDP perf proof: window.__archhub_cull
    carries {total, rendered, ...} so the verifier can assert rendered<<total
    on a big graph. (The live drag-fps proof is described in the PR.)"""
    code = _code()
    assert "window.__archhub_cull" in code
    assert re.search(r"__archhub_cull\s*=\s*\{[\s\S]{0,200}rendered", code)


# ════════════════════════ (B) IN-APP VISIBILITY ════════════════════════

# ── b1. Account chip ─────────────────────────────────────────────────────────
def test_account_chip_component_exists_and_mounted_in_header():
    code = _code()
    assert re.search(r"const\s+AccountChip\s*=\s*\(", code), (
        "AccountChip component must exist")
    # Mounted in the top-nav header (WsHeader renders it).
    assert "<AccountChip" in code, "AccountChip must be mounted in the header"
    # Anchored next to the other header chips so it's genuinely top-nav.
    assert re.search(r"<BrainChip[\s\S]{0,80}<AccountChip", _flat()) or \
           re.search(r"<AccountChip[\s\S]{0,80}<BrainChip", _flat()), (
        "AccountChip must sit in the header chip cluster")


def test_account_chip_uses_real_cloud_status_slot():
    """The chip drives its signed-in/out state from the EXISTING cheap
    cloud_status() slot (no fabricated state)."""
    block = _block("const AccountChip", size=8000)
    assert "bridgeAsync('cloud_status')" in block, (
        "AccountChip must read the real cloud_status() slot")
    assert "signed_in" in block, "AccountChip must read the signed_in flag"
    assert "cloud_url" in block, "AccountChip must read cloud_url for the dashboard"


def test_account_chip_reads_email_from_signin_signal_not_fabricated():
    """The email shown comes from the real cloud_signin_done signal payload —
    never invented. Signed-out flips back via cloud_signout_done."""
    block = _block("const AccountChip", size=8000)
    assert "cloud_signin_done" in block, (
        "AccountChip must listen to cloud_signin_done for the real email")
    assert "cloud_signout_done" in block, (
        "AccountChip must listen to cloud_signout_done to flip back to signed-out")
    assert "res.email" in block or ".email" in block, (
        "the displayed email must come from the signal payload")


def test_account_chip_menu_has_account_dashboard_signout():
    """Signed-in menu: Account / Open cloud dashboard / Sign out — and Sign out
    calls the REAL cloud_sign_out slot (server revoke + local clear)."""
    block = _block("const AccountChip", size=8000)
    assert "Account" in block
    assert "Open cloud dashboard" in block
    assert "Sign out" in block
    assert "bridgeAsync('cloud_sign_out')" in block, (
        "Sign out must call the real cloud_sign_out slot")
    # Account routes to the real Settings → Account surface.
    assert "section:'account'" in re.sub(r"\s+", "", block) or \
           "section: 'account'" in block


def test_account_chip_signed_out_shows_sign_in_cta():
    """Signed-out state shows a real "Sign in" CTA that drives the actual PKCE
    browser sign-in (cloud_sign_in), with the Settings fallback."""
    block = _block("const AccountChip", size=8000)
    assert "Sign in" in block
    assert "bridgeAsync('cloud_sign_in')" in block, (
        "the signed-out CTA must drive the real cloud_sign_in flow")
    assert 'data-account-state="signed-out"' in block


# ── b2. Brain cold-start shimmer ─────────────────────────────────────────────
def test_brain_chip_has_connecting_shimmer_keyed_on_brain_ok():
    """While the first stats snapshot is the cached-empty one, the chip shows a
    "connecting to brain…" shimmer keyed on brain_ok (get_runtime_info) — NOT
    an offline error. On origin/main the cold state is a dead "idle" with no
    brain_ok probe and no shimmer."""
    block = _block("const BrainChip", size=7600)
    assert "connecting to brain" in block, (
        "BrainChip must show a 'connecting to brain…' cold-start label")
    assert "get_runtime_info" in block, (
        "the cold-start state must be keyed on the instant brain_ok probe "
        "(get_runtime_info), not on the slow first stats snapshot")
    assert "brain_ok" in block
    # A real shimmer animation, not a static label.
    assert "lmBrainShimmer" in block
    assert "@keyframes lmBrainShimmer" in _src(), (
        "the shimmer keyframes must be defined in the global styles")


def test_brain_offline_only_after_warmed_repull():
    """The "offline" verdict must be gated on a warm-up — a cold cached-empty
    with brain_ok unknown must NEVER read offline. The fix introduces a
    `warmed` gate so offline only shows after a real re-pull confirms down."""
    block = _block("const BrainChip", size=7600)
    assert "warmed" in block, (
        "BrainChip must gate 'offline' on a warmed re-pull (no instant offline "
        "on cold start)")
    assert "connecting" in block
    # The offline expression references warmed (so cold-empty can't be offline).
    assert re.search(r"offline\s*=\s*[\s\S]{0,160}warmed", block), (
        "the offline derivation must depend on `warmed`")
    # A connecting state must NOT also be flagged offline.
    assert re.search(r"connecting\s*=\s*[^\n;]*brainOk\s*!==\s*false", block), (
        "connecting must hold while the daemon socket is up (brainOk !== false)")


# ── b3. Router status ────────────────────────────────────────────────────────
def test_router_status_component_exists_and_mounted():
    code = _code()
    assert re.search(r"const\s+RouterStatus\s*=\s*\(", code), (
        "RouterStatus component must exist")
    assert "<RouterStatus" in code, "RouterStatus must be mounted in the header"


def test_router_status_reads_real_routed_model():
    """The active/auto-routed model is the REAL provider-reported model from
    get_token_usage().model, refreshed on lm-usage-bump. Not a client guess."""
    block = _block("const RouterStatus", size=2400)
    assert "bridgeAsync('get_token_usage')" in block, (
        "RouterStatus must read the real provider-reported model from "
        "get_token_usage()")
    assert ".model" in block, "RouterStatus must read the routed model field"
    assert "lm-usage-bump" in block, (
        "RouterStatus must refresh on lm-usage-bump (the real usage event)")
    # Honest fallback to the selected model when no completion has landed yet.
    assert "model.name" in block


# ════════════════════════ COMPILED BUNDLE PARITY ════════════════════════
# The app loads the .compiled.js — the wiring must be present there too, not
# only in source (same parity gate the existing JSX-guard tests enforce).
def test_cull_in_compiled_bundle():
    cf = _compiled_flat()
    assert "cullToViewport" in cf
    assert "visibleNodesSrc.map(n=>" in cf or "visibleNodesSrc.map(n =>" in cf
    assert "visibleWires.map(w=>" in cf or "visibleWires.map(w =>" in cf
    assert "__archhub_cull" in _compiled()


def test_visibility_chips_in_compiled_bundle():
    comp = _compiled()
    assert "AccountChip" in comp
    assert "RouterStatus" in comp
    assert "connecting to brain" in comp
    assert "cloud_sign_out" in comp
    assert "get_token_usage" in comp


def test_compiled_artifact_sha_matches_source():
    """Belt-and-braces with the existing precompile test: the committed bundle
    must be freshly built from this source (else the app boots stale code)."""
    import hashlib
    live = hashlib.sha256(JSX.read_bytes()).hexdigest()
    head = COMPILED.read_text(encoding="utf-8")[:4096]
    m = re.search(r"ARCHHUB_JSX_SRC_SHA256:\s*([0-9a-f]{64})", head)
    assert m, "compiled bundle missing its source-sha header"
    assert m.group(1) == live, (
        "compiled bundle is STALE — run `python tools/build_jsx.py`")
