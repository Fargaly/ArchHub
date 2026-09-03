"""Every node-grammar category MUST have a real label in the JSX `CAT` map.

WHY this exists (founder, 2026-06-09: "why does the UI show NODES instead of
the right categorization")
-------------------------------------------------------------------------
The node library renders each category header via `catMeta(cat)` in
app/web_ui/studio-lm.jsx, which looks the cat up in the `CAT` map and falls
back to `_CAT_FALLBACK = { label:'NODE' }` on a miss. The grammar
(app/workflows/node_grammar.py) emits 15 category tags; the `CAT` map only
covered 4 of them for the synthesized/typed cats, so the library rendered a
wall of "NODE" headers for input/connector/shape/math/text/code/adapter/skill/
share/watch/note.

This test is the cross-language guard: every category the grammar can emit must
have an explicit `CAT` entry whose label is NOT the generic 'NODE' fallback —
so the regression (a visual user staring at "NODE · NODE · NODE") cannot return,
and adding a new grammar cat forces a matching label.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_APP = _ROOT / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import workflows  # noqa: E402  registers built-ins
from workflows import node_grammar as ng  # noqa: E402

_JSX = _ROOT / "app" / "web_ui" / "studio-lm.jsx"


def _cat_map_keys() -> set[str]:
    """Extract the top-level keys of the `const CAT = { ... }` object literal
    in studio-lm.jsx. Keys are the leading identifier of each entry line:
        ``  input:     { col:..., label:'INPUT', ... },``
    """
    text = _JSX.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"const CAT = \{(.*?)\n\};", text, re.DOTALL)
    assert m, "could not locate the `const CAT = { ... };` block in studio-lm.jsx"
    body = m.group(1)
    keys = set()
    for line in body.splitlines():
        km = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*\{", line)
        if km:
            keys.add(km.group(1))
    return keys


def _grammar_cats() -> set[str]:
    """Every category the grammar payload can surface to the library."""
    return {e.get("cat") for e in ng.grammar_payload() if e.get("cat")}


def test_every_grammar_category_has_a_cat_label():
    cat_keys = _cat_map_keys()
    grammar_cats = _grammar_cats()
    missing = sorted(c for c in grammar_cats if c not in cat_keys)
    assert not missing, (
        "node-grammar categories with NO entry in the JSX `CAT` map — the "
        f"library will render the generic 'NODE' fallback for each: {missing}. "
        "Add a {col, icon, label, role} entry to `const CAT` in studio-lm.jsx."
    )


def test_cat_map_has_no_accidental_node_label():
    """No CAT entry should literally label itself 'NODE' — that is the generic
    fallback, never an intentional category."""
    text = _JSX.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"const CAT = \{(.*?)\n\};", text, re.DOTALL)
    assert m
    # Within the CAT block, no entry's label should be the generic 'NODE'.
    for line in m.group(1).splitlines():
        if re.match(r"\s*[A-Za-z_][A-Za-z0-9_]*\s*:\s*\{", line):
            assert "label:'NODE'" not in line.replace(" ", ""), (
                f"a CAT entry uses the generic 'NODE' label: {line.strip()!r}")
