"""CI gate for the founder's challenge: *"DID YOU TEST THE EFFICIENCY OF THESE
STEM NODES BY RECREATING THE PREVIOUS SESSIONS?"* (2026-06-09).

This pins, in the suite forever, that the #90 stem-cell palette can RECREATE a
real past session — the BBC4 submittal-QC reconcile — by composing REGISTERED
cells into a graph the real `WorkflowRunner` cooks against a real on-disk
fixture (`proof_bbc4/`). It reuses `tools/proof_bbc4_recreate.build_graph` so
there is ONE source of truth for the recreation, not a parallel copy.

Jury-verified live (workflow wf_9b16fbd9, 2026-06-09): artifact / diligence /
palette-reachability lenses each failed to refute on the real artifact, incl. an
anti-tamper probe (adding a file to the fixture flips the partition → FAIL).

BOUNDARY (honest): this is the ENGINE half — registered cells compose + the
runner cooks real disk + the partition is correct. It does NOT prove a human
dragged the cells in the live PyQt GUI; that needs the running app + CDP and is
verified separately.
"""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
# APPEND (never insert(0)) and only app/ + tools/ — prepending, or adding the
# repo root itself, would change import precedence for the whole test session
# and can cause order-dependent failures in unrelated suites.
for _p in (os.path.join(_REPO, "tools"), os.path.join(_REPO, "app")):
    if _p not in sys.path:
        sys.path.append(_p)

# HARD import — this is a CI GATE, so a missing/broken proof module or fixture
# must FAIL LOUD, never silently skip (a skip would let a regression sail
# through CI green). proof_bbc4/ is committed beside this test, so it is always
# present in CI. Importing the proof module also loads the whole node registry
# (its import side effect) and gives us the SAME build_graph the live proof uses.
import proof_bbc4_recreate as proof  # noqa: E402

from workflows import registry              # noqa: E402
from workflows.runner import WorkflowRunner  # noqa: E402
from workflows.subgraph import compose_subgraph  # noqa: E402

assert os.path.isdir(proof.SUBMITTALS) and os.path.isfile(proof.MASTER), (
    "proof_bbc4/ fixture missing — this CI gate requires it present, not skipped")

USED_CELLS = ["fs.list", "fs.read", "data.json", "code.python",
              "verify.assert", "subgraph.user"]


def _cook_partition():
    graph = proof.build_graph()
    runner = WorkflowRunner(graph)
    out = runner.pull("partition")
    # upstream_error propagates an upstream cell's failure (fs.read / data.json);
    # treat it as a failure too — never let it slip through as a false success.
    assert out.get("status") not in ("error", "upstream_error"), out.get("error")
    part = out.get("value") or {}
    return runner, {k: part.get(k) for k in ("matched", "strays", "missing")}


def test_used_cells_are_registered_executors():
    """Every cell the recreation uses is a REAL registered executor — not a
    bespoke shim. (ANTI-LIE: the palette cells do the work.)"""
    for t in USED_CELLS:
        assert registry.get(t) is not None, f"cell {t!r} is not registered"


def test_used_cells_are_palette_reachable():
    """The founder's point — a visual user must be able to FIND each cell in
    the palette. Every used cell maps to a real category in the same map the
    JSX palette renders (`all_specs_by_category`)."""
    by = registry.all_specs_by_category()
    cat = {s.type: k for k, specs in by.items() for s in specs}
    missing = [c for c in USED_CELLS if c not in cat]
    assert not missing, f"cells not reachable from any palette category: {missing}"


def test_stem_palette_recreates_bbc4_qc_partition():
    """The composed graph of palette cells, cooked against the REAL fixture,
    produces the exact matched/strays/missing partition of the past session.
    The file list + master come from real disk reads (fs.list scandir / fs.read
    open), never inlined — see the proof module."""
    runner, got = _cook_partition()
    expected = {k: proof.EXPECTED[k] for k in ("matched", "strays", "missing")}
    assert got == expected, f"partition {got} != truth set {expected}"

    # the upstream cells actually read disk (not a constant): fs.list saw the
    # 5 fixture files, fs.read pulled the master bytes.
    list_out = runner.node_outputs.get("list_folder", {})
    read_out = runner.node_outputs.get("read_master", {})
    assert list_out.get("count"), "fs.list cooked 0 rows — did not read disk"
    assert read_out.get("bytes_read"), "fs.read read 0 bytes — did not read disk"


def test_in_graph_verify_assert_gate_passes():
    """The in-graph verify.assert cell (the canvas-visible gate) independently
    confirms the partition equals the oracle."""
    runner, _ = _cook_partition()
    assert_out = runner.pull("assert_truth")
    assert bool(assert_out.get("passed")), assert_out.get("report")


def test_cells_collapse_into_one_subgraph_composite():
    """Composability (Cmd-G): the partition cells collapse into a single
    subgraph.user composite via the real compose_subgraph, and that composite
    cooks to the same correct partition."""
    graph = proof.build_graph()
    composed = compose_subgraph(graph, ["parse_master", "partition"],
                                title="BBC4 QC partition")
    comp_node = next(n for n in composed["nodes"]
                     if n.get("type") == "subgraph.user")
    out = WorkflowRunner(composed).pull(comp_node["id"])
    comp_val = next((v for v in out.values()
                     if isinstance(v, dict) and "matched" in v), None)
    assert comp_val is not None, "composite produced no partition output"
    got = {k: comp_val.get(k) for k in ("matched", "strays", "missing")}
    expected = {k: proof.EXPECTED[k] for k in ("matched", "strays", "missing")}
    assert got == expected, f"composite partition {got} != {expected}"
