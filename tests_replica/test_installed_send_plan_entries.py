import threading
from types import SimpleNamespace

import pytest

import nodelang.installed_workshop_coordination as installed
from nodelang.application_machine_transport import UniversalRuntimeClient
from nodelang.installed_workshop_coordination import InstalledWorkshopCoordinationClient


WORK = "assembly-instance:" + "a" * 32


class FakeRuntimeClient(UniversalRuntimeClient):
    def __init__(self):
        self._request_lock = threading.RLock()
        self.agent_session_root = "app:agent-session:runtime:" + "b" * 32
        self._agent_session_token = "token"
        self._agent_session_access = "full"
        self.descriptor_path = "runtime.json"
        self.key_provider = object()
        self._pinned_runtime_descriptor = None
        self.requests = []

    def pin_runtime_descriptor(self, descriptor):
        self._pinned_runtime_descriptor = descriptor

    def request(self, method, path, body, response_timeout_seconds):
        self.requests.append((method, path, body, response_timeout_seconds))
        root = "app:workshop-message:" + str(len(self.requests))
        return {"ok": True, "workshop": "app:workshop:" + "c" * 32,
                "storage": "conversation-content", "actor": self.agent_session_root,
                "recipients": list(body["recipients"]), "reply_to": body["reply_to"],
                "message_id": root, "root": root}


@pytest.fixture
def client(monkeypatch):
    descriptor = SimpleNamespace(runtime_id="runtime", application_root="app:application:" + "d" * 32,
        workshop_root="app:workshop:" + "c" * 32, work_registry_root="app:work-registry:" + "e" * 32,
        database="graph.sqlite3", pipe="pipe", process_id=123, started_at=1.0,
        key_id="key", key_version=1, agent_session_root="app:agent-session:runtime:" + "f" * 32)
    monkeypatch.setattr(installed, "resolve_active_runtime", lambda _path, _keys: descriptor)
    runtime = FakeRuntimeClient()
    return InstalledWorkshopCoordinationClient(runtime), runtime


def test_plan_entry_carries_category_and_refs(client):
    control, runtime = client
    control.call("send_message", {"target": "", "message": "Plan for the work.",
        "idempotency_key": "court-plan", "category": "plan", "refs": [WORK]})
    assert runtime.requests[-1][2]["category"] == "plan"
    assert runtime.requests[-1][2]["refs"] == [WORK]
    assert runtime.requests[-1][2]["recipients"] == []


def test_research_entry_carries_evidence_exactly(client):
    control, runtime = client
    evidence = ["source:one", "source:two"]
    control.call("send_message", {"target": "", "message": "Prior art.",
        "idempotency_key": "court-research", "category": "research", "refs": [WORK], "evidence": evidence})
    assert runtime.requests[-1][2]["category"] == "research"
    assert runtime.requests[-1][2]["evidence"] == evidence
    assert runtime.requests[-1][2]["recipients"] == []


def test_invalid_category_ref_and_too_many_refs_are_rejected_before_request(client):
    control, runtime = client
    for index, extra in enumerate(({"category": "finding"},
            {"category": "plan", "refs": ["assembly-instance:BAD"]},
            {"category": "plan", "refs": [WORK] * 9})):
        with pytest.raises(ValueError):
            control.call("send_message", {"target": "", "message": "x",
                "idempotency_key": "court-invalid-%d" % index, **extra})
    assert runtime.requests == []


def test_default_call_still_sends_note_with_empty_refs(client):
    control, runtime = client
    target = "app:agent-session:runtime:" + "1" * 32
    control.call("send_message", {"target": target, "message": "ordinary note", "idempotency_key": "court-note"})
    assert runtime.requests[-1][2]["category"] == "note"
    assert runtime.requests[-1][2]["refs"] == []
    assert runtime.requests[-1][2]["evidence"] == []
    assert runtime.requests[-1][2]["recipients"] == [target]


def test_research_entry_carries_one_source_capture(client):
    control, runtime = client
    control.call("send_message", {"target": "", "message": "prior art: read the hook.",
        "idempotency_key": "court-capture", "category": "research", "refs": [WORK],
        "capture": {"path": "00.GOVERNANCE/hooks/workspace_roots.py"}})
    assert runtime.requests[-1][2]["capture"] == {"path": "00.GOVERNANCE/hooks/workspace_roots.py"}


def test_capture_is_refused_outside_one_research_entry_for_one_work(client):
    control, runtime = client
    for index, extra in enumerate(({"category": "plan", "refs": [WORK]},
            {"category": "research", "refs": []},
            {"category": "research", "refs": [WORK, "assembly-instance:" + "9" * 32]})):
        with pytest.raises(ValueError):
            control.call("send_message", {"target": "", "message": "x",
                "idempotency_key": "court-capture-bad-%d" % index,
                "capture": {"path": "README.md"}, **extra})
    assert runtime.requests == []


def test_no_capture_key_is_sent_by_default(client):
    control, runtime = client
    control.call("send_message", {"target": "", "message": "plan", "idempotency_key": "court-nocap",
        "category": "plan", "refs": [WORK]})
    assert "capture" not in runtime.requests[-1][2]
