"""bumpGraph — rAF-coalesced canvas re-render bumper (REAL BEHAVIOR tests).

REWRITTEN 2026-05-28 (MAKE-IT-REAL §7): this file used to PIN DEAD CODE via
INVERTED assertions — it asserted that the `bumpGraphRaf` alias + its
`__archhubBumpGraphRaf` window export were ABSENT. Asserting a string is gone
gives false coverage credit: a safe rename of the real `bumpGraph` would pass
(the absent symbol stays absent) while the live behavior silently broke. Per
the founder's "tests must catch fakes," we replace the absence-pins with
assertions on the REAL coalescing behavior + wiring that bumpGraph must have.

What bumpGraph IS (the behavior these tests pin):
  * a single rAF-coalesced bumper split across TWO functions (refactored
    2026-06-02 — the "WHERE ARE THE WIRES?" visibility fix):
      - `bumpGraph` is the SCHEDULER: a guard ref (`bumpPendingRef`) drops
        duplicate bumps within a frame, then it schedules the flush via
        `requestAnimationFrame(flushGraphBump)` for the live 60Hz foreground
        path AND arms a `setTimeout(flushGraphBump, 32)` fallback (rAF is
        suspended while the window is hidden, so the timer guarantees the
        flush still lands — whichever fires first wins, the other is a no-op).
      - `flushGraphBump` is the rAF CALLBACK / one-frame WORKER: it releases
        the guard (`bumpPendingRef.current = false`), does ONE setState
        (`setGraphBump(b => b+1)`), and fires ONE `lm-graph-bump` dispatch.
    That is the god-counter kill (founder 2026-05-25): render rate drops from
    per-mutation to per-frame. The rAF coalescing is genuine — it just sits
    one layer deeper, behind the scheduler, with a visibility-proof timer
    twin firing the same idempotent flush.
  * exported once on `window.__archhubBumpGraph` (AgDR-0024) for non-React
    callers, and cleaned up on unmount.

LAG-ROOT DECOUPLING (2026-06-01): the streaming chat handlers (onChunk +
onReasoning) NO LONGER call the root `bumpGraph()`. That WAS the lag root —
every streamed token bumped the ROOT, re-rendering the WHOLE app (NodeCanvas +
Workspace) ~60×/sec for the entire AI response, even though the canvas geometry
never changes while text streams. The per-token path now bumps a dedicated
`STREAM_STORE` that ONLY the ConversationRail subscribes to (useSyncExternalStore),
so streaming repaints just the conversation subtree and the canvas stays flat.
A real graph-structure change (onDone, node/wire edits) still calls bumpGraph
once. These tests pin that decoupling so a regression that re-wires streaming
back into the root bump (resurrecting the 60Hz canvas storm) FAILS.

These are structural/behavioral assertions parsed from the JSX. The live-render
proof (NodeCanvas render count staying FLAT across a 30-chunk stream) is
exercised by the render harness in .lagfix_harness/ on the real vendored
Babel+React transform; here we pin the mechanism so a regression to per-call
setState, a lost rAF/dispatch in the flush, a lost export, or streaming
re-coupled to the root bump FAILS.
"""
from __future__ import annotations

import re
from pathlib import Path


JSX = Path(__file__).resolve().parents[1] / "app" / "web_ui" / "studio-lm.jsx"


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


def _callback_body(name: str) -> str:
    """The body of a `const <name> = React.useCallback(() => { … }, [...])`
    declaration, brace-balanced from the arrow's opening brace.

    The leading `const\\s+<name>\\s*=` anchor keeps `bumpGraph` from matching
    `flushGraphBump` (and vice-versa) even though both are useCallback arrows
    that sit adjacent in the source."""
    src = _src()
    m = re.search(
        r"const\s+" + re.escape(name) + r"\s*=\s*React\.useCallback\(\s*\(\)\s*=>\s*\{",
        src,
    )
    assert m, f"{name} must be a React.useCallback arrow"
    brace = src.index("{", m.end() - 1)
    depth, i = 0, brace
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[brace + 1:i]
        i += 1
    return ""


def _bump_graph_body() -> str:
    """The body of `const bumpGraph = React.useCallback(...)` — the SCHEDULER
    half: it sets the reentrancy guard and arms the rAF + timer that run
    `flushGraphBump`. The reset / setState / dispatch live in the flush (see
    `_flush_graph_bump_body`)."""
    return _callback_body("bumpGraph")


def _flush_graph_bump_body() -> str:
    """The body of `const flushGraphBump = React.useCallback(...)` — the rAF
    CALLBACK half: it releases the guard, does the single `setGraphBump(b=>b+1)`
    counter bump, and dispatches the coalesced `lm-graph-bump` event."""
    return _callback_body("flushGraphBump")


# ── 1. bumpGraph really coalesces via rAF + a guard ref ───────────────────

def test_bump_graph_is_raf_coalesced_with_guard():
    """bumpGraph (scheduler) short-circuits on a pending bump, sets the guard,
    and schedules the real work via requestAnimationFrame; flushGraphBump (the
    rAF callback) releases the guard and does the single setState — the
    per-frame coalescing that killed the god-counter render storm.

    Refactored 2026-06-02: the rAF/reset/counter-bump moved out of bumpGraph
    into flushGraphBump (so a setTimeout twin can fire the SAME flush when the
    window is hidden and rAF is suspended). The coalescing is still rAF-driven
    — bumpGraph calls requestAnimationFrame(flushGraphBump) — just one layer
    deeper. Each marker is asserted in the function it now lives in; nothing is
    weakened."""
    body = _bump_graph_body()
    flush = _flush_graph_bump_body()
    # ── scheduler half (bumpGraph) ───────────────────────────────────────
    # Guard ref read + early return (drop duplicate bumps in the same frame).
    assert "bumpPendingRef.current" in body
    assert re.search(r"if\s*\(\s*bumpPendingRef\.current\s*\)\s*return", body), (
        "bumpGraph must early-return when a bump is already pending this frame"
    )
    # Guard is set BEFORE scheduling the frame.
    assert re.search(r"bumpPendingRef\.current\s*=\s*true", body)
    # The actual re-render is scheduled in a rAF (not run synchronously) — the
    # coalescing is genuinely rAF-based, dispatched to flushGraphBump.
    assert "requestAnimationFrame" in body
    assert re.search(r"requestAnimationFrame\(\s*flushGraphBump\s*\)", body), (
        "bumpGraph must coalesce by scheduling flushGraphBump in a rAF"
    )
    # ── rAF-callback half (flushGraphBump) ───────────────────────────────
    # Inside the frame, the guard is released + exactly one counter bump fires.
    assert re.search(r"bumpPendingRef\.current\s*=\s*false", flush), (
        "flushGraphBump (the rAF callback) must release the bump guard"
    )
    assert re.search(r"setGraphBump\(\s*b\s*=>\s*b\s*\+\s*1\s*\)", flush), (
        "the rAF callback (flushGraphBump) must do a single setGraphBump(b => "
        "b+1) — one re-render per frame, not per call"
    )


def test_bump_graph_notifies_non_canvas_listeners_once_per_frame():
    """The coalesced frame also dispatches `lm-graph-bump` so footer surfaces
    (HealthStripItem graph_validate poll) refresh — but coalesced with the rAF,
    never >60 Hz. The dispatch lives in flushGraphBump (the rAF callback, after
    the guard release), so it fires exactly once per coalesced frame."""
    flush = _flush_graph_bump_body()
    assert "lm-graph-bump" in flush, (
        "flushGraphBump must notify non-canvas listeners via the lm-graph-bump "
        "event (footer HealthStripItem graph_validate poll depends on it)"
    )
    assert "dispatchEvent" in flush
    # The dispatch lives INSIDE the rAF callback (after the guard release), so it
    # is coalesced too: exactly one dispatchEvent in the flush body → one event
    # per frame, never per call.
    assert flush.count("dispatchEvent") == 1


def test_bump_graph_useCallback_has_stable_identity():
    """bumpGraph is a useCallback with an empty dep array → stable identity, so
    the 70+ call sites + the window export don't churn every render."""
    src = _src()
    m = re.search(
        r"const\s+bumpGraph\s*=\s*React\.useCallback\([\s\S]*?\}\s*,\s*\[\s*\]\s*\)",
        src,
    )
    assert m, "bumpGraph must be a useCallback with a [] dep array (stable identity)"


# ── 2. The canonical window export is wired + cleaned up ───────────────────

def test_bump_graph_window_export_present_and_cleaned():
    """`window.__archhubBumpGraph = bumpGraph` is set in an effect and removed
    on unmount (AgDR-0024) — non-React callers (CDP, tools) use it."""
    src = _src()
    assert "window.__archhubBumpGraph = bumpGraph" in src
    # Cleanup: the effect returns a teardown that deletes the export.
    assert re.search(
        r"window\.__archhubBumpGraph === bumpGraph[\s\S]{0,120}delete window\.__archhubBumpGraph",
        src,
    ), "the bumpGraph export must be cleaned up on unmount"


# ── 3. The streaming chat handlers actually call bumpGraph ─────────────────

def _strip_line_comments(s: str) -> str:
    """Drop `// …` line comments so assertions match real CODE, not prose
    (the old tests false-passed on a `bumpGraph()` mention inside a comment)."""
    out = []
    for line in s.splitlines():
        i = line.find("//")
        out.append(line if i < 0 else line[:i])
    return "\n".join(out)


def _handler_body(src: str, decl: str, end_marker: str) -> str:
    start = src.find(decl)
    assert start >= 0, f"handler {decl!r} not found"
    end = src.find(end_marker, start)
    assert end > start, f"end marker {end_marker!r} not found after {decl!r}"
    return src[start:end]


def test_chat_chunk_handler_streams_to_store_not_the_canvas():
    """LAG-ROOT FIX: onChunk (streaming text) must bump the dedicated
    STREAM_STORE (conversation-only) and must NOT call the root bumpGraph().
    Bumping the root per token was the 60Hz whole-app re-render storm."""
    src = _src()
    body = _strip_line_comments(
        _handler_body(src, "const onChunk = (sid, piece) =>", "const onDone"))
    assert "STREAM_STORE.bump()" in body, (
        "onChunk must route the per-token update to STREAM_STORE (decoupled "
        "from the canvas)")
    assert "bumpGraph()" not in body, (
        "onChunk must NOT call the root bumpGraph() — that re-renders the whole "
        "app per token (the lag root). Stream updates go to STREAM_STORE only.")


def test_reasoning_handler_streams_to_store_not_the_canvas():
    """LAG-ROOT FIX: onReasoning (streaming reasoning steps) is conversation-
    only too — it must bump STREAM_STORE, not the root bumpGraph()."""
    src = _src()
    body = _strip_line_comments(
        _handler_body(src, "const onReasoning = (sid, step) =>", "const wires = [];"))
    assert "STREAM_STORE.bump()" in body, (
        "onReasoning must route the step update to STREAM_STORE")
    assert "bumpGraph()" not in body, (
        "onReasoning must NOT call the root bumpGraph() — reasoning steps only "
        "change the conversation, so they must not repaint the canvas.")


def test_stream_store_exists_and_conversation_subscribes():
    """The decoupling needs (a) a STREAM_STORE with bump/subscribe/getSnapshot
    and (b) the ConversationRail subscribing to it via useSyncExternalStore so
    streamed tokens repaint ONLY the conversation, never the canvas."""
    src = _src()
    assert re.search(r"STREAM_STORE\b[\s\S]{0,400}subscribe\b", src), (
        "a STREAM_STORE external store (bump/subscribe/getSnapshot) must exist")
    # ConversationRail subscribes to the stream store.
    rail = _handler_body(src, "const ConversationRail = ", "const ThinkingDots")
    assert "useSyncExternalStore(STREAM_STORE.subscribe" in rail, (
        "ConversationRail must subscribe to STREAM_STORE (so it — and not the "
        "canvas — re-renders on each streamed token)")
