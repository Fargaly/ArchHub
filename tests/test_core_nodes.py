"""Core node types for the graph-first architecture (ADR-003 Phase 1).

Pins the contracts:
  - PortType enum has the new families
  - Port dataclass has exec + multiple fields
  - typesystem.can_wire enforces exec/data isolation + coercion table
  - host.* (7), conversation.chat, doc.* (8) register on import
  - Each executor returns a well-typed envelope
  - JSON round-trip of Port preserves the new fields

Phase 4 will replace the executor bodies with real adapter calls; the
tests here pin the *shapes* so Phase 4 can't accidentally drop a port
or change a return key.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))


# Importing workflows.nodes triggers registration; do it once for the
# whole module.
from workflows import nodes as _nodes_pkg     # noqa: F401
from workflows.graph import Port, PortType
from workflows import registry as _registry
from workflows import typesystem


# ── PortType enum surface ──────────────────────────────────────────
class TestPortTypeSurface:
    def test_new_bridge_families_present(self):
        for name in ("HOST", "DOCUMENT", "MODEL", "PROJECT"):
            assert hasattr(PortType, name), name

    def test_new_ai_families_present(self):
        for name in ("PROMPT", "MESSAGE", "CONVERSATION", "INTENT",
                     "COMPLETION", "TOOL_RESULT"):
            assert hasattr(PortType, name), name

    def test_new_aec_entity_families_present(self):
        for name in ("ELEMENT", "SELECTION"):
            assert hasattr(PortType, name), name

    def test_new_control_families_present(self):
        for name in ("EXEC", "CRON", "TRIGGER", "EVENT"):
            assert hasattr(PortType, name), name

    def test_existing_primitives_preserved(self):
        for name in ("ANY", "STRING", "NUMBER", "BOOLEAN", "OBJECT",
                     "LIST", "IMAGE", "GEOMETRY", "TOOL_RESULT"):
            assert hasattr(PortType, name), name


# ── Port dataclass shape ───────────────────────────────────────────
class TestPortShape:
    def test_exec_field_defaults_false(self):
        p = Port(name="a", type=PortType.STRING)
        assert p.exec is False
        assert p.multiple is False

    def test_exec_field_in_to_dict(self):
        p = Port(name="a", type=PortType.EXEC, exec=True, multiple=True)
        d = p.to_dict()
        assert d["exec"] is True
        assert d["multiple"] is True

    def test_from_dict_round_trip(self):
        original = Port(name="ctx", type=PortType.CONVERSATION,
                         multiple=True, required=True)
        roundtrip = Port.from_dict(original.to_dict())
        assert roundtrip.name == original.name
        assert roundtrip.type == original.type
        assert roundtrip.multiple == original.multiple
        assert roundtrip.required == original.required
        assert roundtrip.exec == original.exec

    def test_legacy_dict_without_exec_falls_back_to_false(self):
        # Saved graphs from v1.3.x won't have exec/multiple keys.
        legacy = {"name": "x", "type": "string"}
        p = Port.from_dict(legacy)
        assert p.exec is False
        assert p.multiple is False


# ── Type compatibility table ───────────────────────────────────────
class TestTypesystem:
    def test_identity_always_wires(self):
        for t in PortType:
            assert typesystem.can_wire(t, t)

    def test_any_matches_anything(self):
        for t in PortType:
            assert typesystem.can_wire(PortType.ANY, t)
            assert typesystem.can_wire(t, PortType.ANY)

    def test_exec_and_data_cannot_cross(self):
        # Output is exec-marked, input is data-marked → refuse.
        assert not typesystem.can_wire(
            PortType.EXEC, PortType.STRING,
            output_is_exec=True, input_is_exec=False)
        assert not typesystem.can_wire(
            PortType.STRING, PortType.EXEC,
            output_is_exec=False, input_is_exec=True)

    def test_exec_to_exec_wires(self):
        assert typesystem.can_wire(
            PortType.EXEC, PortType.EXEC,
            output_is_exec=True, input_is_exec=True)

    def test_element_coerces_to_selection(self):
        assert typesystem.can_wire(PortType.ELEMENT, PortType.SELECTION)

    def test_selection_coerces_to_list(self):
        assert typesystem.can_wire(PortType.SELECTION, PortType.LIST)

    def test_string_coerces_to_prompt(self):
        assert typesystem.can_wire(PortType.STRING, PortType.PROMPT)

    def test_prompt_coerces_to_string(self):
        assert typesystem.can_wire(PortType.PROMPT, PortType.STRING)

    def test_document_to_model_and_back(self):
        assert typesystem.can_wire(PortType.DOCUMENT, PortType.MODEL)
        assert typesystem.can_wire(PortType.MODEL, PortType.DOCUMENT)

    def test_trigger_fires_exec_disallowed_without_exec_pin(self):
        # Even though TRIGGER lists EXEC as coercible, the canvas-side
        # wiring requires the exec flag to be set; otherwise the cross-
        # family rule blocks it. The type table allows the value
        # transition; the exec gate enforces the visual segregation.
        # Here both ends are data pins → coercion goes through.
        assert typesystem.can_wire(PortType.TRIGGER, PortType.EXEC)

    def test_unrelated_pairs_refuse(self):
        # NUMBER → IFC should never wire.
        assert not typesystem.can_wire(PortType.NUMBER, PortType.IFC)

    def test_list_compatible_inputs_includes_self(self):
        for t in (PortType.STRING, PortType.ELEMENT, PortType.HOST):
            assert t in typesystem.list_compatible_inputs(t)
            assert PortType.ANY in typesystem.list_compatible_inputs(t)


# ── Registration of host.* family ──────────────────────────────────
class TestHostNodeRegistration:
    EXPECTED_FAMILIES = ("revit", "autocad", "blender", "rhino",
                         "max", "speckle", "outlook")

    def test_all_seven_host_types_registered(self):
        for fam in self.EXPECTED_FAMILIES:
            assert _registry.get(f"host.{fam}") is not None, fam

    def test_host_has_action_input_and_state_output(self):
        for fam in self.EXPECTED_FAMILIES:
            spec, _ = _registry.get(f"host.{fam}")
            input_names = {p.name for p in spec.inputs}
            output_names = {p.name for p in spec.outputs}
            assert "action" in input_names
            assert "trigger" in input_names
            assert "opened_doc" in output_names
            assert "selection" in output_names
            assert "state" in output_names
            assert "after" in output_names

    def test_host_executor_returns_typed_envelope(self, monkeypatch):
        # Hermetic: neutralise the live-host probe so the envelope is
        # deterministic regardless of which Revit (if any) is installed
        # on the test machine. A live session's real version would
        # otherwise win over config.version (core._host_exec:480), so
        # a machine with Revit 2023 running fails a hardcoded "2025".
        from workflows.nodes import core as _core
        monkeypatch.setattr(_core, "_pick_session_by_version",
                            lambda family, version: None)
        monkeypatch.setattr(_core, "_broker_host_info",
                            lambda family: {"alive": False,
                                            "reason": "unavailable"})
        spec, executor = _registry.get("host.revit")
        out = executor({"_family": "revit", "version": "2025"},
                        {"action": "open"}, None)
        assert out["status"] == "ok"
        assert out["family"] == "revit"
        # No live session -> version falls back to the configured value.
        assert out["version"] == "2025"
        assert "selection" in out and isinstance(out["selection"], list)

    def test_host_trigger_input_is_exec_pin(self):
        spec, _ = _registry.get("host.revit")
        trig = next(p for p in spec.inputs if p.name == "trigger")
        assert trig.exec is True
        assert trig.type == PortType.EXEC


# ── Registration of conversation.chat ──────────────────────────────
class TestConversationNode:
    def test_registered(self):
        assert _registry.get("conversation.chat") is not None

    def test_has_prompt_required_input(self):
        spec, _ = _registry.get("conversation.chat")
        prompt = next(p for p in spec.inputs if p.name == "prompt")
        assert prompt.required is True
        assert prompt.type == PortType.STRING

    def test_context_input_accepts_multiple(self):
        spec, _ = _registry.get("conversation.chat")
        ctx = next(p for p in spec.inputs if p.name == "context")
        assert ctx.multiple is True

    def test_outputs_have_response_intent_tool_trace(self):
        spec, _ = _registry.get("conversation.chat")
        out_names = {p.name for p in spec.outputs}
        for required in ("response", "intent", "tool_trace",
                          "conversation", "after"):
            assert required in out_names, required

    def test_executor_appends_turn_to_messages(self):
        spec, executor = _registry.get("conversation.chat")
        out = executor(
            {"model": "auto", "body": {"messages": [
                {"role": "user", "content": "earlier turn"}]}},
            {"prompt": "hello"},
            None,
        )
        assert out["status"] == "ok"
        assert out["response"].startswith("[stub-")
        msgs = out["messages"]
        assert len(msgs) == 3   # 1 prior + user + assistant
        assert msgs[-1]["role"] == "assistant"
        assert msgs[-2]["role"] == "user"
        assert msgs[-2]["content"] == "hello"

    def test_executor_empty_prompt_returns_error(self):
        spec, executor = _registry.get("conversation.chat")
        out = executor({"model": "auto"}, {"prompt": ""}, None)
        assert out["status"] == "error"


# ── Registration of doc.* family ───────────────────────────────────
class TestDocumentNodes:
    EXPECTED_FAMILIES = ("revit", "dwg", "ifc", "blender",
                         "3dm", "max", "csv", "pdf")

    def test_all_eight_doc_types_registered(self):
        for fam in self.EXPECTED_FAMILIES:
            assert _registry.get(f"doc.{fam}") is not None, fam

    def test_doc_has_path_input_and_document_output(self):
        spec, _ = _registry.get("doc.revit")
        in_names = {p.name for p in spec.inputs}
        out_names = {p.name for p in spec.outputs}
        assert "path" in in_names
        assert "host" in in_names
        assert "trigger" in in_names
        assert "document" in out_names
        assert "contents" in out_names
        assert "selection" in out_names
        assert "warnings" in out_names

    def test_ifc_doc_output_is_ifc_typed(self):
        spec, _ = _registry.get("doc.ifc")
        doc_out = next(p for p in spec.outputs if p.name == "document")
        assert doc_out.type == PortType.IFC

    def test_csv_doc_output_is_csv_typed(self):
        spec, _ = _registry.get("doc.csv")
        doc_out = next(p for p in spec.outputs if p.name == "document")
        assert doc_out.type == PortType.CSV

    def test_doc_executor_returns_typed_envelope(self):
        spec, executor = _registry.get("doc.revit")
        out = executor(
            {"_family": "revit"},
            {"path": "/tmp/tower-a.rvt"},
            None,
        )
        assert out["status"] == "ok"
        assert out["family"] == "revit"
        assert out["path"] == "/tmp/tower-a.rvt"
        assert isinstance(out["selection"], list)
        assert isinstance(out["warnings"], list)


# ── Cross-family wiring (the actual unlock) ─────────────────────────
class TestCrossFamilyWiring:
    def test_host_output_wires_into_doc_input(self):
        # host.opened_doc (DOCUMENT) → doc.host (HOST) ? No — host
        # output is DOCUMENT, doc.host input is HOST. They DON'T wire.
        # But host's "opened_doc" output IS a document, which wires
        # into another doc's `document` input via identity? doc.host
        # input is HOST, not DOCUMENT. So expect refusal here.
        host_spec, _ = _registry.get("host.revit")
        doc_spec, _ = _registry.get("doc.revit")
        opened_doc = next(p for p in host_spec.outputs
                            if p.name == "opened_doc")
        host_input = next(p for p in doc_spec.inputs
                            if p.name == "host")
        # DOCUMENT into HOST — not a listed coercion, both data pins.
        assert not typesystem.can_wire(
            opened_doc.type, host_input.type,
            output_is_exec=opened_doc.exec,
            input_is_exec=host_input.exec)

    def test_doc_document_wires_into_conversation_context_via_any(self):
        # The Conversation node's `context` is ANY (multiple), so a
        # Document output should plug straight in.
        doc_spec, _ = _registry.get("doc.revit")
        conv_spec, _ = _registry.get("conversation.chat")
        doc_out = next(p for p in doc_spec.outputs if p.name == "document")
        ctx_in = next(p for p in conv_spec.inputs if p.name == "context")
        assert typesystem.can_wire(doc_out.type, ctx_in.type)

    def test_conversation_intent_wires_into_logic_string_input(self):
        # INTENT → STRING is in the coercion table.
        assert typesystem.can_wire(PortType.INTENT, PortType.STRING)

    def test_host_after_exec_into_conversation_trigger_exec(self):
        host_spec, _ = _registry.get("host.revit")
        conv_spec, _ = _registry.get("conversation.chat")
        after = next(p for p in host_spec.outputs if p.name == "after")
        trigger = next(p for p in conv_spec.inputs if p.name == "trigger")
        assert typesystem.can_wire(
            after.type, trigger.type,
            output_is_exec=after.exec,
            input_is_exec=trigger.exec)
