"""AgDR-0022 P2.a — ReactFlow scaffold groundwork (INVERTED 2026-05-26).

Original purpose: pin the existence of the ReactFlow feature flag +
stub component so the P2.b sub-slice could land RF nodes safely.

Inverted purpose (per AgDR-0048 supersede + AgDR-0047 §C3 + Q1 founder
pick 2026-05-26): pin the **REMOVAL** of every ReactFlow scaffold
artifact, so a future agent cannot accidentally resurrect the stub or
the inert flavor toggle. Custom canvas (NodeView + WireLayer) is the
substrate of record.

The original AgDR-0022 doc stays on disk (status: proposed) as the
historical record of the abandoned migration; this test no longer
asserts its contents — only the doc presence is sanity-checked.
"""
from __future__ import annotations

from pathlib import Path

JSX = Path(__file__).resolve().parents[1] / "app" / "web_ui" / "studio-lm.jsx"


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


# ── Inverted assertions: these symbols must NOT appear in the JSX. ──

def test_canvas_flavor_reader_removed():
    src = _src()
    assert "const _readCanvasFlavor" not in src, (
        "AgDR-0048 supersede: `_readCanvasFlavor` was removed. "
        "Custom canvas is the substrate of record; the flavor toggle "
        "was inert and is gone."
    )
    assert "const _setCanvasFlavor" not in src, (
        "AgDR-0048 supersede: `_setCanvasFlavor` was removed alongside "
        "the reader. ReactFlow was never installed; the toggle wrote "
        "to a localStorage key nothing read."
    )


def test_canvas_flavor_window_exports_removed():
    src = _src()
    # The literal assignment statements that exposed the flavor
    # reader / setter on `window` are gone. The substring may still
    # appear in deprecation comments, so we check the assignment shape
    # specifically (matches `window.__archhub<X> = ` followed by the
    # local symbol name).
    assert "window.__archhubCanvasFlavor = _readCanvasFlavor" not in src
    assert "window.__archhubSetCanvasFlavor = _setCanvasFlavor" not in src


def test_nodecanvas_rf_stub_removed():
    src = _src()
    assert "NodeCanvasRF_Stub" not in src, (
        "AgDR-0048 supersede + AgDR-0047 §C3 (deleted 2026-05-26 per "
        "Q1): the placeholder stub is gone. Custom NodeView shipped "
        "every feature ReactFlow would have offered; the stub was "
        "kept only for this test, now inverted."
    )
    assert 'data-testid="reactflow-canvas-stub"' not in src


def test_archhub_canvas_storage_key_gone():
    src = _src()
    # The localStorage key the flavor toggle wrote to is no longer
    # referenced anywhere in the JSX bundle.
    assert "'archhub.canvas'" not in src
    assert '"archhub.canvas"' not in src


# ── Historical record: the original AgDR doc stays on disk. ───────

def test_agdr_0022_doc_still_exists_as_history():
    """The AgDR-0022 file remains on disk as the historical record of
    the abandoned ReactFlow scaffold. Status `proposed` per ledger."""
    agdr = (Path(__file__).resolve().parents[1] / "docs" / "agdr"
            / "AgDR-0022-reactflow-scaffold-migration.md")
    assert agdr.exists()


def test_agdr_0048_supersede_doc_exists():
    """The supersede AgDR is on disk + names the renumber chain
    (renumbered 0045 → 0046 → 0048 during 2026-05-25/26 work)."""
    agdr = (Path(__file__).resolve().parents[1] / "docs" / "agdr"
            / "AgDR-0048-supersede-reactflow-lock.md")
    assert agdr.exists()
    text = agdr.read_text(encoding="utf-8")
    assert "renumbered_from" in text
    assert "AgDR-0045" in text
    assert "AgDR-0046" in text
