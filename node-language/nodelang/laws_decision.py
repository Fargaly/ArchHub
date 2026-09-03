"""nodelang.laws_decision -- decisions as VISIBLE node compositions, not engine
commands (founder, 2026-07-09).

TOPSIS is not a Lego brick -- it is a small machine made of bricks: normalize ->
weight -> ideal best -> ideal worst -> distance -> rank. So it must be a GROUP
node: from outside you see one node ("Rank Design Options"); open it and you see
those steps as real generic nodes (math/merge over wires) in the one table. No
hidden `op='topsis'` -- the algorithm IS the visible sub-graph.

build_topsis_group(store, matrix, weights, benefit) wires the steps from the
generic floor primitives only (math +,-,*,/,min,max,sqrt ; merge list) and
returns the group node id. The group's value = the ranking (closeness score per
option, in row order), because the pack node is the group's only sink.
"""
from __future__ import annotations


def _val(store, title, v, bag):
    nid = store.add('value', title, floor={'op': 'value', 'value': v})
    bag.append(nid)
    return nid


def _math(store, fn, srcs, title, bag):
    """A generic math node; operands arrive through wires (in `srcs` order)."""
    nid = store.add('op', title, floor={'op': 'math', 'fn': fn})
    for s in srcs:
        store.wire(s, nid)
    bag.append(nid)
    return nid


def _sq(store, src, title, bag):
    """x^2 = math '*' with the SAME source wired twice (composition, no pow op)."""
    return _math(store, '*', [src, src], title, bag)


def build_topsis_group(store, matrix, weights, benefit=None, title='Rank Design Options'):
    """Build TOPSIS as an openable group of visible generic nodes. Returns the
    group node id; its value = closeness score per row (higher = better)."""
    nrows = len(matrix)
    ncols = len(matrix[0])
    benefit = benefit if benefit is not None else [True] * ncols
    inner = []

    # -- input layer: the option/criterion matrix (values) + the weights, which
    #    are PARAM nodes (a weight IS a parameter, SPEC section 2 -- edit one and
    #    the ranking re-cooks) ---------------------------------------------------
    cell = [[_val(store, 'x[%d,%d]' % (i, j), matrix[i][j], inner)
             for j in range(ncols)] for i in range(nrows)]
    wnode = []
    for j in range(ncols):
        pid = store.add('param', 'w[%d]' % j, floor={'op': 'value', 'value': weights[j]})
        inner.append(pid)
        wnode.append(pid)

    # -- step 1: normalize -- per column, norm_j = sqrt(sum_i x_ij^2) -----------
    norm = []
    for j in range(ncols):
        sqs = [_sq(store, cell[i][j], 'sq[%d,%d]' % (i, j), inner) for i in range(nrows)]
        ss = _math(store, '+', sqs, 'sumsq[%d]' % j, inner)
        norm.append(_math(store, 'sqrt', [ss], 'norm[%d]' % j, inner))
    normd = [[_math(store, '/', [cell[i][j], norm[j]], 'n[%d,%d]' % (i, j), inner)
              for j in range(ncols)] for i in range(nrows)]

    # -- step 2: apply weights -- v_ij = normalized * w_j ----------------------
    wtd = [[_math(store, '*', [normd[i][j], wnode[j]], 'v[%d,%d]' % (i, j), inner)
            for j in range(ncols)] for i in range(nrows)]

    # -- step 3/4: ideal best + ideal worst per column (benefit=max, cost=min) --
    best, worst = [], []
    for j in range(ncols):
        col = [wtd[i][j] for i in range(nrows)]
        best.append(_math(store, 'max' if benefit[j] else 'min', col, 'best[%d]' % j, inner))
        worst.append(_math(store, 'min' if benefit[j] else 'max', col, 'worst[%d]' % j, inner))

    # -- step 5: distance of each option to best and to worst ------------------
    def _dist(i, ref, tag):
        sqs = []
        for j in range(ncols):
            d = _math(store, '-', [wtd[i][j], ref[j]], '%s_d[%d,%d]' % (tag, i, j), inner)
            sqs.append(_sq(store, d, '%s_sq[%d,%d]' % (tag, i, j), inner))
        ss = _math(store, '+', sqs, '%s_ss[%d]' % (tag, i), inner)
        return _math(store, 'sqrt', [ss], '%s[%d]' % (tag, i), inner)

    # -- step 6: closeness score = d_worst / (d_best + d_worst), then RANK -----
    scores = []
    for i in range(nrows):
        db = _dist(i, best, 'dbest')
        dw = _dist(i, worst, 'dworst')
        denom = _math(store, '+', [db, dw], 'denom[%d]' % i, inner)
        scores.append(_math(store, '/', [dw, denom], 'score[%d]' % i, inner))
    rank = store.add('op', 'ranking', floor={'op': 'merge', 'fn': 'list'})
    for sc in scores:
        store.wire(sc, rank)
    inner.append(rank)

    return store.add('group', title, inner=inner)   # value = rank (its only sink)
