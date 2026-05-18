"""Connector contract guard — the structural net that makes a stripped
or drifted connector fail the build instead of shipping silently.

Founder mandate 2026-05-18: the Outlook connector shipped as a shell —
8 ops while `ai_behaviour.py` was hand-configured for ~15 — and nothing
caught it. Root cause: the permission model kept a hand-maintained
per-op table that drifted from the real connector ops. The fix:
permission defaults now DERIVE from each op's own `kind`/`destructive`
(see `ai_behaviour._connector_op_policy`), so there is no second list
to drift. This file is the CI guard that keeps it honest — any
connector that drifts from the uniform contract turns the build red.

What each test pins:
  * every connector module imports + self-registers (no silent vanish)
  * every connector genuinely overrides build_ops() + probe()
  * every op is well-formed (real fn, valid id/kind/inputs)
  * every op resolves to a valid permission policy
  * every mutating op DEFAULTS to confirm ('ask'/'deny'), never 'allow'
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

# Connector + behaviour modules live under app/ — put it on the path,
# the same way the other connector test files do.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "app"))

from connectors.base import (  # noqa: E402
    Connector, ConnectorOp, ParamSpec, all_connectors, load_all_connectors,
)
import ai_behaviour  # noqa: E402


_VALID_STATUS = {"live", "loaded_dead", "missing", "unauthorized"}
_VALID_KIND = {"read", "action"}
_VALID_POLICY = {"allow", "ask", "deny"}
_OP_ID_RE = re.compile(r"^[a-z][a-z0-9]*\.[a-z][a-z0-9_]*$")
# load_all_connectors imports 16 connector modules.
_EXPECTED_MIN = 16


@pytest.fixture(scope="module")
def connectors():
    load_all_connectors()
    return all_connectors()


def _tool_name(op: ConnectorOp) -> str:
    """The flat tool name the policy layer keys on — `<host>_<verb>`."""
    host, _, verb = (op.op_id or "").partition(".")
    return f"{host}_{verb}"


def test_all_connectors_register(connectors):
    """Every connector module imports + self-registers. A connector
    that fails to import vanishes silently — load_all_connectors
    swallows the error. This is the floor."""
    hosts = sorted(c.host for c in connectors)
    assert len(connectors) >= _EXPECTED_MIN, (
        f"only {len(connectors)} connectors registered "
        f"(expected >= {_EXPECTED_MIN}): {hosts}")


def test_every_connector_implements_the_contract(connectors):
    for c in connectors:
        assert isinstance(c, Connector), f"{c!r} is not a Connector"
        assert c.host, f"{c!r} has no host id"
        assert c.display_name, f"{c.host}: no display_name"
        # build_ops must be overridden + yield real ConnectorOps.
        ops = c.ops()
        assert isinstance(ops, list) and ops, (
            f"{c.host}: build_ops() returned nothing — shell connector")
        for o in ops:
            assert isinstance(o, ConnectorOp), (
                f"{c.host}: build_ops() yielded a non-ConnectorOp {o!r}")
        # probe must be overridden — the base default returns this exact
        # note, so its presence means probe() was never implemented.
        st = c.probe()
        assert isinstance(st, dict), f"{c.host}: probe() didn't return a dict"
        assert st.get("status") in _VALID_STATUS, (
            f"{c.host}: probe() status {st.get('status')!r} invalid")
        assert st.get("note") != "probe not implemented", (
            f"{c.host}: probe() not overridden — base stub still in place")


def test_every_op_is_well_formed(connectors):
    seen: dict[str, str] = {}
    for c in connectors:
        for o in c.ops():
            tag = f"{c.host}:{o.op_id}"
            assert _OP_ID_RE.match(o.op_id or ""), (
                f"{tag}: op_id not in '<host>.<verb>' form")
            assert o.op_id.split(".", 1)[0] == c.host, (
                f"{tag}: op_id prefix != connector host {c.host!r}")
            assert o.op_id not in seen, (
                f"duplicate op_id {o.op_id} "
                f"({seen.get(o.op_id)} + {c.host})")
            seen[o.op_id] = c.host
            assert o.host == c.host, f"{tag}: op.host != connector host"
            assert callable(o.fn), f"{tag}: fn not callable — stub op"
            assert o.kind in _VALID_KIND, f"{tag}: invalid kind {o.kind!r}"
            assert (o.label or "").strip(), f"{tag}: empty label"
            assert (o.description or "").strip(), f"{tag}: empty description"
            assert isinstance(o.destructive, bool), (
                f"{tag}: destructive flag is not a bool")
            for p in o.inputs:
                assert isinstance(p, ParamSpec), (
                    f"{tag}: input {p!r} is not a ParamSpec")


def test_every_op_resolves_to_a_valid_policy(connectors):
    """Every op must resolve to a real permission policy. Catches a
    crash or a None leaking out of the policy layer."""
    for c in connectors:
        for o in c.ops():
            pol = ai_behaviour.get_tool_policy(_tool_name(o))
            assert pol in _VALID_POLICY, (
                f"{o.op_id}: policy resolved to {pol!r}")


def test_mutating_ops_default_to_confirm(connectors):
    """A destructive / action-kind op must DEFAULT to 'ask' (or 'deny')
    — never 'allow'. User overrides may loosen it later, but the
    built-in default for anything that mutates a host must require
    confirmation. This is what makes a code-exec op un-shippable as
    auto-fire — and it holds because the default now derives from the
    op's own kind/destructive, not a hand-maintained table."""
    bad: list[str] = []
    for c in connectors:
        for o in c.ops():
            if not (o.destructive or o.kind == "action"):
                continue
            default = ai_behaviour._default_policy_for(_tool_name(o))
            if default == "allow":
                bad.append(f"{o.op_id} -> default '{default}'")
    assert not bad, (
        "mutating ops whose DEFAULT policy is 'allow' (must be "
        f"ask/deny): {sorted(bad)}")


def test_policy_derives_from_op_metadata(connectors):
    """Sanity-check the derivation is actually wired: a read op resolves
    'allow', an action op resolves 'ask' — straight from op metadata,
    no per-op table involved."""
    a_read = next((o for c in connectors for o in c.ops()
                   if o.kind == "read" and not o.destructive), None)
    an_action = next((o for c in connectors for o in c.ops()
                      if o.kind == "action" or o.destructive), None)
    if a_read is not None:
        assert ai_behaviour._default_policy_for(_tool_name(a_read)) == "allow"
    if an_action is not None:
        assert ai_behaviour._default_policy_for(_tool_name(an_action)) == "ask"
