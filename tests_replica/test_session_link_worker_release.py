import os
import shutil
from pathlib import Path

from nodelang.session_link_transport import SessionLinkTransport


def test_worker_result_releases_busy_before_next_discover(tmp_path):
    node = Path(os.environ.get("SESSION_LINK_NODE") or shutil.which("node") or "")
    assert node.is_file(), "node executable unavailable for real worker court"
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "worker.mjs").write_text(
        """
import readline from 'node:readline';
const input=readline.createInterface({input:process.stdin,crlfDelay:Infinity});
input.on('line',line=>{
 const r=JSON.parse(line);
 if(r.operation==='request'){
  process.stdout.write(JSON.stringify({event:'dispatch_attempted'})+'\\n');
  process.stdout.write(JSON.stringify({event:'result',status:'replied',dispatch_attempted:true,recipient:r.recipient,reply:{text:'done'}})+'\\n',()=>process.exit(0));
 }else if(r.operation==='discover'){
  process.stdout.write(JSON.stringify({event:'result',status:'ok',recipients:[],providers:{},complete_apps:[],truncated:false})+'\\n',()=>process.exit(0));
 }
});
""",
        encoding="utf8",
    )
    transport = SessionLinkTransport(node_executable=node, state_dir=tmp_path / "state")
    transport._assets = assets
    try:
        first = transport.request({"app": "claude", "id": "exact"}, "hello", timeout_seconds=3)
        assert first["status"] == "replied"
        second = transport.discover(timeout_seconds=3)
        assert second["status"] == "ok"
        assert second.get("reason") != "transport_busy"
    finally:
        transport.close()


def test_installed_layout_keeps_state_beside_shipped_code(tmp_path, monkeypatch):
    import sys
    import pytest
    from nodelang import desktop, session_link_transport

    app_root = tmp_path / "ArchHub"
    module = app_root / "nodelang" / "session_link_transport.py"
    node = app_root / "runtime" / "node.exe"
    node.parent.mkdir(parents=True)
    node.touch()  # Constructor-only court: no process executes this fixture file.
    monkeypatch.setattr(session_link_transport, "__file__", str(module))
    monkeypatch.setattr(desktop, "__file__", str(module.with_name("desktop.py")))
    monkeypatch.delenv("SESSION_LINK_NODE", raising=False)
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    transport = desktop.create_workshop_transport(app_root)
    try:
        assert transport._state == app_root / "session-link"
        channel = transport.create_channel()
        channel.close()
    finally:
        transport.close()
    for code in (app_root / "nodelang", app_root / "runtime",
                 app_root / "nodelang" / "session_link"):
        for state in (code, code / "x"):
            with pytest.raises(ValueError, match="transport state must be outside installed code"):
                SessionLinkTransport(node_executable=node, state_dir=state)

    assets = app_root / "nodelang" / "session_link"
    assets.parent.mkdir(parents=True)
    external = tmp_path / "linked-assets"
    external.mkdir()
    if os.name == "nt":
        import subprocess
        subprocess.run(["cmd", "/c", "mklink", "/J", str(assets), str(external)],
                       check=True, capture_output=True)
    else:
        assets.symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match="transport state must be outside installed code"):
        SessionLinkTransport(node_executable=node, state_dir=external / "x")

    bundle = app_root / "_MEIPASS"
    monkeypatch.setattr(sys, "frozen", True)
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    with pytest.raises(ValueError, match="transport state must be outside installed code"):
        SessionLinkTransport(node_executable=node, state_dir=bundle / "x")
