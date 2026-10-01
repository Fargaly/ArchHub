"""Courts: the Workshop model turn keeps the retired signed-execution promises (plan B, GAP 1-3).

The retired clean flow (clean_agent_coordination execute_claimed_task / publish_task_result over
clean_host_execution.execute_host_operation "model.review") promised three things this file holds
its replacement to: an execution whose executor is detached is refused before any physical call;
an execution receipt survives reopen and the same request never runs again; a result is never
accepted once its task changed during execution or before its publication, refresh or not.

The replacement is the application's Workshop model turn: the browser's /api/universal/workshop-native
prepare, approval, execute and publish, over the one-use /api/universal/model-delegation-* grant.
Graph, machine transport, grants, receipts and the Workshop publication are real, on a persistent
temporary owner; only the model provider is a recorded double. Project operations and native agent
turns cross their own execution boundaries and are not covered by this file.
"""
import hashlib
import json
import re
from types import SimpleNamespace
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest

from nodelang import commit_intent
from nodelang import universal_application as app
from nodelang.application_machine_transport import MachineTransportError
from nodelang.application_server import ApplicationServer
from nodelang.baboom_attach import _machine_device_key, prepare_workshop_execution_client
from nodelang.cell_model_execution import read_model_execution_receipt
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.existing_workshop_native_host import ExistingWorkshopNativeHost
from nodelang.model_execution_broker import ModelExecutionResult
from nodelang.universal_cell import Cell
from tests_replica.recorded_model_broker import _RecordedModelBroker
from tests_replica.test_application_machine_transport import _FounderLocalClient
from tests_replica.workshop_gate_support import open_execution_gate

ENDPOINT = "/api/universal/workshop-native"
EXECUTE = "/api/universal/model-delegation-execute"
GRANT = "/api/universal/model-delegation-grant"
RECEIPT_PREFIX = "app:baboom-model-receipt:"
STALE = "Workshop Work changed after this model result; it is not published"


class _Broker(_RecordedModelBroker):
    """The provider boundary: records every physical call; may fail or act mid-call."""

    def __init__(self, *, fail=False, during=None):
        super().__init__()
        self.fail, self.during = fail, during

    def execute(self, *, free_only, reasoning_effort, max_output_tokens, **request):
        assert free_only is True and reasoning_effort == "none" and max_output_tokens == 4096
        if self.during is not None:
            self.during()
        if self.fail:
            self.calls.append(dict(request))
            return ModelExecutionResult("failed", hashlib.sha256(b"").hexdigest(), 0,
                                        "provider_unavailable", None)
        return super().execute(**request)


def _request(server, path, body=None, *, csrf=True):
    headers = {"Content-Type": "application/json",
               "Cookie": "ArchHub-Session=" + server.browser_session_token}
    if csrf:
        headers["X-ArchHub-CSRF"] = server.browser_csrf_token
    call = Request(server.url + path, method="GET" if body is None else "POST", headers=headers,
                   data=None if body is None else json.dumps(body).encode("utf-8"))
    try:
        with urlopen(call, timeout=60) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        return error.code, json.loads(error.read().decode("utf-8"))


def _start(tmp_path, keys, broker):
    server = ApplicationServer(universal_state_path=tmp_path / "application.sqlite3",
        universal_workspace_root=tmp_path, universal_key_provider=keys, enable_machine_transport=True,
        machine_descriptor_path=tmp_path / "runtime.json", machine_key_provider=keys,
        model_execution_broker=broker, enable_universal_cloud_gateway=False, live_watch=False).start()
    server._existing_workshop_native_host = ExistingWorkshopNativeHost(server,
        state_dir=tmp_path, descriptor_path=tmp_path / "runtime.json", key_provider=keys)
    return server


def _keys():
    keys = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"p" * 32)
    keys.add_key("archhub.local.relationship-authority", b"r" * 32)
    keys.add_key("archhub.local.court-attestation", b"c" * 32)
    return keys


def _founder_edit(server, reason):
    return commit_intent.declare(commit_intent.USER_ACTION,
        actor=server.universal_registry.authorization.subject_root, reason=reason)


def _approved(tmp_path, broker, request_id="model-turn-court"):
    """One Work on the Workshop canvas, prepared and approved; nothing has executed."""
    keys = _keys()
    _machine_device_key(tmp_path)
    server = _start(tmp_path, keys, broker)
    # The founder acts in process, as the desktop does (unbound pipe writes are refused).
    founder = _FounderLocalClient(server, tmp_path / "runtime.json", keys)
    registry, store = server.universal_registry, server.universal_store
    work = founder.request("POST", "/api/universal/work", {
        "title": "Review the public input", "description": "A public model-turn court.",
        "priority": 80, "external_key": "model-turn-court-" + request_id,
        "references": {"scope": registry.map.domains["orchestration"]},
        "structured_references": {"requirements": {"court": "workshop-result"},
                                  "required-capabilities": ["governance"]},
        "x": 840, "y": 540})["created_root"]
    # The founder plans the Work with captured research, as the execution gate requires.
    open_execution_gate(server, work, "model-turn-" + request_id)
    binding = server._resolve_browser_session(server.browser_session_token)
    with server.mutation_lock, _founder_edit(server, "open the Workshop workbench"):
        app.set_universal_scope(store, registry, registry.map.domains["brain"],
                                authentication_context=binding.context)
        app.set_universal_scope(store, registry, registry.workshop_workbench_root,
                                authentication_context=binding.context)
    body = dict(action="prepare", root=registry.workshop_root, scope=registry.workshop_workbench_root,
                work=work, request_id=request_id, data_class="public-text")
    status, prepared = _request(server, ENDPOINT, body)
    assert status == 200 and prepared["state"] == "awaiting_approval", prepared
    approval = {key: prepared[key] for key in ("work", "delegation", "input_digest")}
    approval.update(root=body["root"], scope=body["scope"], revision=store.revision)
    assert _request(server, "/api/universal/workshop-model-approval", approval)[0] == 200
    host = server._existing_workshop_native_host
    return SimpleNamespace(server=server, keys=keys, broker=broker, work=work, body=body,
                           prepared=prepared, host=host, worker=host._client.agent_session_root)


_RECEIPT_ROOT = re.compile(re.escape(RECEIPT_PREFIX) + r"[0-9a-f]{32}")


def _receipts(server):
    return sorted(root for root in server.universal_store.snapshot().cells if _RECEIPT_ROOT.fullmatch(root))


def _outcome(response):
    """What a publish attempt left behind, for the court's message."""
    status, page = response
    return {"status": status, "state": page.get("state"), "error": page.get("error"),
            "publication": (page.get("publication") or {}).get("root")}


def _transcript(server, rig):
    query = urlencode({"root": rig.body["root"], "scope": rig.body["scope"]})
    status, page = _request(server, "/api/universal/workshop?" + query)
    assert status == 200, page
    return page


def _published_results(server, rig):
    """Reviews shown in the Workshop as a Work's model result."""
    return [row for row in _transcript(server, rig)["messages"]
            if "Model review evidence" in (row.get("body") or "")]


def _revise_task(server, work, text):
    """The founder changes the Work's task: the accepted intent is no longer this one."""
    store, registry = server.universal_store, server.universal_registry
    target = app._governed_work_interface_target(store.snapshot(), registry, work, "title")
    title = store.snapshot().cells[target]
    with server.mutation_lock, _founder_edit(server, "revise the Work task"):
        store.commit(store.revision, replace=(Cell(title.id, title.link0, title.link1, text.encode("utf-8")),))


# ------------------------------------------------------------------ GAP 1 --

DETACHES = ("claim-released", "session-released")
DETACHED = {"claim-released": "requires the caller's claimed Work",
            "session-released": "runtime Agent Session is unknown"}
UNDELETABLE = ("this card belongs to the application and stays in the System view; "
               "only cards you placed can be deleted")


def detach(rig, how, real, grant_path):
    """Wrap the executor's client: after its grant, detach it from its Work in one named way.

    claim-released: the executor lets go of its Work. session-released: the executor's Agent
    Session ends through the native release, and its client then ignores that and sends the call
    with the released identity. Two other detaches do not exist mid-turn: deleting the Work node
    (registered Work is never a user-placed card: test_a_registered_work_node_cannot_be_deleted_mid_turn)
    and blocking the Work (an execution body's block is reserved for receipt settlement).
    """
    import time
    import uuid
    answered = {}

    def after_grant(method, path, *args, **kwargs):
        result = real(method, path, *args, **kwargs)
        if path == grant_path and not answered:
            if how == "claim-released":
                answered["detach"] = real("POST", "/api/universal/work-transition", {
                    "root": rig.work, "event": "release",
                    "evidence": "The executor detached before its physical call."})
            else:
                client = rig.host._client
                answered["detach"] = client.release_agent_session(
                    "%08x" % int(time.time()) + uuid.uuid4().hex[:24])
                # A stale client that disregards its own release, as an adversary would.
                client._agent_session_access = "full"
        return result
    return after_grant, answered


@pytest.mark.parametrize("how", DETACHES)
def test_an_executor_detached_after_its_grant_is_refused_before_any_model_call(tmp_path, how):
    broker = _Broker()
    rig = _approved(tmp_path, broker)
    try:
        wrapped, answered = detach(rig, how, rig.host._client.request, GRANT)
        rig.host._client.request = wrapped
        before = _receipts(rig.server)
        status, refused = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert answered["detach"]["history_root" if how == "claim-released" else "released"], answered
        assert status != 200 and DETACHED[how] in refused["error"], refused
        assert broker.calls == []
        assert _receipts(rig.server) == before
        assert _published_results(rig.server, rig) == []
    finally:
        rig.server.close()


def test_a_registered_work_node_cannot_be_deleted_mid_turn(tmp_path):
    """The Studio's Delete refuses a registered Work card, so no turn is detached that way."""
    broker = _Broker()
    rig = _approved(tmp_path, broker)
    try:
        revision = rig.server.universal_store.revision
        status, refused = _request(rig.server, "/api/universal/retract", {"root": rig.work})
        assert (status, refused) == (400, {"ok": False, "error": UNDELETABLE})
        assert rig.server.universal_store.revision == revision and broker.calls == []
    finally:
        rig.server.close()


# ------------------------------------------------------------------ GAP 2 --

@pytest.mark.parametrize("outcome", ["succeeded", "failed"])
def test_a_receipt_survives_reopen_and_the_same_request_never_runs_again(tmp_path, outcome):
    broker = _Broker(fail=outcome == "failed")
    rig = _approved(tmp_path, broker)
    sent = []
    try:
        real = rig.host._client.request

        def record(method, path, *args, **kwargs):
            if path == EXECUTE:
                sent.append(dict(args[0] if args else kwargs.get("body", {})))
            return real(method, path, *args, **kwargs)
        rig.host._client.request = record
        status, settled = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert status == 200 and settled["state"] == "settled", settled
        assert len(broker.calls) == 1 and len(sent) == 1
        registry = rig.server.universal_registry
        receipt_root = settled["receipt"]
        receipt = read_model_execution_receipt(rig.server.universal_store.snapshot(),
            registry.baboom_model_execution_protocol, registry.adapter_protocol, receipt_root)
        identity = (receipt.root_id, receipt.outcome, receipt.error_code, receipt.output_digest,
                    receipt.delegation_root)
        assert receipt.outcome == outcome and settled["reconciled"] is (outcome == "succeeded")
        held = rig.server.universal_store.snapshot().cells[receipt_root]
        # The same request, again, before reopen: refused, no second call.
        with pytest.raises(MachineTransportError, match="replayed"):
            real("POST", EXECUTE, sent[0])
        assert len(broker.calls) == 1
    finally:
        rig.server.close()
    successor = _start(tmp_path, rig.keys, broker)
    try:
        registry = successor.universal_registry
        snapshot = successor.universal_store.snapshot()
        assert snapshot.cells[receipt_root] == held
        again = read_model_execution_receipt(snapshot, registry.baboom_model_execution_protocol,
            registry.adapter_protocol, receipt_root)
        assert (again.root_id, again.outcome, again.error_code, again.output_digest,
                again.delegation_root) == identity
        assert _receipts(successor) == [receipt_root]
        # The same executor, re-enrolled on the reopened owner, sends the same request.
        retained = []
        binding = successor._resolve_browser_session(successor.browser_session_token)
        prepare_workshop_execution_client(successor, state_dir=tmp_path,
            descriptor_path=tmp_path / "runtime.json", key_provider=rig.keys,
            external_session_id="workshop-" + rig.body["request_id"],
            authentication_context=binding.context, cancellation_event=None,
            retain_client=retained.append)
        executor = retained[-1]
        assert executor.agent_session_root == rig.worker
        with pytest.raises(MachineTransportError, match="replayed"):
            executor.request("POST", EXECUTE, sent[0])
        # A new grant for the settled delegation is not a replay, and is refused too.
        with pytest.raises(MachineTransportError):
            executor.request("POST", GRANT, {"delegation": rig.prepared["delegation"]})
        assert len(broker.calls) == 1
        assert _receipts(successor) == [receipt_root]
        assert successor.universal_store.snapshot().cells[receipt_root] == held
    finally:
        successor.close()


# ------------------------------------------------------------------ GAP 3 --

def test_a_task_revised_during_the_model_call_is_never_accepted(tmp_path):
    holder = {}
    broker = _Broker(during=lambda: _revise_task(holder["server"], holder["work"],
                                                 "A different task, written during the call"))
    rig = _approved(tmp_path, broker)
    holder.update(server=rig.server, work=rig.work)
    try:
        status, settled = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        registry = rig.server.universal_registry
        assert len(broker.calls) == 1
        receipts = _receipts(rig.server)
        assert len(receipts) == 1
        receipt = read_model_execution_receipt(rig.server.universal_store.snapshot(),
            registry.baboom_model_execution_protocol, registry.adapter_protocol, receipts[0])
        assert receipt.outcome == "failed" and receipt.error_code == "proposal_rejected"
        assert status != 200 or settled.get("reconciled") is False, settled
        # Publishing a rejected turn announces its failure and never a review.
        _outcome(_request(rig.server, ENDPOINT, {**rig.body, "action": "publish"}))
        bodies = [row.get("body") for row in _transcript(rig.server, rig)["messages"]]
        assert "Model execution failed. Review the recorded receipt before another execution." in bodies
        assert not any("Model review evidence" in (body or "") for body in bodies)
        assert len(broker.calls) == 1
    finally:
        rig.server.close()


def test_a_result_whose_task_changed_before_publication_is_never_published_even_after_refresh(tmp_path):
    broker = _Broker()
    rig = _approved(tmp_path, broker)
    try:
        status, settled = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert status == 200 and settled["state"] == "settled" and settled["reconciled"], settled
        _revise_task(rig.server, rig.work, "A different task, written after the result")
        first = _outcome(_request(rig.server, ENDPOINT, {**rig.body, "action": "publish"}))
        assert first["state"] != "published" and first["publication"] is None, first
        assert first["error"] == STALE, first
        held = rig.host._status
        assert (held["state"], held.get("publication"), held["error"]) == ("settled", None, STALE), held
        assert _published_results(rig.server, rig) == []
        # Refresh: the page re-reads the Workshop at its new revision, then asks again.
        _transcript(rig.server, rig)
        status_query = urlencode({"root": rig.body["root"], "scope": rig.body["scope"], "work": rig.work})
        assert _request(rig.server, ENDPOINT + "?" + status_query)[0] == 200
        again = _outcome(_request(rig.server, ENDPOINT, {**rig.body, "action": "publish"}))
        assert again["state"] != "published" and again["publication"] is None, again
        assert again["error"] in (STALE, None), again
        assert _published_results(rig.server, rig) == []
        assert len(broker.calls) == 1
    finally:
        rig.server.close()


# ------------------------------------------------------- positive control --

def test_an_unchanged_approved_task_publishes_its_review_exactly_once(tmp_path):
    """The task-digest gate refuses only a changed task: an unchanged one publishes once."""
    broker = _Broker()
    rig = _approved(tmp_path, broker)
    try:
        status, settled = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert status == 200 and settled["state"] == "settled" and settled["reconciled"], settled
        before = _transcript(rig.server, rig)["messages"]
        status, published = _request(rig.server, ENDPOINT, {**rig.body, "action": "publish"})
        assert status == 200 and published["state"] == "published", _outcome((status, published))
        rows = _transcript(rig.server, rig)["messages"]
        publication = published["publication"]
        assert publication["storage"] == "conversation-content"
        assert len(rows) == len(before) + 1
        reviews = _published_results(rig.server, rig)
        assert [row["root"] for row in reviews] == [publication["root"]]
        review = reviews[0]
        founder = rig.server.universal_registry.authorization.subject_root
        assert review["sender_root"] == rig.worker
        assert review["recipient_roots"] == [founder] and review["reply_to_root"] is None
        assert review["reference_roots"] == [rig.work]
        assert review["evidence_roots"] == [settled["receipt"], settled["proposal"]]
        # Replays: the browser's publish again, and the worker's own publish of the same result.
        revision = rig.server.universal_store.revision
        status, again = _request(rig.server, ENDPOINT, {**rig.body, "action": "publish"})
        assert status == 200 and again["publication"]["root"] == publication["root"]
        direct = rig.host._worker.publish_result(rig.host._settled, recipient_root=founder)
        assert direct["root"] == publication["root"]
        assert len(_transcript(rig.server, rig)["messages"]) == len(rows)
        assert rig.server.universal_store.revision == revision
        assert len(broker.calls) == 1
    finally:
        rig.server.close()


def test_a_review_published_as_a_reply_names_the_message_it_answers_exactly_once(tmp_path):
    """Non-null reply: the review answers a real founder message and names it."""
    broker = _Broker()
    rig = _approved(tmp_path, broker)
    try:
        status, settled = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert status == 200 and settled["state"] == "settled" and settled["reconciled"], settled
        status, asked = _request(rig.server, "/api/universal/workshop", {
            "root": rig.body["root"], "scope": rig.body["scope"], "category": "note",
            "text": "Please review the public input.", "refs": [], "evidence": [],
            "recipients": [rig.worker], "reply_to": None, "idempotency_key": "founder-asks-for-review",
            "created_at": None})
        assert status == 200, asked
        founder = rig.server.universal_registry.authorization.subject_root
        rows = _transcript(rig.server, rig)["messages"]
        published = rig.host._worker.publish_result(rig.host._settled, recipient_root=founder,
                                                    reply_to_root=asked["root"])
        after = _transcript(rig.server, rig)["messages"]
        assert len(after) == len(rows) + 1
        reply = next(row for row in after if row["root"] == published["root"])
        assert reply["reply_to_root"] == asked["root"]
        assert reply["sender_root"] == rig.worker and reply["recipient_roots"] == [founder]
        assert reply["evidence_roots"] == [settled["receipt"], settled["proposal"]]
        assert reply["body"].startswith("Model review evidence.")
        revision = rig.server.universal_store.revision
        again = rig.host._worker.publish_result(rig.host._settled, recipient_root=founder,
                                                reply_to_root=asked["root"])
        assert again["root"] == published["root"]
        assert len(_transcript(rig.server, rig)["messages"]) == len(after)
        assert rig.server.universal_store.revision == revision and len(broker.calls) == 1
    finally:
        rig.server.close()


# ------------------------------------------------------------ GAP 3 race --

def test_a_task_changed_at_the_publication_boundary_is_refused_atomically(tmp_path, monkeypatch):
    """Race: the Work changes after every pre-publication check, at the append itself.

    The change is injected in the publishing thread immediately before the Workshop append,
    after the task digest was verified, so only an append bound to the verified revision
    (a compare-and-set) can refuse it.
    """
    broker = _Broker()
    rig = _approved(tmp_path, broker)
    try:
        status, settled = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert status == 200 and settled["state"] == "settled" and settled["reconciled"], settled
        real = app.append_universal_workshop_entry
        fired = []

        def change_then_append(store, registry, **kwargs):
            if not fired and str(kwargs.get("content", "")).startswith("Model review evidence"):
                fired.append(True)
                _revise_task(rig.server, rig.work, "A different task, written at the publication boundary")
            return real(store, registry, **kwargs)
        monkeypatch.setattr(app, "append_universal_workshop_entry", change_then_append)
        attempt = _outcome(_request(rig.server, ENDPOINT, {**rig.body, "action": "publish"}))
        assert fired == [True]
        assert attempt["state"] != "published" and attempt["publication"] is None, attempt
        assert attempt["error"] == "Workshop admission changed; refresh to continue", attempt
        assert _published_results(rig.server, rig) == [] and len(broker.calls) == 1
        # A refusal before the append is definite: the host keeps its settled receipt.
        held = rig.host._status
        assert (held["state"], held.get("publication"), held["error"]) == (
            "settled", None, "Workshop admission changed; refresh to continue"), held
        assert held["receipt"] == settled["receipt"]
    finally:
        rig.server.close()


def test_a_model_publication_failing_after_its_append_stays_a_reconciliation_case(tmp_path):
    """Only a refusal before the append is definite; a failure after it is not."""
    from nodelang.application_machine_transport import MachineResponseError
    broker = _Broker()
    rig = _approved(tmp_path, broker)
    try:
        status, settled = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert status == 200 and settled["reconciled"], settled
        real = rig.host._worker.publish_result

        def lost_after_append(*args, **kwargs):
            real(*args, **kwargs)
            raise MachineResponseError("publication response lost after its append")
        rig.host._worker.publish_result = lost_after_append
        _request(rig.server, ENDPOINT, {**rig.body, "action": "publish"})
        assert rig.host._status["state"] == "publication_uncertain", rig.host._status
        assert len(_published_results(rig.server, rig)) == 1 and len(broker.calls) == 1
    finally:
        rig.server.close()


# ------------------------------------------------- two publication attempts --

TWO_ATTEMPTS = ("committed-then-changed", "lost-then-changed", "committed-unchanged")


@pytest.mark.parametrize("case", TWO_ATTEMPTS)
def test_a_retry_never_erases_an_unknown_model_publication(tmp_path, case):
    """A first attempt with an unknown outcome stays unknown until its own record settles it."""
    from nodelang.application_machine_transport import MachineResponseError, MachineTransportError
    broker = _Broker()
    rig = _approved(tmp_path, broker)
    try:
        status, settled = _request(rig.server, ENDPOINT, {**rig.body, "action": "execute"})
        assert status == 200 and settled["reconciled"], settled
        real, committed = rig.host._worker.publish_result, []

        def first_attempt(*args, **kwargs):
            if case.startswith("committed"):
                committed.append(real(*args, **kwargs))
                raise MachineResponseError("publication response lost after its append")
            raise MachineTransportError("universal runtime did not respond")
        rig.host._worker.publish_result = first_attempt
        _request(rig.server, ENDPOINT, {**rig.body, "action": "publish"})
        assert rig.host._status["state"] == "publication_uncertain", rig.host._status
        rig.host._worker.publish_result = real
        if case.endswith("changed"):
            _revise_task(rig.server, rig.work, "A different task, written between the two attempts")
        retry = _outcome(_request(rig.server, ENDPOINT, {**rig.body, "action": "publish"}))
        held = rig.host._status
        if case == "lost-then-changed":
            # Refused before any effect, but the first attempt is still unresolved.
            assert retry["error"] == STALE, retry
            assert held["state"] == "publication_uncertain" and "still unresolved" in held["error"], held
            assert _published_results(rig.server, rig) == []
        else:
            # The first attempt's own record settles it: published, with its original identity.
            assert held["state"] == "published", held
            assert held["publication"]["root"] == committed[0]["root"] and held["publication"]["reconciled"]
            assert [row["root"] for row in _published_results(rig.server, rig)] == [committed[0]["root"]]
        assert len(broker.calls) == 1
    finally:
        rig.server.close()
