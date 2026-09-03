"""Geometry + Outlook connector cluster tests — Blender, Rhino, Outlook.

These run with NO host installed / open. Every host-touching call is
mocked at the runner boundary:
  * Outlook  — `connectors.outlook_runner` functions
  * Blender  — `connectors.blender_runner` HTTP functions
  * Rhino    — `connectors.rhino_runner` HTTP / TCP functions

What we assert:
  * each connector self-registers under base.register()
  * the op set, op kinds and destructive flags match the mandate
  * probe() returns a clean `missing` (or other honest) status when the
    host is unreachable — never raises
  * ops never raise to the caller — failures come back as OpResult.fail
  * op metadata (ParamSpec, output_type) is well-formed
  * a happy-path read works end-to-end against a mocked runner
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

APP_ROOT = Path(__file__).resolve().parent.parent / "app"
sys.path.insert(0, str(APP_ROOT))

from connectors import base  # noqa: E402
from connectors.base import OpResult, Connector, ConnectorOp  # noqa: E402
from connectors import outlook_connector as oc  # noqa: E402
from connectors import blender_connector as bc  # noqa: E402
from connectors import rhino_connector as rc  # noqa: E402


# ─────────────────────────────────────────────────────────────────────
# Registration — all three must land in the global registry.
# ─────────────────────────────────────────────────────────────────────
class TestRegistration:
    def test_all_three_connectors_registered(self):
        base.load_all_connectors()
        for host in ("outlook", "blender", "rhino"):
            c = base.get(host)
            assert c is not None, f"{host} connector not registered"
            assert isinstance(c, Connector)

    def test_connector_identity_fields(self):
        assert base.get("outlook").mechanism == "com"
        assert base.get("blender").mechanism == "python_api"
        assert base.get("rhino").mechanism == "python_api"
        assert base.get("outlook").display_name == "Outlook"
        assert base.get("blender").display_name == "Blender"
        assert base.get("rhino").display_name == "Rhino"

    def test_every_op_id_is_host_prefixed_and_unique(self):
        for host in ("outlook", "blender", "rhino"):
            c = base.get(host)
            ids = [o.op_id for o in c.ops()]
            assert len(ids) == len(set(ids)), f"{host}: duplicate op_id"
            for op_id in ids:
                assert op_id.startswith(host + "."), \
                    f"{op_id} not prefixed with {host}."


# ─────────────────────────────────────────────────────────────────────
# Op sets — exact op_id coverage per the mandate.
# ─────────────────────────────────────────────────────────────────────
class TestOpSets:
    def test_outlook_op_set(self):
        ids = {o.op_id for o in oc.OutlookConnector().ops()}
        assert ids == {
            "outlook.list_inbox", "outlook.read_email",
            "outlook.list_calendar", "outlook.list_contacts",
            "outlook.list_drafts", "outlook.unread_count",
            "outlook.create_draft", "outlook.mark_read",
            # Escape hatch — arbitrary Python over COM (2026-05-18).
            "outlook.execute_python",
        }

    def test_blender_op_set(self):
        ids = {o.op_id for o in bc.BlenderConnector().ops()}
        assert ids == {
            "blender.scene_info", "blender.list_objects",
            "blender.list_collections", "blender.list_materials",
            "blender.get_selection", "blender.run_script",
            "blender.set_object_visibility", "blender.render",
            # AgDR-0041 P1: typed-host primitives — export_viewport
            # (read, wraps /render) + import_mesh (action). Resolved by
            # workflows/nodes/host_typed.py for host-swap.
            "blender.export_viewport", "blender.import_mesh",
        }

    def test_rhino_op_set(self):
        ids = {o.op_id for o in rc.RhinoConnector().ops()}
        assert ids == {
            "rhino.document_info", "rhino.list_layers",
            "rhino.list_objects", "rhino.get_selection",
            "rhino.run_script", "rhino.set_layer_visibility",
            # AgDR-0041 P1: typed-host primitives — export_viewport
            # (read, /screenshot) + import_mesh (action). Resolved by
            # workflows/nodes/host_typed.py for host-swap.
            "rhino.export_viewport", "rhino.import_mesh",
        }

    def test_destructive_actions_flagged(self):
        # Every ACTION op must be destructive; every READ op must not.
        for host in ("outlook", "blender", "rhino"):
            for o in base.get(host).ops():
                if o.kind == "action":
                    assert o.destructive is True, \
                        f"{o.op_id} is an action but not destructive"
                elif o.kind == "read":
                    assert o.destructive is False, \
                        f"{o.op_id} is a read but flagged destructive"
                else:
                    pytest.fail(f"{o.op_id}: bad kind {o.kind!r}")

    def test_op_metadata_well_formed(self):
        # Every op carries a label, a valid kind, an output_type, and
        # ParamSpec inputs with non-empty ids.
        for host in ("outlook", "blender", "rhino"):
            for o in base.get(host).ops():
                assert isinstance(o, ConnectorOp)
                assert o.label and isinstance(o.label, str)
                assert o.kind in ("read", "action")
                assert o.output_type
                assert o.fn is not None, f"{o.op_id}: no implementation"
                for p in o.inputs:
                    assert p.id and isinstance(p.id, str)
                    assert p.label
                # to_dict must be JSON-shaped (no exceptions).
                d = o.to_dict()
                assert d["op_id"] == o.op_id
                assert d["host"] == host


# ─────────────────────────────────────────────────────────────────────
# Outlook — probe + ops with the COM runner mocked.
# ─────────────────────────────────────────────────────────────────────
class TestOutlookConnector:
    def test_probe_missing_when_outlook_unreachable(self):
        with patch.object(oc._runner, "is_reachable", return_value=False):
            st = oc.OutlookConnector().probe()
        assert st["status"] == "missing"
        assert "note" in st and st["note"]

    def test_probe_never_raises_when_runner_throws(self):
        with patch.object(oc._runner, "is_reachable",
                          side_effect=RuntimeError("pywin32 missing")):
            st = oc.OutlookConnector().probe()
        assert st["status"] == "missing"   # swallowed, not raised

    def test_probe_live_when_reachable(self):
        with patch.object(oc._runner, "is_reachable", return_value=True), \
             patch.object(oc._runner, "info", return_value={
                 "status": "ok", "inbox_total": 42, "inbox_unread": 3,
                 "drafts_count": 1, "default_account_email": "a@b.com"}):
            st = oc.OutlookConnector().probe()
        assert st["status"] == "live"
        assert st["detail"]["inbox_unread"] == 3

    def test_list_inbox_happy_path(self):
        fake = [
            {"entry_id": "E1", "subject": "Hi", "unread": True},
            {"entry_id": "E2", "subject": "Bye", "unread": False},
        ]
        with patch.object(oc._runner, "list_inbox", return_value=fake):
            res = base.get("outlook").op("outlook.list_inbox").run(limit=10)
        assert res.ok is True
        assert res.value == fake
        assert "2 emails" in res.value_preview
        assert "1 unread" in res.value_preview

    def test_read_email_requires_entry_id(self):
        res = base.get("outlook").op("outlook.read_email").run(entry_id="")
        assert res.ok is False
        assert "entry_id" in res.error

    def test_read_email_happy_path(self):
        thread = {"target": {"subject": "RFI 12"}, "thread": [1, 2, 3]}
        with patch.object(oc._runner, "read_thread", return_value=thread):
            res = base.get("outlook").op("outlook.read_email").run(
                entry_id="E9")
        assert res.ok is True
        assert "RFI 12" in res.value_preview

    def test_unread_count_happy_path(self):
        with patch.object(oc._runner, "info", return_value={
                "status": "ok", "inbox_total": 100, "inbox_unread": 7,
                "drafts_count": 2}):
            res = base.get("outlook").op("outlook.unread_count").run()
        assert res.ok is True
        assert res.value["unread"] == 7

    def test_create_draft_never_sends(self):
        # create_draft must call draft_reply with send=False, or use the
        # COM escape hatch — never .Send(). Assert the send gate.
        captured = {}

        def fake_draft_reply(eid, body, *, reply_all=False, send=False):
            captured["send"] = send
            return {"status": "draft_open", "entry_id": "D1"}

        with patch.object(oc._runner, "draft_reply", fake_draft_reply):
            res = base.get("outlook").op("outlook.create_draft").run(
                reply_to_entry_id="E1", body="hello")
        assert res.ok is True
        assert captured["send"] is False, "create_draft must NOT send"

    def test_create_draft_requires_recipient_for_new_mail(self):
        res = base.get("outlook").op("outlook.create_draft").run(
            to="", subject="x", body="y")
        assert res.ok is False
        assert "to" in res.error.lower()

    def test_mark_read_runs_and_previews(self):
        with patch.object(oc._runner, "mark_read", return_value={
                "status": "ok", "entry_id": "E1", "unread": False}):
            res = base.get("outlook").op("outlook.mark_read").run(
                entry_id="E1", read=True)
        assert res.ok is True
        assert "read" in res.value_preview

    def test_op_failure_when_runner_raises_is_caught(self):
        # ConnectorOp.run() catches everything → OpResult.fail, not raise.
        with patch.object(oc._runner, "list_inbox",
                          side_effect=OSError("COM boom")):
            res = base.get("outlook").op("outlook.list_inbox").run()
        assert res.ok is False
        assert "COM boom" in res.error


# ─────────────────────────────────────────────────────────────────────
# Blender — three-state probe + ops with the HTTP runner mocked.
# ─────────────────────────────────────────────────────────────────────
class TestBlenderConnector:
    def test_probe_missing_when_no_process_no_addon(self):
        with patch.object(bc._runner, "ping", return_value=None), \
             patch.object(bc, "_blender_process_running",
                          return_value=False):
            st = bc.BlenderConnector().probe()
        assert st["status"] == "missing"

    def test_probe_loaded_dead_when_process_up_addon_silent(self):
        with patch.object(bc._runner, "ping", return_value=None), \
             patch.object(bc, "_blender_process_running",
                          return_value=True):
            st = bc.BlenderConnector().probe()
        assert st["status"] == "loaded_dead"

    def test_probe_live_when_addon_answers(self):
        with patch.object(bc._runner, "ping",
                          return_value={"status": "ok", "version": "4.2"}):
            st = bc.BlenderConnector().probe()
        assert st["status"] == "live"

    def test_probe_never_raises_when_ping_throws(self):
        with patch.object(bc._runner, "ping",
                          side_effect=ConnectionError("refused")), \
             patch.object(bc, "_blender_process_running",
                          return_value=False):
            st = bc.BlenderConnector().probe()
        assert st["status"] == "missing"

    def test_scene_info_happy_path(self):
        # The connector wraps a JSON sentinel print; the runner returns
        # captured stdout. Mock execute() to return that envelope.
        payload = {"scene": "Scene", "object_count": 5,
                   "collection_count": 1, "material_count": 2}
        stdout = "__ARCHHUB_JSON__" + __import__("json").dumps(payload)
        with patch.object(bc._runner, "execute",
                          return_value={"stdout": stdout}):
            res = base.get("blender").op("blender.scene_info").run()
        assert res.ok is True
        assert res.value["object_count"] == 5
        assert "Scene" in res.value_preview

    def test_list_objects_happy_path(self):
        objs = [{"name": "Cube", "type": "MESH", "visible": True}]
        stdout = "__ARCHHUB_JSON__" + __import__("json").dumps(objs)
        with patch.object(bc._runner, "execute",
                          return_value={"stdout": stdout}):
            res = base.get("blender").op("blender.list_objects").run()
        assert res.ok is True
        assert res.value == objs
        assert "1 object" in res.value_preview

    def test_read_op_fails_cleanly_when_addon_unreachable(self):
        with patch.object(bc._runner, "execute",
                          side_effect=ConnectionError("no addon")):
            res = base.get("blender").op("blender.list_objects").run()
        assert res.ok is False
        assert res.error  # a message, not a crash

    def test_run_script_requires_code(self):
        res = base.get("blender").op("blender.run_script").run(code="")
        assert res.ok is False
        assert "code" in res.error

    def test_set_object_visibility_requires_name(self):
        res = base.get("blender").op(
            "blender.set_object_visibility").run(object_name="")
        assert res.ok is False
        assert "object_name" in res.error

    def test_render_requires_output_path(self):
        res = base.get("blender").op("blender.render").run(output_path="")
        assert res.ok is False
        assert "output_path" in res.error

    def test_render_happy_path(self):
        with patch.object(bc._runner, "render", return_value={
                "ok": True, "output_path": "C:/tmp/out.png"}):
            res = base.get("blender").op("blender.render").run(
                output_path="C:/tmp/out.png")
        assert res.ok is True
        assert "out.png" in res.value_preview

    def test_blender_script_error_surfaces_as_fail(self):
        with patch.object(bc._runner, "execute", return_value={
                "status": "error", "error": "NameError: bpy"}):
            res = base.get("blender").op("blender.scene_info").run()
        assert res.ok is False
        assert "NameError" in res.error


# ─────────────────────────────────────────────────────────────────────
# Rhino — honest probe + ops with the HTTP runner mocked.
# ─────────────────────────────────────────────────────────────────────
class TestRhinoConnector:
    def test_probe_missing_when_bridge_unreachable(self):
        with patch.object(rc._runner, "is_reachable", return_value=False):
            st = rc.RhinoConnector().probe()
        assert st["status"] == "missing"
        assert "9879" in st["note"] or "bridge" in st["note"].lower()

    def test_probe_never_raises_when_reachable_check_throws(self):
        with patch.object(rc._runner, "is_reachable",
                          side_effect=OSError("socket boom")):
            st = rc.RhinoConnector().probe()
        # _bridge_live() swallows it → treated as unreachable.
        assert st["status"] == "missing"

    def test_probe_missing_when_port_open_but_ping_errors(self):
        # Honest: an open port that doesn't actually answer /ping is
        # NOT live.
        with patch.object(rc._runner, "is_reachable", return_value=True), \
             patch.object(rc._runner, "ping", return_value={
                 "status": "error", "error": "addon not loaded"}):
            st = rc.RhinoConnector().probe()
        assert st["status"] == "missing"

    def test_probe_live_when_bridge_answers(self):
        with patch.object(rc._runner, "is_reachable", return_value=True), \
             patch.object(rc._runner, "ping", return_value={
                 "status": "ok", "version": "8"}):
            st = rc.RhinoConnector().probe()
        assert st["status"] == "live"
        assert "8" in st["note"]

    def test_list_layers_happy_path(self):
        layers = [{"name": "Default", "visible": True, "locked": False}]
        with patch.object(rc._runner, "execute_python", return_value={
                "status": "ok", "result": layers}):
            res = base.get("rhino").op("rhino.list_layers").run()
        assert res.ok is True
        assert res.value == layers
        assert "1 layer" in res.value_preview

    def test_list_objects_rejects_bad_geo_kind(self):
        res = base.get("rhino").op("rhino.list_objects").run(
            geo_kind="bananas")
        assert res.ok is False
        assert "geo_kind" in res.error

    def test_list_objects_happy_path(self):
        objs = [{"id": "g1", "kind": "curves", "layer": "Default"}]
        with patch.object(rc._runner, "execute_python", return_value={
                "status": "ok", "result": objs}):
            res = base.get("rhino").op("rhino.list_objects").run(
                geo_kind="curves")
        assert res.ok is True
        assert res.value == objs

    def test_document_info_via_sentinel_stdout(self):
        # When the addon returns no structured `result`, the connector
        # parses the JSON sentinel out of stdout.
        info = {"name": "model.3dm", "object_count": 12}
        stdout = "__ARCHHUB_JSON__" + __import__("json").dumps(info)
        with patch.object(rc._runner, "execute_python", return_value={
                "status": "ok", "stdout": stdout}):
            res = base.get("rhino").op("rhino.document_info").run()
        assert res.ok is True
        assert res.value["object_count"] == 12

    def test_read_op_fails_cleanly_when_bridge_down(self):
        with patch.object(rc._runner, "execute_python",
                          side_effect=ConnectionError("no bridge")):
            res = base.get("rhino").op("rhino.list_layers").run()
        assert res.ok is False
        assert res.error

    def test_run_script_requires_code(self):
        res = base.get("rhino").op("rhino.run_script").run(code="")
        assert res.ok is False
        assert "code" in res.error

    def test_set_layer_visibility_requires_layer(self):
        res = base.get("rhino").op(
            "rhino.set_layer_visibility").run(layer="")
        assert res.ok is False
        assert "layer" in res.error

    def test_rhino_script_error_surfaces_as_fail(self):
        with patch.object(rc._runner, "execute_python", return_value={
                "status": "error", "error": "Rhino bridge down"}):
            res = base.get("rhino").op("rhino.list_layers").run()
        assert res.ok is False
        assert "bridge" in res.error.lower()

    def test_document_info_file_path_without_rhino3dm(self):
        # File path read with rhino3dm absent → clean fail, not a crash.
        import builtins
        real_import = builtins.__import__

        def no_rhino3dm(name, *a, **k):
            if name == "rhino3dm":
                raise ImportError("no rhino3dm")
            return real_import(name, *a, **k)

        with patch("builtins.__import__", side_effect=no_rhino3dm):
            res = base.get("rhino").op("rhino.document_info").run(
                file="C:/models/tower.3dm")
        assert res.ok is False
        assert "rhino3dm" in res.error


# ─────────────────────────────────────────────────────────────────────
# Cross-cutting — the base contract guarantees.
# ─────────────────────────────────────────────────────────────────────
class TestContractGuarantees:
    def test_run_op_resolves_across_registry(self):
        # base.run_op should route a host-prefixed op_id to the right
        # connector and never raise.
        with patch.object(oc._runner, "list_inbox", return_value=[]):
            res = base.run_op("outlook.list_inbox", limit=5)
        assert isinstance(res, OpResult)
        assert res.ok is True

    def test_run_op_unknown_op_is_clean_fail(self):
        res = base.run_op("blender.does_not_exist")
        assert res.ok is False
        assert "unknown op" in res.error

    def test_to_dict_serialises_every_connector(self):
        # Connector.to_dict() calls probe(); must not raise even with a
        # dead host. Patch the runners so probes resolve fast.
        with patch.object(oc._runner, "is_reachable", return_value=False), \
             patch.object(bc._runner, "ping", return_value=None), \
             patch.object(bc, "_blender_process_running",
                          return_value=False), \
             patch.object(rc._runner, "is_reachable", return_value=False):
            for host in ("outlook", "blender", "rhino"):
                d = base.get(host).to_dict()
                assert d["host"] == host
                assert d["status"] in (
                    "live", "loaded_dead", "missing", "unauthorized")
                assert isinstance(d["ops"], list) and d["ops"]
