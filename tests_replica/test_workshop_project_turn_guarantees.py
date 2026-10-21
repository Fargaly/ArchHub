"""Courts: the Workshop project operation keeps the retired signed-execution promises (plan B, GAP 1-3).

The retired clean flow executed declared host operations for a Workshop task and published the
result as a reply. Its replacement for project work is the application's project operation: the
browser's /api/universal/workshop-native prepare_project, approve_project, execute and publish, over
the one-use /api/universal/connector-delegation-grant and /api/universal/project-work-execute.
This file holds that path to the same three promises as the model turn (its own court file), on its
own physical boundary: the real ProjectWorkExecutionBroker writing into a temporary artifact
directory, with only the provider chat replaced by a recording double. Graph, machine transport,
grants, receipts, the artifact file and the Workshop publication are real, on a persistent owner.
"""
import hashlib
import json
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest

from nodelang.application_machine_transport import MachineTransportError
from nodelang.application_server import ApplicationServer
from nodelang.baboom_attach import _machine_device_key, prepare_workshop_execution_client
from nodelang.cell_value_graph import read_value_graph
from nodelang.existing_workshop_native_host import ExistingWorkshopNativeHost
from nodelang.model_router import resolve_model_route
from nodelang.project_work_execution_broker import ProjectWorkExecutionBroker
from tests_replica.test_application_machine_transport import _FounderLocalClient
from tests_replica.test_universal_workshop_assignments import _green_runtime_compliance
from tests_replica.test_workshop_model_turn_guarantees import (
    DETACHED, DETACHES, ENDPOINT, _founder_edit, _keys, _outcome, _request, _revise_task, _transcript, detach,
)
from tests_replica.workshop_gate_support import open_execution_gate

GRANT = "/api/universal/connector-delegation-grant"
EXECUTE = "/api/universal/project-work-execute"
SOURCE = "value = 1\n"
STALE = "Workshop Work changed after this project result; it is not published"
CONSUMED = "Project execution capability is invalid, expired or consumed"


class _Chat:
    """The provider chat behind the real project broker: records calls; may fail or act mid-call."""

    def __init__(self, *, fail=False, during=None):
        self.calls, self.fail, self.during = [], fail, during

    def __call__(self, model, messages, **options):
        self.calls.append(model)
        if self.during is not None:
            self.during()
        text = "not the requested JSON" if self.fail else json.dumps({
            "summary": "Name the value explicitly.",
            "edits": [{"path": "example.py", "before": SOURCE, "after": "value = 2\n"}]})
        return {"ok": True, "family": "openrouter", "model": resolve_model_route(model).model,
                "text": text, "finish_reason": "stop"}


def _start(tmp_path, keys, chat):
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir(exist_ok=True)
    server = ApplicationServer(universal_state_path=tmp_path / "application.sqlite3",
        universal_workspace_root=tmp_path, universal_key_provider=keys,
        enable_machine_transport=True, machine_descriptor_path=tmp_path / "runtime.json",
        machine_key_provider=keys, runtime_compliance_runner=_green_runtime_compliance,
        project_work_execution_broker=ProjectWorkExecutionBroker(artifacts, chat=chat),
        enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False,
        live_watch=False).start()
    server._existing_workshop_native_host = ExistingWorkshopNativeHost(server,
        state_dir=tmp_path, descriptor_path=tmp_path / "runtime.json", key_provider=keys)
    return server


def _approved(tmp_path, chat, request_id="project-turn-court"):
    """One project Work on the Workshop canvas, prepared and approved; nothing has executed."""
    keys = _keys()
    _machine_device_key(tmp_path)
    server = _start(tmp_path, keys, chat)
    founder = _FounderLocalClient(server, tmp_path / "runtime.json", keys)
    registry, store = server.universal_registry, server.universal_store
    work = founder.request("POST", "/api/universal/work", {
        "title": "Name the value", "description": "Return a public repair patch only.",
        "priority": 80, "external_key": "project-turn-court-" + request_id,
        "references": {"scope": registry.map.domains["orchestration"]},
        "structured_references": {
            "inputs": {"model": "openrouter/free", "data_class": "public-text",
                       "artifact_name": "court.patch",
                       "files": [{"path": "example.py", "content": SOURCE,
                                  "sha256": hashlib.sha256(SOURCE.encode()).hexdigest()}]},
            "requirements": {"acceptance_criteria": [{"criterion": "The value is 2",
                                                      "verification": "Inspect the patch"}]}},
        "x": 840, "y": 540})["created_root"]
    open_execution_gate(server, work, "project-turn-" + request_id)
    binding = server._resolve_browser_session(server.browser_session_token)
    from nodelang import universal_application as app
    with server.mutation_lock, _founder_edit(server, "open the Workshop workbench"):
        app.set_universal_scope(store, registry, registry.map.domains["brain"],
                                authentication_context=binding.context)
        app.set_universal_scope(store, registry, registry.workshop_workbench_root,
                                authentication_context=binding.context)
    body = dict(action="prepare_project", root=registry.workshop_root,
                scope=registry.workshop_workbench_root, work=work, request_id=request_id,
                data_class="public-text")
    status, prepared = _request(server, ENDPOINT, body)
    assert status == 200 and prepared["state"] == "awaiting_approval", prepared
    status, approved = _request(server, ENDPOINT, {**body, "action": "approve_project",
                                                   "input_digest": prepared["input_digest"]})
    assert status == 200 and approved["state"] == "awaiting_approval" and approved["approved"], approved
    host = server._existing_workshop_native_host
    return SimpleNamespace(server=server, keys=keys, chat=chat, work=work, body=body,
                           prepared=prepared, host=host, worker=host._client.agent_session_root,
                           artifacts=tmp_path / "artifacts")


def _files(rig):
    return sorted(path.name for path in rig.artifacts.iterdir())


def _repairs(server, rig):
    return [row for row in _transcript(server, rig)["messages"]
            if (row.get("body") or "").startswith("Repair artifact created:")]


def _receipts(server):
    return sorted(root for root in server.universal_store.snapshot().cells if root.endswith(":project-receipt"))


# ------------------------------------------------------------------ GAP 1 --

@pytest.mark.parametrize("how", DETACHES)
def test_a_project_executor_detached_after_its_grant_is_refused_before_any_host_call(tmp_path, how):
    chat = _Chat()
    rig = _approved(tmp_path, chat)
    try:
        wrapped, answered = detach(rig, how, rig.host._client.request, GRANT)
        rig.host._client.request = wrapped
        status, refused = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert answered["detach"]["history_root" if how == "claim-released" else "released"], answered
        assert status != 200 and DETACHED[how] in refused["error"], refused
        assert chat.calls == [] and _files(rig) == [] and _receipts(rig.server) == []
        assert _repairs(rig.server, rig) == []
    finally:
        rig.server.close()


# ------------------------------------------------------------------ GAP 2 --

@pytest.mark.parametrize("outcome", ["succeeded", "failed"])
def test_a_project_receipt_survives_reopen_and_the_same_request_never_runs_again(tmp_path, outcome):
    chat = _Chat(fail=outcome == "failed")
    rig = _approved(tmp_path, chat)
    sent = []
    try:
        real = rig.host._client.request

        def record(method, path, *args, **kwargs):
            if path == EXECUTE:
                sent.append(dict(args[0]))
            return real(method, path, *args, **kwargs)
        rig.host._client.request = record
        status, settled = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert status == 200 and settled["state"] == "settled", settled
        assert settled["artifact"]["outcome"] == outcome
        assert len(chat.calls) == 1 and len(sent) == 1
        receipt_root = settled["receipt"]
        result_root = settled["artifact"]["result"]
        files = _files(rig)
        assert files == (["court.patch"] if outcome == "succeeded" else [])
        written = {name: (rig.artifacts / name).read_bytes() for name in files}
        snapshot = rig.server.universal_store.snapshot()
        held = {root: snapshot.cells[root] for root in (receipt_root, result_root)}
        result = read_value_graph(snapshot, rig.server.universal_registry.value_graph_protocol, result_root)
        assert result["outcome"] == outcome
        with pytest.raises(MachineTransportError, match=CONSUMED):
            real("POST", EXECUTE, sent[0])
        assert len(chat.calls) == 1
    finally:
        rig.server.close()
    successor = _start(tmp_path, rig.keys, chat)
    try:
        snapshot = successor.universal_store.snapshot()
        assert {root: snapshot.cells[root] for root in held} == held
        assert read_value_graph(snapshot, successor.universal_registry.value_graph_protocol,
                                result_root) == result
        assert _receipts(successor) == [receipt_root]
        retained = []
        binding = successor._resolve_browser_session(successor.browser_session_token)
        prepare_workshop_execution_client(successor, state_dir=tmp_path,
            descriptor_path=tmp_path / "runtime.json", key_provider=rig.keys,
            external_session_id="workshop-" + rig.body["request_id"],
            authentication_context=binding.context, retain_client=retained.append)
        executor = retained[-1]
        assert executor.agent_session_root == rig.worker
        with pytest.raises(MachineTransportError, match=CONSUMED):
            executor.request("POST", EXECUTE, sent[0])
        # A new grant for the settled delegation is not a replay, and is refused too.
        with pytest.raises(MachineTransportError, match="adapter permission is not granted"):
            executor.request("POST", GRANT, {"delegation": rig.prepared["delegation"]})
        assert len(chat.calls) == 1
        assert _files(rig) == files and all((rig.artifacts / n).read_bytes() == b for n, b in written.items())
        assert successor.universal_store.snapshot().cells[receipt_root] == held[receipt_root]
    finally:
        successor.close()


# ------------------------------------------------------------------ GAP 3 --

def test_a_project_task_revised_during_the_call_is_never_published(tmp_path):
    holder = {}
    chat = _Chat(during=lambda: _revise_task(holder["server"], holder["work"],
                                             "A different project task, written during the call"))
    rig = _approved(tmp_path, chat)
    holder.update(server=rig.server, work=rig.work)
    try:
        status, settled = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert status == 200 and settled["state"] == "settled", settled
        assert settled["artifact"]["outcome"] == "failed"
        assert settled["error"] == "publication_not_admitted", settled
        assert len(chat.calls) == 1 and _files(rig) == []
        _outcome(_request(rig.server, ENDPOINT, {**rig.body, "action": "publish"}))
        bodies = [row.get("body") for row in _transcript(rig.server, rig)["messages"]]
        assert "Project repair failed: publication_not_admitted" in bodies
        assert _repairs(rig.server, rig) == [] and len(chat.calls) == 1
    finally:
        rig.server.close()


def test_a_project_result_whose_task_changed_before_publication_is_never_published_even_after_refresh(tmp_path):
    chat = _Chat()
    rig = _approved(tmp_path, chat)
    try:
        status, settled = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert status == 200 and settled["state"] == "settled", settled
        assert settled["artifact"]["outcome"] == "succeeded"
        _revise_task(rig.server, rig.work, "A different project task, written after the result")
        first = _outcome(_request(rig.server, ENDPOINT, {**rig.body, "action": "publish"}))
        assert first["state"] != "published" and first["publication"] is None, first
        assert first["error"] == STALE, first
        held = rig.host._status
        assert (held["state"], held.get("publication"), held["error"]) == ("settled", None, STALE), held
        assert held["artifact"] == settled["artifact"]
        _transcript(rig.server, rig)
        query = urlencode({"root": rig.body["root"], "scope": rig.body["scope"], "work": rig.work})
        assert _request(rig.server, ENDPOINT + "?" + query)[0] == 200
        again = _outcome(_request(rig.server, ENDPOINT, {**rig.body, "action": "publish"}))
        assert again["state"] != "published" and again["publication"] is None, again
        assert _repairs(rig.server, rig) == [] and len(chat.calls) == 1
    finally:
        rig.server.close()


# ------------------------------------------------------- positive control --

def test_an_unchanged_project_task_publishes_its_repair_exactly_once(tmp_path):
    chat = _Chat()
    rig = _approved(tmp_path, chat)
    try:
        status, settled = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert status == 200 and settled["artifact"]["outcome"] == "succeeded", settled
        before = _transcript(rig.server, rig)["messages"]
        status, published = _request(rig.server, ENDPOINT, {**rig.body, "action": "publish"})
        assert status == 200 and published["state"] == "published", _outcome((status, published))
        rows = _transcript(rig.server, rig)["messages"]
        assert len(rows) == len(before) + 1
        repairs = _repairs(rig.server, rig)
        assert [row["root"] for row in repairs] == [published["publication"]["root"]]
        repair = repairs[0]
        founder = rig.server.universal_registry.authorization.subject_root
        assert repair["sender_root"] == rig.worker
        assert repair["recipient_roots"] == [founder] and repair["reply_to_root"] is None
        assert repair["reference_roots"] == [rig.work]
        # The repair cites its receipt: the evidence the receiving append admits it against.
        assert repair["evidence_roots"] == [settled["receipt"]]
        assert "court.patch" in repair["body"] and settled["artifact"]["digest"] in repair["body"]
        revision = rig.server.universal_store.revision
        status, again = _request(rig.server, ENDPOINT, {**rig.body, "action": "publish"})
        assert status == 200 and again["publication"]["root"] == published["publication"]["root"]
        assert len(_transcript(rig.server, rig)["messages"]) == len(rows)
        assert rig.server.universal_store.revision == revision
        assert len(chat.calls) == 1 and _files(rig) == ["court.patch"]
    finally:
        rig.server.close()


# ------------------------------------------------------------ GAP 3 race --

BOUNDARY_REFUSAL = {"before-the-send": STALE,
                    "inside-the-receiving-append": "conversation authority changed; refresh"}


@pytest.mark.parametrize("boundary", sorted(BOUNDARY_REFUSAL))
def test_a_project_task_changed_at_the_publication_boundary_is_never_published(tmp_path, monkeypatch, boundary):
    """Race: the Work changes after the host's checks, at either side of the publication pipe.

    before-the-send: right before the worker's POST /api/universal/workshop leaves the host (the
    host holds no owner lock across the pipe). inside-the-receiving-append: right before the
    content append commits, after the receiving rule passed. Either way it is never published.
    """
    chat = _Chat()
    rig = _approved(tmp_path, chat)
    try:
        status, settled = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert status == 200 and settled["artifact"]["outcome"] == "succeeded", settled
        fired = []

        def change():
            fired.append(True)
            _revise_task(rig.server, rig.work, "A different project task, written at the publication boundary")
        if boundary == "before-the-send":
            real = rig.host._client.request

            def change_then_send(method, path, *args, **kwargs):
                if path == "/api/universal/workshop" and not fired and str(args[0].get("text", "")).startswith(
                        "Repair artifact created:"):
                    change()
                return real(method, path, *args, **kwargs)
            rig.host._client.request = change_then_send
        else:
            service = rig.server.conversation_content
            real = service.append_authenticated

            def change_then_append(**kwargs):
                if not fired and str(kwargs.get("content", "")).startswith("Repair artifact created:"):
                    change()
                return real(**kwargs)
            monkeypatch.setattr(service, "append_authenticated", change_then_append)
        attempt = _outcome(_request(rig.server, ENDPOINT, {**rig.body, "action": "publish"}))
        assert fired == [True]
        assert attempt["state"] != "published" and attempt["publication"] is None, attempt
        assert attempt["error"] == BOUNDARY_REFUSAL[boundary], attempt
        assert _repairs(rig.server, rig) == [] and len(chat.calls) == 1
        # A typed refusal from before the receiving commit is definite: the artifact stays settled.
        held = rig.host._status
        assert (held["state"], held.get("publication"), held["error"]) == (
            "settled", None, BOUNDARY_REFUSAL[boundary]), held
        assert held["artifact"] == settled["artifact"] and _files(rig) == ["court.patch"]
    finally:
        rig.server.close()


@pytest.mark.parametrize("failure", ["response-lost", "untyped-refusal"])
def test_a_project_publication_failing_after_its_send_stays_a_reconciliation_case(tmp_path, failure):
    """Only the typed pre-commit refusal is definite; a lost response or other error is not."""
    from nodelang.application_machine_transport import MachineResponseError, MachineTransportError
    chat = _Chat()
    rig = _approved(tmp_path, chat)
    try:
        status, settled = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert status == 200 and settled["artifact"]["outcome"] == "succeeded", settled
        real = rig.host._client.request

        def fail_after(method, path, *args, **kwargs):
            if path != "/api/universal/workshop":
                return real(method, path, *args, **kwargs)
            if failure == "response-lost":
                real(method, path, *args, **kwargs)
                raise MachineTransportError("universal runtime did not respond")
            raise MachineResponseError("an untyped refusal")
        rig.host._client.request = fail_after
        _request(rig.server, ENDPOINT, {**rig.body, "action": "publish"})
        assert rig.host._status["state"] == "publication_uncertain", rig.host._status
        assert len(_repairs(rig.server, rig)) == (1 if failure == "response-lost" else 0)
    finally:
        rig.server.close()


# ------------------------------------------------- two publication attempts --

TWO_ATTEMPTS = ("committed-then-changed", "lost-then-changed", "committed-unchanged")


@pytest.mark.parametrize("case", TWO_ATTEMPTS)
def test_a_retry_never_erases_an_unknown_project_publication(tmp_path, case):
    """Ping's repro: committed, response lost, Work revised, retry refused -> never 'nothing published'."""
    from nodelang.application_machine_transport import MachineTransportError
    chat = _Chat()
    rig = _approved(tmp_path, chat)
    try:
        status, settled = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert status == 200 and settled["artifact"]["outcome"] == "succeeded", settled
        real, committed = rig.host._client.request, []

        def first_attempt(method, path, *args, **kwargs):
            if path != "/api/universal/workshop":
                return real(method, path, *args, **kwargs)
            if case.startswith("committed"):
                committed.append(real(method, path, *args, **kwargs))
            raise MachineTransportError("universal runtime did not respond")
        rig.host._client.request = first_attempt
        _request(rig.server, ENDPOINT, {**rig.body, "action": "publish"})
        assert rig.host._status["state"] == "publication_uncertain", rig.host._status
        rig.host._client.request = real
        if case.endswith("changed"):
            _revise_task(rig.server, rig.work, "A different project task, written between the two attempts")
        retry = _outcome(_request(rig.server, ENDPOINT, {**rig.body, "action": "publish"}))
        held = rig.host._status
        if case == "lost-then-changed":
            assert retry["error"] == STALE, retry
            assert held["state"] == "publication_uncertain" and "still unresolved" in held["error"], held
            assert _repairs(rig.server, rig) == []
        else:
            assert held["state"] == "published", held
            assert held["publication"]["root"] == committed[0]["root"] and held["publication"]["reconciled"]
            assert [row["root"] for row in _repairs(rig.server, rig)] == [committed[0]["root"]]
        assert len(chat.calls) == 1
    finally:
        rig.server.close()
