"""INSTALLED is not CONNECTED. The founder saw Rhino, Blender, Word, Excel,
PowerPoint as INSTALLED and asked why none of them worked: their bridges were
not running and nothing in the app could start them. This court holds the
path that brings a host to CONNECTED from inside ArchHub -- BABOOM, the
cockpit and the installer -- so the state on the connectors sheet is one the
founder can change with a click, not a report he has to act on by hand.
"""
from __future__ import annotations

import inspect
import subprocess
from pathlib import Path

import nodelang.host_brokers as hb
import nodelang.universal_application as ua
from nodelang.map_import import resolve_map_path

ROOT = Path(__file__).resolve().parents[1]


def test_open_host_is_an_act_baboom_asks_before_and_then_performs():
    assert "open-host" in ua._BABOOM_ACT_INTENTS
    store, registry = ua.build_universal_application(resolve_map_path())
    context = registry.authorization.session.context()
    try:
        for spoken, host in (("open excel", "excel"), ("launch Rhino", "rhino"), ("start blender", "blender"),
                             ("connect 3ds max", "max"), ("open powerpoint", "powerpoint")):
            cmd = ua.resolve_universal_baboom_utterance(store, registry, utterance=spoken, authentication_context=context)
            assert cmd["intent"] == "open-host" and cmd["payload"] == host, (spoken, cmd)
        offer = ua.respond_universal_baboom_utterance(store, registry, utterance="open excel", authentication_context=context)["response"]
        assert offer["kind"] == "host-open-ready" and offer["data"]["requires"] == "explicit execute"
    finally:
        store.close()
    src = inspect.getsource(ua.execute_universal_baboom_utterance)
    assert "_open_host(str(command[\"payload\"]))" in src


def test_office_opens_visible_kept_alive_and_registered(monkeypatch):
    # Measured on the founder's machine: EXCEL.EXE launched as a process never
    # registered in the running-object table (Excel registers only after it
    # loses focus) and a bare COM Dispatch quit the moment the reference
    # dropped. Visible + UserControl + one workbook registered in 1 s, was seen
    # from a separate process and survived release. That recipe is the law here.
    class Docs:
        Count = 0
        def Add(self):
            self.Count += 1
    class App:
        def __init__(self):
            self.Workbooks = Docs(); self.Visible = False; self.UserControl = False
    made = []
    def dispatch(progid):
        made.append(progid); made.append(App()); return made[-1]
    alive = {"n": 0}
    def com_alive(progid):
        alive["n"] += 1
        return alive["n"] > 2  # not before the open, not at once, then registered
    out = hb.open_host("excel", dispatch=dispatch, com_alive=com_alive, wait_s=5)
    app = made[1]
    assert made[0] == "Excel.Application" and app.Visible is True and app.UserControl is True and app.Workbooks.Count == 1
    assert out["ok"] and out["state"] == "connected"
    again = hb.open_host("excel", dispatch=lambda p: made.append("no"), com_alive=lambda p: True)
    assert again["action"] == "already open" and made[-1] is app
    src = inspect.getsource(hb.open_host)
    office = src.split("if host in _OFFICE_PROGIDS:")[1].split('if host == "rhino"')[0]
    assert "popen(" not in office  # Office is never launched as a bare process (it would not register)


def test_rhino_and_blender_launch_with_the_shipped_bridge(monkeypatch, tmp_path):
    calls = []
    def popen(args, **kw):
        calls.append((args, kw))
    bridges = tmp_path / "bridges"
    (bridges / "rhino").mkdir(parents=True); (bridges / "rhino" / "archhub_mcp.py").write_text("# bridge")
    (bridges / "blender" / "archhub_mcp").mkdir(parents=True); (bridges / "blender" / "archhub_mcp" / "__init__.py").write_text("def register(): pass")
    monkeypatch.setattr(hb, "_bridges_dir", lambda: bridges)
    monkeypatch.setattr(hb, "_RHINO_EXES", (str(tmp_path / "Rhino.exe"),)); (tmp_path / "Rhino.exe").write_bytes(b"")
    monkeypatch.setattr(hb, "_blender_exe", lambda: str(tmp_path / "blender.exe"))
    monkeypatch.setattr(hb, "_running", lambda names: False)
    r = hb.open_host("rhino", popen=popen)
    b = hb.open_host("blender", popen=popen)
    assert r["ok"] and b["ok"] and len(calls) == 2
    rhino_args, rhino_kw = calls[0]
    assert rhino_args[0].endswith("Rhino.exe") and "archhub_mcp.py" in rhino_args[-1] and "_-RunPythonScript" in rhino_args[-1]
    blender_args, blender_kw = calls[1]
    assert blender_args[1] == "--python-expr" and "archhub_mcp.register()" in blender_args[2]
    for kw in (rhino_kw, blender_kw):  # a launch never pops a console
        assert kw.get("creationflags") == getattr(subprocess, "CREATE_NO_WINDOW", 0)


def test_a_host_already_running_without_its_bridge_is_told_not_relaunched(monkeypatch, tmp_path):
    bridges = tmp_path / "bridges"; (bridges / "rhino").mkdir(parents=True); (bridges / "rhino" / "archhub_mcp.py").write_text("#")
    monkeypatch.setattr(hb, "_bridges_dir", lambda: bridges)
    monkeypatch.setattr(hb, "_RHINO_EXES", (str(tmp_path / "Rhino.exe"),)); (tmp_path / "Rhino.exe").write_bytes(b"")
    monkeypatch.setattr(hb, "_running", lambda names: True)
    launched = []
    out = hb.open_host("rhino", popen=lambda *a, **k: launched.append(a))
    assert not out["ok"] and out["state"] == "running" and "_-RunPythonScript" in out["error"] and launched == []


def test_max_is_honest_about_needing_maxmcp():
    out = hb.open_host("max", popen=lambda *a, **k: None)
    assert not out["ok"] and "MaxMCP" in out["error"] and "48886" in out["error"]


def test_the_installer_ships_both_bridges_beside_the_app():
    iss = (ROOT / "installer" / "ArchHub.iss").read_text(encoding="utf-8")
    assert r'payload\rhino\archhub_mcp.py"; DestDir: "{app}\bridges\rhino"' in iss
    assert r'payload\blender\archhub_mcp\*"; DestDir: "{app}\bridges\blender\archhub_mcp"' in iss
    src = inspect.getsource(hb._bridges_dir)
    assert '"bridges"' in src  # the app looks exactly where the installer puts them


def test_the_cockpit_offers_open_on_every_host_it_can_open():
    panels = (ROOT.parent / "wt-front-door" / "cloud_backend" / "cockpit_assets" / "atlas-panels.jsx")
    if not panels.is_file():
        return
    src = panels.read_text(encoding="utf-8")
    assert "say('open ' + h.id, true)" in src
    assert "const OPENABLE = ['excel', 'word', 'powerpoint', 'outlook', 'rhino', 'blender']" in src
