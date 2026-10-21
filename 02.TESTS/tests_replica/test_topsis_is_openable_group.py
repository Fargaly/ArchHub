"""TOPSIS is a GROUP you can OPEN, not hidden engine code (founder, 2026-07-09).

From outside: one node ("Rank Design Options"). Open it: the steps are real
generic nodes (normalize -> weight -> best -> worst -> distance -> rank) wired
in the one table. This is "everything is a node": a decision ALGORITHM as a
visible composition of primitives, with no `op='topsis'` anywhere in the engine.
"""
import os
import pytest

from nodelang.core import Store, validate_store
from nodelang.laws_decision import build_topsis_group

CORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    'nodelang', 'core.py')


def test_no_topsis_op_left_in_the_engine():
    src = open(CORE, encoding='utf-8').read()
    assert "op == 'topsis'" not in src      # the hidden command is gone
    assert 'def _topsis' not in src


def test_group_matches_the_algorithm_numerically():
    for matrix, w, ben, want in [
        ([[1, 0], [0, 1]], [0.7, 0.3], [True, True], [0.7, 0.3]),
        ([[2, 1], [1, 2]], [0.5, 0.5], [True, False], [1.0, 0.0]),
    ]:
        s = Store()
        g = build_topsis_group(s, matrix, w, ben)
        assert validate_store(s) is True
        assert s.pull(g) == pytest.approx(want)


def test_it_is_an_openable_group_of_visible_steps():
    s = Store()
    g = build_topsis_group(s, [[100, 8, 6], [140, 9, 9], [80, 6, 5]],
                           [0.4, 0.2, 0.4], [False, True, True],
                           title='Rank Design Options')
    node = s.nodes[g]
    assert node['kind'] == 'group'                 # ONE node from outside
    titles = [s.nodes[c]['title'] for c in node['body']['inner']]
    # open it -> the algorithm's steps are real visible nodes
    for step in ('norm[0]', 'best[0]', 'worst[0]', 'dbest[0]', 'dworst[0]', 'ranking'):
        assert step in titles, step
    # facade example: B (good beauty+energy) wins despite higher cost
    scores = s.pull(g)
    assert scores.index(max(scores)) == 1


def test_editing_a_weight_node_reranks_live():
    s = Store()
    g = build_topsis_group(s, [[1, 0], [0, 1]], [0.7, 0.3], [True, True])
    assert s.pull(g) == pytest.approx([0.7, 0.3])
    w0 = next(nid for nid, n in s.nodes.items() if n['title'] == 'w[0]')
    w1 = next(nid for nid, n in s.nodes.items() if n['title'] == 'w[1]')
    s.edit(w0, ['body', 'floor', 'value'], 0.5)
    s.edit(w1, ['body', 'floor', 'value'], 0.5)
    assert s.pull(g) == pytest.approx([0.5, 0.5])   # the watcher: edit node -> rerank
