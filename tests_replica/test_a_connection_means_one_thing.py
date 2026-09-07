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

STUDIO = Path(__file__).resolve().parents[1] / "nodelang" / "studio"
ONE = STUDIO / "param-types.jsx"
PARAMS = STUDIO / "studio-params.jsx"
PANELS = STUDIO / "atlas-panels.jsx"

WIRE_KEYS = ("enabled", "lacing", "tree", "condition", "on_fail", "throttle_ms")


def _wire_params_block() -> str:
    text = ONE.read_text(encoding="utf-8")
    start = text.index("const WIRE_PARAMS = [")
    return text[start:text.index("];", start)]


def test_the_six_connection_parameters_live_in_one_file():
    block = _wire_params_block()
    flat = block.replace(chr(34), chr(39))
    for key in WIRE_KEYS:
        assert (chr(39) + key + chr(39)) in flat, key
    exported = ONE.read_text(encoding="utf-8").split("Object.assign(window,")[1][:200]
    assert "WIRE_PARAMS" in exported


def test_the_studio_derives_its_wire_rows_and_holds_no_second_copy():
    text = PARAMS.read_text(encoding="utf-8")
    assert "window.WIRE_PARAMS" in text, "the studio must read the one definition"
    assert "WIRE_SPECS.map(spec" in text, "the rows are built from it, not typed again"
    body = text[text.index("const WIRE_SPECS"):]
    for key in ("lacing", "on_fail", "tree"):
        literal = re.search(r"%s:\s*\[" % key, body)
        assert literal is None, "%s options are typed a second time in the studio" % key
    assert "const WIRE_DEFAULTS = Object.fromEntries(" in text, "defaults come from the specs"


def test_both_surfaces_load_the_one_definition_before_they_use_it():
    for page in ("studio.html", "cockpit.html"):
        text = (STUDIO / page).read_text(encoding="utf-8")
        assert "param-types.jsx" in text, page
        if page == "studio.html":
            assert text.index("param-types.jsx") < text.index("studio-params.jsx"), page
    assert "WIRE_PARAMS" in PANELS.read_text(encoding="utf-8"), "the cockpit reads it too"


def test_one_ceiling_for_the_throttle_not_two():
    block = _wire_params_block()
    line = next(l for l in block.splitlines() if "throttle_ms" in l)
    assert "max: 2000" in line and "hard: [0, 10000]" in line, line
    text = PARAMS.read_text(encoding="utf-8")
    body = text[text.index("const WIRE_SPECS"):]
    assert "10000" not in body and "max: 2000" not in body, (
        "a ceiling typed in the studio is the drift this court exists to stop")
