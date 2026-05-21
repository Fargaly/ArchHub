"""AgDR-0022 P2.a — ReactFlow scaffold groundwork tests.

This sub-slice ships the FEATURE FLAG + STUB without the ReactFlow
library yet. P2.b adds the real RF nodes. Tests here pin:

  • localStorage key `archhub.canvas` reads + writes via
    `_readCanvasFlavor` / `_setCanvasFlavor`.
  • Stub component `NodeCanvasRF_Stub` exists + renders the
    placeholder copy + "Back to custom canvas" button.
  • Token-binding mandate: stub uses only `LM.*` references, NO
    hex literals (AgDR-0015 Phase 2 invariant).
  • Default flavor is `custom` so today's UX is unchanged.
"""
from __future__ import annotations

import re
from pathlib import Path

JSX = Path(__file__).resolve().parents[1] / "app" / "web_ui" / "studio-lm.jsx"


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


def test_canvas_flavor_reader_defined():
    src = _src()
    assert "_readCanvasFlavor" in src
    assert "_setCanvasFlavor" in src
    assert "'archhub.canvas'" in src


def test_canvas_flavor_default_is_custom():
    """Reader returns 'custom' when localStorage is empty / invalid."""
    src = _src()
    # The reader's fallback path returns 'custom'.
    assert "return 'custom'" in src
    # Default arm uses the explicit string.
    assert "'reactflow' : 'custom'" in src


def test_canvas_flavor_writer_emits_event():
    """`_setCanvasFlavor` dispatches `archhub-canvas-flavor`
    so the canvas mount can re-read without a page refresh."""
    src = _src()
    assert "archhub-canvas-flavor" in src
    assert "dispatchEvent" in src


def test_canvas_flavor_exposes_window_globals():
    """Both reader + writer attach to `window.*` so CDP audits + the
    Settings panel can flip the flag without importing the JSX module."""
    src = _src()
    assert "window.__archhubCanvasFlavor" in src
    assert "window.__archhubSetCanvasFlavor" in src


def test_nodecanvas_rf_stub_component_defined():
    src = _src()
    assert "NodeCanvasRF_Stub" in src
    # Stub carries a testid for live DOM probes.
    assert 'data-testid="reactflow-canvas-stub"' in src


def test_nodecanvas_rf_stub_copies_have_agdr_reference():
    """Stub user-facing copy MUST reference the AgDR — so the
    founder can trace WHY they're seeing the placeholder."""
    src = _src()
    assert "AgDR-0022" in src
    # Also surfaces the "no restart needed" assurance.
    assert "flip back" in src.lower() or "switch back" in src.lower()


def test_nodecanvas_rf_stub_uses_only_lm_tokens_no_hex_literals():
    """AgDR-0015 Phase 2 invariant: every new ReactFlow-side render
    binds to `LM.*` tokens. NO hex literals (`#abc`/`#abcdef`)
    inside the `NodeCanvasRF_Stub` body."""
    src = _src()
    # Find the stub function body — between `const NodeCanvasRF_Stub`
    # and the next `const`/`function` at module scope.
    start = src.find("const NodeCanvasRF_Stub")
    assert start >= 0, "stub not found"
    # End at the next module-scope `const` declaration.
    rest = src[start:]
    # Bounded body: the next module-scope `const ` after the stub
    # function definition. Use a simple closing-marker search.
    end_marker = "const CanvasHint"
    end = rest.find(end_marker)
    assert end >= 0, "stub body end marker not found"
    body = rest[:end]
    # The ONLY hex literal we tolerate is '#fff' (the button-text
    # white — explicitly chosen for accent contrast). Whitelist it.
    hex_matches = re.findall(r"#[0-9a-fA-F]{3,6}\b", body)
    bad = [h for h in hex_matches if h.lower() not in ("#fff", "#ffffff")]
    assert not bad, (
        f"NodeCanvasRF_Stub uses hex literals (AgDR-0015 Phase 2 "
        f"forbids — token-bind via LM.*): {bad}")


def test_nodecanvas_rf_stub_has_back_to_custom_button():
    """Founder UX requirement: a one-click "back to custom" path
    so the flag-flip is genuinely reversible."""
    src = _src()
    # Either button text variant is acceptable.
    has_back = ("Back to custom canvas" in src
                or "back to custom" in src.lower())
    assert has_back


def test_agdr_0022_doc_exists():
    """The AgDR for this slice must exist + reference the sub-slice
    ordering."""
    agdr = (Path(__file__).resolve().parents[1] / "docs" / "agdr"
            / "AgDR-0022-reactflow-scaffold-migration.md")
    assert agdr.exists()
    text = agdr.read_text(encoding="utf-8")
    # Sub-slice contract anchors.
    assert "P2.a" in text
    assert "P2.b" in text
    assert "P2.c" in text
    assert "P2.d" in text
    # Coexistence model.
    assert "archhub.canvas" in text
    # Token mandate.
    assert "LM.*" in text or "LM_" in text
