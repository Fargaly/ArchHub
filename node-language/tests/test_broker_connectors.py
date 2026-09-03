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
            # AgDR-0041 P1: typed-host primitives — run_script (action),
            # export_viewport (read /screenshot), import_mesh (action).
            # Resolved by workflows/nodes/host_typed.py for host-swap.
            "revit.run_script", "revit.export_viewport",
            "revit.import_mesh",
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
        assert len(c.ops()) == 19

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
            # AgDR-0041 P1: typed-host primitives — export_viewport
            # (read) + import_mesh (action). Resolved by host_typed.py.
            "max.export_viewport", "max.import_mesh",
            # AgDR-0017 send-pattern parity — kind=read.
            "max.send_to_speckle",
        }
        assert ids == expected
        assert len(c.ops()) == 10


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
            # AgDR-0041 P1: run_script + import_mesh mutate the model →
            # destructive. (export_viewport is a read-only screenshot.)
            "revit.run_script", "revit.import_mesh",
            # AgDR-0017: receive creates native elements → destructive.
            "revit.receive_from_speckle",
            # CON-02: send writes a Speckle commit to disk (+ optional
            # remote push) — an outside-world side effect → destructive,
            # so it is approval-gated like every other write.
            "revit.send_to_speckle",
            # AgDR-0018: batch_set mutates existing elements.
            "revit.batch_set_parameters",
        }

    def test_autocad_destructive_set(self):
        c = autocad_connector.AutoCADConnector()
        destructive = {o.op_id for o in c.ops() if o.destructive}
        assert destructive == {
            "autocad.run_command", "autocad.set_layer",
            # CON-02: send writes a Speckle commit to disk (+ optional
            # remote push) → destructive, approval-gated like other writes.
            "autocad.send_to_speckle",
        }

    def test_max_destructive_set(self):
        c = max_connector.MaxConnector()
        destructive = {o.op_id for o in c.ops() if o.destructive}
        # AgDR-0041 P1: import_mesh mutates the scene → destructive.
        # (export_viewport is a read-only viewport grab.)
        assert destructive == {
            "max.run_maxscript", "max.import_mesh",
            # CON-02: send writes a Speckle commit to disk (+ optional
            # remote push) → destructive, approval-gated like other writes.
            "max.send_to_speckle",
        }

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


# ===========================================================================
# revit.import_mesh — REAL geometry, not an empty SetShape shell
# ===========================================================================
# Build-it-real proof: the op must parse an actual mesh file (OBJ/STL)
# and generate C# that rebuilds it with Revit's TessellatedShapeBuilder
# → DirectShape.SetShape(real GeometryObjects). These tests pin the
# parser, pin that the generated C# is real (TessellatedShapeBuilder +
# GetBuildResult + a non-empty SetShape, NOT `new List<GeometryObject>()`),
# and pin every honest-failure mode (missing file / unsupported format /
# parse error / broker offline). No live Revit needed — broker /exec is
# mocked; the headline live-Revit proof lives in the connector's report.
_CUBE_OBJ = """# unit cube (metres)
v 0 0 0
v 1 0 0
v 1 1 0
v 0 1 0
v 0 0 1
v 1 0 1
v 1 1 1
v 0 1 1
f 1 2 3 4
f 5 6 7 8
f 1 2 6 5
f 2 3 7 6
f 3 4 8 7
f 4 1 5 8
"""

_TETRA_OBJ = """# tetrahedron
v 0 0 0
v 1 0 0
v 0 1 0
v 0 0 1
f 1 3 2
f 1 2 4
f 2 3 4
f 3 1 4
"""


def _write(tmp_path, name, text):
    p = tmp_path / name
    if isinstance(text, bytes):
        p.write_bytes(text)
    else:
        p.write_text(text, encoding="utf-8")
    return str(p)


# --- PLY fixtures: a unit cube as ASCII + binary_little_endian ---------
# 8 verts, 6 quad faces (each fan-triangulates → 2 tris ⇒ 12 tris total).
_CUBE_PLY_VERTS = [
    (0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
    (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1),
]
_CUBE_PLY_QUADS = [
    (0, 1, 2, 3), (4, 5, 6, 7), (0, 1, 5, 4),
    (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7),
]

_CUBE_PLY_ASCII = (
    "ply\n"
    "format ascii 1.0\n"
    "comment unit cube\n"
    "element vertex 8\n"
    "property float x\nproperty float y\nproperty float z\n"
    "element face 6\n"
    "property list uchar int vertex_indices\n"
    "end_header\n"
    + "".join(f"{x} {y} {z}\n" for (x, y, z) in _CUBE_PLY_VERTS)
    + "".join("4 " + " ".join(str(i) for i in q) + "\n"
             for q in _CUBE_PLY_QUADS)
)


def _cube_ply_binary() -> bytes:
    """A unit cube as binary_little_endian PLY (verts incl. a junk
    `red uchar` colour property to prove non-xyz props are skipped)."""
    import struct
    header = (
        "ply\n"
        "format binary_little_endian 1.0\n"
        "element vertex 8\n"
        "property float x\nproperty float y\nproperty float z\n"
        "property uchar red\n"          # extra prop → must be skipped
        "element face 6\n"
        "property list uchar int vertex_indices\n"
        "end_header\n"
    ).encode("ascii")
    body = b""
    for (x, y, z) in _CUBE_PLY_VERTS:
        body += struct.pack("<fffB", x, y, z, 200)
    for q in _CUBE_PLY_QUADS:
        body += struct.pack("<B", 4) + struct.pack("<4i", *q)
    return header + body


# --- glTF / GLB fixtures: a single triangle, geometry in a buffer ------
def _tri_buffer() -> bytes:
    """Indices (3×uint16) then POSITION (3×vec3 float) — the layout the
    fixtures' bufferViews describe."""
    import struct
    indices = struct.pack("<3H", 0, 1, 2)
    positions = struct.pack("<9f", 0, 0, 0, 1, 0, 0, 0, 1, 0)
    return indices + positions


def _tri_gltf_dict(buffer_uri=None, with_translation=False) -> dict:
    """A minimal valid glTF 2.0 doc for one triangle. `buffer_uri` None →
    buffer has no URI (for the GLB case); a string → embedded/relative."""
    buf = _tri_buffer()
    buffer = {"byteLength": len(buf)}
    if buffer_uri is not None:
        buffer["uri"] = buffer_uri
    node = {"mesh": 0}
    if with_translation:
        node["translation"] = [10.0, 0.0, 0.0]
    return {
        "asset": {"version": "2.0"},
        "buffers": [buffer],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": 6},
            {"buffer": 0, "byteOffset": 6, "byteLength": 36},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5123, "count": 3,
             "type": "SCALAR"},
            {"bufferView": 1, "componentType": 5126, "count": 3,
             "type": "VEC3"},
        ],
        "meshes": [{"primitives": [
            {"attributes": {"POSITION": 1}, "indices": 0, "mode": 4}]}],
        "nodes": [node],
        "scenes": [{"nodes": [0]}],
        "scene": 0,
    }


def _tri_gltf_embedded() -> str:
    """A .gltf JSON string with the geometry in a base64 data: URI."""
    import base64
    import json as _json
    uri = ("data:application/octet-stream;base64,"
           + base64.b64encode(_tri_buffer()).decode("ascii"))
    return _json.dumps(_tri_gltf_dict(buffer_uri=uri))


def _tri_glb_bytes(with_translation=False) -> bytes:
    """Construct a minimal valid GLB container (12-byte header + JSON
    chunk + BIN chunk) for one triangle, geometry in the BIN chunk."""
    import json as _json
    import struct
    gltf = _tri_gltf_dict(buffer_uri=None, with_translation=with_translation)
    json_bytes = _json.dumps(gltf).encode("utf-8")
    bin_bytes = _tri_buffer()

    def _pad(b, fill):
        while len(b) % 4:
            b += fill
        return b

    json_chunk = _pad(json_bytes, b" ")
    bin_chunk = _pad(bin_bytes, b"\x00")
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    out = b"glTF" + struct.pack("<II", 2, total)
    out += struct.pack("<II", len(json_chunk), 0x4E4F534A) + json_chunk
    out += struct.pack("<II", len(bin_chunk), 0x004E4942) + bin_chunk
    return out


class TestImportMeshParser:
    """The OBJ/STL parsers produce real (vertices, faces) — the data the
    TessellatedShapeBuilder needs. No fabrication, honest errors."""

    def test_parse_obj_cube(self):
        verts, faces = revit_connector._parse_obj(_CUBE_OBJ)
        assert len(verts) == 8
        assert len(faces) == 6           # 6 quad faces, kept whole
        assert verts[6] == [1.0, 1.0, 1.0]
        assert faces[0] == [0, 1, 2, 3]  # 1-based OBJ → 0-based

    def test_parse_obj_negative_indices(self):
        # Relative (negative) OBJ indices resolve against vertex count.
        verts, faces = revit_connector._parse_obj(
            "v 0 0 0\nv 1 0 0\nv 0 1 0\nf -3 -2 -1")
        assert faces == [[0, 1, 2]]

    def test_parse_obj_face_vertex_syntax(self):
        # f v/vt/vn — only the position index is taken.
        _, faces = revit_connector._parse_obj(
            "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1/1/1 2/2/2 3/3/3")
        assert faces == [[0, 1, 2]]

    def test_parse_obj_no_vertices_raises(self):
        with pytest.raises(revit_connector.MeshParseError):
            revit_connector._parse_obj("f 1 2 3\n")

    def test_parse_obj_no_faces_raises(self):
        with pytest.raises(revit_connector.MeshParseError):
            revit_connector._parse_obj("v 0 0 0\nv 1 0 0\nv 0 1 0\n")

    def test_parse_obj_out_of_range_face_raises(self):
        # Face references a vertex that doesn't exist → honest error, not
        # a crash inside Revit later.
        with pytest.raises(revit_connector.MeshParseError):
            revit_connector._parse_obj(
                "v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 99")

    def test_parse_stl_ascii_tetra(self):
        ascii_stl = (
            "solid t\n"
            "facet normal 0 0 0\n outer loop\n"
            "  vertex 0 0 0\n  vertex 1 0 0\n  vertex 0 1 0\n"
            " endloop\nendfacet\n"
            "endsolid t\n")
        verts, faces = revit_connector._parse_stl(ascii_stl.encode("utf-8"))
        assert len(verts) == 3
        assert faces == [[0, 1, 2]]

    def test_parse_stl_binary_one_triangle(self):
        import struct
        # 80-byte header + uint32 count + 1 triangle (50 bytes).
        buf = bytearray(b"\x00" * 80)
        buf += struct.pack("<I", 1)
        buf += struct.pack("<12f",
                           0, 0, 0,      # normal
                           0, 0, 0,      # v0
                           1, 0, 0,      # v1
                           0, 1, 0)      # v2
        buf += struct.pack("<H", 0)      # attribute byte count
        verts, faces = revit_connector._parse_stl(bytes(buf))
        assert len(verts) == 3
        assert faces == [[0, 1, 2]]


class TestImportMeshParserPLY:
    """PLY (ASCII + binary_little_endian) → real (vertices, faces).
    Polygons fan-triangulate; non-xyz properties are read + skipped so
    the binary stride stays correct."""

    def test_parse_ply_ascii_cube(self):
        verts, tris = revit_connector._parse_ply(_CUBE_PLY_ASCII.encode())
        assert len(verts) == 8
        assert len(tris) == 12          # 6 quads → 12 fan triangles
        assert verts[6] == [1.0, 1.0, 1.0]
        assert all(len(t) == 3 for t in tris)
        # First quad (0,1,2,3) fans to (0,1,2) + (0,2,3).
        assert [0, 1, 2] in tris and [0, 2, 3] in tris

    def test_parse_ply_binary_cube(self):
        verts, tris = revit_connector._parse_ply(_cube_ply_binary())
        assert len(verts) == 8          # extra `red` prop skipped cleanly
        assert len(tris) == 12
        assert verts[2] == [1.0, 1.0, 0.0]

    def test_parse_ply_ascii_triangle_kept(self):
        # A native triangle face passes through unchanged.
        ply = (
            "ply\nformat ascii 1.0\n"
            "element vertex 3\n"
            "property float x\nproperty float y\nproperty float z\n"
            "element face 1\n"
            "property list uchar int vertex_indices\n"
            "end_header\n"
            "0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n")
        verts, tris = revit_connector._parse_ply(ply.encode())
        assert len(verts) == 3
        assert tris == [[0, 1, 2]]

    def test_parse_ply_not_ply_raises(self):
        with pytest.raises(revit_connector.MeshParseError):
            revit_connector._parse_ply(b"not a ply file at all\n")

    def test_parse_ply_out_of_range_raises(self):
        ply = (
            "ply\nformat ascii 1.0\n"
            "element vertex 3\n"
            "property float x\nproperty float y\nproperty float z\n"
            "element face 1\n"
            "property list uchar int vertex_indices\n"
            "end_header\n"
            "0 0 0\n1 0 0\n0 1 0\n3 0 1 9\n")   # index 9 doesn't exist
        with pytest.raises(revit_connector.MeshParseError):
            revit_connector._parse_ply(ply.encode())


class TestImportMeshParserGLTF:
    """glTF (.gltf JSON) + GLB (binary container) → real (vertices,
    faces) via the POSITION + indices accessors. Node transforms applied;
    non-triangle modes rejected honestly."""

    def test_parse_gltf_embedded_base64(self):
        import json as _json
        gltf = _json.loads(_tri_gltf_embedded())
        verts, faces = revit_connector._parse_gltf(gltf, "", None)
        assert len(verts) == 3
        assert len(faces) == 1
        assert verts[1] == [1.0, 0.0, 0.0]   # POSITION accessor decoded
        assert faces[0] == [0, 1, 2]         # indices accessor decoded

    def test_parse_gltf_applies_node_translation(self):
        gltf = _tri_gltf_dict(
            buffer_uri=("data:application/octet-stream;base64,"
                        + __import__("base64").b64encode(
                            _tri_buffer()).decode()),
            with_translation=True)
        verts, faces = revit_connector._parse_gltf(gltf, "", None)
        # POSITION[0] = (0,0,0) shifted by the node's +10 X translation.
        assert verts[0] == [10.0, 0.0, 0.0]

    def test_parse_gltf_rejects_non_triangle_mode(self):
        import json as _json
        gltf = _json.loads(_tri_gltf_embedded())
        gltf["meshes"][0]["primitives"][0]["mode"] = 1   # LINES
        with pytest.raises(revit_connector.MeshParseError):
            revit_connector._parse_gltf(gltf, "", None)

    def test_parse_glb_container(self):
        verts, faces = revit_connector._parse_glb(_tri_glb_bytes())
        assert len(verts) == 3
        assert len(faces) == 1
        assert verts[2] == [0.0, 1.0, 0.0]

    def test_parse_glb_with_node_translation(self):
        verts, faces = revit_connector._parse_glb(
            _tri_glb_bytes(with_translation=True))
        assert verts[0] == [10.0, 0.0, 0.0]

    def test_parse_glb_not_glb_raises(self):
        with pytest.raises(revit_connector.MeshParseError):
            revit_connector._parse_glb(b"PK\x03\x04 this is a zip, not glb")


class TestImportMeshDispatch:
    """`_parse_mesh_file` routes by extension first, then magic bytes."""

    def test_dispatch_ply_file(self, tmp_path):
        path = _write(tmp_path, "cube.ply", _CUBE_PLY_ASCII)
        verts, faces, fmt = revit_connector._parse_mesh_file(path)
        assert fmt == "ply"
        assert len(verts) == 8 and len(faces) == 12

    def test_dispatch_gltf_file(self, tmp_path):
        path = _write(tmp_path, "tri.gltf", _tri_gltf_embedded())
        verts, faces, fmt = revit_connector._parse_mesh_file(path)
        assert fmt == "gltf"
        assert len(verts) == 3 and len(faces) == 1

    def test_dispatch_glb_file(self, tmp_path):
        path = _write(tmp_path, "tri.glb", _tri_glb_bytes())
        verts, faces, fmt = revit_connector._parse_mesh_file(path)
        assert fmt == "glb"
        assert len(verts) == 3 and len(faces) == 1

    def test_dispatch_gltf_with_sibling_bin(self, tmp_path):
        # .gltf that references a sibling .bin (not embedded) — the common
        # two-file glTF export.
        import json as _json
        (tmp_path / "geo.bin").write_bytes(_tri_buffer())
        gltf = _tri_gltf_dict(buffer_uri="geo.bin")
        path = _write(tmp_path, "tri.gltf", _json.dumps(gltf))
        verts, faces, fmt = revit_connector._parse_mesh_file(path)
        assert fmt == "gltf"
        assert len(verts) == 3 and len(faces) == 1

    def test_dispatch_magic_bytes_glb_wrong_ext(self, tmp_path):
        # GLB content under a misleading extension → sniffed by magic.
        path = _write(tmp_path, "mystery.dat", _tri_glb_bytes())
        verts, faces, fmt = revit_connector._parse_mesh_file(path)
        assert fmt == "glb"
        assert len(verts) == 3

    def test_dispatch_magic_bytes_ply_no_ext(self, tmp_path):
        path = _write(tmp_path, "noext", _CUBE_PLY_ASCII)
        verts, faces, fmt = revit_connector._parse_mesh_file(path)
        assert fmt == "ply"
        assert len(verts) == 8

    def test_dispatch_truly_unsupported_raises(self, tmp_path):
        path = _write(tmp_path, "model.3dm", b"\x00\x01 binary rhino")
        with pytest.raises(NotImplementedError):
            revit_connector._parse_mesh_file(path)


class TestImportMeshGeneratesRealCSharp:
    """The generated C# is REAL tessellation — the build-it-real core.
    Asserts TessellatedShapeBuilder + GetBuildResult + a non-empty
    SetShape, and that the OLD empty-shell / bad-options code is gone."""

    def test_generated_cs_uses_tessellated_shape_builder(self):
        verts, faces = revit_connector._parse_obj(_CUBE_OBJ)
        cs = revit_connector._tessellate_cs(verts, faces, 3.28084, "Cube")
        # Real builder pipeline present.
        assert "new TessellatedShapeBuilder()" in cs
        assert "AddFace(new TessellatedFace(" in cs
        assert ".Build();" in cs
        assert "GetBuildResult()" in cs
        assert "GetGeometricalObjects()" in cs
        assert "ds.SetShape(objs)" in cs
        # Every real vertex made it into the C# vertex table.
        assert cs.count("new XYZ(") == 8
        # Returns verifiable, non-fabricated proof fields.
        assert "geometry_object_count" in cs
        assert "element_id" in cs

    def test_generated_cs_is_not_the_old_empty_shell(self):
        verts, faces = revit_connector._parse_obj(_CUBE_OBJ)
        cs = revit_connector._tessellate_cs(verts, faces, 3.28084, "Cube")
        # The two bugs from the old code must be gone:
        assert "new List<GeometryObject>()" not in cs   # empty SetShape
        assert "TessellatedShapeBuilderOptions" not in cs  # CS0246 type

    def test_import_mesh_posts_real_tessellation_to_exec(self, tmp_path):
        """End-to-end through the mocked broker: import_mesh of a real
        OBJ file POSTs a /exec body carrying TessellatedShapeBuilder C#
        and returns the parsed element id — proving the generator feeds
        real geometry to Revit, not an empty shell."""
        path = _write(tmp_path, "cube.obj", _CUBE_OBJ)
        broker = revit_connector.revit_broker
        sess = _FakeSession()
        fixture = {"status": "ok", "result": {
            "created": True, "element_id": 991234, "name": "ArchHub Mesh",
            "vertex_count": 8, "face_count": 12,
            "geometry_object_count": 1, "bbox": None, "error": ""}}
        with patch.object(broker, "pick_session", return_value=sess), \
                patch.object(broker, "is_any_alive", return_value=True), \
                patch.object(broker, "forward",
                             return_value=fixture) as fwd:
            res = revit_connector.RevitConnector().op(
                "revit.import_mesh").run(mesh=path)
        assert res.ok is True
        assert res.value["element_id"] == 991234
        assert "8 verts" in res.value_preview
        # The /exec body must carry the real builder.
        args, kwargs = fwd.call_args
        assert args[1] == "/exec"
        body = kwargs.get("body") or b""
        assert b"TessellatedShapeBuilder" in body
        assert b"GetBuildResult" in body
        assert b"new List<GeometryObject>()" not in body  # not the shell

    @pytest.mark.parametrize("name,payload,want_verts,want_faces", [
        ("cube.ply", _CUBE_PLY_ASCII, 8, 12),
        ("tri.glb", None, 3, 1),    # None → built via _tri_glb_bytes()
    ])
    def test_import_mesh_ply_and_glb_post_real_tessellation(
            self, tmp_path, name, payload, want_verts, want_faces):
        """PLY + GLB both flow through the SAME real path: parsed in
        Python → a /exec body carrying TessellatedShapeBuilder C# whose
        vertex table matches the parsed mesh. Proves the new formats are
        first-class, not a half-wired stub."""
        data = payload if payload is not None else _tri_glb_bytes()
        path = _write(tmp_path, name, data)
        broker = revit_connector.revit_broker
        sess = _FakeSession()
        fixture = {"status": "ok", "result": {
            "created": True, "element_id": 770001, "name": "ArchHub Mesh",
            "vertex_count": want_verts, "face_count": want_faces,
            "geometry_object_count": 1, "bbox": None, "error": ""}}
        with patch.object(broker, "pick_session", return_value=sess), \
                patch.object(broker, "is_any_alive", return_value=True), \
                patch.object(broker, "forward",
                             return_value=fixture) as fwd:
            res = revit_connector.RevitConnector().op(
                "revit.import_mesh").run(mesh=path)
        assert res.ok is True
        assert res.value["element_id"] == 770001
        body = fwd.call_args.kwargs.get("body") or b""
        assert b"TessellatedShapeBuilder" in body
        assert b"GetBuildResult" in body
        assert b"new List<GeometryObject>()" not in body
        # The C# vertex table must hold exactly the parsed vertex count —
        # proof the parser fed real geometry, not an empty shell.
        assert body.count(b"new XYZ(") == want_verts


class TestImportMeshHonestFailures:
    """Every bad input fails honestly — never a fabricated success."""

    def test_missing_file_fails(self, tmp_path):
        res = revit_connector.RevitConnector().op(
            "revit.import_mesh").run(mesh=str(tmp_path / "nope.obj"))
        assert res.ok is False
        assert "not found" in res.error.lower()

    def test_unsupported_format_fails(self, tmp_path):
        # A genuinely-exotic format with no parser + no recognisable magic
        # → honest unsupported error that names the supported set. (.obj/
        # .stl/.ply/.gltf/.glb are all supported now.)
        path = _write(tmp_path, "model.3dm", b"\x00\x01\x02 random binary")
        res = revit_connector.RevitConnector().op(
            "revit.import_mesh").run(mesh=path)
        assert res.ok is False
        assert "unsupported" in res.error.lower()
        # The error must name the supported formats so it's actionable.
        for fmt in (".obj", ".stl", ".ply", ".gltf", ".glb"):
            assert fmt in res.error

    def test_parse_error_fails(self, tmp_path):
        # A .obj with vertices but no faces → honest parse error.
        path = _write(tmp_path, "bad.obj", "v 0 0 0\nv 1 0 0\n")
        res = revit_connector.RevitConnector().op(
            "revit.import_mesh").run(mesh=path)
        assert res.ok is False
        assert "parse" in res.error.lower()

    def test_no_path_fails(self):
        res = revit_connector.RevitConnector().op(
            "revit.import_mesh").run(mesh=None)
        assert res.ok is False
        assert "path" in res.error.lower()

    def test_import_mesh_offline_is_honest(self, tmp_path):
        """Broker offline → honest host-missing error, NOT a crash and NOT
        a fake element. The file parses fine; only the host is down."""
        path = _write(tmp_path, "cube.obj", _CUBE_OBJ)
        with _ctx(_offline_patches(revit_connector)):
            res = revit_connector.RevitConnector().op(
                "revit.import_mesh").run(mesh=path)
        assert res.ok is False
        assert not res.value
        assert ("revit" in res.error.lower()
                or "broker" in res.error.lower())

    def test_build_empty_result_is_honest_failure(self, tmp_path):
        """If Revit's Build() yields no geometry, the op fails honestly
        with the builder's reason — never reports a created element."""
        path = _write(tmp_path, "cube.obj", _CUBE_OBJ)
        broker = revit_connector.revit_broker
        sess = _FakeSession()
        fixture = {"status": "ok", "result": {
            "created": False, "element_id": 5, "geometry_object_count": 0,
            "error": "TessellatedShapeBuilder produced no geometry "
                     "(build result empty)."}}
        with patch.object(broker, "pick_session", return_value=sess), \
                patch.object(broker, "is_any_alive", return_value=True), \
                patch.object(broker, "forward", return_value=fixture):
            res = revit_connector.RevitConnector().op(
                "revit.import_mesh").run(mesh=path)
        assert res.ok is False
        assert "no geometry" in res.error.lower()


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
