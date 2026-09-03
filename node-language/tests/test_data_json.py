"""stem-rebuild Phase-0 — `data.json`, the one-engine mode-selected JSON cell.

`data.json` is a PURE JSON codec with ONE engine; the `mode` config selects
the direction (`parse` text→value, or `stringify` value→text) — the JSON twin
of text.op/math.op (one engine, mode in config).

What's pinned here:
  * parse a valid JSON string → the parsed dict / list `value`;
  * parse invalid / empty JSON → `status: "error"` with outputs present+empty
    (never a raise);
  * stringify a dict → a `text` that round-trips back via json.loads;
  * stringify honours `indent` (pretty-print) + `sort_keys` (stable order);
  * stringify is total-tolerant — an exotic object (a set) does NOT raise
    (default=str coerces it);
  * an unknown `mode` is a typed error;
  * a wired input beats config (data.join "wired key wins");
  * outputs are deterministic (same in → byte-identical out), the basis of a
    parity gate;
  * the cell is registered with typed ports + category "data".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows.nodes.serialize import _json_executor  # noqa: E402


# ─── parse: valid JSON → typed value ─────────────────────────────────


def test_parse_valid_object_returns_dict():
    out = _json_executor({"mode": "parse"},
                         {"text": '{"a": 1, "b": [2, 3]}'}, None)
    assert out["status"] == "ok"
    assert out["value"] == {"a": 1, "b": [2, 3]}
    assert out["text"] == ""            # the unused output stays empty


def test_parse_valid_array_returns_list():
    out = _json_executor({"mode": "parse"}, {"text": "[1, 2, 3]"}, None)
    assert out["status"] == "ok"
    assert out["value"] == [1, 2, 3]


def test_parse_is_the_default_mode():
    # No mode given → defaults to parse (mirrors text.op default op).
    out = _json_executor({}, {"text": '{"k": "v"}'}, None)
    assert out["status"] == "ok"
    assert out["value"] == {"k": "v"}


def test_parse_scalar_json():
    out = _json_executor({"mode": "parse"}, {"text": "42"}, None)
    assert out["status"] == "ok"
    assert out["value"] == 42


# ─── parse: invalid JSON → typed error (outputs present, never raises) ─


def test_parse_invalid_json_is_typed_error():
    out = _json_executor({"mode": "parse"}, {"text": "{not valid json"}, None)
    assert out["status"] == "error"
    assert "parse" in out["error"]
    # Every output present + empty.
    assert out["value"] is None
    assert out["text"] == ""


def test_parse_empty_string_is_typed_error():
    out = _json_executor({"mode": "parse"}, {"text": ""}, None)
    assert out["status"] == "error"
    assert out["value"] is None
    assert out["text"] == ""


def test_parse_missing_text_is_typed_error():
    # No text wired and none in config → empty string → invalid JSON error.
    out = _json_executor({"mode": "parse"}, {}, None)
    assert out["status"] == "error"
    assert out["value"] is None


# ─── stringify: dict → text that round-trips ─────────────────────────


def test_stringify_dict_round_trips():
    src = {"a": 1, "b": [2, 3], "c": "hello"}
    out = _json_executor({"mode": "stringify"}, {"value": src}, None)
    assert out["status"] == "ok"
    assert isinstance(out["text"], str)
    assert out["value"] is None         # the unused output stays empty
    # The text round-trips back to the original object.
    assert json.loads(out["text"]) == src


def test_stringify_list_round_trips():
    src = [1, "two", {"three": 3}]
    out = _json_executor({"mode": "stringify"}, {"value": src}, None)
    assert out["status"] == "ok"
    assert json.loads(out["text"]) == src


# ─── stringify: indent + sort_keys ───────────────────────────────────


def test_stringify_indent_pretty_prints():
    out = _json_executor({"mode": "stringify", "indent": 2},
                         {"value": {"a": 1}}, None)
    assert out["status"] == "ok"
    # indent=2 puts the key on its own newline-indented line.
    assert "\n" in out["text"]
    assert '  "a": 1' in out["text"]


def test_stringify_sort_keys_orders_keys_deterministically():
    # Insertion order is z, a, m; sort_keys must emit a, m, z.
    out = _json_executor(
        {"mode": "stringify", "indent": 0, "sort_keys": True},
        {"value": {"z": 1, "a": 2, "m": 3}}, None)
    assert out["status"] == "ok"
    keys_in_order = [k for k in ("a", "m", "z")]
    positions = [out["text"].index(f'"{k}"') for k in keys_in_order]
    assert positions == sorted(positions)   # a before m before z


def test_stringify_is_deterministic_byte_stable():
    # Same input + config → byte-identical text (the parity-gate basis).
    cfg = {"mode": "stringify", "indent": 2, "sort_keys": True}
    val = {"b": 2, "a": 1}
    out1 = _json_executor(cfg, {"value": val}, None)
    out2 = _json_executor(cfg, {"value": val}, None)
    assert out1["text"] == out2["text"]


# ─── stringify: total tolerance — exotic object does not raise ───────


def test_stringify_exotic_set_does_not_raise():
    # A set is NOT natively JSON-serializable; default=str must coerce it
    # rather than raising (total tolerance).
    out = _json_executor({"mode": "stringify"}, {"value": {1, 2, 3}}, None)
    assert out["status"] == "ok"
    assert isinstance(out["text"], str)
    # The coerced text is itself valid JSON (a JSON string of the set's repr).
    assert isinstance(json.loads(out["text"]), str)


def test_stringify_exotic_nested_object_does_not_raise():
    # An exotic value nested inside a dict — default=str coerces the leaf.
    out = _json_executor({"mode": "stringify"},
                         {"value": {"items": {1, 2}}}, None)
    assert out["status"] == "ok"
    round_tripped = json.loads(out["text"])
    assert "items" in round_tripped       # the dict structure survived


# ─── unknown mode → typed error ──────────────────────────────────────


def test_unknown_mode_is_typed_error():
    out = _json_executor({"mode": "frobnicate"}, {"text": "{}"}, None)
    assert out["status"] == "error"
    assert "unknown mode" in out["error"]
    assert out["value"] is None
    assert out["text"] == ""


# ─── wired input beats config (data.join parity) ─────────────────────


def test_parse_wired_text_beats_config():
    # config text is bogus JSON; the wired input text wins and parses ok.
    out = _json_executor(
        {"mode": "parse", "text": "NOT JSON"},
        {"text": '{"wired": true}'}, None)
    assert out["status"] == "ok"
    assert out["value"] == {"wired": True}


def test_stringify_wired_value_beats_config():
    out = _json_executor(
        {"mode": "stringify", "value": {"from": "config"}},
        {"value": {"from": "wire"}}, None)
    assert out["status"] == "ok"
    assert json.loads(out["text"]) == {"from": "wire"}


def test_parse_falls_back_to_config_text_when_unwired():
    # No wired text → config text is read (config is the fallback).
    out = _json_executor({"mode": "parse", "text": '{"cfg": 1}'}, {}, None)
    assert out["status"] == "ok"
    assert out["value"] == {"cfg": 1}


# ─── round-trip: stringify then parse is identity ────────────────────


def test_round_trip_stringify_then_parse_is_identity():
    src = {"name": "ArchHub", "nums": [1, 2, 3], "nested": {"ok": True}}
    s = _json_executor({"mode": "stringify"}, {"value": src}, None)
    assert s["status"] == "ok"
    p = _json_executor({"mode": "parse"}, {"text": s["text"]}, None)
    assert p["status"] == "ok"
    assert p["value"] == src


# ─── registration ────────────────────────────────────────────────────


def test_data_json_registered():
    import workflows.nodes.serialize  # noqa: F401  triggers register()
    import workflows.registry as reg
    assert reg.get("data.json") is not None


def test_data_json_ports_are_typed():
    import workflows.nodes.serialize  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("data.json")
    in_ports = {p.name: p.type.value for p in spec.inputs}
    out_ports = {p.name: p.type.value for p in spec.outputs}
    assert in_ports == {"text": "string", "value": "any"}
    assert out_ports == {"value": "any", "text": "string"}


def test_data_json_category_is_data():
    import workflows.nodes.serialize  # noqa: F401
    import workflows.registry as reg
    spec, _ = reg.get("data.json")
    assert spec.category == "data"
