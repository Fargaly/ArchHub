"""Focused client-hook repair courts; all filesystem effects stay under tmp_path."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from nodelang import session_link_config as config


@pytest.fixture
def inputs(tmp_path):
    home = tmp_path / "home"
    gate = tmp_path / "00.GOVERNANCE" / "hooks" / "agent_scope_gate.py"
    python = tmp_path / "runtime" / "python.exe"
    for path in (gate, python):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# court fixture; never executed\n", encoding="utf-8")
    for folder in (".claude", ".codex", ".gemini"):
        (home / folder).mkdir(parents=True)
    backup = tmp_path / "private"
    backup.mkdir()
    return home, gate, python, backup


@pytest.mark.parametrize("vendor,events,timeout", [
    ("claude-code", ("PreToolUse", "PostToolUse"), 30),
    ("codex", ("PreToolUse", "PostToolUse"), 30),
    ("gemini-cli", ("BeforeTool", "AfterTool"), 30000),
])
def test_tool_hooks_render_deterministically_without_global_lifecycle(inputs, vendor, events, timeout):
    home, gate, python, _ = inputs
    kwargs = dict(python_executable=python, gate_script=gate, install_root=home)
    result = config.render_client_hooks(vendor, **kwargs)
    assert result == config.render_client_hooks(vendor, **kwargs)
    assert set(result) == set(events)
    for event in events:
        assert len(result[event]) == 1
        assert result[event][0]["hooks"][0]["timeout"] == timeout


def test_merge_removes_only_exact_managed_entries_and_is_idempotent(inputs):
    home, gate, python, _ = inputs
    managed = config.render_client_hooks("codex", python_executable=python,
                                        gate_script=gate, install_root=home)
    adapter = managed["PreToolUse"][0]["hooks"][0]
    unrelated = {"type": "command", "command": "my-existing-hook"}
    existing = {"other": {"secret_marker": "keep locally"}, "hooks": {
        "PreToolUse": [{"hooks": [adapter, unrelated, copy.deepcopy(adapter)]}],
        "SessionStart": [{"hooks": [unrelated]}]}}
    original = copy.deepcopy(existing)
    owned = (config._hook_command_identity(adapter),)
    after = config.merge_client_hooks(existing, managed, vendor="codex", known_owned_commands=owned)
    assert after["hooks"]["PreToolUse"][0]["hooks"] == original["hooks"]["PreToolUse"][0]["hooks"]
    assert after["hooks"]["SessionStart"] == existing["hooks"]["SessionStart"]
    assert after["other"] == existing["other"] and existing == original
    assert config.merge_client_hooks(after, managed, vendor="codex", known_owned_commands=owned) == after


def test_writer_preserves_backup_and_second_run_does_nothing(inputs):
    home, _, _, backup = inputs
    target = home / ".codex" / "hooks.json"
    before = b'{"hooks":{}}\r\n'
    target.write_bytes(before)
    result = config.write_with_backup(target, '{"hooks":{"PreToolUse":[]}}\n', backup,
        expected_digest=hashlib.sha256(before).hexdigest(),
        protect_backup=lambda data: b"court-encrypted:" + data)
    assert Path(result["backup"]).read_bytes() == b"court-encrypted:" + before
    assert target.read_bytes().endswith(b"\r\n")
    held = list(backup.iterdir())
    second = config.write_with_backup(target, target.read_text(), backup)
    assert second["changed"] is False and list(backup.iterdir()) == held


def test_writer_refuses_preview_drift_without_modifying_file(inputs):
    home, _, _, backup = inputs
    target = home / ".codex" / "hooks.json"
    target.write_bytes(b"changed-by-user")
    with pytest.raises(config.SessionLinkConfigRefused, match="changed since preview"):
        config.write_with_backup(target, "candidate", backup, expected_digest="outdated")
    assert target.read_bytes() == b"changed-by-user"
    assert not list(backup.iterdir())


def test_failed_atomic_replace_keeps_original_and_cleans_temp(inputs, monkeypatch):
    home, _, _, backup = inputs
    target = home / ".codex" / "hooks.json"
    target.write_bytes(b"original")
    def refuse(*args):
        raise PermissionError("court locked target")
    monkeypatch.setattr(config.os, "replace", refuse)
    with pytest.raises(PermissionError):
        config.write_with_backup(target, "candidate", backup,
                                 protect_backup=lambda data: b"encrypted:" + data)
    assert target.read_bytes() == b"original"
    assert list(target.parent.iterdir()) == [target]


def test_failed_atomic_replace_leaves_no_orphan_backup(inputs, monkeypatch):
    """Court: nothing replaced means nothing backed up; no stray .dpapi is left behind."""
    home, _, _, backup = inputs
    target = home / ".codex" / "hooks.json"
    target.write_bytes(b"original")
    def refuse(*args):
        raise PermissionError("court locked target")
    monkeypatch.setattr(config.os, "replace", refuse)
    with pytest.raises(PermissionError):
        config.write_with_backup(target, "candidate", backup,
                                 protect_backup=lambda data: b"encrypted:" + data)
    assert target.read_bytes() == b"original"
    assert list(backup.iterdir()) == []


def test_plan_requires_reapproval_after_settings_change(inputs):
    home, gate, python, _ = inputs
    target = home / ".codex" / "hooks.json"
    target.write_text('{"hooks":{}}', encoding="utf-8")
    first = config.plan_client_hook_install("codex", home=home, install_root=home,
                                           python_executable=python, gate_script=gate)
    target.write_text('{"hooks":{},"unrelated":"new user setting"}', encoding="utf-8")
    second = config.plan_client_hook_install("codex", home=home, install_root=home,
                                            python_executable=python, gate_script=gate)
    assert first["plan_digest"] != second["plan_digest"]
    with pytest.raises(config.SessionLinkConfigRefused, match="plan changed"):
        config.apply_client_hook_install(second, expected_digest=first["plan_digest"],
                                         backup_dir=home)
    assert json.loads(target.read_text())["unrelated"] == "new user setting"


def test_codex_legacy_direct_validator_removed_without_touching_other_hook(inputs):
    import subprocess
    home, gate, python, _ = inputs
    target = home / ".codex" / "hooks.json"
    direct = {"type":"command", "command":subprocess.list2cmdline(
        [str(python), str(gate.with_name("pretooluse_validate.py"))])}
    other = {"type":"command", "command":"unrelated-validator"}
    target.write_text(json.dumps({"hooks":{"PreToolUse":[{"hooks":[direct, other]}]}}))
    plan = config.plan_client_hook_install("codex", home=home, install_root=home,
                                          python_executable=python, gate_script=gate)
    projected = json.loads(plan["text"])
    hooks = [h for g in projected["hooks"]["PreToolUse"] for h in g["hooks"]]
    assert direct not in hooks and other in hooks
    assert len(hooks) == 2


# Reuse the existing real HTTP fixture rather than starting a second server type.
from tests_replica.test_settings_terminal_routes import server, call


def test_existing_assistant_route_previews_and_applies_reviewed_hooks(server, monkeypatch):
    from nodelang import assistant_registration as registration
    calls = []
    monkeypatch.setattr(registration, "preview_hooks",
                        lambda client: {"client":client, "plan_digest":"reviewed"}, raising=False)
    def repair(client, **kwargs):
        calls.append((client, kwargs))
        return {"changed":True, "activation_pending":True}
    monkeypatch.setattr(registration, "repair_hooks", repair, raising=False)
    preview = call(server, "/api/universal/assistant-registration",
                   {"client":"codex", "action":"preview-hooks"})
    assert preview["result"]["plan_digest"] == "reviewed"
    answer = call(server, "/api/universal/assistant-registration",
                  {"client":"codex", "action":"repair-hooks",
                   "consent":True, "plan_digest":"reviewed"})
    assert answer["result"]["activation_pending"] is True
    assert calls == [("codex", {"consent":True, "plan_digest":"reviewed"})]
    call(server, "/api/universal/assistant-registration",
         {"client":"codex", "action":"repair-hooks",
          "consent":False, "plan_digest":"reviewed"}, expected=400)
    assert len(calls) == 1


def test_hook_repair_request_without_csrf_never_reaches_writer(server, monkeypatch):
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    from nodelang import assistant_registration as registration
    touched = []
    monkeypatch.setattr(registration, "repair_hooks", lambda *a, **k: touched.append(True), raising=False)
    request = Request(server.url + "/api/universal/assistant-registration",
                      headers={"Content-Type":"application/json", "Origin":server.url,
                               "Cookie":"ArchHub-Session=" + server.browser_session_token},
                      data=json.dumps({"client":"codex","action":"repair-hooks",
                                       "consent":True,"plan_digest":"reviewed"}).encode())
    with pytest.raises(HTTPError) as failure:
        urlopen(request, timeout=15)
    assert failure.value.code == 403
    assert touched == []
    # Control: the same request WITH the CSRF token does reach the writer.
    call(server, "/api/universal/assistant-registration",
         {"client":"codex","action":"repair-hooks","consent":True,"plan_digest":"reviewed"})
    assert touched == [True]


def test_renderer_refuses_shell_metacharacters_in_existing_paths(inputs):
    home, gate, python, _ = inputs
    hostile_directory = python.parent / "runtime&extra"
    hostile_directory.mkdir()
    hostile = hostile_directory / python.name
    hostile.write_text("# never execute")
    with pytest.raises(config.SessionLinkConfigRefused, match="metacharacters"):
        config.render_client_hooks("codex", python_executable=hostile,
                                   gate_script=gate, install_root=home)


@pytest.mark.parametrize("vendor", ["claude-code", "codex"])
def test_equivalent_command_keeps_bytes_matcher_and_trust_hash(inputs, vendor):
    home, gate, python, backup = inputs
    managed = config.render_client_hooks(vendor, python_executable=python,
                                        gate_script=gate, install_root=home)
    for groups in managed.values():
        groups[0]["matcher"] = "Read|Write"
        groups[0]["custom_group_setting"] = "keep"
        groups[0]["hooks"][0]["timeout"] = 41
    target = home / config._HOOK_CLIENTS[vendor][0]
    before = b"\xef\xbb\xbf" + (json.dumps({"hooks": managed}, indent=4) + "\r\n").encode()
    target.write_bytes(before)
    plan = config.plan_client_hook_install(vendor, home=home, install_root=home,
                                          python_executable=python, gate_script=gate)
    assert plan["changed"] is False
    assert plan["before_digest"] == plan["after_digest"] == hashlib.sha256(before).hexdigest()
    result = config.apply_client_hook_install(plan, expected_digest=plan["plan_digest"],
                                              backup_dir=backup)
    assert result["changed"] is False and target.read_bytes() == before
    assert not list(backup.iterdir())


def test_renderer_preserves_original_case_and_quotes_forward_slash_paths(inputs):
    home, gate, python, _ = inputs
    result = config.render_client_hooks("claude-code", python_executable=python,
                                        gate_script=gate, install_root=home)
    command = result["PreToolUse"][0]["hooks"][0]["command"]
    assert command.startswith('"' + str(python).replace("\\", "/") + '" "')
    assert '"' + str(gate).replace("\\", "/") + '"' in command
    assert "\\" not in command
    assert config._hook_command_parts(result["PreToolUse"][0]["hooks"][0])[:2] == (
        str(python).replace("\\", "/"), str(gate).replace("\\", "/"))


def test_repair_preserves_bom_and_group_metadata(inputs):
    home, gate, python, _ = inputs
    target = home / ".codex" / "hooks.json"
    direct = {"type": "command", "command": '"' + str(python).replace("\\", "/") +
              '" "' + str(gate.with_name("pretooluse_validate.py")).replace("\\", "/") + '"',
              "timeout": 42}
    original = {"hooks": {"PreToolUse": [{"matcher": "Read|Write", "extra": "keep",
                                         "hooks": [direct]}]}}
    target.write_bytes(b"\xef\xbb\xbf" + json.dumps(original).encode())
    plan = config.plan_client_hook_install("codex", home=home, install_root=home,
                                          python_executable=python, gate_script=gate)
    assert plan["changed"] is True and plan["text"].startswith("\ufeff")
    group = json.loads(plan["text"].lstrip("\ufeff"))["hooks"]["PreToolUse"][0]
    assert group["matcher"] == "Read|Write" and group["extra"] == "keep"
    assert group["hooks"][0]["timeout"] == 42
    assert "agent_scope_gate.py" in group["hooks"][0]["command"]


def test_route_does_not_disclose_exception_paths(server, monkeypatch):
    from nodelang import assistant_registration as registration
    from nodelang.client_mcp_installation import RegistrationRefused
    marker = "PRIVATE-PATH-MUST-NOT-LEAK"
    reached = []
    def refuse(*args, **kwargs):
        reached.append(True)
        raise RegistrationRefused(marker)
    monkeypatch.setattr(registration, "preview_hooks", refuse, raising=False)
    monkeypatch.setattr(registration, "register", refuse)
    for body in ({"client": "codex", "action": "preview-hooks"}, {"client": "codex", "consent": True}):
        result = call(server, "/api/universal/assistant-registration", body, expected=400)
        assert marker not in json.dumps(result)
    assert len(reached) == 2  # both refusals came from the writer, not from body validation


def test_cli_handles_registration_refusal_without_traceback(inputs, monkeypatch, capsys):
    from nodelang.client_mcp_installation import RegistrationRefused
    def refuse(*args, **kwargs):
        raise RegistrationRefused("fixture refusal")
    monkeypatch.setattr(config, "write_with_backup", refuse)
    monkeypatch.setattr(config, "render_skill", lambda *args: "fixture")
    home, gate, python, backup = inputs
    result = config.main(["skill", "--write", str(home / "skill.md"),
                          "--backup-dir", str(backup)])
    assert result != 0
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows path identity")
@pytest.mark.parametrize("vendor", ["claude-code", "codex"])
def test_case_and_slash_equivalence_never_rewrites_existing_command(inputs, vendor):
    home, gate, python, _ = inputs
    managed = config.render_client_hooks(vendor, python_executable=python,
                                        gate_script=gate, install_root=home)
    for groups in managed.values():
        hook = groups[0]["hooks"][0]
        hook["command"] = hook["command"].replace(str(python).replace("\\", "/"),
                                                   str(python).replace("\\", "/").upper())
    target = home / config._HOOK_CLIENTS[vendor][0]
    raw = json.dumps({"hooks": managed}, separators=(",", ":")).encode()
    target.write_bytes(raw)
    plan = config.plan_client_hook_install(vendor, home=home, install_root=home,
                                          python_executable=python, gate_script=gate)
    assert plan["changed"] is False
    assert plan["after_digest"] == hashlib.sha256(raw).hexdigest()


def test_binding_observation_keeps_original_path_spelling(inputs):
    home, gate, python, _ = inputs
    managed = config.render_client_hooks("claude-code", python_executable=python,
                                        gate_script=gate, install_root=home)
    target = home / config._HOOK_CLIENTS["claude-code"][0]
    target.write_text(json.dumps({"hooks": managed}), encoding="utf-8")
    executable, script = config.observed_client_hook_binding("claude-code", home=home)
    assert executable == str(python).replace("\\", "/")
    assert script == str(gate).replace("\\", "/")


# Integrator fixes after the independent verify of v3 (logged in installer-v4 notes).

def _git_bash():
    import os, shutil
    git = shutil.which("git")
    if os.name != "nt" or not git:
        return None
    base = Path(git).resolve().parent.parent
    for candidate in (base / "bin" / "bash.exe", base / "usr" / "bin" / "bash.exe"):
        if candidate.is_file():
            return candidate
    return None


def _unquoted_backslash_settings(vendor, python, gate):
    command = str(python).replace("/", "\\") + " " + str(gate).replace("/", "\\") + \
        " --vendor " + config._HOOK_CLIENTS[vendor][1]
    pre, post = config._HOOK_CLIENTS[vendor][2:4]
    return {"hooks": {event: [{"matcher": "Write|Edit", "hooks": [
        {"type": "command", "command": command, "timeout": 41}]}] for event in (pre, post)}}, command


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows backslash paths")
def test_claude_unquoted_backslash_hook_is_repair_available_and_repairs_to_a_bash_runnable_command(
        tmp_path, inputs):
    import subprocess, sys
    from nodelang import assistant_registration as registration
    home, _, _, _ = inputs
    gate = tmp_path / "00.GOVERNANCE" / "hooks" / "agent_scope_gate.py"
    marker = tmp_path / "gate-ran.txt"
    gate.write_text("import pathlib, sys\npathlib.Path(%r).write_text(' '.join(sys.argv[1:]))\n"
                    % str(marker), encoding="utf-8")
    python = Path(sys.executable)
    settings, broken = _unquoted_backslash_settings("claude-code", python, gate)
    target = home / ".claude" / "settings.json"
    target.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    env = {"USERPROFILE": str(home), "ARCHHUB_TEST_STATE_DIR": str(tmp_path / "state")}
    assert registration.hook_readiness("claude-code", environment=env)["state"] == "repair_available"
    preview = registration.preview_hooks("claude-code", environment=env)
    assert preview["changed"] is True
    result = registration.repair_hooks("claude-code", consent=True,
                                       plan_digest=preview["plan_digest"], environment=env)
    assert result["changed"] is True
    repaired = json.loads(target.read_text(encoding="utf-8"))
    for event in ("PreToolUse", "PostToolUse"):
        group = repaired["hooks"][event]
        assert len(group) == 1 and group[0]["matcher"] == "Write|Edit"
        hook = group[0]["hooks"][0]
        assert hook["timeout"] == 41 and hook["command"] != broken and "\\" not in hook["command"]
    assert registration.hook_readiness("claude-code", environment=env)["state"] == "configured"
    bash = _git_bash()
    if bash is None:
        pytest.skip("Git Bash is not installed")
    command = repaired["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
    before = subprocess.run([str(bash), "-c", broken], capture_output=True, text=True, timeout=60)
    assert before.returncode == 127 and not marker.exists()
    after = subprocess.run([str(bash), "-c", command], capture_output=True, text=True, timeout=60)
    assert after.returncode == 0, after.stderr
    assert marker.read_text() == "--vendor claude"


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows backslash paths")
def test_codex_unquoted_backslash_hook_stays_a_byte_for_byte_no_op(inputs):
    home, gate, python, _ = inputs
    settings, _ = _unquoted_backslash_settings("codex", python, gate)
    target = home / ".codex" / "hooks.json"
    raw = (json.dumps(settings, indent=2) + "\n").encode()
    target.write_bytes(raw)
    plan = config.plan_client_hook_install("codex", home=home, install_root=home,
                                          python_executable=python, gate_script=gate)
    assert plan["changed"] is False and plan["after_digest"] == hashlib.sha256(raw).hexdigest()


def test_hook_preview_sent_to_the_browser_contains_no_path(tmp_path, inputs):
    from nodelang import assistant_registration as registration
    home, gate, python, _ = inputs
    managed = config.render_client_hooks("claude-code", python_executable=python,
                                        gate_script=gate, install_root=home)
    (home / ".claude" / "settings.json").write_text(json.dumps({"hooks": managed}), encoding="utf-8")
    env = {"USERPROFILE": str(home), "ARCHHUB_TEST_STATE_DIR": str(tmp_path / "state")}
    text = json.dumps(registration.preview_hooks("claude-code", environment=env))
    assert "adapter" not in text and "interpreter" not in text
    for spelling in (str(tmp_path), tmp_path.as_posix(), "agent_scope_gate", "python.exe"):
        assert spelling.casefold() not in text.casefold()
    assert ":\\\\" not in text and ":/" not in text


@pytest.mark.parametrize("indent", [4, "\t", 2])
def test_repair_keeps_the_files_own_indent(inputs, indent):
    home, gate, python, _ = inputs
    target = home / ".codex" / "hooks.json"
    existing = {"theme": {"keep": True}, "hooks": {"SessionStart": [
        {"hooks": [{"type": "command", "command": "my-existing-hook"}]}]}}
    target.write_bytes((json.dumps(existing, indent=indent) + "\n").encode())
    plan = config.plan_client_hook_install("codex", home=home, install_root=home,
                                          python_executable=python, gate_script=gate)
    assert plan["changed"] is True
    assert plan["text"] == json.dumps(json.loads(plan["text"]), indent=indent) + "\n"
