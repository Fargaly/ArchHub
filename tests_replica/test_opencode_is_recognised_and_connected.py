"""Court: OpenCode installed as the desktop app is recognised, and setup connects it.

Founder 2026-09-29: "OpenCode must work 100%; all providers working and visible
in the router" and "all hooks and dependencies install automatically and are
recognised by ArchHub". The Providers tab said OpenCode "not installed" beside a
real %LOCALAPPDATA%\\Programs\\@opencode-aidesktop\\OpenCode.exe, and the
installer's connect step skipped OpenCode; the only OpenCode plugin on the
founder's machine was hand-written, named his sessions and pointed at his
workspace. Temp profiles only; the person's own profile is never read or written.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nodelang import assistant_registration as registration  # noqa: E402
from nodelang import model_router  # noqa: E402


@pytest.fixture
def machine(tmp_path, monkeypatch):
    install = tmp_path / "LocalAppData" / "ArchHub"
    module = install / "nodelang" / "session_link" / "opencode-plugin.mjs"
    module.parent.mkdir(parents=True)
    module.write_text("export function createSessionLinkPlugin(){}\n", encoding="utf-8")
    (install / "BUILD_METADATA.json").write_text("{}", encoding="utf-8")
    profile = tmp_path / "profile"
    profile.mkdir()
    state = tmp_path / "LocalAppData" / "ArchHub-Test"
    env = {"USERPROFILE": str(profile), "LOCALAPPDATA": str(tmp_path / "LocalAppData"), "PATH": ""}
    monkeypatch.setattr(registration, "install_roots", lambda environment=None: (install, state))
    return type("Machine", (), {"install": install, "module": module, "profile": profile,
                                "state": state, "env": env, "local": tmp_path / "LocalAppData"})


def _desktop(machine):
    exe = machine.local / "Programs" / "@opencode-aidesktop" / "OpenCode.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"MZ")
    return exe


def _opencode_row(env):
    rows = model_router.provider_rows(
        environ=env, secrets_loader=lambda name: "", cloud_session={},
        local_probe=lambda host, port: False)
    return next(row for row in rows if row["id"] == "opencode")


def test_the_opencode_desktop_app_is_shown_installed(machine):
    """A: no CLI on PATH, the desktop app in its install folder -> installed."""
    assert _opencode_row(machine.env)["state"] == "not installed"
    _desktop(machine)
    assert _opencode_row(machine.env)["state"] == "installed"


def test_opencode_provider_row_does_not_claim_route_without_chat_evidence(machine):
    _desktop(machine)
    row = _opencode_row(machine.env)

    assert row["state"] == "installed"
    assert "OpenRouter sign-in not found" in row["source"]
    assert "chat route not verified" in row["source"]
    assert "signed in to OpenRouter" not in row["source"]
    assert "route ok" not in row["source"]


def test_setup_writes_one_portable_plugin_for_any_user_and_is_idempotent(machine):
    """C: the installer's consent writes a plugin naming this install, never a session."""
    _desktop(machine)
    rows = {r["client"]: r["state"] for r in
            registration.connect_hooks_on_setup(consent=True, environment=machine.env)}
    assert rows["opencode"] == "registered"
    plugin = machine.profile / ".config" / "opencode" / "plugins" / "session-link.js"
    text = plugin.read_text(encoding="utf-8")
    revision = hashlib.sha256(machine.module.read_bytes()).hexdigest()
    assert machine.module.as_uri() + "?revision=" + revision in text
    assert str(machine.state / "session-link").replace("\\", "/") in text
    assert "ses_" not in text and "00.GOVERNANCE" not in text and "gateCommand" not in text
    # Consent again changes nothing; readiness says registered.
    first = plugin.read_bytes()
    assert registration.register("opencode", consent=True, environment=machine.env)["state"] == "registered"
    assert plugin.read_bytes() == first
    report = next(c for c in registration.readiness(machine.env)["clients"] if c["client"] == "opencode")
    assert report["state"] == "registered" and report["governance"] == "blocked"
    # A new install revision re-renders the same file on consent.
    machine.module.write_text("export function createSessionLinkPlugin(){ /* v2 */ }\n", encoding="utf-8")
    assert registration.register("opencode", consent=True, environment=machine.env)["state"] == "registered"
    assert hashlib.sha256(machine.module.read_bytes()).hexdigest() in plugin.read_text(encoding="utf-8")
    # Uninstall removes exactly the file ArchHub wrote.
    registration.disconnect_hooks_on_uninstall(environment=machine.env)
    assert not plugin.exists()


def test_opencode_needs_consent_and_a_foreign_plugin_is_left_alone(machine):
    _desktop(machine)
    plugin = machine.profile / ".config" / "opencode" / "plugins" / "session-link.js"
    with pytest.raises(ValueError):
        registration.register("opencode", consent=False, environment=machine.env)
    assert not plugin.exists()
    plugin.parent.mkdir(parents=True)
    plugin.write_text("export const Mine = async () => ({});\n", encoding="utf-8")
    assert registration.register("opencode", consent=True, environment=machine.env)["state"] == "conflict"
    assert plugin.read_text(encoding="utf-8") == "export const Mine = async () => ({});\n"


def test_setup_never_touches_codex_for_opencode_and_skips_an_absent_opencode(machine):
    rows = {r["client"]: r["state"] for r in
            registration.connect_hooks_on_setup(consent=True, environment=machine.env)}
    assert rows["opencode"] == "not_installed"
    assert not (machine.profile / ".config").exists() and not (machine.profile / ".codex").exists()


def test_a_source_checkout_writes_no_opencode_plugin(machine):
    """Only the installed ArchHub writes assistant plugins; a checkout reports install_required."""
    _desktop(machine)
    (machine.install / "BUILD_METADATA.json").unlink()
    assert registration.register("opencode", consent=True, environment=machine.env)["state"] == "install_required"
    rows = {r["client"]: r["state"] for r in
            registration.connect_hooks_on_setup(consent=True, environment=machine.env)}
    assert rows["opencode"] == "not_connected"
    assert not (machine.profile / ".config").exists()
