"""Governed session bootstrap tests.

This pins the non-technical launch layer: future agent sessions should route
through brainwrap --governed-strict automatically, while already-running
sessions are audited and reported for restart instead of pretending that their
process environment can be mutated after launch.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import governed_sessions as gs  # noqa: E402


def test_powershell_profile_block_wraps_agent_commands(tmp_path):
    block = gs.powershell_profile_block(
        python_exe=Path("C:/Python/python.exe"),
        brainwrap=tmp_path / "tools" / "brainwrap.py",
        workspace_root=tmp_path,
        shim_dir=tmp_path / "governed-bin",
        commands=("codex", "claude", "gemini"),
    )

    assert gs.PROFILE_BEGIN in block
    assert "function codex" in block
    assert "function claude" in block
    assert "function gemini" in block
    assert "--governed-strict" in block
    assert "Get-Command $Name -All" in block
    assert "CommandType -eq 'Application'" in block
    assert "$resolved.Path" in block
    assert "brainwrap.py" in block


def test_upsert_profile_block_preserves_user_content(tmp_path):
    profile = tmp_path / "profile.ps1"
    profile.write_text(
        "Write-Host before\n"
        f"{gs.PROFILE_BEGIN}\nold managed\n{gs.PROFILE_END}\n"
        "Write-Host after\n",
        encoding="utf-8",
    )

    result = gs.upsert_managed_block(profile, "new managed block\n", dry_run=False)
    text = profile.read_text(encoding="utf-8")

    assert result["changed"] is True
    assert "Write-Host before" in text
    assert "Write-Host after" in text
    assert "old managed" not in text
    assert text.count(gs.PROFILE_BEGIN) == 1
    assert "new managed block" in text
    assert Path(result["backup_path"]).exists()


def test_upsert_profile_block_is_idempotent_when_block_starts_file(tmp_path):
    profile = tmp_path / "profile.ps1"
    block = gs.powershell_profile_block(
        python_exe=Path("C:/Python/python.exe"),
        brainwrap=tmp_path / "tools" / "brainwrap.py",
        workspace_root=tmp_path,
        shim_dir=tmp_path / "governed-bin",
        commands=("codex",),
    )

    first = gs.upsert_managed_block(profile, block, dry_run=False)
    second = gs.upsert_managed_block(profile, block, dry_run=False)

    assert first["changed"] is True
    assert second["changed"] is False
    assert profile.read_text(encoding="utf-8").startswith(gs.PROFILE_BEGIN)


def test_cmd_shim_uses_absolute_target_to_avoid_recursion(tmp_path):
    target = tmp_path / "real" / "codex.exe"
    target.parent.mkdir()
    target.write_text("", encoding="utf-8")

    text = gs.cmd_shim_text(
        command="codex",
        target=target,
        python_exe=Path("C:/Python/python.exe"),
        brainwrap=tmp_path / "tools" / "brainwrap.py",
        workspace_root=tmp_path,
    )

    assert "--governed-strict" in text
    assert str(target) in text
    assert " -- codex " not in text.lower()
    assert "brainwrap.py" in text


def test_cmd_shim_install_is_idempotent_with_crlf(tmp_path, monkeypatch):
    real_bin = tmp_path / "real-bin"
    real_bin.mkdir()
    target = real_bin / "codex.exe"
    target.write_text("", encoding="utf-8")
    shim_dir = tmp_path / "governed-bin"
    monkeypatch.setenv("PATH", str(real_bin))

    first = gs.install_cmd_shims(
        shim_dir=shim_dir,
        commands=("codex",),
        python_exe=Path("C:/Python/python.exe"),
        brainwrap=tmp_path / "tools" / "brainwrap.py",
        workspace_root=tmp_path,
        dry_run=False,
    )
    second = gs.install_cmd_shims(
        shim_dir=shim_dir,
        commands=("codex",),
        python_exe=Path("C:/Python/python.exe"),
        brainwrap=tmp_path / "tools" / "brainwrap.py",
        workspace_root=tmp_path,
        dry_run=False,
    )

    assert first[0]["changed"] is True
    assert second[0]["changed"] is False
    assert (shim_dir / "codex.cmd").read_bytes().count(b"\r\n") >= 1


def test_running_session_audit_marks_ungoverned_for_restart():
    report = gs.summarize_running_sessions(
        {
            "ok": True,
            "agent_process_count": 2,
            "ungoverned_count": 1,
            "sessions": [
                {"pid": 1, "name": "codex.exe", "status": "needs_restart"},
                {"pid": 2, "name": "claude.exe", "status": "governed"},
            ],
            "actions": [
                {
                    "pid": 1,
                    "action": "restart_under_governed_launcher",
                    "reason": "missing marker",
                }
            ],
        }
    )

    assert report["ok"] is True
    assert report["can_hot_attach"] is False
    assert report["current_sessions_need_restart"] == 1
    assert report["current_sessions_governed"] == 1
    assert report["actions"][0]["action"] == "restart_under_governed_launcher"


def test_quarantine_ungoverned_sessions_records_no_restart_state(tmp_path):
    quarantine_path = tmp_path / "quarantine.json"

    result = gs.quarantine_ungoverned_sessions(
        {
            "current_sessions_total": 2,
            "current_sessions_governed": 1,
            "current_sessions_need_restart": 1,
            "sessions": [
                {"pid": 1, "name": "codex.exe", "status": "needs_restart"},
                {"pid": 2, "name": "claude.exe", "status": "governed"},
            ],
        },
        quarantine_path=quarantine_path,
    )

    payload = json.loads(quarantine_path.read_text(encoding="utf-8"))
    assert result["ok"] is True
    assert result["mode"] == "no_restart_quarantine"
    assert result["quarantined_count"] == 1
    assert payload["sessions"][0]["status"] == "quarantined_untrusted"
    assert payload["sessions"][0]["original_status"] == "needs_restart"
    assert "retroactive audit" in payload["policy"]["effect"].lower()


def test_desktop_watchdog_restarts_only_primary_ungoverned_apps(tmp_path):
    actions = gs.desktop_watchdog_plan(
        {
            "sessions": [
                {
                    "pid": 1,
                    "name": "Codex.exe",
                    "status": "needs_restart",
                    "command_line": '"C:/Apps/Codex/Codex.exe"',
                },
                {
                    "pid": 4,
                    "parent_pid": 1,
                    "name": "codex.exe",
                    "status": "needs_restart",
                    "command_line": '"C:/Apps/Codex/resources/codex.exe" app-server',
                },
                {
                    "pid": 2,
                    "name": "language_server.exe",
                    "status": "needs_restart",
                    "command_line": "language_server.exe --standalone",
                },
                {
                    "pid": 3,
                    "name": "Claude.exe",
                    "status": "governed",
                    "command_line": '"C:/Apps/Claude/Claude.exe"',
                },
            ]
        },
        pythonw=Path("C:/Python/pythonw.exe"),
        brainwrap=tmp_path / "tools" / "brainwrap.py",
        workspace_root=tmp_path,
    )

    assert len(actions) == 1
    assert actions[0]["pid"] == 1
    assert actions[0]["action"] == "restart_desktop_app_governed"
    assert actions[0]["kill_tree"] is True
    assert actions[0]["argv"][:3] == [
        "C:/Python/pythonw.exe",
        str(tmp_path / "tools" / "brainwrap.py").replace("\\", "/"),
        "launch",
    ]
    assert "--governed-strict" in actions[0]["argv"]
    assert actions[0]["argv"][-1] == "C:/Apps/Codex/Codex.exe"


def test_watchdog_startup_task_uses_pythonw_and_desktop_watchdog(tmp_path):
    spec = gs.watchdog_startup_task_spec(
        pythonw=Path("C:/Python/pythonw.exe"),
        watchdog=tmp_path / "tools" / "agent_desktop_watchdog.py",
        interval_sec=7,
        dry_run=True,
    )

    assert spec["task_name"] == "ArchHub-Governed-Agent-Watchdog"
    assert spec["trigger"] == "AtLogOn"
    assert spec["argv"][:2] == [
        "C:/Python/pythonw.exe",
        str(tmp_path / "tools" / "agent_desktop_watchdog.py").replace("\\", "/"),
    ]
    assert "--interval-sec" in spec["argv"]
    assert "7" in spec["argv"]
    assert "--apply" not in spec["argv"]


def test_governed_shortcut_spec_wraps_window_app_with_brainwrap(tmp_path):
    spec = gs.governed_shortcut_spec(
        name="Codex",
        app=Path("C:/Apps/Codex/Codex.exe"),
        shortcut_path=tmp_path / "Codex.lnk",
        pythonw=Path("C:/Python/pythonw.exe"),
        brainwrap=tmp_path / "tools" / "brainwrap.py",
        workspace_root=tmp_path,
    )

    assert spec["path"] == str(tmp_path / "Codex.lnk")
    assert spec["target"] == "C:/Python/pythonw.exe"
    assert "--governed-strict" in spec["arguments"]
    assert "brainwrap.py" in spec["arguments"]
    assert "Codex.exe" in spec["arguments"]
    assert spec["working_directory"] == str(tmp_path)


def test_install_governed_shortcuts_writes_existing_shortcut_path(tmp_path):
    written = []

    result = gs.install_governed_desktop_shortcuts(
        apps={"Codex": Path("C:/Apps/Codex/Codex.exe")},
        shortcut_paths={"Codex": [tmp_path / "Codex.lnk"]},
        pythonw=Path("C:/Python/pythonw.exe"),
        brainwrap=tmp_path / "tools" / "brainwrap.py",
        workspace_root=tmp_path,
        shortcut_writer=lambda spec: written.append(spec) or {"ok": True, "changed": True},
    )

    assert result["ok"] is True
    assert result["changed"] is True
    assert result["shortcuts"][0]["path"] == str(tmp_path / "Codex.lnk")
    assert written[0]["name"] == "Codex"


def test_desktop_apps_from_sessions_discovers_store_window_apps():
    apps = gs.desktop_apps_from_sessions(
        {
            "sessions": [
                {
                    "name": "Codex.exe",
                    "command_line": '"C:/Program Files/WindowsApps/OpenAI.Codex/app/Codex.exe"',
                },
                {
                    "pid": 2,
                    "name": "claude.exe",
                    "command_line": '"C:/Program Files/WindowsApps/Claude/app/Claude.exe"',
                },
                {
                    "pid": 3,
                    "parent_pid": 2,
                    "name": "claude.exe",
                    "command_line": '"C:/Users/fargaly/AppData/Roaming/Claude/claude-code/claude.exe" --model default',
                },
                {
                    "name": "codex.exe",
                    "command_line": '"C:/Program Files/WindowsApps/OpenAI.Codex/app/resources/codex.exe" app-server',
                },
            ]
        }
    )

    assert apps == {
        "Codex": Path("C:/Program Files/WindowsApps/OpenAI.Codex/app/Codex.exe"),
        "Claude": Path("C:/Program Files/WindowsApps/Claude/app/Claude.exe"),
    }


def test_hard_enforcement_spec_intercepts_ifeo_safe_apps_with_filters(tmp_path):
    spec = gs.hard_enforcement_spec(
        apps={"SafeTool": Path("C:/Tools/SafeTool/SafeTool.exe")},
        package_dir=tmp_path / "hard",
        pythonw=Path("C:/Python/pythonw.exe"),
        workspace_root=tmp_path,
        brainwrap=tmp_path / "tools" / "brainwrap.py",
        gate=tmp_path / "tools" / "agent_os_gate.py",
        broker=tmp_path / "tools" / "agent_os_broker.py",
    )

    assert spec["mode"] == "ifeo_broker"
    assert spec["admin_required"] is True
    assert spec["task_name"] == "ArchHub-Governed-OS-Broker"
    assert spec["broker_url"] == "http://127.0.0.1:8476"
    assert spec["workshop_authority_required"] is True
    entry = spec["ifeo_entries"][0]
    assert entry["image_name"] == "SafeTool.exe"
    assert entry["filter_full_path"] == "C:\\Tools\\SafeTool\\SafeTool.exe"
    assert entry["registry_path"].endswith(
        "\\Image File Execution Options\\SafeTool.exe\\ArchHub-SafeTool"
    )
    assert "agent_os_gate.py" in entry["debugger"]
    assert "ifeo" in entry["debugger"]
    assert "--app SafeTool" in entry["debugger"]


def test_hard_enforcement_spec_cleans_up_multiprocess_desktop_ifeo_filters(tmp_path):
    spec = gs.hard_enforcement_spec(
        apps={"Antigravity": Path("C:/Apps/Antigravity/Antigravity.exe")},
        package_dir=tmp_path / "hard",
        pythonw=Path("C:/Python/pythonw.exe"),
        workspace_root=tmp_path,
        brainwrap=tmp_path / "tools" / "brainwrap.py",
        gate=tmp_path / "tools" / "agent_os_gate.py",
        broker=tmp_path / "tools" / "agent_os_broker.py",
    )

    assert spec["ifeo_entries"] == []
    cleanup = spec["ifeo_cleanup_entries"][0]
    assert cleanup["app"] == "Antigravity"
    assert cleanup["ifeo_supported"] is False
    assert "multi-process desktop app" in cleanup["reason"]


def test_hard_enforcement_scripts_require_admin_and_set_ifeo_filters(tmp_path):
    spec = gs.hard_enforcement_spec(
        apps={"Claude": Path("C:/Program Files/WindowsApps/Claude/app/Claude.exe")},
        package_dir=tmp_path / "hard",
        pythonw=Path("C:/Python/pythonw.exe"),
        workspace_root=tmp_path,
        brainwrap=tmp_path / "tools" / "brainwrap.py",
        gate=tmp_path / "tools" / "agent_os_gate.py",
        broker=tmp_path / "tools" / "agent_os_broker.py",
    )

    install_script = spec["install_script"]
    uninstall_script = spec["uninstall_script"]
    assert "Test-IsAdmin" in install_script
    assert "throw \"Administrator rights required" in install_script
    assert "Image File Execution Options" in install_script
    assert "ifeo_cleanup_entries" in install_script
    assert "Get-NetTCPConnection" in install_script
    assert "Stop-Process" in install_script
    assert "UseFilter" in install_script
    assert "FilterFullPath" in install_script
    assert "Debugger" in install_script
    assert "New-ScheduledTaskAction" in install_script
    assert "Register-ScheduledTask" in install_script
    assert "agent_os_broker.py" in install_script
    assert "Remove-Item" in uninstall_script
    assert "ArchHub-Governed-OS-Broker" in uninstall_script


def test_write_hard_enforcement_package_writes_config_and_scripts(tmp_path):
    result = gs.write_hard_enforcement_package(
        apps={"Antigravity": Path("C:/Apps/Antigravity/Antigravity.exe")},
        package_dir=tmp_path / "hard",
        pythonw=Path("C:/Python/pythonw.exe"),
        workspace_root=tmp_path,
        brainwrap=tmp_path / "tools" / "brainwrap.py",
        gate=tmp_path / "tools" / "agent_os_gate.py",
        broker=tmp_path / "tools" / "agent_os_broker.py",
        dry_run=False,
    )

    assert result["ok"] is True
    assert result["changed"] is True
    config = json.loads((tmp_path / "hard" / "hard-enforcement.json").read_text(encoding="utf-8"))
    assert config["apps"]["Antigravity"]["path"] == "C:\\Apps\\Antigravity\\Antigravity.exe"
    assert config["workshop_authority_required"] is True
    assert config["ifeo_entries"] == []
    assert config["ifeo_cleanup_entries"][0]["app"] == "Antigravity"
    assert (tmp_path / "hard" / "install-hard-enforcement.ps1").exists()
    assert (tmp_path / "hard" / "uninstall-hard-enforcement.ps1").exists()


def test_install_bootstrap_includes_os_hard_enforcement_package(tmp_path, monkeypatch):
    monkeypatch.setattr(gs, "powershell_profile_paths", lambda: [tmp_path / "profile.ps1"])
    monkeypatch.setattr(gs, "install_cmd_shims", lambda **_kwargs: [])
    monkeypatch.setattr(gs, "ensure_user_path_contains", lambda *_args, **_kwargs: {"changed": False})
    monkeypatch.setattr(gs, "install_native_hooks", lambda **_kwargs: {"ok": True})
    monkeypatch.setattr(gs, "install_desktop_watchdog", lambda **_kwargs: {"ok": True, "changed": False})
    monkeypatch.setattr(gs, "install_governed_desktop_shortcuts", lambda **_kwargs: {"ok": True, "changed": False})
    monkeypatch.setattr(gs, "audit_running_sessions", lambda: {"ok": True, "sessions": [], "actions": []})
    monkeypatch.setattr(
        gs,
        "write_hard_enforcement_package",
        lambda **_kwargs: {"ok": True, "mode": "ifeo_broker", "admin_required": True},
    )

    report = gs.install_bootstrap(dry_run=True)

    assert report["os_hard_enforcement"] == {
        "ok": True,
        "mode": "ifeo_broker",
        "admin_required": True,
    }


def test_watchdog_startup_launcher_writes_hidden_user_launcher(tmp_path):
    launcher = tmp_path / "Startup" / "ArchHub-Governed-Agent-Watchdog.vbs"

    first = gs.install_watchdog_startup_launcher(
        launcher_path=launcher,
        pythonw=Path("C:/Python/pythonw.exe"),
        watchdog=tmp_path / "tools" / "agent_desktop_watchdog.py",
        interval_sec=9,
        dry_run=False,
    )
    second = gs.install_watchdog_startup_launcher(
        launcher_path=launcher,
        pythonw=Path("C:/Python/pythonw.exe"),
        watchdog=tmp_path / "tools" / "agent_desktop_watchdog.py",
        interval_sec=9,
        dry_run=False,
    )

    text = launcher.read_text(encoding="utf-8")
    assert first["ok"] is True
    assert first["method"] == "startup_folder"
    assert first["changed"] is True
    assert second["changed"] is False
    assert "WScript.Shell" in text
    assert "agent_desktop_watchdog.py" in text
    assert "--apply" not in text
    assert ", 0, False" in text


def test_watchdog_helper_subprocesses_are_hidden_on_windows():
    kwargs = gs._hidden_subprocess_kwargs()

    if sys.platform.startswith("win"):
        assert kwargs["creationflags"] == gs.subprocess.CREATE_NO_WINDOW
    else:
        assert kwargs == {}


def test_desktop_watchdog_install_falls_back_to_startup_launcher_on_access_denied():
    result = gs.install_desktop_watchdog(
        task_installer=lambda dry_run, interval_sec: {
            "ok": False,
            "stderr": "ERROR: Access is denied.",
        },
        launcher_installer=lambda dry_run, interval_sec: {
            "ok": True,
            "changed": True,
            "method": "startup_folder",
        },
    )

    assert result["ok"] is True
    assert result["method"] == "startup_folder"
    assert result["task"]["ok"] is False
    assert result["launcher"]["changed"] is True


def test_apply_desktop_watchdog_actions_kills_then_relaunches():
    killed = []
    launched = []

    results = gs.apply_desktop_watchdog_actions(
        [
            {
                "pid": 44,
                "name": "Codex.exe",
                "action": "restart_desktop_app_governed",
                "kill_tree": True,
                "argv": ["pythonw", "brainwrap.py", "launch", "--", "Codex.exe"],
            }
        ],
        kill_tree_fn=lambda pid: killed.append(pid) or {"ok": True},
        start_fn=lambda argv: launched.append(list(argv)) or {"ok": True, "pid": 55},
    )

    assert killed == [44]
    assert launched == [["pythonw", "brainwrap.py", "launch", "--", "Codex.exe"]]
    assert results[0]["ok"] is True
    assert results[0]["old_pid"] == 44
    assert results[0]["new_pid"] == 55


def test_taskkill_success_accepts_stale_child_errors_when_root_exited():
    assert gs._taskkill_success(
        pid=44,
        returncode=128,
        pid_exists_fn=lambda _pid: False,
    ) is True


def test_taskkill_success_rejects_error_when_root_still_exists():
    assert gs._taskkill_success(
        pid=44,
        returncode=128,
        pid_exists_fn=lambda _pid: True,
    ) is False
