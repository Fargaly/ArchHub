"""Release refusal executes the same predicate the real qualification calls."""
import json
import os
from pathlib import Path
import shutil
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


@pytest.mark.parametrize("peer", ["claude", "goose"])
def test_qualification_server_and_native_mailbox_select_one_profile(tmp_path, monkeypatch, peer):
    from tools.real_app_check import agentlink_release as gate
    from nodelang import application_server, cell_secret_keys, model_router, workshop_mailbox
    from nodelang.persistence import application_database_path

    profile = tmp_path / "agentlink-qualification-profile"
    native_gate = tmp_path / "native_gate.py"
    native_gate.touch()
    monkeypatch.setattr(gate, "_executable", lambda *_: sys.executable)
    monkeypatch.setattr(gate, "_claude_auth", lambda *_: None)
    monkeypatch.setattr(model_router, "discover_key", lambda *_: ("fixture-credential", "fixture"))
    monkeypatch.setattr(gate, "source_digest", lambda *_: "source-fixture")
    monkeypatch.setattr(gate.shutil, "copytree", lambda *_args, **_kwargs: None)

    class Keys:
        def __init__(self, *_):
            pass
        def current(self, *_):
            pass

    class SelectedProfileChecked(Exception):
        pass

    def server(**options):
        if peer == "goose":
            assert json.loads(os.environ["OPENROUTER_PARAMETERS"]) == {"max_tokens":4096}
            assert os.environ["GOOSE_MODEL"] == gate._GOOSE_MODEL
        selected = options["universal_state_path"]
        assert selected == application_database_path(profile)
        assert selected == workshop_mailbox.profile_database()
        raise SelectedProfileChecked

    monkeypatch.setattr(cell_secret_keys, "WindowsDpapiSigningKeyProvider", Keys)
    monkeypatch.setattr(application_server, "ApplicationServer", server)
    with pytest.raises(SelectedProfileChecked):
        gate.qualify(profile, native_gate=native_gate, peer=peer)
    assert not profile.exists()


@pytest.mark.parametrize("refused", ["compiler", "agentlink"])
def test_actual_installer_refuses_before_creating_output(tmp_path, refused):
    product = tmp_path / "01.WIP" / "PRODUCT"
    (product / "installer").mkdir(parents=True)
    (product / "tools" / "pipeline").mkdir(parents=True)
    (product / "tools" / "real_app_check").mkdir()
    root = Path(__file__).resolve().parents[1]
    shutil.copyfile(root / "installer/build_release.ps1", product / "installer/build_release.ps1")
    (product / "tools/__init__.py").touch()
    (product / "tools/real_app_check/__init__.py").touch()
    (product / "tools/pipeline/build.py").write_text(
        "print('COMPILER_REACHED',flush=True)\nraise SystemExit(" + ("23" if refused == "compiler" else "0") + ")\n")
    (product / "tools/real_app_check/agentlink_release.py").write_text(
        "print('AGENTLINK_REACHED',flush=True)\nraise SystemExit(24)\n")
    env = {**os.environ, "GIT_CONFIG_GLOBAL":os.devnull, "PYTHONPATH":str(product)}
    for args in (["init", "--quiet"], ["add", "."],
                 ["-c", "user.name=Gate fixture", "-c", "user.email=gate@example.invalid",
                  "commit", "--quiet", "-m", "Fixture"]):
        subprocess.run(["git", "-c", "core.longpaths=true", *args],
                       cwd=product, env=env, check=True, capture_output=True)
    archive = tmp_path / "GOOSE.zip"
    archive.touch()
    output = tmp_path / "OUTPUT"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-File",
        str(product / "installer/build_release.ps1"), "-BuildId", "candidate-FIXTURE",
        "-OutputDirectory", str(output), "-GooseArchivePath", str(archive), "-PythonPath", sys.executable],
        cwd=product, env=env, capture_output=True, encoding="utf-8", errors="replace", timeout=30)
    assert result.returncode != 0
    assert "COMPILER_REACHED" in result.stdout
    assert ("AGENTLINK_REACHED" in result.stdout) == (refused == "agentlink")
    assert ("ACOMPILER refused release build" if refused == "compiler" else "AGENTLINK refused release") in result.stderr
    assert not output.exists()
