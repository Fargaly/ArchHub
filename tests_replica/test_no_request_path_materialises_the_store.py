"""No request path materialises the head map. Enforced across the package.

The rule was already written on 2026-09-05, in cell_registry_projection.py:
"Point reads, never set(snapshot.cells): the head map is lazy over a journal
of millions of rows... That one line was half of a 259s boot." It was a
COMMENT in one file, so nothing stopped it coming back: two days later the
same line in cell_deliberation held the app's mutation lock through 162,904
ids on every brain observe and the watchdog killed the brain three times in
one night (2026-09-07). This court is the guard the comment never was: any
new materialisation anywhere in nodelang fails here, and the few legitimate
ones are named with the reason they are allowed.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Materialising the whole head map is legitimate ONLY where the store is
# known to be empty or the work is already O(store) by nature. Each entry
# says why; anything else is a defect.
ALLOWED = {
    ("unified_authority.py", "the genesis check: revision 0, one cell"),
    ("checkpoint_authority_provisioning.py", "provisioning asserts an empty graph"),
    ("universal_map_import.py", "import time, the whole map is being read anyway"),
    ("universal_application.py", "a detach verification that compares two snapshots"),
    ("cell_revision_checkpoint.py", "a snapshot digest commits to every cell by definition"),
}

PATTERN = re.compile(r"(?:set|frozenset|list|tuple|sorted)\(\s*(?:store\.)?snapshot\(?\)?\.cells\s*\)")


def test_no_new_module_materialises_the_head_map():
    offenders = []
    for path in sorted((ROOT / "nodelang").glob("*.py")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith("#"):
                continue
            if PATTERN.search(line):
                if any(path.name == name for name, _why in ALLOWED):
                    continue
                offenders.append("%s:%d %s" % (path.name, number, line.strip()[:90]))
    assert not offenders, (
        "the head map is lazy over the whole journal; ask it root by root: "
        + ", ".join(offenders))


def test_every_allowance_is_still_real():
    for name, why in ALLOWED:
        path = ROOT / "nodelang" / name
        assert path.is_file(), name
        assert why, name
        assert PATTERN.search(path.read_text(encoding="utf-8", errors="replace")), (
            "%s no longer materialises anything; drop its allowance" % name)
