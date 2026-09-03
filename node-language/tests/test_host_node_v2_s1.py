"""AgDR-0024 Host node v2 S1 — REST stage tests.

S1 ships: feature flag (reader/writer/window globals) +
`HostNodeV2Body` component + NodeBody dispatch to v2 when flag on.

Out of S1 scope (covered by later sub-slices):
  - S2: hover-promote markers + ADVANCED INPUTS + floating bar
  - S3: OUTPUT PLUCK
  - S4: Save-as-Skill / ai.plan integration

These tests pin S1 ONLY.
"""
from __future__ import annotations

import re
from pathlib import Path

JSX = Path(__file__).resolve().parents[1] / "app" / "web_ui" / "studio-lm.jsx"


def _src() -> str:
    return JSX.read_text(encoding="utf-8")


# ─── 1. feature flag ────────────────────────────────────────────────


def test_host_node_v2_flag_reader_defined():
    src = _src()
    assert "_readHostNodeV2" in src
    assert "_setHostNodeV2" in src
    assert "'archhub.host_node_v2'" in src


def test_host_node_v2_flag_default_off():
    src = _src()
    # The reader returns 'on' only when localStorage matches; otherwise
    # default falsy. Pin the literal comparison.
    assert "=== 'on'" in src


def test_host_node_v2_flag_writer_emits_event():
    src = _src()
    assert "archhub-host-node-v2" in src
    # Writer fires custom event so canvas re-render is instant.
    assert "dispatchEvent" in src


def test_host_node_v2_flag_window_globals():
    src = _src()
    assert "window.__archhubHostNodeV2" in src
    assert "window.__archhubSetHostNodeV2" in src


# ─── 2. dispatch wired into NodeBody ───────────────────────────────


def test_node_body_dispatches_v2_when_flag_on():
    """NodeBody's `connector` case checks `_readHostNodeV2()` and
    returns <HostNodeV2Body> when on; falls through to
    <ConnectorOpBody> when off."""
    src = _src()
    # Find the dispatch block.
    assert "case 'connector':" in src
    assert "if (_readHostNodeV2()) return <HostNodeV2Body" in src
    # ConnectorOpBody fallback path stays so flag-off UX is unchanged.
    assert "return <ConnectorOpBody" in src


# ─── 3. HostNodeV2Body component ────────────────────────────────────


def test_host_node_v2_body_defined():
    src = _src()
    assert "const HostNodeV2Body = " in src
    # Renders the op grid (4 columns per Direction A).
    assert "gridTemplateColumns:'repeat(4, 1fr)'" in src


def test_host_node_v2_body_reads_lm_connectors():
    src = _src()
    # Reads ops from LM_CONNECTORS keyed by host (Slice A reuse).
    assert "(LM_CONNECTORS || []).find(c => c.host === host)" in src


def test_host_node_v2_body_active_tile_renders_main_inputs():
    src = _src()
    # Active tile expands inline + shows MAIN INPUTS section header.
    assert 'data-active-tile="1"' in src
    assert "MAIN INPUTS" in src


def test_host_node_v2_body_filters_instance_param():
    """The host's instance picker is system-level; the v2 body hides
    it from MAIN INPUTS (it lives in the inspector instead)."""
    src = _src()
    assert "i.id !== 'instance'" in src


def test_host_node_v2_body_per_host_brand_stripe():
    """Per-host brand colour table — Slice A constraint (Revit orange,
    AutoCAD red, Max purple, etc.)."""
    src = _src()
    assert "_PER_HOST_BRAND" in src
    # Spot-check Revit + AutoCAD + Max (the 3 broker hosts).
    assert "revit:" in src and "#d97757" in src
    assert "autocad:" in src and "#e6705f" in src
    assert "max:" in src and "#a98cd6" in src


# ─── 4. NOT IN S1 — guards against scope creep ─────────────────────


def test_host_node_v2_s1_no_hover_promote():
    """S1 ships NO hover-promote markers. Guard against future devs
    accidentally introducing them outside the S2 scope."""
    src = _src()
    # The HostNodeV2Body span only — pull its body, check for
    # `param-row hover` markup (the S2 mechanic). Match by data
    # attribute that's unique to v2.
    start = src.find("const HostNodeV2Body = ")
    assert start >= 0
    # Bound at the next top-level `const ` declaration.
    end = src.find("\nconst ", start + 10)
    body = src[start:end if end > 0 else start + 6000]
    # S1 must not include "hover" promote markers — those land in S2.
    # We tolerate the word "host" but no "hover-zone-" / "row-sock-l".
    assert "hover-zone-l" not in body
    assert "row-sock-l" not in body
    assert "row-sock-r" not in body


def test_host_node_v2_s2_has_floating_disable_verbs_bar():
    """S2 (shipped 2026-05-25) — floating verb bar present in HostNodeV2Body."""
    src = _src()
    start = src.find("const HostNodeV2Body = ")
    end = src.find("\nconst ", start + 10)
    body = src[start:end if end > 0 else start + 8000]
    # Each verb fires a dedicated lm-node-toggle-* event from the bar.
    assert "lm-node-toggle-pin" in body
    assert "lm-node-toggle-freeze" in body
    assert "lm-node-toggle-bypass" in body
    assert "lm-node-toggle-preview" in body


def test_host_node_v2_s3_has_output_pluck_section():
    """S3 (shipped 2026-05-25) — OUTPUT PLUCK section + promote handler."""
    src = _src()
    start = src.find("const HostNodeV2Body = ")
    end = src.find("\nconst ", start + 10)
    body = src[start:end if end > 0 else start + 8000]
    # Per AgDR-0024 S3 — outputs render with hover-to-promote affordance
    # and dispatch lm-host-promote-output.
    assert "HOVER TO PROMOTE" in body
    assert "lm-host-promote-output" in body


def test_host_node_v2_s2_has_advanced_inputs_section():
    """S2 — ADVANCED INPUTS collapsible band present."""
    src = _src()
    start = src.find("const HostNodeV2Body = ")
    end = src.find("\nconst ", start + 10)
    body = src[start:end if end > 0 else start + 8000]
    assert "ADVANCED INPUTS" in body
    assert "setAdvancedOpen" in body


# ─── 5. AgDR doc exists ─────────────────────────────────────────────


def test_agdr_0024_doc_exists():
    p = (Path(__file__).resolve().parents[1] / "docs" / "agdr"
         / "AgDR-0024-host-node-v2-direction-a-comfyui.md")
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    # Sub-slice plan anchors.
    assert "S1 · REST" in text
    assert "S2 · HOVER + ADVANCED + FLOATING BAR" in text
    assert "S3 · OUTPUT PLUCK" in text
    assert "S4 · ECOSYSTEM INTEGRATION" in text
    # Feature flag is the key.
    assert "archhub.host_node_v2" in text


# ─── 6. flag-off path leaves existing ConnectorOpBody untouched ────


def test_connector_op_body_still_exists():
    """Flag-off ⇒ existing ConnectorOpBody renders. The component
    must still be defined."""
    src = _src()
    assert "const ConnectorOpBody = " in src or "ConnectorOpBody = " in src
