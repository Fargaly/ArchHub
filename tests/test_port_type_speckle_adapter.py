"""AgDR-0012 §232-233 migration · Stage 1+2 (Q4 founder pick 2026-05-26).

Pins the PortType ↔ speckle_type bidirectional adapter:

  * Every PortType value maps to a stable Speckle-protocol string.
  * Round-trip: PortType → speckle_type → PortType preserves identity
    for every enum value.
  * Unknown speckle_type strings degrade gracefully to ANY (back-compat).
  * Port.to_dict() emits the speckle_type alongside the legacy `type`.
  * Port.from_dict() prefers speckle_type when present; falls back to
    legacy type when speckle_type is absent (so old saved workflows
    keep loading).
"""
from __future__ import annotations

import sys
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

from workflows.graph import Port, PortType  # noqa: E402


# ── Mapping integrity ──────────────────────────────────────────────

def test_every_port_type_has_a_speckle_type():
    """No PortType value emits the unknown sentinel."""
    for pt in PortType:
        s = pt.to_speckle_type()
        assert isinstance(s, str) and s, f"{pt} returned empty"
        assert not s.startswith("archhub.unknown."), (
            f"{pt} missing from _PORT_TO_SPECKLE mapping"
        )


def test_speckle_type_round_trip_preserves_identity():
    """PortType → speckle_type → PortType returns the original value."""
    for pt in PortType:
        s = pt.to_speckle_type()
        round_trip = PortType.from_speckle_type(s)
        assert round_trip is pt, f"{pt} round-tripped to {round_trip}"


def test_unknown_speckle_type_degrades_to_any():
    """Unknown / missing strings hit the AgDR-0012 §312 deprecation path."""
    assert PortType.from_speckle_type("Objects.NotARealThing") is PortType.ANY
    assert PortType.from_speckle_type("") is PortType.ANY
    assert PortType.from_speckle_type(None) is PortType.ANY


def test_archhub_namespace_used_for_non_speckle_types():
    """Control flow + canvas-internal types live under archhub.* so the
    round-trip stays lossless for a future replay tool."""
    archhub_namespace = {
        PortType.EXEC, PortType.CRON, PortType.TRIGGER, PortType.EVENT,
        PortType.HOST, PortType.DOCUMENT, PortType.MODEL, PortType.PROJECT,
        PortType.PROMPT, PortType.MESSAGE, PortType.CONVERSATION,
        PortType.INTENT, PortType.COMPLETION, PortType.TOOL_RESULT,
        PortType.SELECTION, PortType.FILE, PortType.PATH, PortType.IMAGE,
        PortType.CSV, PortType.ANY,
    }
    for pt in archhub_namespace:
        assert pt.to_speckle_type().startswith("archhub."), (
            f"{pt} should be in archhub.* namespace but is "
            f"{pt.to_speckle_type()}"
        )


def test_objects_namespace_used_for_speckle_native_types():
    """STRING / NUMBER / BOOLEAN / OBJECT / LIST / ELEMENT / GEOMETRY /
    IFC map to Speckle's real Objects.* protocol namespace so they can
    flow through a real Speckle server unchanged."""
    speckle_native = {
        PortType.STRING, PortType.NUMBER, PortType.BOOLEAN, PortType.OBJECT,
        PortType.LIST, PortType.ELEMENT, PortType.GEOMETRY, PortType.IFC,
    }
    for pt in speckle_native:
        assert pt.to_speckle_type().startswith("Objects."), (
            f"{pt} should be in Objects.* Speckle-native namespace but is "
            f"{pt.to_speckle_type()}"
        )


# ── Port serialisation ─────────────────────────────────────────────

def test_port_to_dict_emits_speckle_type_alongside_legacy_type():
    p = Port(name="walls", type=PortType.ELEMENT, description="walls in view")
    d = p.to_dict()
    assert d["type"] == "element"  # legacy field preserved
    assert d["speckle_type"] == "Objects.BuiltElements.Base"  # new field


def test_port_from_dict_prefers_speckle_type_when_present():
    d = {"name": "walls", "speckle_type": "Objects.BuiltElements.Base"}
    p = Port.from_dict(d)
    assert p.type is PortType.ELEMENT


def test_port_from_dict_falls_back_to_legacy_type():
    """Saved workflows from before the migration have no speckle_type
    field — the legacy `type` is the source of truth."""
    d = {"name": "walls", "type": "element"}
    p = Port.from_dict(d)
    assert p.type is PortType.ELEMENT


def test_port_from_dict_legacy_wins_when_speckle_is_unknown():
    """If speckle_type is unrecognised but legacy `type` is present,
    use the legacy hint rather than degrading to ANY."""
    d = {"name": "walls", "type": "element",
         "speckle_type": "Objects.FromTheFuture"}
    p = Port.from_dict(d)
    assert p.type is PortType.ELEMENT


def test_round_trip_through_to_dict_and_from_dict():
    for pt in PortType:
        p = Port(name=f"p_{pt.value}", type=pt)
        d = p.to_dict()
        back = Port.from_dict(d)
        assert back.type is pt, f"{pt} lost identity through dict round-trip"
