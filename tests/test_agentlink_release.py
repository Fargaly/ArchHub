"""Release refusal executes the same predicate the real qualification calls."""
import os
from pathlib import Path
import subprocess
import sys
import pytest
from tools.real_app_check.agentlink_release import require_checks, QualificationRefused


@pytest.mark.parametrize("failed", ["exchange", "overlap", "opencode"])
def test_each_required_scenario_refuses_in_a_real_gate_process(failed):
    program = ("from tools.real_app_check.agentlink_release import require_checks; "
        "require_checks({'exchange':True,'overlap':True,'opencode':True," + repr(failed) + ":False})")
    result = subprocess.run([sys.executable, "-c", program],
        cwd=Path(__file__).resolve().parents[1], capture_output=True, encoding="utf-8",
        env={**os.environ, "PYTHONDONTWRITEBYTECODE":"1"},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    assert result.returncode != 0
    assert "AGENTLINK release refused: " + failed in result.stderr


def test_missing_or_unknown_state_never_becomes_pass():
    with pytest.raises(QualificationRefused):
        require_checks({"exchange":True,"overlap":True})
    with pytest.raises(QualificationRefused):
        require_checks({"exchange":True,"overlap":True,"opencode":"skipped"})
    require_checks({"exchange":True,"overlap":True,"opencode":True})


def test_echoed_ids_are_not_tool_read_receipts():
    import json
    from tools.real_app_check.agentlink_release import read_messages, write_sequence
    message = {"id":"overlap-proof", "refs":["one", "two"]}
    echoed = json.dumps({"type":"text","part":{"text":json.dumps({"messages":[message]})}})
    assert read_messages(echoed) == []
    result = json.dumps({"type":"tool_use", "part":{"tool":"archhub_agent_coordination_read",
        "state":{"status":"completed","output":json.dumps({"messages":[message]})}}})
    assert read_messages(result) == [message]
    good = "\n".join(json.dumps({"type":"tool_use","part":{"tool":tool,
        "state":{"status":"completed","output":"ok"}}}) for tool in ["write","read","write","glob"])
    assert write_sequence(good)
    assert not write_sequence(good.replace('"status": "completed"','"status": "error"',1))


def test_goose_only_auto_allows_the_shared_mailbox_boundary():
    from nodelang.goose_adapter import safe_workshop_call
    def identity(tool):
        return {"extensionName":"archhub-agent", "toolName":"archhub-agent__"+tool}
    assert safe_workshop_call(identity("read"), {"since":0})
    assert safe_workshop_call(identity("declare"), {"task":"Check fixture","paths":["fixture"],"status":"working","request_id":"proof"})
    assert safe_workshop_call(identity("send"), {"to":"OpenCode","text":"proof","reply_to":"root"})
    assert not safe_workshop_call(identity("send"), {"to":"OpenCode","text":"proof","sender":"forged"})
    assert not safe_workshop_call(identity("office_execute"), {"code":"unsafe"})
    assert not safe_workshop_call({"extensionName":"other","toolName":"archhub-agent__read"}, {})
