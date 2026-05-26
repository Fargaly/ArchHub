"""AgDR-0032 — rAF-coalesced bumpGraph for streaming chat.

INVERTED 2026-05-26 per AgDR-0047 §C4 + Q1 founder pick: the cosmetic
`bumpGraphRaf` alias + its `__archhubBumpGraphRaf` window export have
been removed. The rAF-coalescing behavior is preserved — it now lives
inside `bumpGraph` itself, and the two call sites (onChunk + onReasoning)
call `bumpGraph()` directly.

Original pins:
  - bumpGraphRaf defined alongside bumpGraph                ← REMOVED
  - exposed on window so external callers can choose                ← REMOVED
  - onChunk + onReasoning use the coalesced variant         ← STILL TRUE via bumpGraph

Inverted pins:
  - bumpGraphRaf is GONE (no alias, no window export)
  - bumpGraph still uses requestAnimationFrame + bumpPendingRef
  - onChunk + onReasoning still bump after work (via bumpGraph)
"""
from __future__ import annotations

from pathlib import Path


JSX = Path(__file__).resolve().parents[1] / "app" / "web_ui" / "studio-lm.jsx"


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


def test_bump_graph_raf_alias_removed():
    src = _src()
    # The alias declaration is gone — only `bumpGraph` survives as the
    # rAF-coalesced bumper.
    assert "const bumpGraphRaf" not in src, (
        "AgDR-0047 §C4 (2026-05-26): `bumpGraphRaf` alias was removed; "
        "bumpGraph itself coalesces via rAF — single symbol, same behavior."
    )
    # No call site should reference the removed alias either.
    assert "bumpGraphRaf()" not in src


def test_bump_graph_window_export_intact_raf_export_removed():
    src = _src()
    # The canonical `__archhubBumpGraph` survives per AgDR-0024.
    assert "window.__archhubBumpGraph = bumpGraph" in src
    # The cosmetic `__archhubBumpGraphRaf` export is gone.
    assert "__archhubBumpGraphRaf" not in src


def test_bump_graph_still_coalesces_via_raf():
    src = _src()
    # The coalescing mechanism stays — just on `bumpGraph` instead of the alias.
    assert "requestAnimationFrame" in src
    assert "bumpPendingRef" in src


def test_chat_chunk_calls_bump_graph():
    src = _src()
    # onChunk handler still bumps after the streaming update; it now
    # calls bumpGraph() directly (which is the coalesced rAF version).
    start = src.find("const onChunk = (sid, piece) =>")
    assert start >= 0
    end = src.find("const onDone", start)
    assert end > start
    body = src[start:end]
    assert "bumpGraph()" in body


def test_reasoning_calls_bump_graph():
    src = _src()
    start = src.find("const onReasoning = (sid, step) =>")
    assert start >= 0
    end = src.find("const wires = [];", start)
    assert end > start
    body = src[start:end]
    assert "bumpGraph()" in body
