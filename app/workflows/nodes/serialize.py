"""Serialization primitive — stem-rebuild Phase-0 (in-place plan data cell-family).

`data.json` is a PURE, mode-selected JSON codec: ONE engine, the `mode`
config picks the direction (`parse` text→value, or `stringify` value→text).
It turns the ad-hoc `json.loads` / `json.dumps` blob that scatters through
every "read this JSON string" / "serialize this dict to disk" job into a
single composable stem cell — the JSON twin of `text.op` (one engine, op in
config) sitting beside `data.join` / `aggregate.py` in the data family.

DECISION — a PURE PRIMITIVE, not a host. `json` is the stdlib, in-process,
synchronous, always reachable: no probe, no auth, no session, no network.
Wrapping a string<->object transcode in a connector would mint ceremony with
zero payload (a LIBRARY-FIRST / ONE-SYSTEM violation). So `data.json` is
modeled 1:1 on `math.op` / `text.op`: one executor over typed ports, the
direction chosen by a `mode` config key, registered via
`register(NodeSpec(...), _json_executor)`, status-tagged, total-tolerant.

ONE engine, mode-selected (load-bearing) — mirrors math.op/text.op dispatch:
  * `mode: "parse"`     reads `text` (STRING) → `json.loads` → `value` (ANY);
  * `mode: "stringify"` reads `value` (ANY) → `json.dumps` → `text` (STRING);
  * `mode` selects WHICH input is read; a wired input beats config
    (the data.join "wired key wins" rule);
  * `indent` (stringify pretty-print) + `sort_keys` (stringify stable key
    order) are config knobs — no hard-coded literals in the body;
  * `default=str` on stringify makes it total-tolerant: an exotic, normally
    non-JSON-serializable object (a set, a datetime, a Path) is coerced to
    its str() rather than raising.

Pure + side-effect-free. No host, no LLM, no network — only `json` + str().
Total-tolerant: invalid JSON on parse, or an unknown `mode`, is a TYPED
ERROR (every output present + empty, `status: "error"`, a message), NEVER a
raise. Deterministic: the same inputs + config always yield byte-identical
outputs (json is stable; `sort_keys` pins key order), so a golden-oracle
parity gate over this cell is byte-stable.
"""
from __future__ import annotations

import json

from ..graph import Port, PortType
from ..registry import NodeSpec, register


# ── shared ────────────────────────────────────────────────────────────

# The two directions this one engine dispatches on (mirrors text.op's op
# table being the single source of the enum). `parse` is the default.
_JSON_MODES = ("parse", "stringify")


def _err(message: str) -> dict:
    """A typed error with EVERY output present + empty — the total-tolerance
    contract (mirrors fs.list's typed-error returns). `value` is None and
    `text` is "" so an `upstream_error` propagation in runner.py stays
    well-typed; never a raise."""
    return {"status": "error", "value": None, "text": "", "error": message}


# ── data.json ───────────────────────────────────────────────────────────

def _json_executor(config: dict, inputs: dict, ctx) -> dict:
    """One-engine, mode-selected JSON codec (parse | stringify).

    `mode` (config) picks the direction. In `parse` the `text` input is
    `json.loads`-ed to `value`; in `stringify` the `value` input is
    `json.dumps`-ed to `text` using `indent` + `sort_keys` (+ `default=str`
    for total tolerance). A wired input beats config (data.join rule).
    Invalid JSON, or an unknown `mode`, is a typed error (outputs present +
    empty), NEVER a crash.
    """
    cfg = config or {}
    ins = inputs or {}

    mode = str(cfg.get("mode", "parse") or "parse").strip().lower()
    if mode not in _JSON_MODES:
        return _err(f"data.json: unknown mode {mode!r} — want one of "
                    f"{', '.join(_JSON_MODES)}")

    if mode == "parse":
        # wired `text` input beats config `text` (data.join "wired key wins").
        text = ins.get("text") if ins.get("text") is not None else cfg.get("text")
        text = "" if text is None else str(text)
        try:
            value = json.loads(text)
        except Exception as ex:
            # Invalid / empty JSON → typed error, outputs present + empty.
            return _err(f"data.json parse: {type(ex).__name__}: {ex}")
        return {"status": "ok", "value": value, "text": ""}

    # mode == "stringify" — wired `value` input beats config `value`.
    value = ins.get("value") if ins.get("value") is not None else cfg.get("value")
    # `indent` / `sort_keys` are config knobs (no hard-coded literals).
    indent = cfg.get("indent", 2)
    sort_keys = bool(cfg.get("sort_keys", False))
    try:
        # default=str makes this total-tolerant: an exotic object (set,
        # datetime, Path) is coerced to str() rather than raising.
        text = json.dumps(value, indent=indent, sort_keys=sort_keys, default=str)
    except Exception as ex:
        # default=str catches the common cases; a key-type / recursion
        # failure that still escapes is a typed error, not a crash.
        return _err(f"data.json stringify: {type(ex).__name__}: {ex}")
    return {"status": "ok", "value": None, "text": text}


register(NodeSpec(
    type="data.json", category="data", display_name="JSON",
    description="One-engine, mode-selected JSON codec. `mode: parse` reads "
                "the `text` input and emits the parsed `value`; `mode: "
                "stringify` reads the `value` input and emits a JSON `text` "
                "string (pretty-printed by `indent`, keys ordered by "
                "`sort_keys`). A wired input overrides config. Invalid JSON "
                "or an unknown mode is a typed error, never a crash; "
                "stringify is total-tolerant (exotic objects fall back to "
                "str()). Pure — no host, no network.",
    inputs=[Port(name="text",  type=PortType.STRING),
            Port(name="value", type=PortType.ANY)],
    outputs=[Port(name="value", type=PortType.ANY),
             Port(name="text",  type=PortType.STRING)],
    config_schema={
        "mode":      {"type": "string", "default": "parse",
                      "options": list(_JSON_MODES),
                      "description": "Direction: 'parse' (text→value) or "
                                     "'stringify' (value→text)."},
        "indent":    {"type": "number", "default": 2,
                      "description": "Stringify pretty-print indent "
                                     "(spaces per level)."},
        "sort_keys": {"type": "boolean", "default": False,
                      "description": "Stringify: sort object keys for a "
                                     "stable, deterministic output."},
    },
    icon="{}"), _json_executor)
