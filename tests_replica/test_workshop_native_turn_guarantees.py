"""Court: a native Workshop agent turn runs end to end on the application's real path.

The browser's /api/universal/workshop-native prepare_native, approve_native, execute and publish
launch an agent process from a Workshop profile, reserve and consume one turn, write the returned
patch through the project artifact publisher, settle a native receipt and announce it once.

Only the model loop is a double (tests_replica/native_workshop_agent_double.py), launched with
the profile's exact argv and environment in place of the Claude CLI. The profile's own MCP server
is real and enrolls over the application's real machine pipe as that process's descendant; process
custody, assignment, reservation, artifact publication, receipts and the Workshop publication are
real, on a persistent owner. The whole run is confined to the test's temporary directory:
LOCALAPPDATA, APPDATA, USERPROFILE and CLAUDE_CONFIG_DIR all point into it, so the descriptor,
the DPAPI key file and any settings the profile reads are the court's own, never the user's.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from tests_replica.recorded_model_broker import _RecordedModelBroker

HERE = Path(__file__).resolve().parent
DOUBLE = HERE / "native_workshop_agent_double.py"
SOURCE = "value = 1\n"
REPAIR = json.dumps({"summary": "Name the value explicitly.",
                     "edits": [{"path": "example.py", "before": SOURCE, "after": "value = 2\n"}]})


def _values():
    return {"inputs": {"runtime": "claude", "model": "sonnet", "data_class": "public-text",
        "files": [{"path": "example.py", "content": SOURCE,
                   "sha256": hashlib.sha256(SOURCE.encode()).hexdigest()}],
        "artifact_name": "native-court.patch", "limits": {
            "max_turns": 8, "max_processes": 16, "max_input_bytes": 262144,
            "max_output_bytes": 262144, "max_event_bytes": 131072, "max_events": 64,
            "max_process_bytes": 2 * 1024**3, "startup_timeout_seconds": 90,
            "turn_timeout_seconds": 120, "lifetime_seconds": 300, "stop_timeout_seconds": 20}},
        "requirements": {"acceptance_criteria": [{"criterion": "The value is 2",
                                                  "verification": "Inspect the patch"}]}}


class _Broker(_RecordedModelBroker):
    """No model call is expected on this path; the native executable is the launched double."""

    def _executable(self, location):
        assert location == "local-cli:claude"
        return sys.executable


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    """Every path the owner, the profile and the MCP child resolve lies inside tmp_path."""
    for name in ("appdata", "localappdata", "home", "claude-config", "gate"):
        (tmp_path / name).mkdir()
    for key in list(os.environ):
        if key.upper().startswith(("ARCHHUB_", "SESSION_LINK", "CODEX", "CLAUDE_CODE", "ANTHROPIC_")):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-config"))
    monkeypatch.setenv("ARCHHUB_NATIVE_DOUBLE_ANSWER", REPAIR)
    monkeypatch.setenv("ARCHHUB_NATIVE_DOUBLE_TURNS", str(tmp_path / "turns.log"))
    import psutil
    monkeypatch.setattr(psutil, "virtual_memory",
                        lambda: SimpleNamespace(available=16 * 1024**3, total=32 * 1024**3))
    from nodelang import native_workshop_process as process_module
    real = process_module.NativeWorkshopProcess

    class Launched(real):
        def __init__(self, launch, **options):
            def launch_double(argv, **popen):
                return subprocess.Popen([sys.executable, str(DOUBLE), *argv[1:]], **popen)
            super().__init__(launch, launch_factory=launch_double, **options)
    monkeypatch.setattr(process_module, "NativeWorkshopProcess", Launched)
    return tmp_path


def _start(root):
    from nodelang.application_machine_transport import default_runtime_descriptor_path
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import WindowsDpapiSigningKeyProvider
    from nodelang.existing_workshop_native_host import ExistingWorkshopNativeHost
    from nodelang.project_work_execution_broker import ProjectWorkExecutionBroker
    from tests_replica.test_universal_workshop_assignments import _green_runtime_compliance
    from tests_replica.test_workshop_model_turn_guarantees import _keys
    descriptor = default_runtime_descriptor_path()
    keys_path = WindowsDpapiSigningKeyProvider.default_path()
    assert root in descriptor.parents and root in keys_path.parents
    machine_keys = WindowsDpapiSigningKeyProvider(keys_path)
    artifacts = root / "artifacts"
    artifacts.mkdir(exist_ok=True)

    def no_provider(*args, **kwargs):
        raise AssertionError("a native turn never calls the project provider")
    server = ApplicationServer(universal_state_path=root / "application.sqlite3",
        universal_workspace_root=root, universal_key_provider=_keys(),
        enable_machine_transport=True, machine_descriptor_path=descriptor,
        machine_key_provider=machine_keys, model_execution_broker=_Broker(),
        project_work_execution_broker=ProjectWorkExecutionBroker(artifacts, chat=no_provider),
        runtime_compliance_runner=_green_runtime_compliance, enable_universal_cloud_gateway=False,
        enable_machine_projection_prewarm=False, live_watch=False).start()
    server._existing_workshop_native_host = ExistingWorkshopNativeHost(server,
        state_dir=root, descriptor_path=descriptor, key_provider=machine_keys)
    return server, machine_keys, descriptor


def _prepared(root, request_id="native-turn-court"):
    """One native Work on the Workshop canvas, its agent launched and assigned, then approved."""
    from nodelang import universal_application as app
    from tests_replica.test_application_machine_transport import _FounderLocalClient
    from tests_replica.test_workshop_model_turn_guarantees import _founder_edit, _request
    server, machine_keys, descriptor = _start(root)
    founder = _FounderLocalClient(server, descriptor, machine_keys)
    registry, store = server.universal_registry, server.universal_store
    work = founder.request("POST", "/api/universal/work", {
        "title": "Name the value", "description": "Return a public repair patch only.",
        "priority": 80, "external_key": "native-turn-court-" + request_id,
        "references": {"scope": registry.map.domains["orchestration"]},
        "structured_references": _values(), "x": 840, "y": 540})["created_root"]
    binding = server._resolve_browser_session(server.browser_session_token)
    with server.mutation_lock, _founder_edit(server, "open the Workshop workbench"):
        app.set_universal_scope(store, registry, registry.map.domains["brain"],
                                authentication_context=binding.context)
        app.set_universal_scope(store, registry, registry.workshop_workbench_root,
                                authentication_context=binding.context)
    body = dict(action="prepare_native", root=registry.workshop_root,
                scope=registry.workshop_workbench_root, work=work, request_id=request_id,
                data_class="public-text")
    status, prepared = _request(server, "/api/universal/workshop-native", body)
    assert status == 200 and prepared["state"] == "awaiting_approval", prepared
    status, approved = _request(server, "/api/universal/workshop-native", {**body, "action": "approve_native",
                                "input_digest": prepared["input_digest"]})
    assert status == 200 and approved["state"] == "awaiting_approval" and approved["approved"], approved
    host = server._existing_workshop_native_host
    return SimpleNamespace(server=server, work=work, body=body, prepared=prepared, host=host,
                           worker=prepared["worker"], artifacts=root / "artifacts", root=root)


def _turns(root):
    log = root / "turns.log"
    return len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0


def _files(rig):
    return sorted(path.name for path in rig.artifacts.iterdir())


def _results(rig):
    from tests_replica.test_workshop_model_turn_guarantees import _transcript
    return [row for row in _transcript(rig.server, rig)["messages"]
            if "native-court.patch" in (row.get("body") or "")
            and not (row.get("body") or "").lower().startswith(("preparing", "claimed"))]


def _execute(rig):
    from tests_replica.test_workshop_model_turn_guarantees import _request
    return _request(rig.server, "/api/universal/workshop-native", {**rig.body, "action": "execute"})


def _publish(rig):
    from tests_replica.test_workshop_model_turn_guarantees import _outcome, _request
    return _outcome(_request(rig.server, "/api/universal/workshop-native", {**rig.body, "action": "publish"}))


# ------------------------------------------------------- positive control --

def test_an_unchanged_native_task_publishes_its_artifact_exactly_once(isolated):
    from tests_replica.test_workshop_model_turn_guarantees import _transcript
    rig = _prepared(isolated)
    try:
        status, settled = _execute(rig)
        assert status == 200 and settled["state"] == "settled", settled
        assert settled["artifact"]["outcome"] == "succeeded" and _files(rig) == ["native-court.patch"]
        assert _turns(rig.root) == 1
        before = _transcript(rig.server, rig)["messages"]
        published = _publish(rig)
        assert published["state"] == "published" and published["publication"], published
        rows = _transcript(rig.server, rig)["messages"]
        assert len(rows) == len(before) + 1
        row = next(item for item in rows if item["root"] == published["publication"])
        founder = rig.server.universal_registry.authorization.subject_root
        # The founder's own host announces the saved artifact (a browser send, no refs).
        assert row["sender_root"] == founder and row["recipient_roots"] == [founder]
        assert row["reply_to_root"] is None and row["reference_roots"] == []
        assert row["body"].startswith("Workshop saved a draft artifact: native-court.patch")
        assert _results(rig) == [row]
        again = _publish(rig)
        assert again["publication"] == published["publication"]
        assert len(_transcript(rig.server, rig)["messages"]) == len(rows) and _turns(rig.root) == 1
    finally:
        rig.server.close()
