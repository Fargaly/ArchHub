"""Broker-backed AEC connector tests — Revit · AutoCAD · 3ds Max.

These connectors drive Revit / AutoCAD / 3ds Max through a host-side
add-in that serves an HTTP listener; the `*_broker` modules forward to
it. This whole suite runs with NO host running — every broker call is
mocked.

What is pinned here:
  * all three connectors register under their host id;
  * op sets + op metadata (kind / destructive / output_type) are correct;
  * `probe()` returns a clean `missing` when the broker is offline;
  * an op against a mocked-offline broker returns `OpResult(ok=False)`
    — it NEVER fabricates Revit/CAD/Max data (the founder's
    hallucination bug);
  * an op against a mocked-SUCCESSFUL broker parses the add-in's JSON
    response into the right shape and preview.

No real processes, no real sockets — `broker.list_sessions`,
`broker.pick_session`, `broker.forward`, `broker.is_any_alive` and
`broker.sessions_count` are all patched.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from connectors.base import OpResult  # noqa: E402
from connectors import (  # noqa: E402
    revit_connector,
    autocad_connector,
    max_connector,
)


# ---------------------------------------------------------------------------
# Fixtures — a fake broker Session, plus offline / online broker states.
# ---------------------------------------------------------------------------
class _FakeSession:
    """Minimal stand-in for a broker Session dataclass."""

    def __init__(self, sid="revit-1234", pid=1234, port=48884,
                 doc_title="Tower-A.rvt"):
        self.session_id = sid
        self.family = sid.split("-", 1)[0]
        self.pid = pid
        self.port = port
        self.version = "2025"
        self.doc_title = doc_title
        self.started_at = ""
        self.last_heartbeat = ""
        self.healthy = True
        self.legacy = False

    def url(self, path="/ping"):
        if not path.startswith("/"):
            path = "/" + path
        return f"http://localhost:{self.port}{path}"


# (connector module, broker-module-name) for the three connectors.
_TRIO = [
    (revit_connector, "revit_broker"),
    (autocad_connector, "acad_broker"),
    (max_connector, "max_broker"),
]


def _offline_patches(conn_module):
    """Patches that simulate 'no host running' for one connector's broker."""
    broker = getattr(conn_module, _broker_attr(conn_module))
    return [
        patch.object(broker, "list_sessions", return_value=[]),
        patch.object(broker, "pick_session", return_value=None),
        patch.object(broker, "is_any_alive", return_value=False),
        patch.object(broker, "sessions_count", return_value=0),
    ]


def _broker_attr(conn_module):
    """Name of the broker module attribute on a connector module."""
    if conn_module is revit_connector:
        return "revit_broker"
    if conn_module is autocad_connector:
        return "acad_broker"
    return "max_broker"


# ===========================================================================
# Registration
# ===========================================================================
class TestRegistration:
    """All three connectors must self-register on import."""

    def test_revit_registered(self):
        from connectors.base import get
        assert get("revit") is not None
        assert get("revit").host == "revit"

    def test_autocad_registered(self):
        from connectors.base import get
        assert get("autocad") is not None
        assert get("autocad").host == "autocad"

    def test_max_registered(self):
        from connectors.base import get
        assert get("max") is not None
        assert get("max").host == "max"

    def test_all_three_mechanism_is_broker(self):
        from connectors.base import get
        for host in ("revit", "autocad", "max"):
            assert get(host).mechanism == "broker", host

    def test_load_all_connectors_includes_trio(self):
        """The base loader must pull in all three modules + register them."""
        from connectors.base import load_all_connectors, get
        load_all_connectors()
        for host in ("revit", "autocad", "max"):
            assert get(host) is not None, host


# ===========================================================================
# Op sets
# ===========================================================================
class TestOpSets:
    """Pin exactly which ops each connector exposes."""

    def test_revit_op_ids(self):
        c = revit_connector.RevitConnector()
        ids = {o.op_id for o in c.ops()}
        expected = {
            "revit.list_views", "revit.list_walls", "revit.list_doors",
            "revit.list_windows", "revit.list_rooms", "revit.list_levels",
            "revit.list_sheets", "revit.list_families",
            "revit.get_selection", "revit.list_warnings",
            "revit.create_dimensions", "revit.place_tags",
            "revit.set_parameter",
            # AgDR-0017 (M2-Python): Revit ↔ Speckle ops. `send` is
            # kind="read" (does not mutate Revit — ships upstream
            # through SpeckleWire); `receive` is kind="action" +
            # destructive (creates native elements).
            "revit.send_to_speckle", "revit.receive_from_speckle",
            # AgDR-0018 (Batch 2): excel-param flow — action +
            # destructive (mutates existing element parameters).
            "revit.batch_set_parameters",
        }
        assert ids == expected
        assert len(c.ops()) == 16

    def test_autocad_op_ids(self):
        c = autocad_connector.AutoCADConnector()
        ids = {o.op_id for o in c.ops()}
        expected = {
            "autocad.list_documents",
            "autocad.list_layers", "autocad.list_blocks",
            "autocad.list_entities", "autocad.list_layouts",
            "autocad.get_selection", "autocad.list_xrefs",
            "autocad.run_command", "autocad.set_layer",
            # AgDR-0017 send-pattern parity — kind=read (does not mutate AutoCAD).
            "autocad.send_to_speckle",
        }
        assert ids == expected
        assert len(c.ops()) == 10

    def test_max_op_ids(self):
        c = max_connector.MaxConnector()
        ids = {o.op_id for o in c.ops()}
        expected = {
            "max.scene_info", "max.list_objects", "max.list_cameras",
            "max.list_lights", "max.list_materials", "max.get_selection",
            "max.run_maxscript",
            # AgDR-0017 send-pattern parity — kind=read.
            "max.send_to_speckle",
        }
        assert ids == expected
        assert len(c.ops()) == 8


# ===========================================================================
# Op metadata
# ===========================================================================
class TestOpMetadata:
    """Op kind / destructive flags / output types must be correct."""

    def test_destructive_actions_flagged(self):
        """Every ACTION op is destructive=True; every READ is not."""
        for conn_module, _ in _TRIO:
            cls = _connector_class(conn_module)
            for op in cls().ops():
                if op.kind == "action":
                    assert op.destructive is True, op.op_id
                else:
                    assert op.kind == "read", op.op_id
                    assert op.destructive is False, op.op_id

    def test_revit_destructive_set(self):
        c = revit_connector.RevitConnector()
        destructive = {o.op_id for o in c.ops() if o.destructive}
        assert destructive == {
            "revit.create_dimensions", "revit.place_tags",
            "revit.set_parameter",
            # AgDR-0017: receive creates native elements → destructive.
            "revit.receive_from_speckle",
            # AgDR-0018: batch_set mutates existing elements.
            "revit.batch_set_parameters",
        }

    def test_autocad_destructive_set(self):
        c = autocad_connector.AutoCADConnector()
        destructive = {o.op_id for o in c.ops() if o.destructive}
        assert destructive == {"autocad.run_command", "autocad.set_layer"}

    def test_max_destructive_set(self):
        c = max_connector.MaxConnector()
        destructive = {o.op_id for o in c.ops() if o.destructive}
        assert destructive == {"max.run_maxscript"}

    def test_every_op_has_host_and_fn(self):
        for conn_module, _ in _TRIO:
            cls = _connector_class(conn_module)
            host = cls.host
            for op in cls().ops():
                assert op.host == host, op.op_id
                assert op.op_id.startswith(host + "."), op.op_id
                assert callable(op.fn), op.op_id
                assert op.label, op.op_id

    def test_ops_have_instance_param(self):
        """Every op accepts an `instance` param for multi-window targeting."""
        for conn_module, _ in _TRIO:
            cls = _connector_class(conn_module)
            for op in cls().ops():
                param_ids = {p.id for p in op.inputs}
                assert "instance" in param_ids, op.op_id


# ===========================================================================
# probe() — offline / honest
# ===========================================================================
class TestProbeOffline:
    """probe() must return a clean `missing` when the broker is offline."""

    def test_revit_probe_missing(self):
        with _ctx(_offline_patches(revit_connector)):
            st = revit_connector.RevitConnector().probe()
        assert st["status"] == "missing"
        assert isinstance(st["note"], str) and st["note"]
        assert isinstance(st["detail"], dict)

    def test_autocad_probe_missing(self):
        with _ctx(_offline_patches(autocad_connector)):
            st = autocad_connector.AutoCADConnector().probe()
        assert st["status"] == "missing"
        assert st["note"]

    def test_max_probe_missing(self):
        with _ctx(_offline_patches(max_connector)):
            st = max_connector.MaxConnector().probe()
        assert st["status"] == "missing"
        assert st["note"]

    def test_probe_loaded_dead_when_session_file_stale(self):
        """A stale session file (is_any_alive True, 0 healthy) → loaded_dead."""
        broker = revit_connector.revit_broker
        with patch.object(broker, "sessions_count", return_value=0), \
                patch.object(broker, "is_any_alive", return_value=True), \
                patch.object(broker, "pick_session", return_value=None):
            st = revit_connector.RevitConnector().probe()
        assert st["status"] == "loaded_dead"

    def test_probe_live_when_session_healthy(self):
        """A healthy session + good /ping → live."""
        broker = revit_connector.revit_broker
        sess = _FakeSession()
        with patch.object(broker, "sessions_count", return_value=1), \
                patch.object(broker, "is_any_alive", return_value=True), \
                patch.object(broker, "pick_session", return_value=sess), \
                patch.object(broker, "forward",
                             return_value={"status": "ok", "version": "0.3.0"}):
            st = revit_connector.RevitConnector().probe()
        assert st["status"] == "live"
        assert st["detail"]["sessions"] == 1

    def test_probe_never_raises(self):
        """A broker that raises everywhere still yields a dict, not a crash."""
        broker = autocad_connector.acad_broker
        with patch.object(broker, "sessions_count",
                           side_effect=RuntimeError("boom")):
            st = autocad_connector.AutoCADConnector().probe()
        assert isinstance(st, dict)
        assert st["status"] == "missing"


# ===========================================================================
# Offline ops — honest failure, NEVER fabricated data
# ===========================================================================
class TestOfflineOpsHonest:
    """When the broker is offline, ops fail honestly — no invented data."""

    def test_revit_read_offline_fails(self):
        with _ctx(_offline_patches(revit_connector)):
            res = revit_connector.RevitConnector().op(
                "revit.list_walls").run(instance="")
        assert isinstance(res, OpResult)
        assert res.ok is False
        # No fabricated wall list — value must be falsy, error must be set.
        assert not res.value
        assert res.error
        assert "revit" in res.error.lower() or "broker" in res.error.lower()

    def test_autocad_read_offline_fails(self):
        with _ctx(_offline_patches(autocad_connector)):
            res = autocad_connector.AutoCADConnector().op(
                "autocad.list_layers").run(instance="")
        assert res.ok is False
        assert not res.value
        assert res.error

    def test_max_read_offline_fails(self):
        with _ctx(_offline_patches(max_connector)):
            res = max_connector.MaxConnector().op(
                "max.list_objects").run(instance="")
        assert res.ok is False
        assert not res.value
        assert res.error

    def test_revit_action_offline_fails(self):
        with _ctx(_offline_patches(revit_connector)):
            res = revit_connector.RevitConnector().op(
                "revit.set_parameter").run(
                    instance="", element_id=42, parameter="Comments",
                    value="x")
        assert res.ok is False
        assert res.error

    def test_offline_op_via_run_op(self):
        """The registry-level run_op path also fails honestly when offline."""
        from connectors.base import run_op
        with _ctx(_offline_patches(autocad_connector)):
            res = run_op("autocad.list_blocks", instance="")
        assert isinstance(res, OpResult)
        assert res.ok is False

    def test_broker_timeout_is_caught(self):
        """A broker.forward that raises (timeout-like) → OpResult.fail."""
        broker = revit_connector.revit_broker
        sess = _FakeSession()
        with patch.object(broker, "pick_session", return_value=sess), \
                patch.object(broker, "is_any_alive", return_value=True), \
                patch.object(broker, "forward",
                             side_effect=TimeoutError("timed out")):
            res = revit_connector.RevitConnector().op(
                "revit.list_views").run(instance="")
        assert res.ok is False
        assert not res.value

    def test_addin_error_response_is_failure(self):
        """An add-in {'status':'error'} body → OpResult.fail, not fake data."""
        broker = autocad_connector.acad_broker
        sess = _FakeSession(sid="autocad-1", port=48885)
        with patch.object(broker, "pick_session", return_value=sess), \
                patch.object(broker, "is_any_alive", return_value=True), \
                patch.object(broker, "forward",
                             return_value={"status": "error",
                                           "error": "No active document."}):
            res = autocad_connector.AutoCADConnector().op(
                "autocad.list_layers").run(instance="")
        assert res.ok is False
        assert "No active document" in res.error


# ===========================================================================
# Successful ops — parse the add-in JSON correctly
# ===========================================================================
class TestSuccessfulOps:
    """A mocked-SUCCESSFUL broker.forward → the op parses its JSON."""

    def test_revit_list_walls_parses_result(self):
        broker = revit_connector.revit_broker
        sess = _FakeSession()
        fixture = {
            "status": "ok",
            "result": [
                {"id": 1, "name": "Basic Wall", "type": "Generic - 200mm",
                 "length": 12.5, "level": "L01"},
                {"id": 2, "name": "Basic Wall", "type": "Generic - 200mm",
                 "length": 8.0, "level": "L01"},
            ],
        }
        with patch.object(broker, "pick_session", return_value=sess), \
                patch.object(broker, "is_any_alive", return_value=True), \
                patch.object(broker, "forward", return_value=fixture):
            res = revit_connector.RevitConnector().op(
                "revit.list_walls").run(instance="")
        assert res.ok is True
        assert isinstance(res.value, list)
        assert len(res.value) == 2
        assert res.value[0]["type"] == "Generic - 200mm"
        assert "2 walls" in res.value_preview

    def test_revit_forward_called_with_exec_post(self):
        """The op must POST to /exec with a C# 'code' body."""
        broker = revit_connector.revit_broker
        sess = _FakeSession()
        with patch.object(broker, "pick_session", return_value=sess), \
                patch.object(broker, "is_any_alive", return_value=True), \
                patch.object(broker, "forward",
                             return_value={"status": "ok",
                                           "result": []}) as fwd:
            revit_connector.RevitConnector().op(
                "revit.list_views").run(instance="")
        assert fwd.called
        args, kwargs = fwd.call_args
        # path is positional arg #2 (session, path).
        assert args[1] == "/exec"
        assert kwargs.get("method") == "POST"
        body = kwargs.get("body")
        assert body is not None
        assert b"code" in body  # C# script payload present

    def test_autocad_list_layers_parses_result(self):
        broker = autocad_connector.acad_broker
        sess = _FakeSession(sid="autocad-9", port=48885,
                            doc_title="Plan.dwg")
        fixture = {
            "status": "ok",
            "result": [
                {"name": "0", "is_off": False, "is_frozen": False,
                 "is_locked": False, "color": 7},
                {"name": "WALLS", "is_off": False, "is_frozen": False,
                 "is_locked": False, "color": 1},
                {"name": "DIMS", "is_off": True, "is_frozen": False,
                 "is_locked": False, "color": 2},
            ],
        }
        with patch.object(broker, "pick_session", return_value=sess), \
                patch.object(broker, "is_any_alive", return_value=True), \
                patch.object(broker, "forward", return_value=fixture):
            res = autocad_connector.AutoCADConnector().op(
                "autocad.list_layers").run(instance="")
        assert res.ok is True
        assert len(res.value) == 3
        assert res.value[1]["name"] == "WALLS"
        assert "3 layers" in res.value_preview
        assert "Plan.dwg" in res.value_preview

    def test_max_scene_info_parses_dict(self):
        broker = max_connector.max_broker
        sess = _FakeSession(sid="max-7", port=48886, doc_title="scene.max")
        fixture = {
            "status": "ok",
            "result": {
                "max_version": "26000",
                "scene_file": "C:/proj/scene.max",
                "object_count": 137,
                "current_time": 0.0,
                "animation_range_end": 100.0,
            },
        }
        with patch.object(broker, "pick_session", return_value=sess), \
                patch.object(broker, "is_any_alive", return_value=True), \
                patch.object(broker, "forward", return_value=fixture):
            res = max_connector.MaxConnector().op(
                "max.scene_info").run(instance="")
        assert res.ok is True
        assert isinstance(res.value, dict)
        assert res.value["object_count"] == 137
        assert "137 objects" in res.value_preview

    def test_max_run_maxscript_uses_maxscript_route(self):
        """run_maxscript must POST to /exec_maxscript with a 'script' body."""
        broker = max_connector.max_broker
        sess = _FakeSession(sid="max-3", port=48886)
        with patch.object(broker, "pick_session", return_value=sess), \
                patch.object(broker, "is_any_alive", return_value=True), \
                patch.object(broker, "forward",
                             return_value={"status": "ok",
                                           "result": 42}) as fwd:
            res = max_connector.MaxConnector().op(
                "max.run_maxscript").run(instance="", script="2 + 40")
        assert res.ok is True
        assert res.value == 42
        args, kwargs = fwd.call_args
        assert args[1] == "/exec_maxscript"
        body = kwargs.get("body")
        assert b"script" in body

    def test_autocad_run_command_dispatches(self):
        broker = autocad_connector.acad_broker
        sess = _FakeSession(sid="autocad-2", port=48885)
        with patch.object(broker, "pick_session", return_value=sess), \
                patch.object(broker, "is_any_alive", return_value=True), \
                patch.object(broker, "forward",
                             return_value={"status": "ok",
                                           "result": {"dispatched": True,
                                                      "command": "_ZOOM E "}}):
            res = autocad_connector.AutoCADConnector().op(
                "autocad.run_command").run(instance="", command="_ZOOM E")
        assert res.ok is True
        assert res.value["dispatched"] is True

    def test_empty_required_arg_fails_before_broker(self):
        """A missing required arg fails fast — no fabricated success."""
        # run_command with empty command must fail without touching broker.
        res = autocad_connector.AutoCADConnector().op(
            "autocad.run_command").run(instance="", command="")
        assert res.ok is False
        assert "empty" in res.error.lower()

    def test_revit_empty_result_is_zero_items_not_error(self):
        """An empty (but valid) result is an honest '0 items', not a failure."""
        broker = revit_connector.revit_broker
        sess = _FakeSession()
        with patch.object(broker, "pick_session", return_value=sess), \
                patch.object(broker, "is_any_alive", return_value=True), \
                patch.object(broker, "forward",
                             return_value={"status": "ok", "result": []}):
            res = revit_connector.RevitConnector().op(
                "revit.list_rooms").run(instance="")
        assert res.ok is True
        assert res.value == []
        assert "0 rooms" in res.value_preview


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
import contextlib  # noqa: E402


@contextlib.contextmanager
def _ctx(patches):
    """Enter a list of patch() context managers together."""
    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        yield


def _connector_class(conn_module):
    """Return the Connector subclass defined in a connector module."""
    if conn_module is revit_connector:
        return revit_connector.RevitConnector
    if conn_module is autocad_connector:
        return autocad_connector.AutoCADConnector
    return max_connector.MaxConnector


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
