"""Courts for BABOOM's volatile Node Language presence host."""
from __future__ import annotations

from copy import deepcopy
import time

import pytest

from nodelang.baboom_native_host import BaboomNativeHost


def _context(*, blocked: int = 0, review: int = 0) -> dict[str, object]:
    return {
        "cell_native": True,
        "context_lens": "app:baboom-context:v3",
        "revision": 41,
        "work": {
            "total": blocked + review,
            "open": 0,
            "claimed": 0,
            "blocked": blocked,
            "review": review,
        },
        "workshop": {"entry_count": 2, "category_counts": {"plan": 2}},
        "attention": {
            "open_obligations": 0,
            "blocked_obligations": 0,
            "active_focus": False,
        },
        "presence": {
            "active_runtime_sessions": 1,
            "baboom_connected": True,
            "baboom_action_capability_active": False,
        },
        "activity": {"active_baboom_devices": 1, "foreground_apps": {}},
        "meeting_notes": {"active_sessions": 0},
        "device": {
            "enrollment_handoff_available": False,
            "current_runtime_proven": True,
            "active_baboom_devices": 1,
            "native_identity_provider_configured": False,
            "issued_cloud_sessions": 0,
            "remote_gateway_serving": False,
        },
        "persona_form": "steward",
        "suggestion": "Review blocked governed work.",
    }


def _directive(*, revision: int = 41, actionable: bool = False) -> dict[str, object]:
    message = (
        "1 blocked Work item needs review."
        if actionable else "No governed Work needs attention."
    )
    return {
        "projection": "app:baboom-companion-directive:v1",
        "revision": revision,
        "fingerprint": "baboom-directive:sha256:" + "a" * 64,
        "persona_form": "steward",
        "motion": "warning" if actionable else "idle",
        "message": message,
        "context": "ArchHub | Live activity",
        "compact_message": message if actionable else "",
        "ttl_seconds": 12.0,
        "action": "review-governed-work" if actionable else "",
        "action_label": "Review Work" if actionable else "",
    }


def _report(*, revision: int = 41) -> dict[str, object]:
    return {
        "kind": "steward-briefing",
        "summary": "Founder-local Work, Workshop, and attention briefing.",
        "revision": revision,
        "data": {
            "projection": "founder-local-baboom-steward-briefing",
            "revision": revision,
            "context": {"revision": revision},
            "governed_work": {"revision": revision},
            "workshop": {"revision": revision},
            "attention": {"revision": revision},
        },
    }


class _Transport:
    def __init__(self) -> None:
        self.agent_session_root = ""
        self.context = _context(blocked=1)
        self.binds: list[dict[str, object]] = []
        self.presence_renewals = 0
        self.signals: list[dict[str, str]] = []
        self.executions: list[str] = []
        self.activities: list[str] = []
        self.frame_calls = 0
        self.context_calls = 0
        self.briefing_calls = 0
        self.frame_expired = False
        self.report_revision_offset = 0

    def bind_agent_session(self, **kwargs):
        self.binds.append(kwargs)
        self.agent_session_root = "app:agent-session:runtime:baboom-host-court"
        return {"agent_session": self.agent_session_root}

    def renew_runtime_presence(self):
        self.presence_renewals += 1
        return {
            "agent_session": self.agent_session_root,
            "runtime": "baboom",
            "expires_at": 1234.5,
        }

    def baboom_context(self, **kwargs):
        self.context_calls += 1
        return deepcopy(self.context)

    def baboom_native_frame(self, **kwargs):
        self.frame_calls += 1
        revision = self.context["revision"]
        actionable = bool(
            self.context["work"]["blocked"] or self.context["work"]["review"]
        )
        issued_at = time.time() - (24.0 if self.frame_expired else 0.0)
        return {
            "projection": "app:baboom-native-frame:v2",
            "revision": revision,
            "issued_at": issued_at,
            "expires_at": issued_at + 12.0,
            "context": deepcopy(self.context),
            "directive": _directive(revision=revision, actionable=actionable),
            "report": (
                _report(revision=revision + self.report_revision_offset)
                if actionable else None
            ),
        }

    def resolve_baboom_command(self, **kwargs):
        return {
            "catalog": "app:baboom-command-catalog:v1",
            "intent": "assign-task",
            "payload": kwargs["utterance"],
            "revision": self.context["revision"],
        }

    def respond_baboom_command(self, **kwargs):
        self.briefing_calls += 1
        return {
            "command": {
                "catalog": "app:baboom-command-catalog:v1",
                "intent": "workshop-report",
                "payload": kwargs["utterance"],
                "revision": self.context["revision"],
            },
            "response": {
                "kind": "workshop-report",
                "summary": "Latest bounded founder-local Workshop entries.",
                "data": {"revision": self.context["revision"], "entries": []},
            },
        }

    def execute_baboom_command(self, **kwargs):
        self.executions.append(kwargs["utterance"])
        return {
            "catalog": "app:baboom-command-catalog:v1",
            "intent": "assign-task",
            "work": "assembly-instance:governed-work:baboom-host-court",
            "external_key": "baboom-founder-task:v1:" + "a" * 64,
            "created": True,
            "state": "open",
            "revision": self.context["revision"] + 1,
        }

    def record_baboom_activity(self, *, app):
        self.activities.append(app)
        return {
            "activity": "baboom-activity:sha256:" + "a" * 64,
            "app": app,
            "expires_at": 1234.5,
            "agent_session": self.agent_session_root,
            "revision": self.context["revision"],
        }

    def record_baboom_steward_signal(self, **kwargs):
        self.signals.append(kwargs)
        return {
            "signal": "app:baboom-steward-signal:" + kwargs["fingerprint"],
            "agent_session": self.agent_session_root,
            "revision": self.context["revision"],
        }


def test_native_host_is_explicitly_connected_and_keeps_only_volatile_projection_state():
    transport = _Transport()
    host = BaboomNativeHost(
        transport,
        external_session_id="baboom-native-host-court",
        device_credential_provider=lambda challenge: {"proof": "approved"},
    )

    with pytest.raises(RuntimeError, match="not explicitly connected"):
        host.poll()

    snapshot = host.connect()
    assert transport.binds == [{
        "runtime": "baboom",
        "external_session_id": "baboom-native-host-court",
        "device_credential_provider": transport.binds[0]["device_credential_provider"],
    }]
    assert snapshot.revision == 41
    assert snapshot.presence_expires_at == 1234.5
    assert snapshot.frame_issued_at < snapshot.frame_expires_at
    assert snapshot.context["work"]["blocked"] == 1
    assert snapshot.directive["motion"] == "warning"
    assert snapshot.report is not None
    assert snapshot.report["revision"] == snapshot.revision
    assert transport.frame_calls == 1
    assert transport.context_calls == 0
    assert transport.briefing_calls == 0
    resolution = host.resolve_input("Assign task: review the coordination brief")
    assert resolution["intent"] == "assign-task"
    assert resolution["payload"] == "Assign task: review the coordination brief"
    response = host.respond_input("Workshop report")
    assert response["response"]["kind"] == "workshop-report"
    execution = host.execute_input("Assign task: review the coordination brief")
    assert execution["intent"] == "assign-task"
    assert execution["created"] is True
    assert transport.executions == ["Assign task: review the coordination brief"]
    assert snapshot.steward_signal_root and snapshot.steward_signal_root.startswith(
        "app:baboom-steward-signal:"
    )
    assert len(transport.signals) == 1
    assert not hasattr(host, "queue")
    assert not hasattr(host, "task_store")

    second = host.poll()
    assert second.steward_signal_root is None
    assert len(transport.signals) == 1

    transport.context = _context(review=1)
    changed = host.poll()
    assert changed.steward_signal_root is not None
    assert len(transport.signals) == 2
    assert transport.signals[-1]["summary"] == "Governed work is awaiting founder review."


def test_native_host_quiet_frame_is_sprite_only_and_has_no_secondary_report_poll():
    transport = _Transport()
    transport.context = _context()
    host = BaboomNativeHost(
        transport,
        external_session_id="baboom-native-quiet-court",
        device_credential_provider=lambda challenge: {"proof": "approved"},
    )

    snapshot = host.connect()

    assert snapshot.directive["message"] == "No governed Work needs attention."
    assert snapshot.directive["compact_message"] == ""
    assert snapshot.report is None
    assert transport.frame_calls == 1
    assert transport.context_calls == 0
    assert transport.briefing_calls == 0


@pytest.mark.parametrize("failure", ("expired", "drifted"))
def test_native_host_fails_closed_on_expired_or_drifted_frame(failure):
    transport = _Transport()
    if failure == "expired":
        transport.frame_expired = True
    else:
        transport.report_revision_offset = 1
    host = BaboomNativeHost(
        transport,
        external_session_id="baboom-native-frame-denial-court",
        device_credential_provider=lambda challenge: {"proof": "approved"},
    )

    with pytest.raises(RuntimeError, match="native frame response is invalid"):
        host.connect()


def test_native_host_records_only_an_allowlisted_foreground_app_and_throttles_renewals():
    transport = _Transport()
    host = BaboomNativeHost(
        transport,
        external_session_id="baboom-native-activity-court",
        device_credential_provider=lambda challenge: {"proof": "approved"},
        activity_provider=lambda: "Revit",
    )

    host.connect()
    host.poll()

    assert transport.activities == ["Revit"]


def test_native_host_rejects_activity_metadata_outside_the_released_vocabulary():
    transport = _Transport()
    host = BaboomNativeHost(
        transport,
        external_session_id="baboom-native-activity-reject-court",
        device_credential_provider=lambda challenge: {"proof": "approved"},
        activity_provider=lambda: "C:/private/client-model.rvt",
    )

    with pytest.raises(RuntimeError, match="unreleased app"):
        host.connect()
