"""data.dedupe — drop duplicate rows from a list, keeping one per identity.

Distinct from data.group_by (which PARTITIONS): dedupe keeps exactly one
row per identity in stable first-seen order, so a parity gate over the
output is byte-stable. Total-tolerant — a non-list `rows` or an exotic
row is a typed error / repr-keyed identity, never a crash.
"""
from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.nodes.aggregate import _dedupe_executor  # noqa: E402


# ─── dedupe by key ──────────────────────────────────────────────────


def test_dedupe_by_key_keep_first():
    rows = [
        {"id": 1, "v": "a"},
        {"id": 2, "v": "b"},
        {"id": 1, "v": "c"},   # dup of id=1 — dropped, first kept
        {"id": 3, "v": "d"},
    ]
    out = _dedupe_executor({"key": "id", "keep": "first"}, {"rows": rows}, None)
    assert out["status"] == "ok"
    assert out["rows"] == [
        {"id": 1, "v": "a"},   # first id=1 retained, with its value
        {"id": 2, "v": "b"},
        {"id": 3, "v": "d"},
    ]
    assert out["removed"] == 1
    assert out["count"] == 3


def test_dedupe_by_key_keep_last():
    rows = [
        {"id": 1, "v": "a"},
        {"id": 2, "v": "b"},
        {"id": 1, "v": "c"},   # dup of id=1 — later VALUE wins
        {"id": 3, "v": "d"},
    ]
    out = _dedupe_executor({"key": "id", "keep": "last"}, {"rows": rows}, None)
    assert out["status"] == "ok"
    # keep=last: id=1 takes the LATER value "c" but holds the FIRST-SEEN
    # position (slot 0), so order matches keep=first exactly.
    assert out["rows"] == [
        {"id": 1, "v": "c"},
        {"id": 2, "v": "b"},
        {"id": 3, "v": "d"},
    ]
    assert out["removed"] == 1
    assert out["count"] == 3


def test_keep_defaults_to_first():
    rows = [{"id": 1, "v": "a"}, {"id": 1, "v": "z"}]
    out = _dedupe_executor({"key": "id"}, {"rows": rows}, None)   # no keep
    assert out["rows"] == [{"id": 1, "v": "a"}]   # first-seen value kept
    assert out["removed"] == 1


# ─── whole-row dedupe (empty key) ───────────────────────────────────


def test_whole_row_dedupe_empty_key():
    rows = [
        {"id": 1, "v": "a"},
        {"id": 1, "v": "a"},   # identical whole row — dropped
        {"id": 1, "v": "b"},   # same id, different row — KEPT
    ]
    out = _dedupe_executor({"key": ""}, {"rows": rows}, None)
    assert out["rows"] == [{"id": 1, "v": "a"}, {"id": 1, "v": "b"}]
    assert out["removed"] == 1
    assert out["count"] == 2


def test_whole_row_dedupe_is_key_order_independent():
    # Same dict, keys written in different order → SAME identity (json
    # sort_keys), so the second is a duplicate.
    rows = [{"a": 1, "b": 2}, {"b": 2, "a": 1}]
    out = _dedupe_executor({}, {"rows": rows}, None)   # no key at all
    assert out["count"] == 1
    assert out["removed"] == 1


def test_whole_row_dedupe_scalars():
    rows = [1, 2, 2, 3, 1, 3, 3]
    out = _dedupe_executor({}, {"rows": rows}, None)
    assert out["rows"] == [1, 2, 3]
    assert out["removed"] == 4
    assert out["count"] == 3


# ─── no dupes → unchanged ───────────────────────────────────────────


def test_no_dupes_unchanged_removed_zero():
    rows = [{"id": 1}, {"id": 2}, {"id": 3}]
    out = _dedupe_executor({"key": "id"}, {"rows": rows}, None)
    assert out["rows"] == rows
    assert out["removed"] == 0
    assert out["count"] == 3


def test_empty_list_is_ok():
    out = _dedupe_executor({"key": "id"}, {"rows": []}, None)
    assert out["status"] == "ok"
    assert out["rows"] == []
    assert out["removed"] == 0
    assert out["count"] == 0


# ─── non-dict rows tolerated ────────────────────────────────────────


def test_non_dict_rows_tolerated_when_key_set():
    # key is set but rows are scalars — fall back to whole-row identity,
    # never crash.
    rows = [1, "x", 1, "x", 2]
    out = _dedupe_executor({"key": "id"}, {"rows": rows}, None)
    assert out["status"] == "ok"
    assert out["rows"] == [1, "x", 2]
    assert out["removed"] == 2


def test_mixed_dict_and_scalar_rows():
    rows = [{"id": 1}, 5, {"id": 1}, 5, {"id": 2}]
    out = _dedupe_executor({"key": "id"}, {"rows": rows}, None)
    assert out["status"] == "ok"
    # {"id":1} dedupes by key; 5 dedupes by whole-row repr.
    assert out["rows"] == [{"id": 1}, 5, {"id": 2}]
    assert out["removed"] == 2


def test_unhashable_key_value_does_not_crash():
    # The value AT the key is itself a list (unhashable) — identity falls
    # back to a stable json repr, so equal lists dedupe and nothing raises.
    rows = [
        {"id": [1, 2], "v": "a"},
        {"id": [1, 2], "v": "b"},   # same unhashable key → dup
        {"id": [3], "v": "c"},
    ]
    out = _dedupe_executor({"key": "id"}, {"rows": rows}, None)
    assert out["status"] == "ok"
    assert out["rows"] == [{"id": [1, 2], "v": "a"}, {"id": [3], "v": "c"}]
    assert out["removed"] == 1


# ─── wired input beats config (data.join parity) ────────────────────


def test_wired_key_overrides_config():
    rows = [{"a": 1, "b": 9}, {"a": 1, "b": 8}]
    # config keys on "b" (rows would be distinct); wired "a" wins → dup.
    out = _dedupe_executor({"key": "b"}, {"rows": rows, "key": "a"}, None)
    assert out["count"] == 1
    assert out["rows"] == [{"a": 1, "b": 9}]


# ─── stable order preserved ─────────────────────────────────────────


def test_stable_first_seen_order_preserved():
    # Build in a deliberately non-sorted order; output keeps first-seen
    # order, NOT sorted order.
    rows = [
        {"id": "zebra"},
        {"id": "alpha"},
        {"id": "zebra"},   # dup
        {"id": "mike"},
        {"id": "alpha"},   # dup
    ]
    out = _dedupe_executor({"key": "id"}, {"rows": rows}, None)
    assert [r["id"] for r in out["rows"]] == ["zebra", "alpha", "mike"]
    assert out["removed"] == 2


def test_output_is_deterministic_across_runs():
    rows = [{"k": 2}, {"k": 1}, {"k": 2}, {"k": 3}, {"k": 1}]
    a = _dedupe_executor({"key": "k"}, {"rows": rows}, None)
    b = _dedupe_executor({"key": "k"}, {"rows": rows}, None)
    assert a == b   # byte-stable — same input, same output every time


# ─── removed count correct ──────────────────────────────────────────


def test_removed_count_correct_many_dups():
    rows = [{"id": 1}] * 5 + [{"id": 2}] * 3 + [{"id": 3}]
    out = _dedupe_executor({"key": "id"}, {"rows": rows}, None)
    assert out["count"] == 3                 # 3 distinct ids
    assert out["removed"] == len(rows) - 3   # everything else dropped
    assert out["removed"] == 6


def test_count_plus_removed_equals_input_len():
    rows = [{"id": i % 4} for i in range(20)]
    out = _dedupe_executor({"key": "id"}, {"rows": rows}, None)
    assert out["count"] + out["removed"] == len(rows)


# ─── total-tolerant: rows not a list → typed error ──────────────────


def test_rows_not_a_list_is_typed_error():
    out = _dedupe_executor({"key": "id"}, {"rows": {"id": 1}}, None)
    assert out["status"] == "error"
    assert "must be a list" in out["error"]
    # Every output present + empty (typed-error contract).
    assert out["rows"] == []
    assert out["removed"] == 0
    assert out["count"] == 0


def test_missing_rows_is_typed_error():
    out = _dedupe_executor({"key": "id"}, {}, None)
    assert out["status"] == "error"
    assert out["rows"] == [] and out["removed"] == 0 and out["count"] == 0


def test_unknown_keep_is_typed_error():
    out = _dedupe_executor({"keep": "middle"}, {"rows": [{"id": 1}]}, None)
    assert out["status"] == "error"
    assert "unknown keep" in out["error"]
    assert out["rows"] == [] and out["removed"] == 0 and out["count"] == 0


def test_tuple_rows_accepted_as_list():
    # A tuple is list-like — accepted, not a typed error.
    out = _dedupe_executor({}, {"rows": (1, 1, 2)}, None)
    assert out["status"] == "ok"
    assert out["rows"] == [1, 2]
    assert out["removed"] == 1


# ─── registration ───────────────────────────────────────────────────


def test_data_dedupe_registered():
    import workflows.nodes.aggregate  # noqa: F401  triggers register()
    import workflows.registry as reg
    assert reg.get("data.dedupe") is not None


def test_data_dedupe_ports_and_category():
    import workflows.nodes.aggregate  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("data.dedupe")
    assert spec.category == "data"
    out_ports = {p.name: p.type.value for p in spec.outputs}
    assert out_ports == {"rows": "list", "removed": "number", "count": "number"}
    in_ports = {p.name for p in spec.inputs}
    assert {"rows", "key"} <= in_ports
    # `rows` is the only required input.
    req = {p.name for p in spec.inputs if p.required}
    assert req == {"rows"}
