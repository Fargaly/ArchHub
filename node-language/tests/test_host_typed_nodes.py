"""AgDR-0041 Property 1 — typed host nodes (host swap).

Same wire, different host. Verify the 4 typed nodes are registered,
the host param resolves the right op-id, the 3dsmax→max alias works,
and missing host gives a clear error (not a silent crash).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

APP = Path(__file__).resolve().parents[1] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from workflows import registry as _reg  # noqa: E402
from workflows.nodes import host_typed   # noqa: E402,F401


# ── registration ───────────────────────────────────────────────────


@pytest.mark.parametrize("node_type", [
    "host.import_mesh",
    "host.read_walls",
    "host.export_viewport",
    "host.run_script",
])
def test_typed_host_node_registered(node_type):
    spec_tup = _reg.get(node_type)
    assert spec_tup is not None, f"{node_type} not registered"


def test_typed_host_node_specs_carry_host_options():
    spec, _exec = _reg.get("host.import_mesh")
    cfg = spec.config_schema or {}
    assert "host" in cfg
    opts = set(cfg["host"].get("options") or [])
    assert opts == {"revit", "rhino", "3dsmax", "blender"}


# ── op-id resolution ───────────────────────────────────────────────


@pytest.mark.parametrize("host,expected", [
    ("revit",   "revit.import_mesh"),
    ("rhino",   "rhino.import_mesh"),
    ("blender", "blender.import_mesh"),
    ("3dsmax",  "max.import_mesh"),       # alias
])
def test_resolve_op_id_per_host(host, expected):
    assert host_typed._resolve_op_id(host, "import_mesh") == expected


def test_resolve_op_id_empty_inputs():
    assert host_typed._resolve_op_id("", "import_mesh") == ""
    assert host_typed._resolve_op_id("revit", "") == ""


# ── op-alias correctness (the contract-break fix) ──────────────────
# Before the fix `_resolve_op_id` did a naive `{host}.{typed_op}` so
# `read_walls`/`run_script` pointed at ops no connector implements.
# These assert the REAL per-host verbs each connector actually exposes.


@pytest.mark.parametrize("host,typed_op,expected", [
    # read_walls — only Revit has a literal walls op; the other hosts
    # route to their generic element/object list (same host-swap intent).
    ("revit",   "read_walls",      "revit.list_walls"),
    ("rhino",   "read_walls",      "rhino.list_objects"),
    ("3dsmax",  "read_walls",      "max.list_objects"),
    ("blender", "read_walls",      "blender.list_objects"),
    # run_script — host-native script verb (max uses run_maxscript).
    ("revit",   "run_script",      "revit.run_script"),
    ("rhino",   "run_script",      "rhino.run_script"),
    ("3dsmax",  "run_script",      "max.run_maxscript"),
    ("blender", "run_script",      "blender.run_script"),
    # export_viewport / import_mesh — identity verbs (AgDR-0041 P1 ops).
    ("revit",   "export_viewport", "revit.export_viewport"),
    ("3dsmax",  "export_viewport", "max.export_viewport"),
    ("blender", "import_mesh",     "blender.import_mesh"),
])
def test_resolve_op_id_alias_table(host, typed_op, expected):
    assert host_typed._resolve_op_id(host, typed_op) == expected


@pytest.mark.parametrize("host", ["revit", "rhino", "3dsmax", "blender"])
@pytest.mark.parametrize("typed_op", [
    "import_mesh", "read_walls", "export_viewport", "run_script",
])
def test_every_typed_op_resolves_to_a_real_connector_op(host, typed_op):
    """The whole point of the fix: every typed-host primitive maps to an
    op-id that an actual registered connector implements — no
    `unknown op` at cook time. Loads the real connectors and asserts the
    resolved op_id is a live ConnectorOp."""
    import connectors.base as cb
    cb.load_all_connectors()
    op_id = host_typed._resolve_op_id(host, typed_op)
    family = op_id.split(".", 1)[0]
    connector = cb.get(family)
    assert connector is not None, f"no connector registered for {family!r}"
    real = connector.op(op_id)
    assert real is not None, (
        f"{op_id} resolved from host.{typed_op} (host={host}) is NOT a "
        f"real connector op — the workflow↔connector contract is broken")


# ── executor behaviour ─────────────────────────────────────────────


def test_missing_host_returns_clear_error():
    """No silent crash — Composer / user gets actionable message."""
    spec, exec_fn = _reg.get("host.import_mesh")
    out = exec_fn({}, {"mesh": object()}, None)
    assert out["status"] == "error"
    assert "host" in out["error"].lower()


def test_unknown_op_id_resolution_fails_gracefully(monkeypatch):
    """If connectors.base.run_op rejects, executor surfaces it
    honestly (never fabricates a value)."""
    spec, exec_fn = _reg.get("host.import_mesh")

    class _StubResult:
        ok = False
        error = "no such op"

    def _stub_run_op(op_id, **_):
        return _StubResult()

    # Patch the import inside the executor's closure
    import sys as _sys
    cb = _sys.modules.get("connectors.base")
    if cb is None:
        import connectors.base as cb  # type: ignore  # noqa
    monkeypatch.setattr("connectors.base.run_op", _stub_run_op)

    out = exec_fn({"host": "rhino"}, {"mesh": object()}, None)
    assert out["status"] == "error"
    assert "rhino.import_mesh" in out["op_id"]


def test_host_swap_preserves_op_semantics(monkeypatch):
    """Same wire, swap host param — op-id changes to the REAL per-host
    verb but the contract (typed value out) stays. Before the fix this
    asserted `revit.read_walls`/`rhino.read_walls`, op-ids that exist on
    no connector — the contract break. Now it asserts the real resolved
    op-ids (`revit.list_walls` / `rhino.list_objects`)."""
    import connectors.base as cb
    cb.load_all_connectors()
    spec, exec_fn = _reg.get("host.read_walls")

    captured = {"calls": []}

    class _OK:
        ok = True
        value = [{"id": "w1"}, {"id": "w2"}]
        value_preview = "[2 walls]"

    def _stub(op_id, **kw):
        captured["calls"].append((op_id, kw))
        return _OK()

    monkeypatch.setattr("connectors.base.run_op", _stub)

    out_a = exec_fn({"host": "revit", "scope": "view"}, {}, None)
    out_b = exec_fn({"host": "rhino", "scope": "view"}, {}, None)
    assert out_a["value"] == out_b["value"]
    assert captured["calls"][0][0] == "revit.list_walls"
    assert captured["calls"][1][0] == "rhino.list_objects"


def test_param_filter_drops_unknown_keys(monkeypatch):
    """A typed-node config key the resolved op does NOT declare (e.g.
    read_walls' `scope`) must be filtered out before the connector fn is
    called — otherwise a live cook dies with an unexpected-keyword
    TypeError. Proves the executor only forwards declared params."""
    import connectors.base as cb
    cb.load_all_connectors()
    spec, exec_fn = _reg.get("host.read_walls")

    captured = {}

    class _OK:
        ok = True
        value = []
        value_preview = ""

    def _stub(op_id, **kw):
        captured["op_id"] = op_id
        captured["kwargs"] = kw
        return _OK()

    monkeypatch.setattr("connectors.base.run_op", _stub)
    # `scope` is a typed-node config but NOT an input of revit.list_walls.
    out = exec_fn({"host": "revit", "scope": "selection"}, {}, None)
    assert out.get("op_id") == "revit.list_walls"
    assert "scope" not in captured["kwargs"], (
        "scope leaked to revit.list_walls — would TypeError on live cook")


def test_run_script_code_renamed_for_max(monkeypatch):
    """max.run_maxscript names its body param `script`, not `code`. The
    typed `run_script` node uses `code`; the executor must rename it so
    the live op receives `script`."""
    import connectors.base as cb
    cb.load_all_connectors()
    spec, exec_fn = _reg.get("host.run_script")

    captured = {}

    class _OK:
        ok = True
        value = "ok"
        value_preview = ""

    def _stub(op_id, **kw):
        captured["op_id"] = op_id
        captured["kwargs"] = kw
        return _OK()

    monkeypatch.setattr("connectors.base.run_op", _stub)
    out = exec_fn({"host": "3dsmax"}, {"code": "spheres = 1"}, None)
    assert captured["op_id"] == "max.run_maxscript"
    assert captured["kwargs"].get("script") == "spheres = 1"
    assert "code" not in captured["kwargs"]


# ── end-to-end cook through the real runner (host OFFLINE) ──────────
# The headline guarantee: cook a typed host node through WorkflowRunner
# with the host's broker FORCED offline → an honest host-missing error,
# NOT an `unknown op` error and NOT a fabricated value. This is the
# regression guard for the workflow↔connector contract break.


def _force_brokers_offline(monkeypatch):
    """Make every broker/bridge report 'no live host' so the cook path
    is deterministic regardless of what is actually running on the box."""
    for mod in ("revit_broker", "acad_broker", "max_broker"):
        try:
            m = __import__(mod)
        except Exception:
            continue
        monkeypatch.setattr(m, "sessions_count", lambda: 0, raising=False)
        monkeypatch.setattr(m, "is_any_alive", lambda: False, raising=False)
        monkeypatch.setattr(m, "pick_session", lambda prefer=None: None,
                            raising=False)
    # Rhino + Blender bridges are HTTP — force their reachability probes
    # to report down.
    import connectors.rhino_connector as rc
    import connectors.blender_connector as bc
    monkeypatch.setattr(rc, "_bridge_live", lambda: False)
    monkeypatch.setattr(rc._runner, "is_reachable",
                        lambda *a, **k: False, raising=False)
    monkeypatch.setattr(bc._runner, "ping",
                        lambda *a, **k: None, raising=False)
    monkeypatch.setattr(
        bc._runner, "execute",
        lambda *a, **k: {"status": "error",
                         "error": "Blender addon unreachable"},
        raising=False)
    monkeypatch.setattr(
        bc._runner, "render",
        lambda *a, **k: {"status": "error",
                         "error": "Blender addon unreachable"},
        raising=False)


@pytest.mark.parametrize("host,typed_op,const_val,dst_port", [
    ("revit",   "read_walls",      None,                  None),
    ("rhino",   "export_viewport", None,                  None),
    ("3dsmax",  "run_script",      "spheres = 1",         "code"),
    ("blender", "import_mesh",     "C:/tmp/model.glb",    "mesh"),
    ("revit",   "run_script",      "result = 1;",         "code"),
    ("blender", "export_viewport", None,                  None),
])
def test_cook_offline_returns_honest_host_missing(
        monkeypatch, host, typed_op, const_val, dst_port):
    import connectors.base as cb
    cb.load_all_connectors()
    import workflows.nodes  # noqa: F401 — register data.constant etc.
    from workflows.runner import WorkflowRunner

    _force_brokers_offline(monkeypatch)

    nodes = [{"id": "tgt", "type": f"host.{typed_op}",
              "config": {"host": host}}]
    edges = []
    if dst_port and const_val is not None:
        nodes.append({"id": "src", "type": "data.constant",
                      "config": {"value": const_val}})
        edges.append({"id": "e", "src_node": "src", "src_port": "value",
                      "dst_node": "tgt", "dst_port": dst_port})

    runner = WorkflowRunner({"nodes": nodes, "edges": edges})
    out = runner.pull("tgt")

    # The op resolved to a REAL connector op (carried on the output).
    assert out.get("op_id"), f"no op_id resolved for host.{typed_op}"
    # It errored honestly (host is offline) …
    assert out.get("status") == "error"
    msg = (out.get("error") or "").lower()
    # … and the error is host-missing, NOT the unknown-op contract lie.
    assert "unknown op" not in msg, (
        f"host.{typed_op}/{host} cooked to an UNKNOWN-OP error — the "
        f"contract break is back: {out.get('error')!r}")
    assert any(s in msg for s in (
        "not running", "not reachable", "unreachable", "broker",
        "not installed", "open ", "not found")), (
        f"host.{typed_op}/{host} error is not an honest host-missing "
        f"message: {out.get('error')!r}")
