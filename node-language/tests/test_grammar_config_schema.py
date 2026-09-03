"""config_schema → editable inspector fields (the #1 stem-FIELD gap).

Founder named it: "stem fields — sliders, inputs, selects." A primitive's
typed `config_schema` must reach the JSX canvas so a placed cell (map / join /
assert / …) renders EDITABLE typed widgets instead of a flat read-only param
list. Before this, `grammar_payload()` serialized ports + params but DROPPED
`config_schema` — so it never reached the inspector and the cells could not be
tuned on the canvas.

This is the Python half of the contract:

  1. `grammar_payload()` carries `config_schema` for the founder-named test
     cells `verify.assert` (mode/op/expected/expr/safe_mode/message) and
     `data.join` (key/how/left_key/right_key).
  2. The change is purely ADDITIVE — every entry grows a `config_schema` key;
     a type with no registry schema gets `{}` (→ the JSX flat-param fallback,
     unchanged).
  3. The engine contract is UNCHANGED — a field edit lands in `node.params`
     (list of `{k, v}`) and `_params_to_config` still folds that to the flat
     `config` dict the executor reads.

The JSX renderer reuses the existing `FullParam` widget; the schema→widget
mapping it relies on (options→select, boolean→checkbox, number→number,
string→text) is pinned here so a schema-shape change can't silently break the
inspector.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_APP = Path(__file__).resolve().parent.parent / "app"
if str(_APP) not in sys.path:
    sys.path.insert(0, str(_APP))

import workflows  # noqa: E402  importing registers all built-in node types
from workflows import node_grammar as ng  # noqa: E402


# ── 1. The founder-named test cells carry their full schema ──────────


def _by_kind() -> dict:
    return {e["kind"]: e for e in ng.grammar_payload()}


def test_verify_assert_carries_full_config_schema():
    """`verify.assert` (palette kind `assert`) is RICHER than its flat
    params (mode/expr) — the schema unlocks tuning safe_mode/op/expected/
    message too. All six must ride in the payload's config_schema."""
    e = _by_kind()["assert"]
    cs = e.get("config_schema")
    assert isinstance(cs, dict), "assert lost its config_schema"
    assert {"mode", "expr", "safe_mode", "op", "expected", "message"} <= set(cs)
    # Shapes the JSX widget renderer dispatches on must be intact.
    assert cs["mode"].get("options"), "mode must be a select (has options)"
    assert cs["safe_mode"].get("type") == "boolean"
    assert cs["op"].get("options"), "op must be a select (has options)"


def test_data_join_carries_full_config_schema():
    """`data.join` (palette kind `join`) — the reconcile core — exposes
    key/left_key/right_key (strings) + how (select w/ default inner)."""
    e = _by_kind()["join"]
    cs = e.get("config_schema")
    assert isinstance(cs, dict), "join lost its config_schema"
    assert {"key", "left_key", "right_key", "how"} <= set(cs)
    assert cs["how"].get("default") == "inner"
    assert cs["how"].get("options"), "how must be a select (has options)"
    assert cs["key"].get("type") == "string"


def test_config_schema_matches_the_registry_nodespec():
    """The payload's config_schema is the registry NodeSpec's, verbatim —
    ONE source (no JS-side copy that can drift)."""
    bk = _by_kind()
    for kind, engine_t in (("assert", "verify.assert"), ("join", "data.join")):
        spec, _ = workflows.get(engine_t)
        assert bk[kind]["config_schema"] == spec.config_schema


# ── 2. Additive: EVERY entry gains the key; empty ⇒ flat fallback ────


def test_every_payload_entry_has_a_config_schema_key():
    """Additive invariant: the new key rides on every entry. Types with no
    registry schema get {} — the JSX inspector falls through to flat-param
    rendering for those (the unchanged path)."""
    pl = ng.grammar_payload()
    for e in pl:
        assert "config_schema" in e, f"{e['kind']} missing config_schema key"
        assert isinstance(e["config_schema"], dict)


def test_schemaless_primitives_get_empty_schema_not_dropped():
    """A primitive whose engine type declares no config_schema (e.g. the
    `note` annotation / `reroute` identity dot) gets {} — which the JSX maps
    to the flat-param fallback. It is never None / missing."""
    bk = _by_kind()
    # `note` has no registry executor → _config_schema_for returns {}.
    assert bk["note"]["config_schema"] == {}


def test_library_skills_keep_empty_schema():
    """Library Capability specs derive no schema today (out of scope) — they
    stay flat-param. Any `_source == 'library'` entry has config_schema == {}."""
    for e in ng.grammar_payload():
        if e.get("_source") == "library":
            assert e["config_schema"] == {}, (e["kind"], e["config_schema"])


def test_synthesized_registry_typed_nodes_can_carry_schema():
    """Tier-1/2 typed nodes (host_typed/render_typed/…) are registry-backed,
    so they pick up their declared config_schema too — tunable on canvas."""
    bk = _by_kind()
    # At least one synthesized registry entry should expose a non-empty schema
    # (these specs declare config_schema in host_typed/render_typed/aec/adapter).
    synth_with_schema = [
        e["kind"] for e in bk.values()
        if e.get("_source") == "registry" and e.get("config_schema")
    ]
    assert synth_with_schema, (
        "no synthesized registry node surfaced a config_schema — the additive "
        "wire to _synthesized_primitives regressed"
    )


def test_payload_still_json_serialisable_with_schema():
    """Nested config_schema dicts must serialize — the bridge ships this as
    JSON to the JSX canvas via get_node_grammar."""
    json.dumps(ng.grammar_payload())  # must not raise


# ── 3. Engine contract UNCHANGED: a field edit folds to config ───────


def test_param_edit_folds_to_config_for_assert():
    """A user editing the `op` field writes node.params = [{k:'op', v:'gte'}];
    `_params_to_config` folds that to the flat config the executor reads. The
    engine contract is untouched by the inspector change."""
    edited_params = [
        {"k": "mode", "v": "compare"},
        {"k": "op", "v": "gte"},
        {"k": "expected", "v": 3},
        {"k": "message", "v": "walls must exist"},
    ]
    cfg = ng._params_to_config(edited_params)
    assert cfg == {"mode": "compare", "op": "gte",
                   "expected": 3, "message": "walls must exist"}


def test_param_edit_folds_to_config_for_join():
    """Editing join's `how` select + `key` text folds to the executor config."""
    cfg = ng._params_to_config([
        {"k": "key", "v": "tag"},
        {"k": "how", "v": "outer"},
    ])
    assert cfg == {"key": "tag", "how": "outer"}


def test_params_to_config_passthrough_dict_unchanged():
    """Engine-native nodes already carry a dict config — it passes through
    untouched (the inspector only ever produces the list form)."""
    assert ng._params_to_config({"how": "left"}) == {"how": "left"}


# ── 4. Pin the schema→widget mapping the JSX relies on ───────────────
#
# The JSX `_schemaFieldToParam` helper turns a JSON-Schema property into the
# {k,type,...} shape `FullParam` renders. We can't run JS here, but we CAN pin
# the schema shapes it keys off so a registry-side change that would silently
# break the inspector mapping is caught in Python.


@pytest.mark.parametrize("kind,prop,expected_widget", [
    # options present → select (regardless of declared type)
    ("assert", "mode", "select"),
    ("assert", "op", "select"),
    ("join", "how", "select"),
    # boolean → checkbox/toggle
    ("assert", "safe_mode", "boolean"),
    # plain string (no options) → text
    ("join", "key", "text"),
    ("assert", "expr", "text"),
])
def test_schema_property_shapes_map_to_expected_widget(kind, prop, expected_widget):
    """Mirror of the JSX `_schemaFieldToParam` dispatch rules — pins the
    property shapes so options→select / boolean→checkbox / string→text holds."""
    cs = _by_kind()[kind]["config_schema"]
    spec = cs[prop]

    # Replicate the JSX dispatch (kept in lockstep with studio-lm.jsx).
    if spec.get("options"):
        widget = "select"
    elif str(spec.get("type", "")).lower() == "boolean":
        widget = "boolean"
    elif str(spec.get("type", "")).lower() in ("number", "integer"):
        widget = "number"
    else:
        widget = "text"

    assert widget == expected_widget, (kind, prop, spec, widget)
