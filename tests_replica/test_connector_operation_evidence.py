"""Court: every catalogue operation has real evidence or a named dependency.

The table (nodelang/connector_operation_evidence.py) must cover exactly the
engines the catalogue declares, every named court must be a test that exists,
and the courts this file owns run the real engines on real inputs: the DXF
file the installer ships, real skill files, a real folder, this machine.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodelang import connector_operation_evidence as evidence  # noqa: E402
from nodelang.pipeline_engines import PIPELINE_ENGINES  # noqa: E402


def test_the_table_covers_exactly_the_catalogue():
    assert set(evidence.EVIDENCE) == set(PIPELINE_ENGINES)
    for op, row in evidence.EVIDENCE.items():
        assert len(row) == 1 and set(row) <= {"court", "unavailable"}, op
        assert next(iter(row.values())).strip(), op


def test_every_library_card_maps_to_an_operation_in_the_table():
    from nodelang.library_engines import LIBRARY_ITEM_ENGINES
    assert {row["engine"] for row in LIBRARY_ITEM_ENGINES.values()} <= set(evidence.EVIDENCE)


def test_every_named_court_is_a_test_that_exists():
    for op, row in evidence.EVIDENCE.items():
        if "court" not in row:
            continue
        file_part, name = row["court"].split("::")
        tree = ast.parse((ROOT / file_part).read_text(encoding="utf-8"))
        names = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
        assert name in names, (op, row["court"])


def test_rows_say_court_or_unavailable_and_carry_the_live_connector_state():
    rows = evidence.operation_rows([{"id": "rhino", "state": "installed"}])
    assert [row["op"] for row in rows] == sorted(PIPELINE_ENGINES)
    assert {row["evidence"] for row in rows} == {"court", "unavailable"}
    rhino = next(row for row in rows if row["op"] == "rhino.exec")
    assert rhino["evidence"] == "unavailable" and rhino["connector_state"] == "installed"


# ------------------------------------------ the real courts this table names --

def test_cad_read_lines_reads_the_shipped_sample_dxf():
    sample = ROOT / "nodelang" / "samples" / "sample-plan.dxf"
    out, said = PIPELINE_ENGINES["cad.read_lines"]({"file_path": str(sample)}, {})
    lines = out["out"]
    assert lines and all(len(line) == 4 for line in lines)
    assert said == "%d lines from sample-plan.dxf" % len(lines)


def test_lines_watch_passes_real_lines_through():
    sample = ROOT / "nodelang" / "samples" / "sample-plan.dxf"
    lines = PIPELINE_ENGINES["cad.read_lines"]({"file_path": str(sample)}, {})[0]["out"]
    out, said = PIPELINE_ENGINES["lines.watch"]({}, {"in": lines})
    assert out["out"] == lines and said.startswith("%d lines" % len(lines))


def test_skill_engines_read_real_skill_files(tmp_path, monkeypatch):
    home = tmp_path / "home"
    skill = home / ".claude" / "skills" / "court-skill"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: court-skill\ndescription: >\n  Proves the skill engines read files.\n---\nBody line.\n",
        encoding="utf-8")
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("HOME", str(home))
    catalogue, _ = PIPELINE_ENGINES["skills.catalogue"]({"match": "court-skill"}, {})
    found = [row for row in catalogue["out"] if row["name"] == "court-skill"]
    assert found and found[0]["description"] == "Proves the skill engines read files."
    body, said = PIPELINE_ENGINES["skills.read"]({"skill": "court-skill"}, {})
    assert "Body line." in body["out"] and "court-skill" in said
    chain, _ = PIPELINE_ENGINES["skills.thinking_chain"]({}, {})
    assert isinstance(chain["out"], str) and chain["out"].strip()
    matched, said = PIPELINE_ENGINES["library.match_skill"]({"intent": "prove the skill engines", "count": "5"}, {})
    assert "court-skill" in [row["name"] for row in matched["out"]] and "word overlap" in said


def test_dropbox_list_reads_a_real_folder(tmp_path, monkeypatch):
    from nodelang import host_brokers
    profile = tmp_path / "profile"
    (profile / "Dropbox" / "Project A").mkdir(parents=True)
    (profile / "Dropbox" / "notes.txt").write_text("12345", encoding="utf-8")
    monkeypatch.setattr(host_brokers.Path, "home", classmethod(lambda cls: profile))
    monkeypatch.setenv("USERPROFILE", str(profile))
    out, said = PIPELINE_ENGINES["dropbox.list"]({}, {})
    assert {row["name"]: row["bytes"] for row in out["out"]} == {"Project A": 0, "notes.txt": 5}
    escaped = PIPELINE_ENGINES["dropbox.list"]({"path": ".."}, {})[0]
    assert escaped["ok"] is False


def test_connector_probes_read_this_machine():
    """The probes read this machine's processes and install paths; every row has a state.

    The court guard (conftest.no_live_hosts) keeps ports and COM closed, so a
    live connection is never part of this court and nothing is opened.
    """
    rows, said = PIPELINE_ENGINES["connector.rows"]({}, {})
    assert rows["out"] and all(row.get("state") for row in rows["out"])
    status, _ = PIPELINE_ENGINES["connector.status"]({"connector": rows["out"][0]["id"]}, {})
    assert status["out"][0]["id"] == rows["out"][0]["id"]
