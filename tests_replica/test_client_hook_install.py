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


@pytest.fixture
def installed(tmp_path, monkeypatch):
    """A temp INSTALLED ArchHub layout (BUILD_METADATA.json marks an install, not a checkout)."""
    from nodelang import assistant_registration as registration
    root = tmp_path / "LocalAppData" / "ArchHub"
    for rel in (".venv/Scripts/python.exe", "nodelang/native_stop_hook.py"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("# court fixture; never executed\n", encoding="utf-8")
    (root / "BUILD_METADATA.json").write_text("{}", encoding="utf-8")
    state = tmp_path / "state"
    monkeypatch.setattr(registration, "install_roots", lambda environment=None: (root, state))
    return root


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
        tmp_path, inputs, installed):
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


def test_hook_preview_sent_to_the_browser_contains_no_path(tmp_path, inputs, installed):
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


# ---------------------------------------------------------------------------
# v7: ArchHub's own end-of-turn hook, from the INSTALLED copy, on one consent.

_STOP = {"claude-code": ("Stop", "claude-code"), "codex": ("Stop", "codex"),
         "gemini-cli": ("AfterAgent", "gemini")}


def _stop_command(root, flag):
    return '"%s" "%s" --vendor %s' % ((root / ".venv/Scripts/python.exe").as_posix(),
                                     (root / "nodelang/native_stop_hook.py").as_posix(), flag)


@pytest.mark.parametrize("vendor", sorted(_STOP))
def test_stop_hook_points_at_the_installed_copy_keeps_other_hooks_and_is_idempotent(
        inputs, installed, vendor):
    """Court: each client gets its end-of-turn entry, pointing at the installed copy."""
    home, _, _, backup = inputs
    event, flag = _STOP[vendor]
    target = home / config._HOOK_CLIENTS[vendor][0]
    theirs = {"type": "command", "command": "someone-elses-hook --keep", "timeout": 5}
    target.write_text(json.dumps({"model": "x", "hooks": {event: [{"hooks": [theirs]}]}}), encoding="utf-8")
    plan = config.plan_client_hook_install(vendor, home=home, install_root=installed, stop_root=installed)
    projected = json.loads(plan["text"])
    commands = [h["command"] for g in projected["hooks"][event] for h in g["hooks"]]
    assert commands == ["someone-elses-hook --keep", _stop_command(installed, flag)]
    assert projected["model"] == "x" and "00.ARCHUB" not in plan["text"]
    config.apply_client_hook_install(plan, expected_digest=plan["plan_digest"], backup_dir=backup)
    again = config.plan_client_hook_install(vendor, home=home, install_root=installed, stop_root=installed)
    assert again["changed"] is False
    assert config.hook_event_states(vendor, home=home, install_root=installed) == [
        {"event": event, "purpose": "end_of_turn_check", "state": "on", "roles": ["ours"]}]


def test_stop_hook_refuses_a_source_checkout(inputs, tmp_path):
    """Court: without an install (BUILD_METADATA.json) nothing points at a source path."""
    home, _, _, _ = inputs
    checkout = tmp_path / "00.ARCHUB" / "10.PRODUCT" / "13.NODE-LANGUAGE"
    for rel in (".venv/Scripts/python.exe", "nodelang/native_stop_hook.py"):
        (checkout / rel).parent.mkdir(parents=True, exist_ok=True)
        (checkout / rel).write_text("#", encoding="utf-8")
    with pytest.raises(config.SessionLinkConfigRefused, match="installed ArchHub"):
        config.render_stop_hook("claude-code", install_root=checkout)


def test_setup_leaves_the_workspace_gate_byte_identical_and_adds_only_the_stop_hook(
        inputs, installed, tmp_path):
    """Court: the installer never installs, rewrites or drops the workspace gate."""
    from nodelang import assistant_registration as registration
    home, gate, python, _ = inputs
    gate_hooks = config.render_client_hooks("claude-code", python_executable=python,
                                            gate_script=gate, install_root=home)
    broken = {"type": "command", "timeout": 41, "command": str(python).replace("/", "\\") + " "
              + str(gate).replace("/", "\\") + " --vendor claude"}
    gate_hooks["PreToolUse"][0]["hooks"].append(broken)
    target = home / ".claude" / "settings.json"
    target.write_text(json.dumps({"hooks": gate_hooks}, indent=2), encoding="utf-8")
    env = {"USERPROFILE": str(home)}
    results = registration.connect_hooks_on_setup(consent=True, environment=env)
    assert {r["client"]: r["state"] for r in results} == {
        "claude-code": "configured", "codex": "configured", "gemini-cli": "configured",
        "opencode": "not_installed"}
    after = json.loads(target.read_text(encoding="utf-8"))
    assert after["hooks"]["PreToolUse"] == gate_hooks["PreToolUse"]
    assert after["hooks"]["PostToolUse"] == gate_hooks["PostToolUse"]
    assert [h["command"] for h in after["hooks"]["Stop"][0]["hooks"]] == [
        _stop_command(installed, "claude-code")]
    with pytest.raises(ValueError):
        registration.connect_hooks_on_setup(consent=False, environment=env)


def test_setup_refuses_gemini_jsonc_and_a_hard_link_and_keeps_their_bytes(inputs, installed):
    """Court: the v5 refusals hold on the setup path."""
    import os
    from nodelang import assistant_registration as registration
    home, _, _, _ = inputs
    gemini = home / ".gemini" / "settings.json"
    gemini.write_bytes(b'{\n  // a comment\n  "theme": "x"\n}\n')
    claude = home / ".claude" / "settings.json"
    claude.write_bytes(b'{"hooks": {}}\n')
    os.link(claude, home / "twin.json")
    results = {r["client"]: r["state"] for r in registration.connect_hooks_on_setup(
        consent=True, environment={"USERPROFILE": str(home)})}
    assert results["gemini-cli"] == "not_connected" and results["claude-code"] == "not_connected"
    assert gemini.read_bytes() == b'{\n  // a comment\n  "theme": "x"\n}\n'
    assert claude.read_bytes() == (home / "twin.json").read_bytes() == b'{"hooks": {}}\n'


def test_setup_option_is_the_only_consent_and_writes_nothing_when_unticked(inputs, installed, monkeypatch, capsys):
    """Court: no marker, nothing written; the ticked option writes the stop hook once."""
    import colleague_setup
    home, _, _, _ = inputs
    monkeypatch.setenv("USERPROFILE", str(home))
    before = {p: p.read_bytes() if p.is_file() else None for p in home.rglob("*")}
    assert colleague_setup._assistant_hooks(installed) == []
    assert {p: p.read_bytes() if p.is_file() else None for p in home.rglob("*")} == before
    marker = installed / colleague_setup.ASSISTANT_HOOKS_CONSENT
    marker.write_text(colleague_setup.ASSISTANT_HOOKS_CONSENT_TEXT, encoding="ascii")
    rows = colleague_setup._assistant_hooks(installed)
    assert {r["client"] for r in rows if r["state"] == "configured"} == {"claude-code", "codex", "gemini-cli"}
    assert not marker.exists()
    stop = json.loads((home / ".codex" / "hooks.json").read_text(encoding="utf-8"))["hooks"]["Stop"]
    assert stop[0]["hooks"][0]["command"] == _stop_command(installed, "codex")
    assert "approve the new hook in Codex" in capsys.readouterr().out


def test_installer_offers_the_connect_option_ticked_by_default():
    """Court: one setup-page option, on by default, writing exactly the marker setup reads."""
    import re
    import colleague_setup
    iss = (Path(__file__).resolve().parents[1] / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    task = re.search(r'^Name: "connectassistants"; Description: "Connect my AI assistants to ArchHub[^\n]*$',
                     iss, re.M)
    assert task and "unchecked" not in task.group(0)
    assert ("WizardIsTaskSelected('connectassistants')" in iss
            and "'%s'" % colleague_setup.ASSISTANT_HOOKS_CONSENT_TEXT in iss
            and colleague_setup.ASSISTANT_HOOKS_CONSENT in iss)


def test_settings_shows_each_event_in_plain_words(inputs, installed):
    """Court: Settings > Assistants says, per event, whether the check is on; Codex approval
    stays with the person; OpenCode connects per session."""
    from nodelang import assistant_registration as registration
    home, _, _, _ = inputs
    env = {"USERPROFILE": str(home)}
    claude = registration.hook_readiness("claude-code", environment=env)
    assert claude["available"] is True and claude["state"] == "repair_available"
    assert [e["said"] for e in claude["events"]] == ["When a reply ends, ArchHub checks for open work: Off"]
    registration.connect_hooks_on_setup(consent=True, environment=env)
    for client, event in (("claude-code", "Stop"), ("codex", "Stop"), ("gemini-cli", "AfterAgent")):
        report = registration.hook_readiness(client, environment=env)
        assert report["state"] == "configured"
        assert report["events"][0]["event"] == event
        assert report["events"][0]["said"] == "When a reply ends, ArchHub checks for open work: On"
    assert registration.hook_readiness("codex", environment=env)["approval"] == "Approve in Codex"
    assert "approval" not in registration.hook_readiness("claude-code", environment=env)
    assert registration.hook_readiness("opencode", environment=env)["reason"] == "Connects when you open a session"
    text = (home / ".codex" / "hooks.json").read_text(encoding="utf-8")
    assert "trust" not in text.casefold() and not (home / ".codex" / "config.toml").exists()


# Every package a written hook or the MCP server imports must be declared for the installed venv.
_RECORDER = r"""
import builtins, importlib, json, sys
root, modules = sys.argv[1], sys.argv[2:]
seen, original = set(), builtins.__import__
def record(name, globals=None, locals=None, fromlist=(), level=0):
    caller = (globals or {}).get("__name__", "")
    if level == 0 and (caller.startswith("nodelang") or caller.startswith("app")):
        top = name.split(".")[0]
        if top not in sys.stdlib_module_names and top not in ("nodelang", "app", "__future__"):
            seen.add(top)
    return original(name, globals, locals, fromlist, level)
builtins.__import__ = record
sys.path.insert(0, root)
failed = []
for module in modules:
    try:
        importlib.import_module(module)
    except Exception as exc:
        failed.append("%s: %s" % (module, type(exc).__name__))
print(json.dumps({"third_party": sorted(seen), "failed": failed}))
"""
_PYWIN32 = ("pythoncom", "pywintypes", "winerror", "_win32typing")
_DECLARED = {"joserfc": "joserfc", "httpx": "httpx", "cryptography": "cryptography", "rpds-py": "rpds",
             "markdown-it-py": "markdown_it", "pydantic": "pydantic", "anyio": "anyio", "mcp": "mcp",
             "pyqt6": "PyQt6", "pyqt6-webengine": "PyQt6", "ezdxf": "ezdxf", "numpy": "numpy",
             "psutil": "psutil", "keyring": "keyring", "pywin32": "win32"}


def _declared_top_levels(root):
    import re
    names = set()
    for line in (root / "requirements.txt").read_text(encoding="utf-8").splitlines():
        found = re.match(r"\s*([A-Za-z0-9_.\-]+)", line.split("#")[0])
        if found:
            names.add(_DECLARED.get(found.group(1).lower(), found.group(1).lower()))
    return names


def test_every_written_hook_and_the_mcp_server_run_under_the_installed_venv(tmp_path):
    """Court: a clean temp install (payload copy + its own venv) runs each Stop command exactly as
    written, and every third-party module those entry points import is declared for the venv."""
    import ast, os, re, shutil, subprocess, sys, uuid
    from nodelang.client_mcp_installation import _require_plain  # noqa: F401 - same payload rules
    source = Path(__file__).resolve().parents[1]
    root = tmp_path / "LocalAppData" / "ArchHub"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", "*.sqlite3", "*.db", "node_modules")
    shutil.copytree(source / "nodelang", root / "nodelang", ignore=ignore)
    (root / "app").mkdir()
    for name in ("__init__.py", "secrets_store.py", "credential_lock.py"):
        shutil.copy2(source / "app" / name, root / "app" / name)
    shutil.copy2(source / "requirements.txt", root / "requirements.txt")
    (root / "BUILD_METADATA.json").write_text("{}", encoding="utf-8")
    # The wheelhouse stands in as this interpreter's site-packages; the venv itself is new.
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", "--system-site-packages",
                    str(root / ".venv")], check=True, timeout=300)
    home = tmp_path / "home"
    env = {**os.environ, "USERPROFILE": str(home), "LOCALAPPDATA": str(tmp_path / "LocalAppData"),
           "APPDATA": str(tmp_path / "AppData"), "PYTHONNOUSERSITE": "1"}
    for key in ("PYTHONPATH", "PYTHONHOME", "CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID",
                "ARCHHUB_EXTERNAL_SESSION_ID"):
        env.pop(key, None)
    env["ARCHHUB_TEST_STATE_DIR"] = str(tmp_path / "state")
    python_exe = str(root / ".venv/Scripts/python.exe")
    for vendor in _STOP:
        (home / config._HOOK_CLIENTS[vendor][0]).parent.mkdir(parents=True, exist_ok=True)
    # Install exactly as first open does: the installed interpreter, the installed package.
    connect = subprocess.run([python_exe, "-E", "-s", "-B", "-c",
                              "from nodelang.assistant_registration import connect_hooks_on_setup as c; "
                              "print(c(consent=True))"], cwd=root, capture_output=True, env=env, timeout=300)
    assert connect.returncode == 0 and connect.stdout.count(b"'configured'") == 3, connect.stderr[-2000:]
    for vendor, (event, flag) in sorted(_STOP.items()):
        settings = json.loads((home / config._HOOK_CLIENTS[vendor][0]).read_text(encoding="utf-8"))
        hook = settings["hooks"][event][0]["hooks"][0]
        python, script, args = config._hook_command_parts(hook)
        assert Path(python) == root / ".venv/Scripts/python.exe" and Path(script) == root / "nodelang/native_stop_hook.py"
        ran = subprocess.run([python, script, *args], input=json.dumps(
            {"session_id": str(uuid.uuid4()), "stop_hook_active": False}).encode(),
            capture_output=True, env=env, timeout=120)
        assert ran.returncode == 0 and b"Traceback" not in ran.stderr, ran.stderr[-2000:]
        assert type(json.loads(ran.stdout)) is dict
    hook_file = root / "nodelang" / "native_stop_hook.py"
    lazy = set()
    for node in ast.walk(ast.parse(hook_file.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            lazy.add("nodelang." + node.module)
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("nodelang."):
            lazy.add(node.module)
        elif isinstance(node, ast.Import):
            lazy.update(a.name for a in node.names if a.name.split(".")[0] not in sys.stdlib_module_names)
    modules = ["nodelang.native_stop_hook", "nodelang.native_agent_mcp", *sorted(lazy)]
    probe = subprocess.run([str(root / ".venv/Scripts/python.exe"), "-I", "-B", "-c", _RECORDER,
                            str(root), *modules], capture_output=True, env=env, timeout=300)
    assert probe.returncode == 0, probe.stderr[-2000:]
    report = json.loads(probe.stdout)
    assert report["failed"] == []
    declared = _declared_top_levels(source)
    direct = {name.split(".")[0] for name in lazy if not name.startswith("nodelang.")}
    undeclared = [name for name in sorted(set(report["third_party"]) | direct)
                  if name not in declared and not (name.startswith("win32") or name in _PYWIN32)]
    assert undeclared == [], undeclared
    # Uninstall exactly as ArchHub.iss spells it: every file ArchHub created goes again.
    iss = (source / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    arguments = re.search(r"'(-E -s -B -m nodelang\.assistant_registration disconnect-hooks)'", iss).group(1)
    gone = subprocess.run([python_exe, *arguments.split()], cwd=root, capture_output=True, env=env, timeout=300)
    assert gone.returncode == 0, gone.stderr[-2000:]
    assert [v for v in _STOP if (home / config._HOOK_CLIENTS[v][0]).exists()] == []



@pytest.mark.parametrize("vendor", sorted(_STOP))
def test_install_then_uninstall_leaves_the_settings_byte_equal(inputs, installed, vendor):
    """Court: uninstall puts every client file back byte-for-byte (odd spacing, CRLF, BOM),
    and a file ArchHub created is gone again."""
    from nodelang import assistant_registration as registration
    home, _, _, _ = inputs
    env = {"USERPROFILE": str(home)}
    target = home / config._HOOK_CLIENTS[vendor][0]
    original = b'\xef\xbb\xbf{"model":"x",  "hooks" : {"Other": [{"hooks": [{"type": "command", "command": "mine"}]}]}}\r\n'
    target.write_bytes(original)
    registration.connect_hooks_on_setup(consent=True, environment=env)
    assert target.read_bytes() != original
    registration.disconnect_hooks_on_uninstall(environment=env)
    assert target.read_bytes() == original
    for other in _STOP:
        if other != vendor:
            assert not (home / config._HOOK_CLIENTS[other][0]).exists()


def test_uninstall_after_later_edits_takes_out_only_our_entries(inputs, installed, tmp_path):
    """Court: a file changed since install keeps every change and every other hook; only
    this install's end-of-turn entries (matched by the installed path) go."""
    from nodelang import assistant_registration as registration
    home, _, _, _ = inputs
    env = {"USERPROFILE": str(home)}
    target = home / ".claude" / "settings.json"
    other_copy = {"type": "command", "command": '"C:/Elsewhere/python.exe" "C:/Elsewhere/nodelang/native_stop_hook.py" --vendor claude-code'}
    registration.connect_hooks_on_setup(consent=True, environment=env)
    settings = json.loads(target.read_text(encoding="utf-8"))
    settings["theme"] = "added after install"
    settings["hooks"]["Stop"][0]["hooks"].append({"type": "command", "command": "their-stop"})
    settings["hooks"]["Stop"].append({"hooks": [other_copy]})
    target.write_text(json.dumps(settings), encoding="utf-8")
    registration.disconnect_hooks_on_uninstall(environment=env)
    after = json.loads(target.read_text(encoding="utf-8"))
    assert after["theme"] == "added after install"
    assert after["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": "their-stop"}]},
                                      {"hooks": [other_copy]}]



# ---------------------------------------------------------------------------
# v8: another or stale ArchHub copy is reported and migrated only on review;
# Codex uses one effective home (CODEX_HOME) everywhere.

def _foreign_stop(tmp_path, *, exists):
    script = tmp_path / ("other-copy" if exists else "retired-source") / "nodelang" / "native_stop_hook.py"
    if exists:
        script.parent.mkdir(parents=True)
        script.write_text("# another ArchHub copy\n", encoding="utf-8")
    python = tmp_path / "other-python" / "python.exe"
    return {"type": "command", "timeout": 30,
            "command": '"%s" "%s" --vendor claude-code' % (python.as_posix(), script.as_posix())}


@pytest.mark.parametrize("exists,state,word", [(False, "stale", "missing file"),
                                               (True, "conflict", "another archhub copy")])
def test_setup_reports_another_or_stale_copy_and_never_claims_configured(
        inputs, installed, tmp_path, exists, state, word):
    """Court: a Stop check from another or a retired ArchHub copy is never silently kept as
    ours, never overwritten at setup, and never reported as configured for this install."""
    from nodelang import assistant_registration as registration
    home, _, _, _ = inputs
    env = {"USERPROFILE": str(home)}
    target = home / ".claude" / "settings.json"
    raw = json.dumps({"hooks": {"Stop": [{"hooks": [_foreign_stop(tmp_path, exists=exists)]}]}}).encode()
    target.write_bytes(raw)
    results = {r["client"]: r for r in registration.connect_hooks_on_setup(consent=True, environment=env)}
    assert results["claude-code"]["state"] == state and results["claude-code"]["changed"] is False
    assert target.read_bytes() == raw
    report = registration.hook_readiness("claude-code", environment=env)
    assert report["state"] == "migration_available" and report["available"] is True
    assert word in report["events"][0]["said"].casefold()


@pytest.mark.parametrize("exists", [False, True])
def test_reviewed_migration_leaves_exactly_this_installs_check(inputs, installed, tmp_path, exists):
    """Court: Repair previews the migration, applies only that reviewed digest, and leaves one
    Stop check (this install's) with every other hook kept."""
    from nodelang import assistant_registration as registration
    home, _, _, _ = inputs
    env = {"USERPROFILE": str(home)}
    target = home / ".claude" / "settings.json"
    theirs = {"type": "command", "command": "their-own-stop"}
    target.write_text(json.dumps({"hooks": {"Stop": [
        {"matcher": "keep-me", "hooks": [_foreign_stop(tmp_path, exists=exists), theirs]}]}}), encoding="utf-8")
    preview = registration.preview_hooks("claude-code", environment=env)
    assert preview["migration"] is True and "Repair moves it to this install" in preview["description"]
    target.write_text(target.read_text(encoding="utf-8").replace("keep-me", "keep-me-2"), encoding="utf-8")
    with pytest.raises(config.SessionLinkConfigRefused):
        registration.repair_hooks("claude-code", consent=True, plan_digest=preview["plan_digest"], environment=env)
    preview = registration.preview_hooks("claude-code", environment=env)
    registration.repair_hooks("claude-code", consent=True, plan_digest=preview["plan_digest"], environment=env)
    stop = json.loads(target.read_text(encoding="utf-8"))["hooks"]["Stop"]
    assert stop == [{"matcher": "keep-me-2", "hooks": [
        {"type": "command", "timeout": 30, "command": _stop_command(installed, "claude-code")}, theirs]}]
    assert registration.hook_readiness("claude-code", environment=env)["state"] == "configured"


def test_codex_home_is_the_one_place_for_install_readiness_and_uninstall(inputs, installed, tmp_path):
    """Court: with CODEX_HOME set, setup, Settings and uninstall all use <CODEX_HOME>/hooks.json
    and never touch %USERPROFILE%/.codex (which here is another, unrelated folder)."""
    from nodelang import assistant_registration as registration
    home, _, _, _ = inputs
    codex_home = tmp_path / "custom-codex-home"
    codex_home.mkdir()
    decoy = home / ".codex" / "hooks.json"
    decoy.write_bytes(b'{"hooks": {}}\n')
    env = {"USERPROFILE": str(home), "CODEX_HOME": str(codex_home)}
    results = {r["client"]: r["state"] for r in registration.connect_hooks_on_setup(consent=True, environment=env)}
    assert results["codex"] == "configured"
    stop = json.loads((codex_home / "hooks.json").read_text(encoding="utf-8"))["hooks"]["Stop"]
    assert stop[0]["hooks"][0]["command"] == _stop_command(installed, "codex")
    assert decoy.read_bytes() == b'{"hooks": {}}\n'
    report = registration.hook_readiness("codex", environment=env)
    assert report["state"] == "configured" and report["events"][0]["state"] == "on"
    registration.disconnect_hooks_on_uninstall(environment=env)
    assert not (codex_home / "hooks.json").exists()
    assert decoy.read_bytes() == b'{"hooks": {}}\n'
    missing = {"USERPROFILE": str(home), "CODEX_HOME": str(tmp_path / "no-such-codex-home")}
    assert registration.hook_readiness("codex", environment=missing)["state"] == "not_installed"



@pytest.mark.parametrize("exists,foreign", [(False, "stale"), (True, "other_copy")])
def test_mixed_own_and_foreign_check_is_disclosed_and_migrated_only_on_review(
        inputs, installed, tmp_path, exists, foreign):
    """Court: ours beside a stale or live other-copy check. Setup leaves the file unchanged and
    reports a conflict; Settings never lets "on" hide the foreign entry; the reviewed preview
    discloses the migration; afterwards exactly one check (ours) and unrelated hooks kept."""
    from nodelang import assistant_registration as registration
    home, _, _, _ = inputs
    env = {"USERPROFILE": str(home)}
    target = home / ".claude" / "settings.json"
    ours = {"type": "command", "timeout": 30, "command": _stop_command(installed, "claude-code")}
    theirs = {"type": "command", "command": "their-own-stop"}
    raw = json.dumps({"hooks": {"Stop": [{"hooks": [ours, theirs]},
                                         {"matcher": "x", "hooks": [_foreign_stop(tmp_path, exists=exists)]}]},
                      "keep": 1}).encode()
    target.write_bytes(raw)
    results = {r["client"]: r for r in registration.connect_hooks_on_setup(consent=True, environment=env)}
    assert results["claude-code"]["state"] == "conflict" and results["claude-code"]["changed"] is False
    assert results["claude-code"]["roles"] == sorted(["ours", foreign])
    assert target.read_bytes() == raw
    report = registration.hook_readiness("claude-code", environment=env)
    assert report["state"] == "migration_available"
    assert report["events"][0]["state"] == "on_with_" + foreign
    assert report["events"][0]["roles"] == sorted(["ours", foreign])
    assert "Repair leaves only this install's" in report["events"][0]["said"]
    preview = registration.preview_hooks("claude-code", environment=env)
    assert preview["migration"] is True and preview["changed"] is True
    assert "leaves only this install's" in preview["description"]
    registration.repair_hooks("claude-code", consent=True, plan_digest=preview["plan_digest"], environment=env)
    after = json.loads(target.read_text(encoding="utf-8"))
    stop_commands = [h["command"] for g in after["hooks"]["Stop"] for h in g["hooks"]]
    assert stop_commands == [ours["command"], "their-own-stop"]
    assert after["hooks"]["Stop"] == [{"hooks": [ours, theirs]}]  # the emptied group goes too
    assert after["keep"] == 1
    assert registration.hook_readiness("claude-code", environment=env)["state"] == "configured"
