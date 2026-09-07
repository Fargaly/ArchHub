"""The boot splash counts what is loaded, and an error wears the palette.

Two lines could never say anything: the Brain line read a global assigned
nowhere in the codebase, so it was permanently 'connecting', and the sign-in
error reached for a token neither palette defines, so every refusal painted
a red that is in no palette, beside the one that is (2026-09-07).
"""
from __future__ import annotations

import re
from pathlib import Path

STUDIO = Path(__file__).resolve().parents[1] / "nodelang" / "studio"
ACCOUNT = STUDIO / "studio-account.jsx"
TOKENS = STUDIO / "tokens.jsx"


def test_no_boot_line_reads_a_global_nothing_assigns():
    text = ACCOUNT.read_text(encoding="utf-8")
    code = chr(10).join(
        line for line in text.split(chr(10)) if not line.lstrip().startswith(chr(47) * 2))
    assert "ARCHHUB_BRAIN_FACTS" not in code, "no code path may read it"
    brain = text[text.index("if (key === 'brain')"):]
    brain = brain[:brain.index("if (key === 'hosts')")]
    assert "live.memory" in brain, "it counts the facts the app already loaded"
    assert "folders" in brain, "his two-part phrasing, and both halves are true"


def test_the_palette_has_the_error_colour_the_panel_uses():
    palette = TOKENS.read_text(encoding="utf-8")
    assert re.search(r"err:\s*'#", palette), "the palette defines err"
    assert "danger:" not in palette, "and nothing named danger"
    text = ACCOUNT.read_text(encoding="utf-8")
    assert "AC.danger" not in text, "the panel must not reach for a token that does not exist"
    assert "color: AC.err" in text
    assert "#b4443c" not in text, "the off-palette red is gone"


def test_the_token_line_says_two_true_halves():
    text = ACCOUNT.read_text(encoding="utf-8")
    block = text[text.index("if (key === 'tokens')"):]
    block = block[:block.index("if (key === 'brain')")]
    assert "colours" in block and "other" in block
    assert "Object.keys(T).length + ' tokens'" not in block
