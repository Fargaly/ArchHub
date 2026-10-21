"""Courts: the Workshop native agent turn keeps the retired signed-execution promises (plan B, GAP 1-3).

The retired clean flow also ran a worker's own turn on a Workshop task (run_workshop_task) and
published its result. The replacement is the application's native turn: the browser's
/api/universal/workshop-native prepare_native, approve_native, execute and publish. It launches
an agent process from a Workshop profile, reserves and consumes one turn, writes the returned
patch through the project artifact publisher and settles a native receipt.

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
STALE = "Workshop Work changed after this agent result; it is not published"


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


def _receipts(server):
    return sorted(root for root in server.universal_store.snapshot().cells if root.endswith(":native-receipt"))


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
        assert len(_transcript(rig.server, rig)["messages"]) == len(rows)
    finally:
        rig.server.close()


# ------------------------------------------------------------------ GAP 3 --

def test_a_native_result_whose_task_changed_before_publication_is_never_published_even_after_refresh(isolated):
    from tests_replica.test_workshop_model_turn_guarantees import _request, _revise_task, _transcript
    rig = _prepared(isolated)
    try:
        status, settled = _execute(rig)
        assert status == 200 and settled["state"] == "settled", settled
        assert settled["artifact"]["outcome"] == "succeeded"
        before = len(_transcript(rig.server, rig)["messages"])
        _revise_task(rig.server, rig.work, "A different native task, written after the result")
        first = _publish(rig)
        assert first["state"] != "published" and first["publication"] is None, first
        assert first["error"] == STALE, first
        held = rig.host._status
        assert (held["state"], held.get("publication"), held["error"]) == ("settled", None, STALE), held
        assert held["artifact"] == settled["artifact"]
        query = urlencode({"root": rig.body["root"], "scope": rig.body["scope"], "work": rig.work})
        assert _request(rig.server, "/api/universal/workshop-native?" + query)[0] == 200
        again = _publish(rig)
        assert again["state"] != "published" and again["publication"] is None, again
        assert len(_transcript(rig.server, rig)["messages"]) == before
    finally:
        rig.server.close()


# ------------------------------------------------------------------ GAP 1 --

@pytest.mark.parametrize("how", ["agent-exited", "work-reassigned"])
def test_a_native_executor_detached_after_approval_is_refused_before_any_turn(isolated, how):
    from nodelang import universal_application as app
    rig = _prepared(isolated)
    try:
        server, registry = rig.server, rig.server.universal_registry
        detached = None
        if how == "agent-exited":
            # The approved agent's process ends before its turn.
            process = rig.host._native["process"]._process
            import psutil
            for child in psutil.Process(process.pid).children(recursive=True):
                child.kill()
            process.kill()
            process.wait(timeout=30)
        else:
            # The founder assigns the same Work to a second agent before the turn.
            from tests_replica.test_workshop_model_turn_guarantees import _founder_edit
            with _founder_edit(server, "court: a second agent joins"):
                other = server._enroll_universal_machine_agent_session(
                    {"runtime": "codex", "external_session_id": "native-court-second-agent"},
                    runtime_id=server.machine_transport._descriptor("active").runtime_id)["agent_session"]
            binding = server._resolve_browser_session(server.browser_session_token)
            try:
                with server.mutation_lock, _founder_edit(server, "assign the Work to a second agent"):
                    app.assign_universal_workshop_work(server.universal_store, registry,
                        assignment_id="app:workshop-assignment:native-court-second", work_root=rig.work,
                        agent_session_root=other, authentication_context=binding.context)
            except Exception as refusal:  # noqa: BLE001 - a refused reassignment is the answer
                detached = str(refusal)
        status, refused = _execute(rig)
        assert detached is None, detached
        expected = {"agent-exited": (403, "The owned agent process could not be confirmed"),
                    "work-reassigned": (400, "Native Work requires one exact assignment to this child")}
        assert (status, refused["error"]) == expected[how], refused
        assert _turns(rig.root) == 0 and _receipts(server) == [] and _files(rig) == []
        assert _results(rig) == []
    finally:
        rig.server.close()


# ------------------------------------------------------------------ GAP 2 --

@pytest.mark.parametrize("outcome", ["succeeded", "failed"])
def test_a_native_receipt_survives_reopen_and_the_same_turn_never_runs_again(isolated, monkeypatch, outcome):
    from nodelang.native_workshop_execution import consume_native_turn, reserve_native_turn
    if outcome == "failed":
        monkeypatch.setenv("ARCHHUB_NATIVE_DOUBLE_ANSWER", "!error")
    rig = _prepared(isolated)
    try:
        server = rig.server
        status, settled = _execute(rig)
        assert status == 200 and settled["state"] == "settled", settled
        result = settled["native_result"]
        assert result["outcome"] == outcome and _turns(rig.root) == 1
        receipt_root = result["receipt"]
        files = _files(rig)
        assert files == (["native-court.patch"] if outcome == "succeeded" else [])
        written = {name: (rig.artifacts / name).read_bytes() for name in files}
        snapshot = server.universal_store.snapshot()
        held = {receipt_root: snapshot.cells[receipt_root]}
        binding = server._resolve_browser_session(server.browser_session_token)
        reservation = rig.host._native["reservation"]
        external = rig.host._native["profile"].external_session_id
        with pytest.raises(Exception, match="Native turn has already been consumed"):
            consume_native_turn(server, reservation, context=binding.context)
        # Reserving the settled delegation again is not a replay, and is refused too.
        with pytest.raises(Exception, match="adapter permission is not granted"):
            reserve_native_turn(server, delegation_root=rig.prepared["delegation"], session_root=rig.worker,
                external_session_id=external, reviewed_digest=rig.prepared["input_digest"],
                context=binding.context)
        assert _turns(rig.root) == 1
    finally:
        rig.server.close()
    successor, _, _ = _start(rig.root)
    try:
        snapshot = successor.universal_store.snapshot()
        assert {root: snapshot.cells[root] for root in held} == held
        assert _receipts(successor) == [receipt_root]
        binding = successor._resolve_browser_session(successor.browser_session_token)
        with pytest.raises(Exception, match="adapter permission is not granted"):
            reserve_native_turn(successor, delegation_root=rig.prepared["delegation"], session_root=rig.worker,
                external_session_id=external, reviewed_digest=rig.prepared["input_digest"],
                context=binding.context)
        assert _turns(rig.root) == 1
        assert _files(rig) == files and all((rig.artifacts / n).read_bytes() == b for n, b in written.items())
    finally:
        successor.close()


# ---------------------------------------------------------------- GAP 3a --

def test_a_native_task_revised_during_the_turn_is_never_published(isolated, monkeypatch):
    import threading
    import time
    from tests_replica.test_workshop_model_turn_guarantees import _revise_task, _transcript
    gate = isolated / "gate"
    monkeypatch.setenv("ARCHHUB_NATIVE_DOUBLE_GATE", str(gate))
    rig = _prepared(isolated)
    try:
        def revise_during_turn():
            deadline = time.monotonic() + 120
            while not (gate / "turn-started").exists() and time.monotonic() < deadline:
                time.sleep(0.05)
            _revise_task(rig.server, rig.work, "A different native task, written during the turn")
            (gate / "go").write_text("go", encoding="utf-8")
        reviser = threading.Thread(target=revise_during_turn)
        reviser.start()
        status, settled = _execute(rig)
        reviser.join(timeout=150)
        native = settled["native_result"]
        assert status == 200 and settled["state"] == "settled", settled
        assert (native["outcome"], native["error_code"]) == ("failed", "publication_not_admitted"), native
        assert _turns(rig.root) == 1 and _files(rig) == []
        attempt = _publish(rig)
        assert attempt == {"status": 400, "state": None, "publication": None,
                           "error": "A saved native artifact is required before publication"}, attempt
        assert _results(rig) == []
    finally:
        rig.server.close()


# ------------------------------------------------------------ GAP 3 race --

def test_a_native_task_changed_at_the_publication_boundary_is_never_published(isolated, monkeypatch):
    """Race: the Work changes after the material check, right before the announcement is sent.

    The change is injected in the publishing thread, inside the owner lock, between the
    material check and the Workshop send, so only a send bound to the checked revision refuses it.
    """
    from nodelang import existing_workshop_conversation as conversation
    from tests_replica.test_workshop_model_turn_guarantees import _revise_task
    rig = _prepared(isolated)
    try:
        status, settled = _execute(rig)
        assert status == 200 and settled["state"] == "settled", settled
        assert settled["artifact"]["outcome"] == "succeeded"
        real = conversation.send_browser_workshop
        fired = []

        def change_then_send(owner, binding, body, **kwargs):
            if not fired and "native-court.patch" in str(body.get("text", "")):
                fired.append(True)
                _revise_task(rig.server, rig.work, "A different native task, written at the publication boundary")
            return real(owner, binding, body, **kwargs)
        monkeypatch.setattr(conversation, "send_browser_workshop", change_then_send)
        attempt = _publish(rig)
        assert fired == [True]
        assert attempt["state"] != "published" and attempt["publication"] is None, attempt
        assert attempt["error"] == "Workshop changed during publication admission; refresh", attempt
        assert _results(rig) == []
        # Refused before the append: the saved artifact stays settled, nothing was announced.
        held = rig.host._status
        assert (held["state"], held.get("publication"), held["error"]) == (
            "settled", None, "Workshop changed during publication admission; refresh"), held
        assert held["artifact"] == settled["artifact"] and _files(rig) == ["native-court.patch"]
    finally:
        rig.server.close()


def test_a_native_publication_failing_after_its_append_stays_a_reconciliation_case(isolated, monkeypatch):
    """An AuthorizationDenied raised after the announcement committed is not a definite refusal."""
    from nodelang import existing_workshop_conversation as conversation
    from nodelang.cell_authorization import AuthorizationDenied
    rig = _prepared(isolated)
    try:
        status, settled = _execute(rig)
        assert status == 200 and settled["state"] == "settled", settled
        real = conversation.send_browser_workshop

        def fail_after_append(owner, binding, body, **kwargs):
            real(owner, binding, body, **kwargs)
            raise AuthorizationDenied("relay refused after the announcement was appended")
        monkeypatch.setattr(conversation, "send_browser_workshop", fail_after_append)
        _publish(rig)
        assert rig.host._status["state"] == "publication_uncertain", rig.host._status
        assert len(_results(rig)) == 1
    finally:
        rig.server.close()


# ------------------------------------------------- two publication attempts --

TWO_ATTEMPTS = ("committed-then-changed", "lost-then-changed", "committed-unchanged")


@pytest.mark.parametrize("case", TWO_ATTEMPTS)
def test_a_retry_never_erases_an_unknown_native_publication(isolated, monkeypatch, case):
    """The native announcement keeps an unknown first outcome until its own record settles it."""
    from nodelang import existing_workshop_conversation as conversation
    from nodelang.cell_authorization import AuthorizationDenied
    from tests_replica.test_workshop_model_turn_guarantees import _revise_task
    rig = _prepared(isolated)
    try:
        status, settled = _execute(rig)
        assert status == 200 and settled["state"] == "settled", settled
        real, committed = conversation.send_browser_workshop, []

        def first_attempt(owner, binding, body, **kwargs):
            if case.startswith("committed"):
                committed.append(real(owner, binding, body, **kwargs))
            raise AuthorizationDenied("relay outcome unknown")
        monkeypatch.setattr(conversation, "send_browser_workshop", first_attempt)
        _publish(rig)
        assert rig.host._status["state"] == "publication_uncertain", rig.host._status
        monkeypatch.setattr(conversation, "send_browser_workshop", real)
        if case.endswith("changed"):
            _revise_task(rig.server, rig.work, "A different native task, written between the two attempts")
        retry = _publish(rig)
        held = rig.host._status
        if case == "lost-then-changed":
            assert retry["error"] == STALE, retry
            assert held["state"] == "publication_uncertain" and "still unresolved" in held["error"], held
            assert _results(rig) == []
        else:
            assert held["state"] == "published", held
            assert held["publication"]["root"] == committed[0]["root"] and held["publication"]["reconciled"]
            assert [row["root"] for row in _results(rig)] == [committed[0]["root"]]
        assert _turns(rig.root) == 1
    finally:
        rig.server.close()
