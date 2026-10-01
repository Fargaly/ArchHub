"""Canvas card parity, field 1 — a node's result line is its REAL last run.

The design shows a result on the card ("47 walls"). The shipped renderer (LiveBody)
had nothing to draw because the projection carried no result. This proves the data
source: latest_run_by_node reads each node's last run from the graph's history in ONE
pass (no per-node walk — canvas-perf), wording it exactly as the Properties panel does
(_run_summary), and a node that never ran is absent (honest-empty, never a stale or
borrowed count).

RED on fd2bba8c: latest_run_by_node does not exist (ImportError on collection).
"""
import uuid

from nodelang.clean_visual_projection import (
    destructive_operations, latest_run_by_node, _run_summary)
from nodelang.clean_host_operations import read_host_operations
from tests_replica.test_clean_server_visual_projection import _provision_clean_runtime


def _install_probe(authority, caller):
    from nodelang.clean_host_operations import (
        compose_host_operations, install_host_operations,
    )
    install_host_operations(
        authority,
        compose_host_operations([{
            "op_id": "probe.rows", "host": "probe", "kind": "read",
            "label": "Rows", "description": "d", "output_type": "row",
            "destructive": False, "inputs": [],
        }]),
        caller=caller, command_id=str(uuid.uuid4()),
    )


def _run(authority, caller, node, names):
    from nodelang.clean_host_execution import execute_host_operation
    execute_host_operation(
        authority, "probe.rows", {}, caller=caller,
        command_id=str(uuid.uuid4()), subject_root=node,
        invoker=lambda op, args: {"result": [{"name": name} for name in names]},
    )


def test_each_nodes_result_is_its_own_real_run_in_one_pass(tmp_path):
    built, _provider = _provision_clean_runtime(tmp_path)
    authority, caller = built.location.authority, built.caller
    _install_probe(authority, caller)
    _run(authority, caller, "node-a", ["alpha"])
    _run(authority, caller, "node-b", ["beta", "gamma"])  # newer run, different node

    summaries = latest_run_by_node(
        authority, authority.store.snapshot(),
        ["node-a", "node-b", "node-never-run"])
    # Each node shows ITS run, worded exactly as the Properties panel words it.
    assert summaries["node-a"] == _run_summary("probe.rows", 1, 1)
    assert summaries["node-b"] == _run_summary("probe.rows", 2, 2)
    # A node that never ran has no result line -- honest empty, not a borrowed count.
    assert "node-never-run" not in summaries


def test_a_run_scrolled_past_the_bound_reads_as_no_result(tmp_path):
    built, _provider = _provision_clean_runtime(tmp_path)
    authority, caller = built.location.authority, built.caller
    _install_probe(authority, caller)
    _run(authority, caller, "node-a", ["alpha"])
    _run(authority, caller, "node-b", ["beta"])  # newer than node-a
    # Bounded walk: with room for only the newest member, node-a's older run is
    # not found -- the card reads as no run rather than getting slower forever.
    assert latest_run_by_node(
        authority, authority.store.snapshot(), ["node-a"], limit=1) == {}


def test_mutation_badge_comes_from_the_graph_held_destructive_flag(tmp_path):
    """The card's "mutates model, requires approval" is the operation catalogue's
    own `destructive` flag, read from the graph -- not a Python guess; a read op
    gets no badge, and a node whose operation is unknown gets none (honest empty).
    """
    from nodelang.clean_host_operations import (
        compose_host_operations, install_host_operations,
    )
    built, _provider = _provision_clean_runtime(tmp_path)
    authority, caller = built.location.authority, built.caller
    install_host_operations(
        authority,
        compose_host_operations([
            {"op_id": "revit.place", "host": "revit", "kind": "write", "label": "Place",
             "description": "d", "output_type": "row", "destructive": True, "inputs": []},
            {"op_id": "revit.list", "host": "revit", "kind": "read", "label": "List",
             "description": "d", "output_type": "row", "destructive": False, "inputs": []},
        ]),
        caller=caller, command_id=str(uuid.uuid4()),
    )
    flags = destructive_operations(read_host_operations(authority, caller=caller))
    assert flags["revit.place"] is True        # mutates -> the badge shows
    assert flags["revit.list"] is False        # read -> no badge
    assert "revit.unknown" not in flags        # a node with no such op -> honest empty
