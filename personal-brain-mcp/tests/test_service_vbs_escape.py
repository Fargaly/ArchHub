"""Regression: the Startup-folder .vbs shim must be VALID VBScript.

Root cause (founder hit it live, 2026-06-19): `_windows_install_startup_folder`
embedded `full_cmd` — which already wraps the python path in quotes for
`schtasks /tr` — directly into a VBScript string literal:

    oShell.Run "{full_cmd}", 0, False

VBScript escapes a literal `"` by DOUBLING it. The un-escaped form emitted
`oShell.Run ""C:\...python.exe" -m ...` which VBScript parses as an EMPTY string
("") immediately followed by a bare `C:\...` token → compile error 800A0401
"Expected end of statement" in a Windows Script Host popup at every logon, and
the brain never autostarted. The fix doubles the quotes before embedding.

These gates assert the emitted .vbs is a single well-formed string literal that
ROUND-TRIPS back to the original command (the real semantic check), plus a guard
for the exact broken byte-pattern. RED on the un-escaped code, GREEN after.
"""
from __future__ import annotations

import re

from personal_brain import service


def _emit_vbs(monkeypatch, tmp_path, full_cmd: str) -> str:
    # Both _windows_install_startup_folder and _startup_vbs_path resolve the
    # folder through _startup_folder_path — point it at a throwaway dir.
    monkeypatch.setattr(service, "_startup_folder_path", lambda: tmp_path)
    res = service._windows_install_startup_folder(full_cmd)
    assert res.get("ok") is True, res
    return (tmp_path / "ArchHub-Brain.vbs").read_text(encoding="utf-8")


def test_vbs_quotes_round_trip(monkeypatch, tmp_path):
    """The Run-line string literal decodes back to the EXACT full_cmd."""
    full_cmd = ('"C:\\Users\\x\\AppData\\Local\\Python\\python.exe"'
                ' -m personal_brain.service supervise --port 8473')
    vbs = _emit_vbs(monkeypatch, tmp_path, full_cmd)
    m = re.search(r'oShell\.Run "(.*)", 0, False', vbs)
    assert m, f"no well-formed Run line in:\n{vbs}"
    literal = m.group(1)
    # VBScript: "" inside a string is one literal ". Decode it back.
    decoded = literal.replace('""', '"')
    assert decoded == full_cmd, (
        f"escaped .vbs literal does not round-trip to the command.\n"
        f"decoded={decoded!r}\nexpected={full_cmd!r}")


def test_vbs_no_broken_empty_string_pattern(monkeypatch, tmp_path):
    """Guard the exact 800A0401 byte-pattern: Run followed by ""<drive>."""
    full_cmd = '"C:\\py\\python.exe" -m personal_brain.service supervise --port 8473'
    vbs = _emit_vbs(monkeypatch, tmp_path, full_cmd)
    assert 'oShell.Run ""C:' not in vbs, (
        "emitted the broken empty-string-then-bare-path form (800A0401)")
    assert 'oShell.Run """C:' in vbs, "expected the properly escaped triple-quote opening"


def test_vbs_unquoted_command_unaffected(monkeypatch, tmp_path):
    """A command with no embedded quotes is emitted verbatim (no over-escaping)."""
    full_cmd = "pythonw -m personal_brain.service supervise --port 8473"
    vbs = _emit_vbs(monkeypatch, tmp_path, full_cmd)
    assert f'oShell.Run "{full_cmd}", 0, False' in vbs


def test_autostart_prefers_windowless_pythonw(monkeypatch, tmp_path):
    """The logon autostart must launch the WINDOWLESS pythonw.exe (no console
    window) — python.exe always allocates a console; pythonw.exe doesn't.
    Derived next to sys.executable. RED before the fix (used sys.executable =
    python.exe), GREEN after. Founder saw a console pop at logon 2026-06-19."""
    import types

    exe = tmp_path / "python.exe"
    exe.write_text("")
    (tmp_path / "pythonw.exe").write_text("")  # sibling windowless interpreter
    monkeypatch.setattr(service.sys, "executable", str(exe))

    captured = {}

    def fake_run(cmd, **kw):
        captured["cmd"] = list(cmd)
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(service.subprocess, "run", fake_run)
    res = service._windows_install(port=8473)
    assert res.get("ok") is True, res
    cmd = captured["cmd"]
    tr = cmd[cmd.index("/tr") + 1]
    assert "pythonw.exe" in tr, f"autostart must launch pythonw.exe, got: {tr}"
