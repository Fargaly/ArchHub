"""The founder's app restarting orphans enrolled Agent Sessions; the stop gate
re-enrolls once instead of denying the stop and demanding a human ritual."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import brainwrap  # noqa: E402


def test_gate_reenrolls_once_then_reads_status(monkeypatch):
    calls = []

    def fake_call_tool(name, arguments, **kwargs):
        calls.append(name)
        if name == "brain.universal_work_status":
            # First read: authority orphaned. After the re-enroll: healthy, no owned work.
            if "brain.hook_session_start" in calls:
                return {"agent_session": "app:agent-session:runtime:x", "items": []}
            return None
        if name == "brain.hook_session_start":
            return {"ok": True}
        raise AssertionError(name)

    monkeypatch.setattr(brainwrap, "call_tool", fake_call_tool)
    blocked, reason = brainwrap._completion_gate_verdict(
        None, runtime="claude-code", session_id="s-1"
    )
    assert calls == [
        "brain.universal_work_status",
        "brain.hook_session_start",
        "brain.universal_work_status",
    ]
    assert blocked is False and reason == ""


def test_gate_still_denies_when_reenroll_cannot_restore(monkeypatch):
    monkeypatch.setattr(brainwrap, "call_tool", lambda *a, **k: None)
    # No brain on the port at all: the settling-brain reading cannot apply.
    monkeypatch.setattr(brainwrap, "_port_held", lambda *a, **k: False)
    blocked, reason = brainwrap._completion_gate_verdict(
        None, runtime="claude-code", session_id="s-1"
    )
    assert blocked is True and "unavailable" in reason
