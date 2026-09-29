"""Court: signing up seeds the personal brain, and nothing it seeds can leave.

The Practice step says it "seeds the brain". Until P1 it wrote the answers to
localStorage only. Now finish() remembers one fact per answer through the
owner's own Brain route, and those facts are never classified, so
may_release answers False for the firm and the community lakes.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests_replica.test_settings_terminal_routes import call, server  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
ACCOUNT = ROOT / "nodelang" / "studio" / "studio-account.jsx"


def _source():
    return ACCOUNT.read_text(encoding="utf-8")


def test_finish_remembers_every_seed_fact():
    jsx = _source()
    finish = jsx[jsx.index("  const finish = () => {"):]
    finish = finish[:finish.index("\n  };") + 5]
    assert "acSeedFacts(rec, hosts).forEach(text => window.ARCHHUB_REMEMBER(text)" in finish
    assert finish.index("ARCHHUB_REMEMBER") < finish.index("onDone && onDone(rec)")


def test_the_brain_step_shows_exactly_what_is_seeded():
    jsx = _source()
    step = jsx[jsx.index("SEEDED FROM THIS SIGN-UP"):]
    step = step[:step.index("</div>\n              </div>")]
    assert "{acSeedFacts(a, hosts).map(" in step


def test_the_seed_facts_are_the_answers_given():
    node = shutil.which("node")
    if not node:
        pytest.skip("node is not installed")
    jsx = _source()
    start = jsx.index("const acSeedFacts = ")
    body = jsx[start:jsx.index("].filter(Boolean);", start) + len("].filter(Boolean);")]
    script = body + "\nconsole.log(JSON.stringify([" \
        "acSeedFacts({name: 'Amina Habib', firm: '  Habib Studio ', discipline: 'Architecture'}, ['Revit', 'AutoCAD'])," \
        "acSeedFacts({name: '', firm: ' ', discipline: ''}, [])]));"
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=60, check=True)
    full, empty = json.loads(out.stdout)
    assert full == ["My name is Amina Habib.", "My practice is Habib Studio.", "My discipline is Architecture.",
                    "The design tools on this machine are Revit, AutoCAD."]
    assert empty == [], "an unanswered step seeds nothing"


def test_seeded_facts_land_in_the_graph_and_stay_on_this_machine(server):
    from nodelang import app_brain
    from nodelang.cell_brain_governance import may_release
    seeds = ["My practice is Habib Studio.", "My discipline is Architecture."]
    for text in seeds:
        assert call(server, "/api/universal/brain-remember", {"text": text}) == {"ok": True, "written": 1}
    held = {fact["body"] for folder in app_brain.list_facts()["folders"] for fact in folder["facts"]}
    assert set(seeds) <= held
    snapshot = server.universal_store.snapshot()
    for text in seeds:
        fragment = hashlib.sha256(text.encode("utf-8")).hexdigest()
        for lake in ("firm", "community"):
            release = may_release(snapshot, session_root=app_brain.SESSION_ROOT,
                                  fragment_id=fragment, to_lake=lake)
            assert release.allowed is False, (text, lake, release)