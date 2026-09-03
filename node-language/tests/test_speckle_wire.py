"""Tests for app/speckle_wire.py — M1 (AgDR-0012).

Proves the Speckle wire substrate:
  • Round-trip of every Python value type (scalar/dict/list/Base)
  • Content-addressed hash: identical input → identical hash
  • Per-project isolation via separate SQLiteTransport
  • Foreign Base passthrough (host-extracted Walls/Rooms/Meshes)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from specklepy.objects.base import Base  # noqa: E402

from speckle_wire import (  # noqa: E402
    SpeckleWire,
    _coerce_from_base,
    _coerce_to_base,
    default_project_dir,
)


# ---------------------------------------------------------------------------
# Coercion helpers


def test_coerce_scalar_int():
    base = _coerce_to_base(42)
    # New wrap: JSON-encoded under archhubJson + shape="json".
    assert getattr(base, "archhubShape") == "json"
    assert _coerce_from_base(base) == 42


def test_coerce_scalar_string():
    base = _coerce_to_base("hello")
    assert _coerce_from_base(base) == "hello"


def test_coerce_scalar_bool():
    assert _coerce_from_base(_coerce_to_base(True)) is True
    assert _coerce_from_base(_coerce_to_base(False)) is False


def test_coerce_scalar_none():
    base = _coerce_to_base(None)
    assert _coerce_from_base(base) is None


def test_coerce_dict_roundtrip():
    src = {"name": "wall_a", "height": 3000, "level": "L1"}
    base = _coerce_to_base(src)
    assert getattr(base, "archhubShape") == "json"
    out = _coerce_from_base(base)
    assert out == src


def test_coerce_dict_with_reserved_key_id():
    # `id` is a reserved Speckle attr — coercer must prefix.
    src = {"id": "abc", "name": "wall"}
    base = _coerce_to_base(src)
    out = _coerce_from_base(base)
    assert out == src  # round-trip preserves the user's keys


def test_coerce_list_roundtrip():
    src = ["a", "b", "c"]
    base = _coerce_to_base(src)
    assert getattr(base, "archhubShape") == "json"
    out = _coerce_from_base(base)
    assert out == src


def test_coerce_list_of_dicts_roundtrip():
    src = [{"id": 1, "h": 100}, {"id": 2, "h": 200}]
    base = _coerce_to_base(src)
    out = _coerce_from_base(base)
    assert out == src


def test_coerce_base_passthrough():
    # A foreign Base (e.g. host-extracted Wall) passes through verbatim.
    src = Base()
    src.speckle_type = "Objects.BuiltElements.Wall"
    setattr(src, "height", 3000)
    base = _coerce_to_base(src)
    assert base is src   # no double-wrap


def test_coerce_foreign_base_unwrap_returns_base():
    # A foreign Base (no `_archhub_shape` marker) unwraps to itself
    # so downstream nodes can pluck speckle_type / displayValue.
    src = Base()
    setattr(src, "height", 3000)
    out = _coerce_from_base(src)
    assert out is src


# ---------------------------------------------------------------------------
# SpeckleWire — send / receive round-trip


@pytest.fixture
def wire(tmp_path):
    """A fresh SpeckleWire isolated per-test under tmp_path."""
    w = SpeckleWire(project_dir=tmp_path / "proj")
    yield w
    w.close()


def test_wire_send_scalar_roundtrip(wire):
    h = wire.send(42)
    assert isinstance(h, str)
    assert len(h) >= 16
    assert wire.receive(h) == 42


def test_wire_send_string_roundtrip(wire):
    h = wire.send("hello world")
    assert wire.receive(h) == "hello world"


def test_wire_send_dict_roundtrip(wire):
    payload = {"a": 1, "b": "two", "c": [1, 2, 3]}
    h = wire.send(payload)
    assert wire.receive(h) == payload


def test_wire_send_list_roundtrip(wire):
    payload = ["walls", "doors", "windows"]
    h = wire.send(payload)
    assert wire.receive(h) == payload


def test_wire_send_list_of_dicts_roundtrip(wire):
    payload = [{"id": i, "name": f"item_{i}"} for i in range(5)]
    h = wire.send(payload)
    assert wire.receive(h) == payload


def test_wire_send_nested_dict_roundtrip(wire):
    payload = {
        "outer": "level",
        "inner": {"deep": "value", "n": 42},
        "list_in_dict": [1, 2, 3],
    }
    h = wire.send(payload)
    out = wire.receive(h)
    assert out == payload


# ---------------------------------------------------------------------------
# Content-addressed hash: dirty tracking foundation


def test_identical_values_produce_identical_hashes(wire):
    """Hash equality is the foundation of incremental cooking — if
    a node's input hash matches the cached input, downstream re-execute
    can be skipped. This requires deterministic content addressing.
    """
    h1 = wire.send({"a": 1, "b": 2})
    h2 = wire.send({"a": 1, "b": 2})
    assert h1 == h2


def test_different_values_produce_different_hashes(wire):
    h1 = wire.send({"a": 1})
    h2 = wire.send({"a": 2})
    assert h1 != h2


def test_different_value_types_produce_different_hashes(wire):
    h1 = wire.send(42)
    h2 = wire.send("42")
    assert h1 != h2


def test_list_order_matters_for_hash(wire):
    h1 = wire.send([1, 2, 3])
    h2 = wire.send([3, 2, 1])
    assert h1 != h2


# ---------------------------------------------------------------------------
# Project isolation


def test_wire_isolation_per_project(tmp_path):
    """Two wires with different project_dir maintain separate stores —
    a hash from project A can't be received from project B (and
    shouldn't accidentally match)."""
    w_a = SpeckleWire(project_dir=tmp_path / "proj_a")
    w_b = SpeckleWire(project_dir=tmp_path / "proj_b")
    try:
        h_a = w_a.send({"x": 1})
        # B can't read what A wrote (different SQLite file).
        with pytest.raises(Exception):
            w_b.receive(h_a)
    finally:
        w_a.close()
        w_b.close()


def test_wire_default_project_dir_uses_localappdata():
    p = default_project_dir()
    assert "ArchHub" in str(p)
    assert ".speckle" in str(p)


# ---------------------------------------------------------------------------
# send_base / receive_base — for host connectors with typed Bases


def test_send_base_returns_hash(wire):
    src = Base()
    src.speckle_type = "Objects.Geometry.Mesh"
    setattr(src, "units", "mm")
    h = wire.send_base(src)
    assert isinstance(h, str)


def test_receive_base_returns_full_base(wire):
    src = Base()
    src.speckle_type = "Objects.Geometry.Mesh"
    setattr(src, "vertex_count", 1000)
    h = wire.send_base(src)
    got = wire.receive_base(h)
    assert isinstance(got, Base)
    assert getattr(got, "vertex_count") == 1000


# ---------------------------------------------------------------------------
# Suite contract


def test_no_archhub_shape_leaks_to_caller(wire):
    """The internal `_archhub_shape` marker must NOT appear in
    receive() results — engine code stays free of Speckle implementation
    details."""
    out = wire.receive(wire.send({"a": 1}))
    assert "_archhub_shape" not in out
    out2 = wire.receive(wire.send([1, 2]))
    assert not (isinstance(out2, dict) and "_archhub_shape" in out2)
