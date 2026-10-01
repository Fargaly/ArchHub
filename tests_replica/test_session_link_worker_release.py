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
