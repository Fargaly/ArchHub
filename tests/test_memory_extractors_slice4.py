"""AgDR-0042 slice 4/6 — decision + project extractors.

Decision extractor walks docs/agdr/*.md (REAL filesystem read of the
repo's own AgDRs, since they're stable test data). Project extractor
walks tmp_path so we never touch the user's real Speckle store.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
REPO = Path(__file__).resolve().parents[1]
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from memory import MemoryGraph, Confidence  # noqa: E402
from memory.extractors import (  # noqa: E402
    extract_decisions, extract_projects, extract_library,
)


# ──────────────────────────────────────────────────────────────────────
#  DECISION EXTRACTOR
# ──────────────────────────────────────────────────────────────────────


@pytest.fixture
def g():
    graph = MemoryGraph.open(":memory:")
    yield graph
    graph.close()


@pytest.fixture
def agdr_dir():
    return REPO / "docs" / "agdr"


def test_extract_decisions_emits_decision_nodes(g, agdr_dir):
    stats = extract_decisions(g, agdr_dir)
    assert stats["decisions_added"] > 30, (
        "expected at least 30 AgDRs in docs/agdr/ — got "
        f"{stats['decisions_added']}")
    decisions = g.all_nodes(kind="decision")
    ids = {n.id for n in decisions}
    # Spot-check a few that definitely exist in the repo.
    assert "agdr:0001" in ids
    assert "agdr:0040" in ids
    assert "agdr:0041" in ids
    assert "agdr:0042" in ids


def test_extract_decisions_label_is_title_not_filename(g, agdr_dir):
    extract_decisions(g, agdr_dir)
    n = g.get_node("agdr:0042")
    assert n is not None
    # The H1 title contains the words "Shared-memory" per the AgDR file.
    assert "memory" in n.label.lower()


def test_extract_decisions_props_carry_status(g, agdr_dir):
    extract_decisions(g, agdr_dir)
    n = g.get_node("agdr:0041")
    assert n is not None
    # AgDR-0041 was flipped to executed in commit a27196e earlier.
    assert n.props["status"] in ("executed", "executing")


def test_extract_decisions_builds_on_edges(g, agdr_dir):
    extract_decisions(g, agdr_dir)
    # AgDR-0041 builds-on [AgDR-0001, AgDR-0040].
    out = g.neighbors("agdr:0041", direction="out", relation="builds_on")
    targets = {e.target for e in out}
    assert "agdr:0001" in targets
    assert "agdr:0040" in targets
    # All builds_on edges are EXTRACTED.
    for e in g.all_edges(relation="builds_on"):
        assert e.confidence == Confidence.EXTRACTED


def test_extract_decisions_no_self_edges(g, agdr_dir):
    extract_decisions(g, agdr_dir)
    for e in g.all_edges():
        assert e.source != e.target, (
            f"self-edge on {e.source} via {e.relation}")


def test_extract_decisions_is_idempotent(g, agdr_dir):
    s1 = extract_decisions(g, agdr_dir)
    n1 = g.count_nodes()
    e1 = g.count_edges()
    s2 = extract_decisions(g, agdr_dir)
    assert g.count_nodes() == n1
    assert g.count_edges() == e1
    assert s1["decisions_added"] == s2["decisions_added"]


def test_extract_decisions_missing_dir_returns_zero(g, tmp_path):
    stats = extract_decisions(g, tmp_path / "no_such_dir")
    assert stats == {"decisions_added": 0, "builds_on_edges": 0,
                      "supersedes_edges": 0, "rationale_for_edges": 0}


def test_extract_decisions_rationale_for_synthetic(g, tmp_path):
    """A purpose-built AgDR whose Artifacts section names a module
    that maps to a known library cap surfaces a rationale_for edge."""
    # Seed a cap whose type's last segment matches the module name
    # we'll reference from the AgDR.
    from memory.graph import MemoryNode
    g.add_node(MemoryNode(
        id="lib:cap:render.comfyui", kind="capability",
        label="ComfyUI", props={"type": "render.comfyui"}))
    d = tmp_path / "agdr"
    d.mkdir()
    (d / "AgDR-9100-test.md").write_text(
        "---\nid: AgDR-9100\nstatus: executed\n---\n"
        "# Test decision\n\n"
        "## Artifacts\n\n"
        "- `app/connectors/comfyui.py` — connector module\n",
        encoding="utf-8")
    stats = extract_decisions(g, d)
    rf = g.all_edges(relation="rationale_for")
    assert len(rf) == 1, f"expected 1 rationale_for, got {len(rf)}: {rf}"
    assert rf[0].source == "agdr:9100"
    assert rf[0].target == "lib:cap:render.comfyui"
    assert rf[0].confidence == Confidence.INFERRED


def test_extract_decisions_rationale_for_real_repo_smoke(g, agdr_dir):
    """Sanity: real-repo run doesn't crash. May produce 0 rationale_for
    edges if AgDR Artifacts sections happen not to reference module
    names that match any library type's last dotted segment (the
    common case — most AgDRs cite app/workflows/runner.py etc., not
    app/connectors/<cap_name>.py)."""
    extract_library(g, infer_wires=False)
    extract_decisions(g, agdr_dir)
    # No assertion on count — just no exceptions; rationale_for in real
    # repos depends on heuristic match.
    rf = g.all_edges(relation="rationale_for")
    for e in rf:
        assert e.confidence == Confidence.INFERRED


def test_extract_decisions_synthetic_supersedes(g, tmp_path):
    """A purpose-built minimal AgDR pair that exercises supersedes
    via the `superseded by` status string + the `supersedes:` field."""
    d = tmp_path / "agdr"
    d.mkdir()
    (d / "AgDR-9001-old.md").write_text(
        "---\nid: AgDR-9001\nstatus: superseded by AgDR-9002\n---\n"
        "# Old decision\n", encoding="utf-8")
    (d / "AgDR-9002-new.md").write_text(
        "---\nid: AgDR-9002\nstatus: executed\nsupersedes: AgDR-9001\n---\n"
        "# New decision\n", encoding="utf-8")
    stats = extract_decisions(g, d)
    assert stats["decisions_added"] == 2
    assert stats["supersedes_edges"] >= 2  # both forms emit one each


# ──────────────────────────────────────────────────────────────────────
#  PROJECT EXTRACTOR
# ──────────────────────────────────────────────────────────────────────


def _make_project(root: Path, name: str, designs: list[str]) -> Path:
    proj = root / name / ".speckle"
    proj.mkdir(parents=True)
    for d in designs:
        (proj / f"{d}.sqlite").write_bytes(b"speckle_blob_" + d.encode())
    return root / name


@pytest.fixture
def root(tmp_path):
    """Per-test isolated projects-root. tmp_path can be polluted by
    other pytest machinery (artifacts, cache dirs) so we always use a
    fresh subdir we control entirely."""
    r = tmp_path / "store"
    r.mkdir()
    return r


def test_extract_projects_missing_root_returns_zero(g, root):
    stats = extract_projects(g, root / "nope")
    assert stats == {"projects_added": 0, "designs_added": 0,
                      "contains_edges": 0}


def test_extract_projects_empty_dir_returns_zero(g, root):
    stats = extract_projects(g, root)
    assert stats == {"projects_added": 0, "designs_added": 0,
                      "contains_edges": 0}


def test_extract_projects_emits_project_node(g, root):
    _make_project(root, "tower2", ["wires_a", "wires_b"])
    stats = extract_projects(g, root)
    assert stats["projects_added"] == 1
    assert stats["designs_added"] == 2
    proj = g.get_node("proj:tower2")
    assert proj is not None
    assert proj.kind == "project"
    assert proj.props["name"] == "tower2"


def test_extract_projects_emits_design_nodes(g, root):
    _make_project(root, "default", ["m1", "m2"])
    extract_projects(g, root)
    designs = g.all_nodes(kind="design")
    ids = {d.id for d in designs}
    assert "proj:default:m1" in ids
    assert "proj:default:m2" in ids


def test_extract_projects_emits_contains_edges(g, root):
    _make_project(root, "default", ["m1"])
    extract_projects(g, root)
    out = g.neighbors("proj:default", direction="out", relation="contains")
    assert len(out) == 1
    assert out[0].target == "proj:default:m1"
    assert out[0].confidence == Confidence.EXTRACTED


def test_extract_projects_design_props_carry_size_and_mtime(g, root):
    _make_project(root, "p", ["blob"])
    extract_projects(g, root)
    d = g.get_node("proj:p:blob")
    assert d is not None
    assert d.props["size_bytes"] > 0
    assert d.props["mtime"] > 0
    assert d.props["source"] == "speckle.disk_transport"


def test_extract_projects_skips_dirs_without_speckle_subdir(g, root):
    """A project dir with no .speckle/ shouldn't crash — just no
    design nodes for that project."""
    (root / "barebones").mkdir()
    _make_project(root, "real", ["m1"])
    stats = extract_projects(g, root)
    assert stats["projects_added"] == 2
    assert stats["designs_added"] == 1
    assert g.get_node("proj:barebones") is not None


def test_extract_projects_is_idempotent(g, root):
    _make_project(root, "p", ["m"])
    s1 = extract_projects(g, root)
    n1 = g.count_nodes(); e1 = g.count_edges()
    s2 = extract_projects(g, root)
    assert g.count_nodes() == n1
    assert g.count_edges() == e1
    assert s1 == s2
