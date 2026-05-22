"""AgDR-0032 — rAF-coalesced bumpGraph for streaming chat.

Pins:
  - bumpGraphRaf defined alongside bumpGraph
  - exposed on window so external callers can choose between
    sync bump (drag/click) and coalesced bump (high-freq streaming)
  - onChunk + onReasoning use the coalesced variant
"""
from __future__ import annotations

from pathlib import Path


JSX = Path(__file__).resolve().parents[1] / "app" / "web_ui" / "studio-lm.jsx"


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


def test_bump_graph_raf_defined():
    src = _src()
    assert "const bumpGraphRaf" in src
    # rAF coalescing scheme.
    assert "requestAnimationFrame" in src
    assert "bumpPendingRef" in src


def test_bump_graph_raf_exposed_on_window():
    src = _src()
    assert "window.__archhubBumpGraphRaf = bumpGraphRaf" in src


def test_chat_chunk_uses_coalesced_bump():
    src = _src()
    # The onChunk handler should now call bumpGraphRaf, not bumpGraph.
    # Find the onChunk function body.
    start = src.find("const onChunk = (sid, piece) =>")
    assert start >= 0
    # Find the next handler def (onDone) to bound the body.
    end = src.find("const onDone", start)
    assert end > start
    body = src[start:end]
    assert "bumpGraphRaf()" in body
    # And NO sync bumpGraph() left in the body — would defeat coalescing.
    assert "bumpGraph();" not in body


def test_reasoning_uses_coalesced_bump():
    src = _src()
    start = src.find("const onReasoning = (sid, step) =>")
    assert start >= 0
    end = src.find("const wires = [];", start)
    assert end > start
    body = src[start:end]
    assert "bumpGraphRaf()" in body
    assert "bumpGraph();" not in body
