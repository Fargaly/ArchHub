"""Tests for the new typed OUTPUT executors — output.file / .console / .display.

Each is a sink that records / writes / displays the upstream value AND
passes the value through unchanged so downstream wires can chain.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

# Force registration import.
from workflows.nodes import io_data  # noqa: E402, F401
from workflows.registry import get as registry_get  # noqa: E402


# ---------------------------------------------------------------------------
# output.file


def test_output_file_writes_string(tmp_path):
    spec, ex = registry_get("output.file")
    path = tmp_path / "out.txt"
    r = ex({"path": str(path)}, {"value": "hello"}, None)
    assert r["value"] == "hello"
    assert r["bytes_written"] == 5
    assert path.read_text(encoding="utf-8") == "hello"


def test_output_file_writes_dict_as_json(tmp_path):
    _, ex = registry_get("output.file")
    path = tmp_path / "out.json"
    payload = {"key": "value", "n": 42}
    r = ex({"path": str(path)}, {"value": payload}, None)
    assert r["value"] == payload
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert on_disk == payload


def test_output_file_writes_list_as_json(tmp_path):
    _, ex = registry_get("output.file")
    path = tmp_path / "out.json"
    r = ex({"path": str(path)}, {"value": [1, 2, 3]}, None)
    assert r["value"] == [1, 2, 3]
    assert json.loads(path.read_text(encoding="utf-8")) == [1, 2, 3]


def test_output_file_overwrites_by_default(tmp_path):
    _, ex = registry_get("output.file")
    path = tmp_path / "out.txt"
    ex({"path": str(path)}, {"value": "first"}, None)
    ex({"path": str(path)}, {"value": "second"}, None)
    assert path.read_text(encoding="utf-8") == "second"


def test_output_file_append_mode(tmp_path):
    _, ex = registry_get("output.file")
    path = tmp_path / "out.txt"
    ex({"path": str(path)}, {"value": "first"}, None)
    ex({"path": str(path), "append": True}, {"value": "second"}, None)
    assert path.read_text(encoding="utf-8") == "firstsecond"


def test_output_file_creates_parent_dirs(tmp_path):
    _, ex = registry_get("output.file")
    path = tmp_path / "nested" / "deep" / "out.txt"
    r = ex({"path": str(path)}, {"value": "x"}, None)
    assert r["value"] == "x"
    assert path.exists()


def test_output_file_missing_path_returns_error():
    _, ex = registry_get("output.file")
    r = ex({}, {"value": "x"}, None)
    assert r["value"] == "x"
    assert "error" in r
    assert "path" in r["error"].lower()


def test_output_file_passes_none_through(tmp_path):
    _, ex = registry_get("output.file")
    path = tmp_path / "out.txt"
    r = ex({"path": str(path)}, {"value": None}, None)
    assert r["value"] is None
    assert path.read_text(encoding="utf-8") == ""


# ---------------------------------------------------------------------------
# output.console


def test_output_console_passes_value_through(capsys):
    _, ex = registry_get("output.console")
    r = ex({}, {"value": 42}, None)
    assert r["value"] == 42
    captured = capsys.readouterr()
    assert "42" in captured.out


def test_output_console_with_label(capsys):
    _, ex = registry_get("output.console")
    ex({"label": "result"}, {"value": "hi"}, None)
    captured = capsys.readouterr()
    assert "[result]" in captured.out
    assert "'hi'" in captured.out


def test_output_console_uses_trace_sink_when_available():
    _, ex = registry_get("output.console")
    captured = []

    class _Ctx:
        def trace(self, line):
            captured.append(line)

    ex({"label": "x"}, {"value": "test"}, _Ctx())
    assert captured == ["[x] 'test'"]


def test_output_console_resilient_to_sink_failure():
    _, ex = registry_get("output.console")

    class _BadCtx:
        def trace(self, line):
            raise RuntimeError("sink broken")

    r = ex({}, {"value": "x"}, _BadCtx())
    # Sink failure must not crash — value still passes through.
    assert r["value"] == "x"


# ---------------------------------------------------------------------------
# output.display


def test_output_display_passes_value_through():
    _, ex = registry_get("output.display")
    r = ex({}, {"value": {"k": 1}}, None)
    assert r["value"] == {"k": 1}


def test_output_display_passes_none():
    _, ex = registry_get("output.display")
    r = ex({}, {"value": None}, None)
    assert r["value"] is None


# ---------------------------------------------------------------------------
# Registry shape


@pytest.mark.parametrize("type_name", [
    "output.file", "output.console", "output.display",
])
def test_output_executor_registered(type_name: str):
    tup = registry_get(type_name)
    assert tup is not None, f"{type_name} not registered"
    spec, ex = tup
    assert spec.display_name
    assert callable(ex)
    # All sinks have a single typed input + passthrough output.
    assert len(spec.inputs) == 1
    assert spec.inputs[0].name == "value"
    assert len(spec.outputs) == 1
    assert spec.outputs[0].name == "value"
