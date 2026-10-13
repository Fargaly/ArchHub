from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import replace
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from tests_replica.test_clean_server_admission import (
    _issue_clean_session,
    _provision_clean_runtime,
    _start_clean_server,
)


def _install_revit_probe(authority, caller):
    from nodelang.clean_host_operations import (
        compose_host_operations,
        install_host_operations,
    )

    install_host_operations(
        authority,
        compose_host_operations([{
            "op_id": "revit.probe",
            "host": "revit",
            "kind": "read",
            "label": "Probe",
            "description": "Probe Revit",
            "output_type": "row",
            "destructive": False,
            "inputs": [],
        }]),
        caller=caller,
        command_id=str(uuid.uuid4()),
    )


def _post(server, path, payload, *, token="host-token", csrf="host-csrf"):
    headers = {
        "Content-Type": "application/json",
        "X-ArchHub-Session": token,
    }
    if csrf is not None:
        headers["X-ArchHub-CSRF"] = csrf
    request = Request(
        server.url + path,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def _get(server, path, *, token="host-token"):
    request = Request(
        server.url + path,
        headers={"X-ArchHub-Session": token},
        method="GET",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def _host_rows():
    return [
        {
            "id": "revit",
            "name": "Revit",
            "drive": "revit.probe",
            "state": "connected",
            "detail": "fake session",
        },
        {
            "id": "blender",
            "name": "Blender",
            "drive": "blender.exec",
            "state": "absent",
            "detail": "fake absent",
        },
    ]


def test_disabled_host_refuses_before_transport_and_reenabled_calls_transport(tmp_path):
    from nodelang.clean_host_execution import (
        HostOperationRefused,
        execute_host_operation,
    )
    from nodelang.host_enable import set_host_enabled

    built, _provider = _provision_clean_runtime(tmp_path, root_name="host-enable-dispatch")
    authority = built.location.authority
    _install_revit_probe(authority, built.caller)

    set_host_enabled(authority, "revit", False, name="Revit",
                     caller=built.caller, command_id=str(uuid.uuid4()))
    calls = []
    with pytest.raises(HostOperationRefused, match="Revit is turned off in Settings . Connectors."):
        execute_host_operation(
            authority,
            "revit.probe",
            {},
            caller=built.caller,
            command_id=str(uuid.uuid4()),
            invoker=lambda op, args: calls.append((op, dict(args))) or {"ok": True},
        )
    assert calls == []

    set_host_enabled(authority, "revit", True, name="Revit",
                     caller=built.caller, command_id=str(uuid.uuid4()))
    execute_host_operation(
        authority,
        "revit.probe",
        {},
        caller=built.caller,
        command_id=str(uuid.uuid4()),
        invoker=lambda op, args: calls.append((op, dict(args))) or {"ok": True},
    )
    assert calls == [("revit.probe", {})]


def test_disabling_host_does_not_kill_running_operation_and_refuses_next(tmp_path):
    from nodelang.clean_host_execution import (
        HostOperationRefused,
        execute_host_operation,
    )
    from nodelang.host_enable import set_host_enabled

    built, _provider = _provision_clean_runtime(tmp_path, root_name="host-enable-running")
    authority = built.location.authority
    _install_revit_probe(authority, built.caller)
    started = threading.Event()
    release = threading.Event()
    finished = []

    def invoker(op_id, args):
        started.set()
        assert release.wait(10), "operation release timed out"
        return {"ok": True, "operation": op_id, "arguments": dict(args)}

    thread = threading.Thread(
        target=lambda: finished.append(execute_host_operation(
            authority, "revit.probe", {}, caller=built.caller,
            command_id=str(uuid.uuid4()), invoker=invoker)),
        daemon=True,
    )
    thread.start()
    assert started.wait(10), "operation did not reach the host"
    set_host_enabled(authority, "revit", False, name="Revit",
                     caller=built.caller, command_id=str(uuid.uuid4()))
    calls = []
    with pytest.raises(HostOperationRefused, match="Revit is turned off"):
        execute_host_operation(
            authority, "revit.probe", {}, caller=built.caller,
            command_id=str(uuid.uuid4()),
            invoker=lambda op, args: calls.append((op, args)) or {"ok": True},
        )
    release.set()
    thread.join(10)
    assert not thread.is_alive()
    assert calls == []
    assert len(finished) == 1 and finished[0].replayed is False


def test_host_enabled_parameter_survives_reopen(tmp_path):
    from nodelang.host_enable import authority_host_enabled, set_host_enabled

    built, provider = _provision_clean_runtime(tmp_path, root_name="host-enable-reopen")
    authority = built.location.authority
    set_host_enabled(authority, "blender", False, name="Blender",
                     caller=built.caller, command_id=str(uuid.uuid4()))
    authority.store.close()

    reopened, _provider = _provision_clean_runtime(
        tmp_path,
        root_name="host-enable-reopen",
    )
    assert authority_host_enabled(reopened.location.authority, "blender") is False
    reopened.location.authority.store.close()


def test_tools_and_post_return_enabled_and_refuse_unknown_host(tmp_path):
    from nodelang.host_enable import set_host_enabled

    built, provider = _provision_clean_runtime(tmp_path, root_name="host-enable-route")
    server = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
        private_root_grants_path=tmp_path / "private-root-grants.json",
    )
    try:
        _issue_clean_session(built, token="host-token", csrf="host-csrf")
        server._probe_caches = {"hosts": [time.time(), _host_rows(), False]}
        set_host_enabled(built.location.authority, "revit", False, name="Revit",
                         caller=built.caller, command_id=str(uuid.uuid4()))

        from nodelang.host_enable import annotate_host_rows
        from nodelang.tool_hub import project_tools
        tools = project_tools(host_rows=annotate_host_rows(built.location.authority, _host_rows()))
        connectors = next(row for row in tools["tools"] if row["id"] == "connectors")
        assert connectors["hosts"][0]["id"] == "revit"
        assert connectors["hosts"][0]["enabled"] is False

        status, changed = _post(server, "/api/universal/host-enabled", {
            "host_id": "revit",
            "enabled": True,
        })
        assert status == 200, changed
        assert changed["host"]["id"] == "revit"
        assert changed["host"]["enabled"] is True

        status, refused = _post(server, "/api/universal/host-enabled", {
            "host_id": "paint",
            "enabled": False,
        })
        assert status == 400
        assert "unknown host id" in refused["error"]
    finally:
        server.close()


def test_clean_host_enabled_post_denials_do_not_change_revision(tmp_path, monkeypatch):
    built, provider = _provision_clean_runtime(tmp_path, root_name="host-enable-auth")
    server = _start_clean_server(
        built,
        provider,
        scope_root=built.grand_map.root_id,
        private_root_grants_path=tmp_path / "private-root-grants.json",
    )
    try:
        _issue_clean_session(built, token="host-token", csrf="host-csrf")
        server._probe_caches = {"hosts": [time.time(), _host_rows(), False]}
        revision = built.location.authority.store.revision
        payload = {"host_id": "revit", "enabled": False}

        for token, csrf in (
            ("wrong-token", "host-csrf"),
            ("host-token", None),
            ("host-token", "foreign-csrf"),
        ):
            status, answer = _post(
                server, "/api/universal/host-enabled", payload,
                token=token, csrf=csrf,
            )
            assert status == 403, answer
            assert built.location.authority.store.revision == revision

        monkeypatch.setattr(
            server,
            "_resolve_binding",
            lambda *args, **kwargs: SimpleNamespace(subject_root="foreign-owner"),
        )
        status, answer = _post(server, "/api/universal/host-enabled", payload)
        assert status == 403, answer
        assert "only this instance owner" in answer["error"]
        assert built.location.authority.store.revision == revision
    finally:
        server.close()


def _universal_post(server, path, payload, *, token=None, csrf=None):
    headers = {
        "Content-Type": "application/json",
        "Cookie": "ArchHub-Session=" + (token or server.browser_session_token),
    }
    if csrf is not None:
        headers["X-ArchHub-CSRF"] = csrf
    request = Request(
        server.url + path,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def test_universal_host_enabled_post_is_owner_only_and_read_only_on_denial(tmp_path, monkeypatch):
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider

    provider = MemorySigningKeyProvider("archhub.local.relationship-authority", b"h" * 32)
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    server = ApplicationServer(
        universal_state_path=tmp_path / "universal-host-enable.sqlite3",
        universal_key_provider=provider,
        universal_workspace_root=tmp_path,
        enable_machine_transport=False,
        enable_universal_cloud_gateway=False,
        live_watch=False,
    ).start()
    try:
        owner_binding = server._resolve_browser_session(server.browser_session_token)
        monkeypatch.setattr(
            server,
            "_resolve_browser_session",
            lambda *args, **kwargs: replace(owner_binding, subject_root="foreign-owner"),
        )
        revision = server.universal_store.revision
        status, answer = _universal_post(
            server,
            "/api/universal/host-enabled",
            {"host_id": "revit", "enabled": False},
            csrf=server.browser_csrf_token,
        )
        assert status == 403, answer
        assert "only this instance owner" in answer["error"]
        assert server.universal_store.revision == revision
    finally:
        server.close()


def test_host_catalogue_operations_all_pass_through_one_enabled_gate(tmp_path):
    from nodelang.clean_host_execution import (
        HostOperationRefused,
        execute_host_operation,
    )
    from nodelang.clean_host_operations import (
        compose_host_operations,
        install_host_operations,
        read_host_operations,
    )
    from nodelang.host_enable import canonical_host_id, host_node_root, set_host_enabled

    built, _provider = _provision_clean_runtime(tmp_path, root_name="host-enable-audit")
    authority = built.location.authority
    records = [
        {"op_id": "revit.probe", "host": "revit"},
        {"op_id": "cad.host_lines", "host": "acad"},
        {"op_id": "autocad.export", "host": "autocad"},
        {"op_id": "rhino.mesh", "host": "rhino"},
        {"op_id": "blender.render", "host": "blender"},
    ]
    install_host_operations(
        authority,
        compose_host_operations([
            {
                **record,
                "kind": "read",
                "label": record["op_id"],
                "description": record["op_id"],
                "output_type": "row",
                "destructive": False,
                "inputs": [],
            }
            for record in records
        ]),
        caller=built.caller,
        command_id=str(uuid.uuid4()),
    )
    catalogue = read_host_operations(authority, caller=built.caller)
    assert catalogue is not None
    assert host_node_root("acad") == host_node_root("autocad")
    assert canonical_host_id("known-autocad") == canonical_host_id("acad")
    by_host = {}
    for operation in catalogue["operations"]:
        by_host.setdefault(canonical_host_id(operation["host"]), []).append(operation["op_id"])
    calls = []
    for host_id, operation_ids in by_host.items():
        set_host_enabled(authority, host_id, False, name=host_id,
                         caller=built.caller, command_id=str(uuid.uuid4()))
        for op_id in operation_ids:
            with pytest.raises(HostOperationRefused, match="turned off"):
                execute_host_operation(
                    authority, op_id, {}, caller=built.caller,
                    command_id=str(uuid.uuid4()),
                    invoker=lambda op, args: calls.append((op, args)) or {"ok": True},
                )
    assert calls == []
