from pathlib import Path
import os
import subprocess

import pytest

from nodelang.opencode_native_custody import OpenCodeProcessCustody, Process


def _reader(self_process, parent_process):
    by_pid = {self_process.pid: self_process, parent_process.pid: parent_process}
    return by_pid.__getitem__


def _process(pid, parent, executable, cwd, session):
    return Process(pid, 1.0 + pid, parent, str(Path(executable).resolve()), str(Path(cwd).resolve()), session)


def _env(tmp_path):
    local = tmp_path / "local"
    appdata = tmp_path / "roaming"
    cli = appdata / "npm" / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b"MZ")
    (cli.parent.parent / "package.json").write_text('{"name":"opencode-ai"}', encoding="utf-8")
    desktop = local / "Programs" / "@opencode-aidesktop" / "OpenCode.exe"
    desktop.parent.mkdir(parents=True)
    desktop.write_bytes(b"MZ")
    return {
        "LOCALAPPDATA": str(local),
        "APPDATA": str(appdata),
        "USERPROFILE": str(tmp_path / "home"),
        "PATH": str(appdata / "npm"),
    }, cli, desktop


def _write_cli(root):
    cli = root / "node_modules" / "opencode-ai" / "bin" / "opencode.exe"
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b"MZ")
    (cli.parent.parent / "package.json").write_text('{"name":"opencode-ai"}', encoding="utf-8")
    return cli


def _link_dir(target, link):
    try:
        os.symlink(target, link, target_is_directory=True)
        return
    except OSError:
        pass
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                            text=True, capture_output=True)
    if result.returncode != 0:
        pytest.skip("directory symlink/junction unavailable")


def test_installed_desktop_parent_with_matching_session_is_trusted(tmp_path, monkeypatch):
    env, _cli, desktop = _env(tmp_path)
    self_process = _process(10, 20, tmp_path / "worker.exe", tmp_path, "ses_ok")
    parent_process = _process(20, 1, desktop, tmp_path, "")
    seen = []
    monkeypatch.setattr("os.getpid", lambda: 10)

    OpenCodeProcessCustody("ses_ok", environment=env, process_reader=_reader(self_process, parent_process),
                           session_reader=lambda parent, session, directory: seen.append((parent.executable, session, directory)))

    assert seen == [(str(desktop.resolve()), "ses_ok", str(tmp_path.resolve()))]


def test_installed_cli_parent_with_matching_session_is_trusted(tmp_path, monkeypatch):
    env, cli, _desktop = _env(tmp_path)
    self_process = _process(10, 20, tmp_path / "worker.exe", tmp_path, "ses_cli")
    parent_process = _process(20, 1, cli, tmp_path, "")
    seen = []
    monkeypatch.setattr("os.getpid", lambda: 10)

    OpenCodeProcessCustody("ses_cli", environment=env, process_reader=_reader(self_process, parent_process),
                           session_reader=lambda parent, session, directory: seen.append((parent.executable, session, directory)))

    assert seen == [(str(cli.resolve()), "ses_cli", str(tmp_path.resolve()))]


def test_path_injected_opencode_ai_package_is_refused(tmp_path, monkeypatch):
    env, _cli, _desktop = _env(tmp_path)
    fake = _write_cli(tmp_path / "fake-path")
    env["PATH"] = str(fake.parents[3]) + os.pathsep + env["PATH"]
    self_process = _process(10, 20, tmp_path / "worker.exe", tmp_path, "ses_fake")
    parent_process = _process(20, 1, fake, tmp_path, "")
    monkeypatch.setattr("os.getpid", lambda: 10)

    with pytest.raises(RuntimeError, match="requires its observed installed parent"):
        OpenCodeProcessCustody("ses_fake", environment=env, process_reader=_reader(self_process, parent_process),
                               session_reader=lambda *_: pytest.fail("PATH-injected parent reached session read"))


def test_approved_npm_root_symlink_escape_is_refused(tmp_path, monkeypatch):
    env, _cli, _desktop = _env(tmp_path)
    prefix = Path(env["APPDATA"]) / "npm"
    outside_package = tmp_path / "outside" / "opencode-ai"
    outside_cli = outside_package / "bin" / "opencode.exe"
    outside_cli.parent.mkdir(parents=True)
    outside_cli.write_bytes(b"MZ")
    (outside_package / "package.json").write_text('{"name":"opencode-ai"}', encoding="utf-8")
    escaped = prefix / "node_modules" / "opencode-ai"
    if escaped.exists():
        import shutil
        shutil.rmtree(escaped)
    escaped.parent.mkdir(parents=True, exist_ok=True)
    _link_dir(outside_package, escaped)
    self_process = _process(10, 20, tmp_path / "worker.exe", tmp_path, "ses_escape")
    parent_process = _process(20, 1, escaped / "bin" / "opencode.exe", tmp_path, "")
    monkeypatch.setattr("os.getpid", lambda: 10)

    with pytest.raises(RuntimeError, match="requires its observed installed parent"):
        OpenCodeProcessCustody("ses_escape", environment=env, process_reader=_reader(self_process, parent_process),
                               session_reader=lambda *_: pytest.fail("symlink escape reached session read"))


def test_desktop_prefix_lookalike_root_is_refused_before_session_read(tmp_path, monkeypatch):
    env, _cli, _desktop = _env(tmp_path)
    fake = Path(env["LOCALAPPDATA"]) / "Programs" / "@opencode-ai-fake" / "OpenCode.exe"
    fake.parent.mkdir(parents=True)
    fake.write_bytes(b"MZ")
    self_process = _process(10, 20, tmp_path / "worker.exe", tmp_path, "ses_fake_desktop")
    parent_process = _process(20, 1, fake, tmp_path, "")
    monkeypatch.setattr("os.getpid", lambda: 10)

    with pytest.raises(RuntimeError, match="requires its observed installed parent"):
        OpenCodeProcessCustody("ses_fake_desktop", environment=env, process_reader=_reader(self_process, parent_process),
                               session_reader=lambda *_: pytest.fail("desktop prefix lookalike reached session read"))


def test_desktop_root_junction_escape_is_refused_before_session_read(tmp_path, monkeypatch):
    env, _cli, desktop = _env(tmp_path)
    outside_root = tmp_path / "outside-desktop"
    outside_exe = outside_root / "OpenCode.exe"
    outside_root.mkdir()
    outside_exe.write_bytes(b"MZ")
    if desktop.parent.exists():
        import shutil
        shutil.rmtree(desktop.parent)
    _link_dir(outside_root, desktop.parent)
    self_process = _process(10, 20, tmp_path / "worker.exe", tmp_path, "ses_desktop_escape")
    parent_process = _process(20, 1, outside_exe, tmp_path, "")
    monkeypatch.setattr("os.getpid", lambda: 10)

    with pytest.raises(RuntimeError, match="requires its observed installed parent"):
        OpenCodeProcessCustody("ses_desktop_escape", environment=env, process_reader=_reader(self_process, parent_process),
                               session_reader=lambda *_: pytest.fail("desktop junction escape reached session read"))


def test_prefix_suffix_lookalike_root_is_refused(tmp_path, monkeypatch):
    env, _cli, _desktop = _env(tmp_path)
    fake = _write_cli(Path(env["APPDATA"]) / "npm-lookalike")
    self_process = _process(10, 20, tmp_path / "worker.exe", tmp_path, "ses_lookalike")
    parent_process = _process(20, 1, fake, tmp_path, "")
    monkeypatch.setattr("os.getpid", lambda: 10)

    with pytest.raises(RuntimeError, match="requires its observed installed parent"):
        OpenCodeProcessCustody("ses_lookalike", environment=env, process_reader=_reader(self_process, parent_process),
                               session_reader=lambda *_: pytest.fail("lookalike root reached session read"))


def test_unknown_parent_is_refused(tmp_path, monkeypatch):
    env, _cli, _desktop = _env(tmp_path)
    self_process = _process(10, 20, tmp_path / "worker.exe", tmp_path, "ses_bad")
    parent_process = _process(20, 1, tmp_path / "opencode.exe", tmp_path, "")
    monkeypatch.setattr("os.getpid", lambda: 10)

    with pytest.raises(RuntimeError, match="requires its observed installed parent"):
        OpenCodeProcessCustody("ses_bad", environment=env, process_reader=_reader(self_process, parent_process),
                               session_reader=lambda *_: None)


def test_session_mismatch_is_refused(tmp_path, monkeypatch):
    env, cli, _desktop = _env(tmp_path)
    self_process = _process(10, 20, tmp_path / "worker.exe", tmp_path, "ses_other")
    parent_process = _process(20, 1, cli, tmp_path, "")
    monkeypatch.setattr("os.getpid", lambda: 10)

    with pytest.raises(RuntimeError, match="requires its observed installed parent"):
        OpenCodeProcessCustody("ses_expected", environment=env, process_reader=_reader(self_process, parent_process),
                               session_reader=lambda *_: None)
