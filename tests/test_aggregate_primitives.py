"""AgDR-0040 slice 2 — aggregate primitives.

reduce / accumulate / sort / group_by — the operators that let a node's
logic be COMPOSED from primitives rather than written as a code blob.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.nodes.aggregate import (  # noqa: E402
    _accumulate_executor,
    _group_by_executor,
    _reduce_executor,
    _sort_executor,
)


# ─── reduce ─────────────────────────────────────────────────────────


def test_reduce_sum():
    assert _reduce_executor(
        {"op": "sum"}, {"items": [1, 2, 3, 4]}, None)["value"] == 10


def test_reduce_product():
    assert _reduce_executor(
        {"op": "product"}, {"items": [2, 3, 4]}, None)["value"] == 24


def test_reduce_max():
    assert _reduce_executor(
        {"op": "max"}, {"items": [3, 9, 2]}, None)["value"] == 9


def test_reduce_count():
    assert _reduce_executor(
        {"op": "count"}, {"items": ["a", "b", "c"]}, None)["value"] == 3


def test_reduce_unknown_op_is_typed_error():
    out = _reduce_executor({"op": "frobnicate"}, {"items": [1]}, None)
    assert out["status"] == "error" and "unknown op" in out["error"]


def test_reduce_empty_list():
    assert _reduce_executor({"op": "sum"}, {"items": []}, None)["value"] == 0


# ─── accumulate ─────────────────────────────────────────────────────


def test_accumulate_running_sum():
    out = _accumulate_executor({"op": "sum"}, {"items": [1, 2, 3]}, None)
    assert out["series"] == [1, 3, 6]
    assert out["value"] == 6


# ─── sort ───────────────────────────────────────────────────────────


def test_sort_plain_ascending():
    assert _sort_executor(
        {}, {"items": [3, 1, 2]}, None)["items"] == [1, 2, 3]


def test_sort_descending_by_record_key():
    rows = [{"n": 2}, {"n": 5}, {"n": 1}]
    out = _sort_executor({"key": "n", "order": "desc"}, {"items": rows}, None)
    assert [r["n"] for r in out["items"]] == [5, 2, 1]


def test_sort_mixed_types_never_raises():
    out = _sort_executor({}, {"items": [3, "b", None, 1]}, None)
    assert out["status"] == "ok"


# ─── group_by ───────────────────────────────────────────────────────


def test_group_by_field():
    rows = [{"d": "S", "x": 1}, {"d": "A", "x": 2}, {"d": "S", "x": 3}]
    out = _group_by_executor({"key": "d"}, {"items": rows}, None)
    assert set(out["keys"]) == {"S", "A"}
    assert len(out["groups"]["S"]) == 2
    assert len(out["groups"]["A"]) == 1


# ─── registration ───────────────────────────────────────────────────


def test_all_four_registered():
    import workflows.nodes.aggregate  # noqa: F401  triggers register()
    import workflows.registry as reg
    for t in ("data.reduce", "data.accumulate", "data.sort", "data.group_by"):
        assert reg.get(t) is not None, f"{t} not registered"
