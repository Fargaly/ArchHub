"""A connection means one thing in both surfaces.

The founder's handover names this as the rule that must survive: "defined
once in param-types.jsx so a connection means the same thing in the cockpit
and in Studio... If a future change makes the cockpit's graph behave
differently from the app's canvas, that change is wrong. If it adds a
parameter type to one and not the other, it is wrong for the same reason."

The studio held a SECOND copy of the six wire parameters and the two had
already drifted: a throttle ceiling of 10 s in one, 2 s in the other
(2026-09-07). The studio derives from the one definition now.
"""
from __future__ import annotations

import re
from pathlib import Path

from nodelang.universal_pipeline import WIRE_PARAMETER_SPECS, _WIRE_PARAMETERS

STUDIO = Path(__file__).resolve().parents[1] / "nodelang" / "studio"
ONE = STUDIO / "param-types.jsx"
PARAMS = STUDIO / "studio-params.jsx"
PANELS = STUDIO / "atlas-panels.jsx"

# The rows the run applies (stem_graph_evaluation._carry), declared once on the
# server (universal_pipeline.WIRE_PARAMETER_SPECS) and served to both surfaces.
# Lacing and throttle were drawn but never applied, so they are not offered.
WIRE_KEYS = ("enabled", "tree", "condition", "on_fail")


def test_the_connection_parameters_live_in_one_place():
    assert tuple(spec["k"] for spec in WIRE_PARAMETER_SPECS) == WIRE_KEYS
    assert tuple(key for key, _default in _WIRE_PARAMETERS) == WIRE_KEYS
    assert "const WIRE_PARAMS = [" not in ONE.read_text(encoding="utf-8")


def test_the_studio_derives_its_wire_rows_and_holds_no_second_copy():
    text = PARAMS.read_text(encoding="utf-8")
    assert "window.WIRE_PARAMS" in text, "the studio must read the one definition"
    assert "WIRE_SPECS.map(spec" in text, "the rows are built from it, not typed again"
    body = text[text.index("const WIRE_SPECS"):]
    for key in ("lacing", "on_fail", "tree"):
        literal = re.search(r"%s:\s*\[" % key, body)
        assert literal is None, "%s options are typed a second time in the studio" % key
    assert "const WIRE_DEFAULTS = Object.fromEntries(" in text, "defaults come from the specs"


def test_both_surfaces_load_the_one_served_definition_before_they_use_it():
    studio = (STUDIO / "studio.html").read_text(encoding="utf-8")
    assert "window.WIRE_PARAMS = nodeLibrary.wire_parameters" in studio
    assert studio.index("window.WIRE_PARAMS = nodeLibrary") < studio.rindex("await mountStudio()")
    cockpit = (STUDIO / "cockpit.html").read_text(encoding="utf-8")
    assert "window.WIRE_PARAMS = answer.wire_parameters" in cockpit
    assert "WIRE_PARAMS" in PANELS.read_text(encoding="utf-8"), "the cockpit reads it too"


def test_no_row_is_drawn_that_the_run_does_not_apply():
    offered = {spec["k"] for spec in WIRE_PARAMETER_SPECS}
    assert not offered & {"lacing", "throttle_ms"}
    assert all("pass last" not in spec.get("opts", ()) for spec in WIRE_PARAMETER_SPECS)
