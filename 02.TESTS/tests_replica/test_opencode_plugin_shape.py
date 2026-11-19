"""Court: the OpenCode Workshop plugin loads in OpenCode 2.x and 1.x, and an older one is rewritten at start.

Founder report 2026-11-19: OpenCode 2.3.2 refused ~/.config/opencode/plugins/workshop.js with
"Plugin must export a default definition with an id and an effect or setup function". Temp profiles only.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from nodelang import assistant_registration as registration

FAKE_MODULE = ("export function createWorkshopPlugin({stateDirectory}){\n"
               " return async ({client,directory}) => ({});\n}\n"
               "export function createWorkshopPluginV2({stateDirectory}){\n"
               " return async ctx => {};\n}\n")


@pytest.fixture
def machine(tmp_path, monkeypatch):
    install = tmp_path / "install"
    module = install / "nodelang" / "workshop" / "opencode-plugin.mjs"
    module.parent.mkdir(parents=True)
    module.write_text(FAKE_MODULE, encoding="utf-8")
    (install / "BUILD_METADATA.json").write_text("{}", encoding="utf-8")
    home = tmp_path / "home"
    (home / ".config" / "opencode" / "plugins").mkdir(parents=True, exist_ok=True)
    state = tmp_path / "state"
    env = {"USERPROFILE": str(home), "PATH": ""}
    monkeypatch.setattr(registration, "install_roots", lambda environment=None: (install, state))
    return type("Machine", (), {"install": install, "state": state, "env": env,
                                "target": home / ".config" / "opencode" / "plugins" / "workshop.js"})


def test_the_plugin_default_exports_an_id_setup_and_server(machine):
    text = registration.render_opencode_plugin(machine.install, machine.state)
    assert 'export default {id:"archhub-workshop", server:Workshop, setup:createWorkshopPluginV2(' in text
    assert "export const Workshop = createWorkshopPlugin(" in text  # OpenCode before 1.18.29
    assert "nodelang.custom_mcp_gateway" in text and str(machine.install / ".venv" / "Scripts" / "python.exe").replace(
        "\\", "\\\\") in text  # his own MCP servers, from this install's Python


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")
def test_node_loads_the_shape_opencode_2_validates(machine):
    machine.target.write_text(registration.render_opencode_plugin(machine.install, machine.state), encoding="utf-8")
    probe = ("const m=await import(process.argv[1]);const d=m.default;"
             "console.log(JSON.stringify({id:d.id,setup:typeof d.setup,server:typeof d.server,"
             "named:typeof m.Workshop,same:d.server===m.Workshop}));")
    out = subprocess.run(["node", "--input-type=module", "-e", probe, machine.target.as_uri()],
                         capture_output=True, text=True, timeout=30, check=True,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    assert json.loads(out) == {"id": "archhub-workshop", "setup": "function", "server": "function",
                               "named": "function", "same": True}


def test_start_rewrites_an_older_archhub_plugin(machine):
    old = registration.render_opencode_plugin(machine.install, machine.state).split("export default")[0]
    machine.target.write_text(old, encoding="utf-8")
    result = registration.refresh_opencode_plugin(machine.env)
    assert result["state"] == "registered"
    assert "export default" in machine.target.read_text(encoding="utf-8")


def test_a_test_or_second_server_never_refreshes_the_persons_opencode(tmp_path, monkeypatch):
    from nodelang import nograph_server
    called = []
    monkeypatch.setattr(registration, "refresh_opencode_plugin", lambda env=None: called.append(env) or {})
    real = tmp_path / "LocalAppData" / "ArchHub"
    env = {"LOCALAPPDATA": str(tmp_path / "LocalAppData"), "USERPROFILE": str(tmp_path)}
    assert nograph_server._refresh_opencode_plugin(tmp_path / "elsewhere", env) is None
    assert nograph_server._refresh_opencode_plugin(real, {**env, "ARCHHUB_TEST_STATE_DIR": str(real)}) is None
    assert called == []
    assert nograph_server._refresh_opencode_plugin(real, env) == {} and called == [env]


def test_start_never_writes_a_new_plugin_or_touches_a_foreign_one(machine):
    assert registration.refresh_opencode_plugin(machine.env)["state"] == "ready_to_register"
    assert not machine.target.exists()
    machine.target.write_text("export default {id:'mine', setup(){}}\n", encoding="utf-8")
    assert registration.refresh_opencode_plugin(machine.env)["state"] == "conflict"
    assert machine.target.read_text(encoding="utf-8") == "export default {id:'mine', setup(){}}\n"
