"""Slice C3 — group nesting + recursive member-set + cycle guard.

Reference: AgDR-0006. Adds `childGroupIds: string[]` to the group
data model. `expand_group_members` recursively walks the group tree
returning every leaf node id. `would_create_cycle` refuses
mutations that would close a loop in the tree. `_promoted_ports_for`
takes the recursive member-set when `childGroupIds` is non-empty,
so boundary-port promotion remains correct for nested collapses.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.node_grammar import (  # noqa: E402
    expand_group_members,
    would_create_cycle,
    _promoted_ports_for,
    expand_collapsed_groups,
    normalize_canvas_graph,
)


# ─── 1. expand_group_members ─────────────────────────────────────────


def test_expand_flat_group_returns_node_ids():
    """A group with only `nodeIds` (no children) → its nodeIds as a
    set."""
    groups = [{"id": "g1", "nodeIds": ["n1", "n2"], "childGroupIds": []}]
    assert expand_group_members("g1", groups) == {"n1", "n2"}


def test_expand_one_level_nesting():
    """Parent → child → returns the UNION of both leaf sets."""
    groups = [
        {"id": "parent", "nodeIds": ["pn"], "childGroupIds": ["child"]},
        {"id": "child", "nodeIds": ["cn1", "cn2"], "childGroupIds": []},
    ]
    assert expand_group_members("parent", groups) == {"pn", "cn1", "cn2"}


def test_expand_two_levels_nesting():
    """A → B → C three-level nesting returns ALL leaves."""
    groups = [
        {"id": "A", "nodeIds": ["a1"], "childGroupIds": ["B"]},
        {"id": "B", "nodeIds": ["b1"], "childGroupIds": ["C"]},
        {"id": "C", "nodeIds": ["c1", "c2"], "childGroupIds": []},
    ]
    assert expand_group_members("A", groups) == {"a1", "b1", "c1", "c2"}


def test_expand_cycle_safe():
    """A group that references itself → does not RecursionError;
    returns the visited subtree's leaves (without re-entering)."""
    groups = [
        {"id": "loop", "nodeIds": ["x"], "childGroupIds": ["loop"]},
    ]
    # Should not blow the stack.
    result = expand_group_members("loop", groups)
    assert result == {"x"}


def test_expand_indirect_cycle_safe():
    """A → B → A cycle → returns leaves visited, no infinite recursion."""
    groups = [
        {"id": "A", "nodeIds": ["a1"], "childGroupIds": ["B"]},
        {"id": "B", "nodeIds": ["b1"], "childGroupIds": ["A"]},
    ]
    result = expand_group_members("A", groups)
    assert result == {"a1", "b1"}


def test_expand_missing_group_returns_empty():
    """Referencing a non-existent child group → its branch
    contributes nothing."""
    groups = [
        {"id": "A", "nodeIds": ["a1"], "childGroupIds": ["missing"]},
    ]
    assert expand_group_members("A", groups) == {"a1"}


# ─── 2. would_create_cycle ───────────────────────────────────────────


def test_would_create_cycle_direct_self():
    """Adding a group as its OWN child returns True (self-loop)."""
    groups = [{"id": "g1", "nodeIds": [], "childGroupIds": []}]
    assert would_create_cycle("g1", "g1", groups) is True


def test_would_create_cycle_indirect_ancestor():
    """Parent A → Child B. Adding A as B's child closes a cycle."""
    groups = [
        {"id": "A", "nodeIds": [], "childGroupIds": ["B"]},
        {"id": "B", "nodeIds": [], "childGroupIds": []},
    ]
    assert would_create_cycle("B", "A", groups) is True


def test_would_not_create_cycle_unrelated():
    """Two unrelated groups → adding one to the other is fine."""
    groups = [
        {"id": "A", "nodeIds": [], "childGroupIds": []},
        {"id": "B", "nodeIds": [], "childGroupIds": []},
    ]
    assert would_create_cycle("A", "B", groups) is False


def test_would_create_cycle_deep_ancestor():
    """A → B → C. Adding A as C's child closes a 3-level cycle."""
    groups = [
        {"id": "A", "nodeIds": [], "childGroupIds": ["B"]},
        {"id": "B", "nodeIds": [], "childGroupIds": ["C"]},
        {"id": "C", "nodeIds": [], "childGroupIds": []},
    ]
    assert would_create_cycle("C", "A", groups) is True


# ─── 3. recursive promotion ──────────────────────────────────────────


def test_promoted_ports_nested_uses_recursive_member_set():
    """A parent group with a nested child: wires INTERNAL to the
    full subtree (both endpoints in `expand_group_members`) do NOT
    promote — they're still internal. Only wires whose counter-end
    is OUTSIDE the subtree promote."""
    nodes = [
        {"id": "outer", "kind": "number", "type": "data.constant",
         "config": {"value": 1, "value_type": "number"}},
        {"id": "pn", "kind": "number", "type": "data.passthrough",
         "config": {}},
        {"id": "cn", "kind": "number", "type": "data.passthrough",
         "config": {}},
    ]
    wires = [
        # outer → parent.pn  (external entry)
        {"from": ["outer", "value"], "to": ["pn", "value"]},
        # pn → cn (internal — both inside the subtree if parent
        # contains child)
        {"from": ["pn", "value"], "to": ["cn", "value"]},
    ]
    parent = {"id": "P", "nodeIds": ["pn"], "childGroupIds": ["C"],
              "collapsed": True}
    child = {"id": "C", "nodeIds": ["cn"], "childGroupIds": []}
    groups = [parent, child]
    promoted = _promoted_ports_for(parent, nodes, wires, all_groups=groups)
    in_keys = [(p["memberId"], p["portName"]) for p in promoted["ins"]]
    out_keys = [(p["memberId"], p["portName"]) for p in promoted["outs"]]
    # outer→pn → pn's `value` input is boundary.
    assert ("pn", "value") in in_keys
    # cn's `value` output has no external destination → boundary.
    assert ("cn", "value") in out_keys
    # pn→cn is INTERNAL: pn's `value` output is NOT boundary (its
    # only wire stays inside the subtree). cn's `value` input is
    # NOT boundary (its only wire comes from inside).
    assert ("pn", "value") not in out_keys
    assert ("cn", "value") not in in_keys


def test_collapsed_nested_graph_cooks_same():
    """A 2-level nest, parent collapsed, cooks to the same value as
    the fully-expanded form."""
    from workflows.runner import WorkflowRunner

    # ext(1) → pn(passthrough) → cn(passthrough) → out(passthrough)
    # parent group contains pn; child group contains cn; parent
    # has child as a child-group.
    expanded = {
        "nodes": [
            {"id": "ext", "type": "data.constant",
             "config": {"value": 7}},
            {"id": "pn", "type": "data.passthrough", "config": {}},
            {"id": "cn", "type": "data.passthrough", "config": {}},
            {"id": "out", "type": "data.passthrough", "config": {}},
        ],
        "wires": [
            {"from": ["ext", "value"], "to": ["pn", "value"]},
            {"from": ["pn", "value"], "to": ["cn", "value"]},
            {"from": ["cn", "value"], "to": ["out", "value"]},
        ],
        "groups": [
            {"id": "P", "nodeIds": ["pn"], "childGroupIds": ["C"],
             "collapsed": False},
            {"id": "C", "nodeIds": ["cn"], "childGroupIds": [],
             "collapsed": False},
        ],
    }
    # Same shape but parent collapsed + external wires
    # reference the parent's group socket.
    # Parent collapsed → recursive member-set = {pn, cn}.
    # Promoted ports: pn:value:in (from ext) → P:in:0;
    # cn:value:out (to out) → P:out:0.
    collapsed = {
        **expanded,
        "wires": [
            {"from": ["ext", "value"], "to": ["P:in:0", ""]},
            {"from": ["P:out:0", ""], "to": ["out", "value"]},
            {"from": ["pn", "value"], "to": ["cn", "value"]},
        ],
        "groups": [
            {"id": "P", "nodeIds": ["pn"], "childGroupIds": ["C"],
             "collapsed": True},
            {"id": "C", "nodeIds": ["cn"], "childGroupIds": [],
             "collapsed": False},
        ],
    }

    def cook(graph):
        g = normalize_canvas_graph(graph)
        return WorkflowRunner(g).run_all()

    ge = cook(expanded)
    gc = cook(collapsed)
    assert ge["results"]["out"].get("value") == 7
    assert gc["results"]["out"].get("value") == 7


# ─── 4. expand_collapsed_groups passes all_groups ────────────────────


def test_expand_collapsed_groups_promotes_via_all_groups():
    """`expand_collapsed_groups` must pass `all_groups` to
    `_promoted_ports_for` so nested promotion works."""
    nodes = [
        {"id": "ext", "kind": "number", "type": "data.constant",
         "config": {"value": 1}},
        {"id": "pn", "kind": "number", "type": "data.passthrough",
         "config": {}},
        {"id": "cn", "kind": "number", "type": "data.passthrough",
         "config": {}},
    ]
    wires = [
        # External author wired DIRECTLY to the parent's group socket
        # after collapse:
        {"from": ["ext", "value"], "to": ["P:in:0", ""]},
        # Internal wire between parent-node and child-node:
        {"from": ["pn", "value"], "to": ["cn", "value"]},
    ]
    groups = [
        {"id": "P", "nodeIds": ["pn"], "childGroupIds": ["C"],
         "collapsed": True},
        {"id": "C", "nodeIds": ["cn"], "childGroupIds": [],
         "collapsed": False},
    ]
    out = expand_collapsed_groups(
        {"nodes": nodes, "wires": wires, "groups": groups})
    # `P:in:0` (parent's first boundary input) rewrites to
    # the underlying `(pn, value)` — pn is the FIRST member of the
    # recursive set, its `value` input is boundary because it
    # connects (logically) to outside.
    assert out["wires"][0]["to"] == ["pn", "value"]
