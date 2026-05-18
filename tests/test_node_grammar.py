"""Grounding test for the node grammar (app/workflows/node_grammar.py).

The node grammar is the canonical primitive set for the redesigned node
system (docs/NODE_GRAMMAR.md). The OLD model — 80 enumerated LM_LIBRARY
nodes — was decorative: 0 of 80 resolved to an engine executor.

This test is the structural guarantee that history cannot repeat:
every engine type a READY primitive can dispatch to MUST be a real,
registered executor. A primitive whose executor is not built yet must
be NEEDS_EXECUTOR with no engine types — explicit backlog, never a
fake placeable node.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parent.parent / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import workflows  # noqa: E402  importing registers all built-in node types
from workflows import node_grammar as ng  # noqa: E402


class TestGrammarIsGrounded:
    """Every engine type a primitive names must really exist."""

    @pytest.mark.parametrize("prim", ng.PRIMITIVES, ids=lambda p: p.kind)
    def test_every_engine_type_resolves_in_registry(self, prim):
        for selector_value, engine_t in prim.engine_types.items():
            assert workflows.get(engine_t) is not None, (
                f"primitive {prim.kind!r} names engine type {engine_t!r} "
                f"(for selector value {selector_value!r}) but nothing is "
                f"registered for it — aspirational node, forbidden"
            )

    def test_ready_primitives_are_actually_runnable(self):
        """A READY primitive must have a real dispatch path: a registry
        type, or the connector run_op path."""
        for p in ng.PRIMITIVES:
            if p.status != ng.READY:
                continue
            ok = bool(p.engine_types) or p.kind in ng.NON_REGISTRY_KINDS
            assert ok, (
                f"primitive {p.kind!r} is READY but has no engine type "
                f"and is not a known non-registry kind"
            )

    def test_needs_executor_primitives_name_no_fake_types(self):
        """A not-yet-built primitive must NOT name an engine type —
        an empty engine_types keeps it honestly unplaceable."""
        for p in ng.PRIMITIVES:
            if p.status == ng.NEEDS_EXECUTOR:
                assert p.engine_types == {}, (
                    f"{p.kind!r} is NEEDS_EXECUTOR but names engine types "
                    f"{p.engine_types} — that is aspirational"
                )
                assert p.note, f"{p.kind!r} must cite its build slice"

    def test_needs_executor_set_is_the_known_backlog(self):
        """Adding a new unbuilt primitive must be deliberate — this pins
        the backlog so it cannot grow silently."""
        unbuilt = {p.kind for p in ng.PRIMITIVES
                   if p.status == ng.NEEDS_EXECUTOR}
        assert unbuilt == {"trigger"}   # filter/transform/watch shipped slices 6-7


class TestGrammarShape:
    def test_founder_families_all_covered(self):
        cats = {p.cat for p in ng.PRIMITIVES}
        kinds = {p.kind for p in ng.PRIMITIVES}
        for fam in ng.FOUNDER_FAMILIES:
            assert fam in cats or fam in kinds, (
                f"founder family {fam!r} not covered by the grammar"
            )

    def test_kinds_are_unique(self):
        kinds = [p.kind for p in ng.PRIMITIVES]
        assert len(kinds) == len(set(kinds))

    def test_grammar_is_small_a_grammar_not_a_catalogue(self):
        # If this ever climbs back toward the old 80, the redesign has
        # regressed into a catalogue.
        assert len(ng.PRIMITIVES) <= 20


class TestEngineTypeResolution:
    def test_fixed_primitive_resolves(self):
        assert ng.engine_type("constant") == "data.constant"
        assert ng.engine_type("output") == "output.parameter"
        assert ng.engine_type("input") == "input.parameter"
        assert ng.engine_type("skill") == "subgraph.user"

    def test_selector_primitive_resolves(self):
        assert ng.engine_type("ai", {"action": "chat"}) == "conversation.chat"
        assert ng.engine_type("ai", {"action": "classify"}) == "llm.classify"
        assert ng.engine_type("logic", {"kind": "if"}) == "control.if"
        assert ng.engine_type("logic", {"kind": "foreach"}) == "control.foreach"

    def test_unknown_selector_value_is_none(self):
        assert ng.engine_type("ai", {"action": "telepathy"}) is None
        assert ng.engine_type("ai", {}) is None

    def test_connector_resolves_to_connector_run(self):
        # Slice 2: the connector master node is a real registry executor.
        assert ng.engine_type(
            "connector", {"host": "excel", "op": "read"}) == "connector.run"

    def test_note_has_no_registry_type(self):
        assert ng.engine_type("note") is None

    def test_unknown_kind_is_none(self):
        assert ng.engine_type("does-not-exist") is None


class TestGrammarPayload:
    def test_payload_is_serialisable_and_complete(self):
        import json
        payload = ng.grammar_payload()
        assert len(payload) == len(ng.PRIMITIVES)
        json.dumps(payload)  # must not raise
        for entry in payload:
            assert {"kind", "display", "cat", "selector",
                    "engine_types", "status", "note"} <= entry.keys()
