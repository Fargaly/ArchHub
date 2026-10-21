"""Court: every Work a session submitted holds its turn, named with the court's own step (live 717 and Ping, 2026-09-30).

717's actor ended every turn on "owns multiple unfinished Works; reconcile
ownership": nine submitted Works from 09-14, none named. A submitted Work has
no accepted verdict until its submitter runs native.work_request_court, so it
holds the submitter's turn, and the block now names each Work and its step.

Ping rejected two drafts that let a submitter escape the hold: fabricated
review references and malformed evidence were read as "waiting on the reviewer"
or "legacy". Here nothing the submitter wrote can release the turn: the step is
read through the court's own admission with the court's own artifact review
verifier, and a fake reference, malformed evidence, a missing reviewer
assignment or a failing verifier each hold, naming the court's refusal.

Real application server (in-memory), real agent sessions that claim and submit
through the machine transport, the real "stop-gate" projection. Only the review
verifier is replaced, where a case needs it to approve or to fail.
"""
import json

import pytest

from nodelang import commit_intent
from nodelang import native_agent_hooks as hooks
from nodelang.application_machine_transport import MachineResponseError, MachineTransportError, _read_descriptor
from nodelang.universal_application import create_universal_governed_work
from tests_replica.test_workshop_execution_gate import _agent as _bound, _container, _serve

CRITERIA = ["the stop gate court"]


def _agent(descriptor, provider, name):
    """A bound agent pinned to its owner, as the native owner always pins it."""
    client, session = _bound(descriptor, provider, name)
    client.pin_runtime_descriptor(_read_descriptor(descriptor, provider))
    return client, session


@pytest.fixture
def served(tmp_path, monkeypatch):
    server, descriptor, provider = _serve("in-memory", tmp_path, monkeypatch)
    try:
        yield server, descriptor, provider
    finally:
        server.close()


def _submitted(server, client, key, evidence, *, requirements=None, structured=True):
    references = {}
    if structured:
        # Both inputs the court reads are wired, so the court can run.
        references = {"cde-container": _container(key),
                      "requirements": requirements or {"acceptance_criteria": CRITERIA}}
    with commit_intent.declare(commit_intent.USER_ACTION, actor="court", reason="create Work"):
        work, _wire, _revision = create_universal_governed_work(
            server.universal_store, server.universal_registry, title="Stop gate " + key,
            description="stop gate court", priority=100, external_key=key,
            **({"structured_references": references} if references else {}), x=320, y=240)
    assert client.claim_work(work)["claimed"] is True
    client.request("POST", "/api/universal/work-transition",
                   {"root": work, "event": "submit", "evidence": evidence})
    return work


def _reviewed(reviewer, refs):
    return {"artifact_reviewers": [reviewer], "acceptance_criteria": CRITERIA}, json.dumps({"artifact_review": refs})


FAKE = {"publication": "app:existing-artifact:court-publication",
        "review": "app:existing-artifact:court-publication:review"}


def _gate(client):
    # The gate's own read; an application without it is read through its plain index.
    read = getattr(hooks, "stop_gate_read", None)
    status = read(client) if read else client.request("GET", "/api/universal/work", {"projection": "index"})
    return status, hooks.stop_verdict(status, client)


def _holds(verdict, work):
    assert verdict.get("decision") == "block"                     # it holds the turn
    assert work in verdict["reason"]                              # and names the Work
    assert "no accepted verdict; run native.work_request_court" in verdict["reason"]
    assert "native.work_task_attach %s" % work in verdict["reason"]


def test_a_submitted_work_holds_and_names_its_court_step(served):
    server, descriptor, provider = served
    client, _me = _agent(descriptor, provider, "stop-gate-court")
    work = _submitted(server, client, "court:stop-gate-court", "done: court")
    status, verdict = _gate(client)
    _holds(verdict, work)
    assert status["review_waits"] == {work: {"wait": "court", "reason": ""}}


def test_a_fabricated_review_reference_holds(served):
    server, descriptor, provider = served
    client, _me = _agent(descriptor, provider, "stop-gate-fake")
    _other, reviewer = _agent(descriptor, provider, "stop-gate-fake-reviewer")
    requirements, evidence = _reviewed(reviewer, FAKE)
    work = _submitted(server, client, "court:stop-gate-fake", evidence, requirements=requirements)
    status, verdict = _gate(client)
    _holds(verdict, work)
    # The court's own verifier finds no such publication record.
    assert status["review_waits"] == {work: {
        "wait": "reconcile", "reason": "value-graph root is not registered exactly once"}}
    assert ("Its court refuses this submission as it stands (value-graph root is not registered "
            "exactly once)") in verdict["reason"]


def test_malformed_evidence_holds(served):
    server, descriptor, provider = served
    client, _me = _agent(descriptor, provider, "stop-gate-malformed")
    _other, reviewer = _agent(descriptor, provider, "stop-gate-malformed-reviewer")
    requirements, _evidence = _reviewed(reviewer, FAKE)
    plain = _submitted(server, client, "court:stop-gate-plain", "done, reviewed by a peer",
                       requirements=requirements)
    missing = _submitted(server, client, "court:stop-gate-missing", json.dumps({"artifact": "x"}),
                         requirements=requirements)
    status, verdict = _gate(client)
    for work in (plain, missing):
        _holds(verdict, work)
        assert status["review_waits"][work] == {
            "wait": "reconcile", "reason": "Work submission must identify its artifact publication and review"}


def test_a_missing_reviewer_assignment_holds(served, monkeypatch):
    server, descriptor, provider = served
    client, me = _agent(descriptor, provider, "stop-gate-unassigned")
    _other, reviewer = _agent(descriptor, provider, "stop-gate-unassigned-reviewer")
    _undeclared, stranger = _agent(descriptor, provider, "stop-gate-undeclared")
    none_declared = _submitted(server, client, "court:stop-gate-none", json.dumps({"artifact_review": FAKE}),
                               requirements={"artifact_reviewers": [], "acceptance_criteria": CRITERIA})
    requirements, evidence = _reviewed(reviewer, FAKE)
    by_stranger = _submitted(server, client, "court:stop-gate-stranger", evidence, requirements=requirements)
    # A verifier that approves a review by someone the Work never declared.
    monkeypatch.setattr(server, "_verify_work_artifact_review", lambda **args: {
        "publication": args["publication_root"], "review": args["review_root"], "artifact_digest": "0" * 64,
        "publisher": me, "reviewer": stranger, "material_digest": "0" * 64})
    status, verdict = _gate(client)
    _holds(verdict, none_declared)
    _holds(verdict, by_stranger)
    assert status["review_waits"] == {
        none_declared: {"wait": "reconcile",
                        "reason": "Work requires an available independent artifact review verifier"},
        by_stranger: {"wait": "reconcile", "reason": "Independent artifact review binding is invalid"}}


def test_a_failing_review_verifier_holds(served, monkeypatch):
    server, descriptor, provider = served
    client, _me = _agent(descriptor, provider, "stop-gate-verifier")
    _other, reviewer = _agent(descriptor, provider, "stop-gate-verifier-reviewer")
    requirements, evidence = _reviewed(reviewer, FAKE)
    work = _submitted(server, client, "court:stop-gate-verifier", evidence, requirements=requirements)

    def broken(**_args):
        raise RuntimeError("artifact storage unavailable")

    monkeypatch.setattr(server, "_verify_work_artifact_review", broken)
    status, verdict = _gate(client)
    _holds(verdict, work)
    assert "could not check the submission (RuntimeError)" in verdict["reason"]
    assert status["review_waits"] == {work: {"wait": "unknown", "reason": "RuntimeError"}}


def test_a_work_whose_court_inputs_are_unwired_holds(served):
    server, descriptor, provider = served
    client, _me = _agent(descriptor, provider, "stop-gate-unwired")
    work = _submitted(server, client, "court:stop-gate-unwired", "done: unwired", structured=False)
    status, verdict = _gate(client)
    _holds(verdict, work)
    assert status["review_waits"][work]["wait"] in {"reconcile", "unknown"}


def test_an_approved_independent_review_is_the_court_step(served, monkeypatch):
    server, descriptor, provider = served
    client, me = _agent(descriptor, provider, "stop-gate-approved")
    _other, reviewer = _agent(descriptor, provider, "stop-gate-approved-reviewer")
    requirements, evidence = _reviewed(reviewer, FAKE)
    work = _submitted(server, client, "court:stop-gate-approved", evidence, requirements=requirements)
    seen = []

    def approved(**args):
        seen.append(args["publication_root"])
        return {"publication": args["publication_root"], "review": args["review_root"],
                "artifact_digest": "0" * 64, "publisher": me, "reviewer": reviewer, "material_digest": "0" * 64}

    monkeypatch.setattr(server, "_verify_work_artifact_review", approved)
    status, verdict = _gate(client)
    _holds(verdict, work)
    assert status["review_waits"] == {work: {"wait": "court", "reason": ""}}
    assert seen == [FAKE["publication"]]          # the court's own verifier was asked


def test_every_submitted_work_is_named_and_another_sessions_is_not(served):
    server, descriptor, provider = served
    client, _me = _agent(descriptor, provider, "stop-gate-mine")
    peer, _peer = _agent(descriptor, provider, "stop-gate-peer")
    first = _submitted(server, client, "court:stop-gate-first", "done: first")
    second = _submitted(server, client, "court:stop-gate-second", "not json", structured=False)
    theirs = _submitted(server, peer, "court:stop-gate-theirs", "done: theirs")
    status, verdict = _gate(client)
    assert verdict["reason"].startswith("This session has 2 unfinished Works, each its own step:")
    _holds(verdict, first)
    _holds(verdict, second)
    assert theirs not in verdict["reason"] and set(status["review_waits"]) == {first, second}
    _status, theirs_verdict = _gate(peer)
    _holds(theirs_verdict, theirs)


def test_a_classification_that_skips_a_submitted_work_is_refused(served):
    server, descriptor, provider = served
    client, _me = _agent(descriptor, provider, "stop-gate-skipped")
    _submitted(server, client, "court:stop-gate-skipped", "done: skipped")
    status = hooks.stop_gate_read(client)
    with pytest.raises(MachineTransportError, match="review classification"):
        hooks.stop_verdict(dict(status, review_waits={}), client)
    root = next(iter(status["review_waits"]))
    with pytest.raises(MachineTransportError, match="review classification"):
        hooks.stop_verdict(dict(status, review_waits={root: {"wait": "reviewer", "reason": ""}}), client)


def test_an_older_application_is_read_through_its_plain_index():
    calls = []

    class Older:
        def request(self, method, path, body, **kwargs):
            calls.append(body["projection"])
            if body["projection"] == "stop-gate":
                raise MachineResponseError("work projection request shape is invalid")
            return {"items": []}

    assert hooks.stop_gate_read(Older()) == {"items": []}
    assert calls == ["stop-gate", "index"]
