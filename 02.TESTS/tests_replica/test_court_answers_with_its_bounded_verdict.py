"""Court: the court's answer is a bounded verdict, and a lost one is settled only by proof (live 717, 2026-09-30).

717 attached b199ed22 and ran native.work_request_court. The court ran and
returned the Work, but the caller got "machine response exceeds its size limit":
the court answered with the whole registry status, larger than the machine
response cap on the founder's graph. The verdict was lost, the Work showed only
as CLAIMED, and the tool's latch stayed pending with no way to learn why. The
court also recorded only the exception class ("ValueError") of the gate that
could not run.

Now the court answers with a bounded receipt: this Work's row and the court's
own verdict (result, checks, details with the gate's message). Before a court
runs, the Work tool pins the exact submission it judges. A lost reply is settled
only by the exact verdict committed on that submission, or by a request the
application answered (it has terminated) that committed none. Silence settles
nothing and nothing is repeated (Ping, 2026-09-30).

Real application server, real native owner, real court. Only lost, late or
refused requests are injected.
"""
import json

import pytest

from nodelang import native_agent_mcp as mcp
from nodelang.application_machine_transport import (
    MachineResponseError, MachineTransportError, UniversalRuntimeClient,
)
from nodelang.application_server import ApplicationServer
from nodelang.native_agent_session import NativeAgentSession
from tests_replica.test_native_work_task_attach import KEY, _call
from tests_replica.test_universal_work_completion_court import _InProcessOwner, _green_runtime_compliance

CAP = 256 * 1024
MISSING = {"gate": {"kind": "pytest", "spec": {"path": "no_such_court_test.py"}}}


@pytest.fixture
def rig(tmp_path):
    (tmp_path / "ws").mkdir()
    app = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=tmp_path / "runtime.json",
                            machine_key_provider=KEY, universal_workspace_root=tmp_path / "ws",
                            universal_state_path=tmp_path / "graph.sqlite3",
                            runtime_compliance_runner=_green_runtime_compliance).start()
    try:
        native = NativeAgentSession(environment={"CLAUDE_CODE_SESSION_ID": "bounded-court"},
                                    descriptor_path=tmp_path / "runtime.json", key_provider=KEY)
        yield _InProcessOwner(app), native, mcp.build_server(session=native)
    finally:
        app.close()


def _work(owner, title, *, description="bounded court"):
    return owner.request("POST", "/api/universal/work", {
        "title": title, "description": description, "priority": 100, "x": 720, "y": 480,
        "structured_references": {"requirements": MISSING,
                                  "cde-container": {"container_id": "court-test", "allowed_paths": ["."]}},
    })["created_root"]


def _submitted(server, root, evidence="bounded court evidence"):
    _call(server, "native.work_task_attach", work_root=root)
    _call(server, "native.work_claim")
    _call(server, "native.work_submit", evidence=evidence)


def _refused_gate(verdict):
    assert verdict["result"] == "fail" and verdict["checks"]["gate-execution"] is False
    assert verdict["checks"]["gate-schema"] is True
    # The gate's message, not only its class.
    assert verdict["details"]["gate"].startswith("ValueError: pytest target is missing")


def _lose_reply_after_answer(monkeypatch):
    original = UniversalRuntimeClient.adjudicate_work

    def lost(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise MachineTransportError("injected court reply loss after the application answered")

    monkeypatch.setattr(UniversalRuntimeClient, "adjudicate_work", lost)
    return original


def test_a_large_registry_still_answers_the_court_with_its_verdict(rig):
    owner, _native, server = rig
    for index in range(40):
        _work(owner, "Padding Work %02d" % index, description="padding " * 1200)
    root = _work(owner, "Court on a large registry")
    status = owner.request("GET", "/api/universal/work", {})
    assert len(json.dumps(status)) > CAP          # the whole registry is larger than one answer
    _submitted(server, root, evidence="large submission " * 3500)

    court = _call(server, "native.work_request_court")
    assert (court["work_root"], court["passed"], court["event"], court["state"]) == (root, False, "return", "claimed")
    _refused_gate(court["verdict"])
    assert court["verdict"]["attestation_root"] == court["attestation_root"]
    assert len(json.dumps(court)) < 16 * 1024                 # bounded, whatever the registry holds


def test_a_lost_court_reply_is_settled_by_the_exact_verdict(rig, monkeypatch):
    owner, _native, server = rig
    root = _work(owner, "Court whose reply is lost")
    _submitted(server, root)
    original = _lose_reply_after_answer(monkeypatch)
    with pytest.raises(MachineTransportError, match="injected court reply loss"):
        _call(server, "native.work_request_court")
    monkeypatch.setattr(UniversalRuntimeClient, "adjudicate_work", original)
    with pytest.raises(MachineTransportError, match="unresolved"):
        _call(server, "native.work_task_detach")

    reconciled = _call(server, "native.work_reconcile")
    recovery = reconciled["court_recovery"]
    assert reconciled["reconciled"] is True and reconciled["pending_operation"] is None
    assert (recovery["decided"], recovery["event"], recovery["passed"]) == (True, "return", False)
    assert recovery["verdict"]["submit_event"] == recovery["submit_event"]
    _refused_gate(recovery["verdict"])
    again = _call(server, "native.work_reconcile")
    assert again["reconciled"] is True and "court_recovery" not in again
    assert _call(server, "native.work_task_detach")["work_root"] == root


def test_a_court_request_that_lands_late_is_settled_only_when_it_lands(rig, monkeypatch):
    owner, native, server = rig
    root = _work(owner, "Court that lands after the first read")
    _submitted(server, root)
    original = UniversalRuntimeClient.adjudicate_work
    queued = []

    def silent(self, *args, **kwargs):
        queued.append((args, kwargs))          # sent, not answered yet
        raise MachineTransportError("universal runtime did not respond")

    monkeypatch.setattr(UniversalRuntimeClient, "adjudicate_work", silent)
    with pytest.raises(MachineTransportError, match="did not respond"):
        _call(server, "native.work_request_court")
    monkeypatch.setattr(UniversalRuntimeClient, "adjudicate_work", original)

    first = _call(server, "native.work_reconcile")
    assert first["reconciled"] is False and first["pending_operation"] == "court"   # silence settles nothing
    assert first["court_recovery"]["decided"] is False
    with pytest.raises(MachineTransportError, match="unresolved"):
        _call(server, "native.work_request_court")                                 # never repeated
    with pytest.raises(MachineTransportError, match="unresolved"):
        _call(server, "native.work_task_detach")

    (args, kwargs), = queued
    with native.bound_client() as client:     # the queued request lands now
        original(client, *args, **kwargs)
    second = _call(server, "native.work_reconcile")
    assert second["reconciled"] is True and second["court_recovery"]["decided"] is True
    _refused_gate(second["court_recovery"]["verdict"])


def test_a_refused_court_request_settles_with_no_verdict(rig, monkeypatch):
    owner, _native, server = rig
    root = _work(owner, "Court request the application refuses")
    _submitted(server, root)
    original = UniversalRuntimeClient.adjudicate_work

    def stale(self, work_root, *, projection="status", expected_revision=None):
        return original(self, work_root, projection=projection, expected_revision=expected_revision - 1)

    monkeypatch.setattr(UniversalRuntimeClient, "adjudicate_work", stale)
    with pytest.raises(MachineResponseError, match="expected revision changed"):
        _call(server, "native.work_request_court")
    monkeypatch.setattr(UniversalRuntimeClient, "adjudicate_work", original)
    reconciled = _call(server, "native.work_reconcile")
    assert reconciled["reconciled"] is True and reconciled["court_recovery"]["decided"] is False
    assert reconciled["assignment"]["work"]["operational"]["current_state_label"].casefold() == "review"
    court = _call(server, "native.work_request_court")      # the refused request ran nothing
    assert (court["work_root"], court["event"]) == (root, "return")


def test_a_later_submission_is_settled_against_its_own_court(rig, monkeypatch):
    owner, _native, server = rig
    root = _work(owner, "Two submissions under one claim")
    _submitted(server, root, evidence="first submission")
    first = _call(server, "native.work_request_court")          # returned: the gate cannot run
    _call(server, "native.work_submit", evidence="second submission")
    original = _lose_reply_after_answer(monkeypatch)
    with pytest.raises(MachineTransportError, match="injected court reply loss"):
        _call(server, "native.work_request_court")
    monkeypatch.setattr(UniversalRuntimeClient, "adjudicate_work", original)

    recovery = _call(server, "native.work_reconcile")["court_recovery"]
    assert recovery["decided"] is True
    assert recovery["history_root"] != first["history_root"]
    assert recovery["verdict"]["attestation_root"] != first["attestation_root"]
    assert recovery["verdict"]["submit_event"] == recovery["submit_event"] != first["verdict"]["submit_event"]
