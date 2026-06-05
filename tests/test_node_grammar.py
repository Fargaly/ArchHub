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
        assert unbuilt == set()   # all 12 primitives now have executors


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
        # SLICE H + I + M1.5 SHARE: typed-node split per category +
        # 3 SHARE primitives. ADAPTER batch 1 + 2 → +6; AgDR-0019
        # typed AI split → +4 (with `ai` master hidden); AgDR-0020
        # SLICE L → +1 (`code`); AgDR-0021 M4 foundation → +1
        # (`ai_plan`). stem-rebuild Phase-0 → +1 (`assert`, the verify
        # gate / branch primitive — like the `join` cell). Cap raised
        # 80 → 81 (still well under the 80-node decorative catalogue
        # *intent*; this is a deliberate, grounded primitive, not filler).
        # stem-rebuild Phase-0 → +1 (`list_files`, the READ-ONLY fs.list IO
        # read cell — a real grounded primitive like `join`/`assert`, not
        # filler). Cap raised 81 → 82.
        # stem-rebuild Phase-0 batch 2 → +3 (`read_file` = fs.read single-file
        # read; `dedupe` = data.dedupe duplicate-row drop; `json_codec` =
        # data.json parse/stringify codec). Three real grounded stem cells like
        # `join`/`assert`/`list_files`, not filler. Cap raised 82 → 85.
        # stem-rebuild Phase-0 IO-write → +2 (`write_file` = fs.write text
        # write; `move_file` = fs.move rename/relocate). Two real grounded
        # stem cells like the read pair, not filler. Cap raised 85 → 87.
        # +4 → 91: text.op regex primitives (regex_findall / regex_match /
        # regex_replace / regex_split) — the executor already implemented them
        # (math_text.py); these expose each by name in the library so they're
        # discoverable instead of buried in the op dropdown. Cap raised 87 → 91.
        assert len(ng.PRIMITIVES) <= 91


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
        assert ng.engine_type("logic", {"kind": "switch"}) == "control.switch"

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
        # SLICE H: `input` + `constant` primitives are hidden in the
        # palette (still in PRIMITIVES for legacy engine resolution).
        # The payload count excludes hidden ones BUT also includes
        # synthesized entries (Tier 1 host_typed + Tier 2 typed
        # primitives + shipped Skills) auto-surfaced from registry +
        # library by `_synthesized_primitives()`.
        non_hidden = [p for p in ng.PRIMITIVES if not p.hidden]
        synth_count = sum(1 for e in payload if e.get("_source"))
        assert len(payload) == len(non_hidden) + synth_count
        assert len(payload) >= len(non_hidden)
        json.dumps(payload)  # must not raise
        for entry in payload:
            assert {"kind", "display", "cat", "selector", "engine_types",
                    "status", "note", "ports", "params",
                    "blurb"} <= entry.keys()
            assert {"in", "out"} <= entry["ports"].keys()
            assert isinstance(entry["params"], list)
            # `blurb` is the user-facing palette subtitle — short + plain,
            # NEVER engineering jargon (that lives in `note`). Guards the
            # regression where the dev note got dumped into the palette.
            assert entry["blurb"], f"{entry['kind']} has no blurb"
            assert len(entry["blurb"]) <= 48, (entry["kind"], entry["blurb"])
            low = entry["blurb"].lower()
            for jargon in ("executor", "run_op", "subgraph", "slice",
                           "registry", ".parameter"):
                assert jargon not in low, (
                    f"{entry['kind']} blurb has dev jargon: {entry['blurb']!r}")
        by_kind = {e["kind"]: e for e in payload}
        # the master nodes land with their selector/host/op param rows
        assert {"host", "op"} <= {p["k"] for p in by_kind["connector"]["params"]}
        # AgDR-0019: the `ai` master is now hidden; verify the typed AI
        # nodes are in the payload + each declares its action-relevant
        # params on the rail.
        assert "ai" not in by_kind  # legacy master hidden
        assert by_kind["ai_chat"]["params"][0]["k"] == "model"
        assert {"model", "prompt"} <= {
            p["k"] for p in by_kind["ai_complete"]["params"]}
        assert {"model", "options"} <= {
            p["k"] for p in by_kind["ai_classify"]["params"]}
        assert {"model", "prompt", "allowed_tools"} <= {
            p["k"] for p in by_kind["ai_tools"]["params"]}
        # SLICE I: `logic` primitive split into typed If / For Each /
        # Switch / Merge — sanity-check at least the `if` typed node
        # resolves and lands without selector params.
        assert "if" in by_kind
        assert by_kind["if"]["engine_types"][""] == "control.if"
        # SLICE H: typed INPUT nodes replaced the bare `constant` primitive
        # in the palette. Number / Text / Boolean / File / Color all map
        # to `data.constant` engine via the `value_type` config. Sanity-check
        # one of them carries a `value` param row.
        assert {"value"} <= {p["k"] for p in by_kind["number"]["params"]}
        assert {"field", "op", "match"} <= {p["k"] for p in by_kind["filter"]["params"]}
        # every READY primitive (except `skill` configured on placement,
        # and `reroute` which is an identity wire-organising dot whose
        # whole point is having no config — AgDR-0007) lands with at
        # least one editable param row — no bare nodes.
        # Synthesized entries (Tier 1 host_typed + Tier 2 typed primitives +
        # shipped Skills auto-surfaced from registry/library) are typed
        # nodes whose param rows are derived from the spec config_schema
        # on placement, not from the grammar. Skip them here.
        for e in payload:
            if (e["status"] == "ready"
                    and e["kind"] not in ("skill", "reroute")
                    and not e.get("_source")):
                assert e["params"], f"{e['kind']} has no param rows"

    def test_registry_primitives_carry_engine_ports(self):
        """A primitive with a registry engine type carries that type's
        ports — the canvas sources ports from the engine, never invents
        them (canvas wire ids must match engine port names)."""
        by_kind = {e["kind"]: e for e in ng.grammar_payload()}
        # SLICE H: a typed INPUT node (e.g. `number`) maps to data.constant
        # and surfaces its `value` output port.
        out_ids = [p["id"] for p in by_kind["number"]["ports"]["out"]]
        assert "value" in out_ids                 # data.constant -> `value`
        # SLICE I OUTPUT split: `output` primitive renamed `result`,
        # joined by typed File Save / Console / Display siblings. All
        # of them carry a `value` input port from their respective
        # output.* engine.
        in_ids = [p["id"] for p in by_kind["result"]["ports"]["in"]]
        assert "value" in in_ids                  # output.parameter <- `value`
