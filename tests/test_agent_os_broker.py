from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import agent_os_broker as broker  # noqa: E402


class FakeProcess:
    pid = 123


def test_brainwrap_argv_launches_target_as_governed_strict():
    config = {
        "pythonw": "C:\\Python\\pythonw.exe",
        "brainwrap": "C:\\ArchHub\\tools\\brainwrap.py",
        "workspace_root": "C:\\Users\\fargaly\\00.ARCHUB",
        "apps": {
            "Codex": {"path": "C:\\Apps\\Codex\\Codex.exe"},
        },
    }
    payload = {
        "target": "C:\\Apps\\Codex\\Codex.exe",
        "args": ["--new-window"],
    }

    argv = broker.brainwrap_argv(config, payload)

    assert argv[:6] == [
        "C:\\Python\\pythonw.exe",
        "C:\\ArchHub\\tools\\brainwrap.py",
        "launch",
        "--governed-strict",
        "--cwd",
        "C:\\Users\\fargaly\\00.ARCHUB",
    ]
    assert argv[-3:] == ["--", "C:\\Apps\\Codex\\Codex.exe", "--new-window"]


def test_launch_governed_disables_ifeo_only_around_brainwrap_launch():
    events = []
    config = {
        "pythonw": "C:\\Python\\pythonw.exe",
        "brainwrap": "C:\\ArchHub\\tools\\brainwrap.py",
        "workspace_root": "C:\\Users\\fargaly\\00.ARCHUB",
        "apps": {
            "Codex": {"path": "C:\\Apps\\Codex\\Codex.exe"},
        },
    }
    payload = {
        "app": "Codex",
        "target": "C:\\Apps\\Codex\\Codex.exe",
        "args": [],
        "workshop_authority_required": True,
    }

    result = broker.launch_governed(
        config,
        payload,
        set_ifeo_fn=lambda cfg, app, enabled: events.append((app, enabled)),
        popen_fn=lambda argv, **_kwargs: events.append(("popen", argv)) or FakeProcess(),
    )

    assert result == {"ok": True, "pid": 123}
    assert events[0] == ("Codex", False)
    assert events[1][0] == "popen"
    assert "--governed-strict" in events[1][1]
    assert events[2] == ("Codex", True)


def test_dispatch_launch_rejects_chromium_child_processes():
    config = {
        "pythonw": "C:\\Python\\pythonw.exe",
        "brainwrap": "C:\\ArchHub\\tools\\brainwrap.py",
        "workspace_root": "C:\\Users\\fargaly\\00.ARCHUB",
        "apps": {
            "Antigravity": {"path": "C:\\Apps\\Antigravity\\Antigravity.exe"},
        },
    }
    payload = {
        "app": "Antigravity",
        "target": "C:\\Apps\\Antigravity\\Antigravity.exe",
        "args": ["--type=gpu-process", "--user-data-dir=C:\\Users\\fargaly\\AppData\\Roaming\\Antigravity"],
        "launch_kind": "app_child",
    }

    result = broker.dispatch_launch(
        config,
        payload,
        set_ifeo_fn=lambda *_args: (_ for _ in ()).throw(AssertionError("should not change IFEO")),
        popen_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not launch")),
    )

    assert result["ok"] is False
    assert "cannot pass through child process" in result["error"]


def test_reconcile_ifeo_config_removes_cleanup_entries_and_enables_supported_entries():
    events = []
    config = {
        "ifeo_cleanup_entries": [
            {"app": "Antigravity"},
            {"app": "Codex"},
        ],
        "ifeo_entries": [
            {"app": "Codex"},
        ],
    }

    result = broker.reconcile_ifeo_config(
        config,
        set_ifeo_fn=lambda cfg, app, enabled: events.append((app, enabled)),
    )

    assert result == {"ok": True, "removed": 2, "enabled": 1}
    assert events == [
        ("Antigravity", False),
        ("Codex", False),
        ("Codex", True),
    ]


def test_launch_governed_rejects_target_not_declared_in_config():
    config = {
        "pythonw": "C:\\Python\\pythonw.exe",
        "brainwrap": "C:\\ArchHub\\tools\\brainwrap.py",
        "workspace_root": "C:\\Users\\fargaly\\00.ARCHUB",
        "apps": {
            "Codex": {"path": "C:\\Apps\\Codex\\Codex.exe"},
        },
    }
    payload = {
        "app": "Codex",
        "target": "C:\\Windows\\System32\\cmd.exe",
        "args": [],
    }

    result = broker.launch_governed(
        config,
        payload,
        set_ifeo_fn=lambda *_args: None,
        popen_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not launch")),
    )

    assert result["ok"] is False
    assert "target mismatch" in result["error"]


def test_launch_governed_rejects_missing_workshop_authority_marker():
    config = {
        "pythonw": "C:\\Python\\pythonw.exe",
        "brainwrap": "C:\\ArchHub\\tools\\brainwrap.py",
        "workspace_root": "C:\\Users\\fargaly\\00.ARCHUB",
        "workshop_authority_required": True,
        "apps": {
            "Codex": {"path": "C:\\Apps\\Codex\\Codex.exe"},
        },
    }
    payload = {
        "app": "Codex",
        "target": "C:\\Apps\\Codex\\Codex.exe",
        "args": [],
    }

    result = broker.launch_governed(
        config,
        payload,
        set_ifeo_fn=lambda *_args: None,
        popen_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not launch")),
    )

    assert result["ok"] is False
    assert "workshop authority marker missing" in result["error"]
