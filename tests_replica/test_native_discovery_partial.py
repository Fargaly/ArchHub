"""One owned fixture worker; no native agent or application starts."""
import os
from pathlib import Path
import time
import pytest
from nodelang.session_link_transport import SessionLinkTransport


@pytest.mark.parametrize('operation',['discover','request'])
def test_completed_discovery_survives_slow_provider_but_never_becomes_reply(tmp_path,operation):
    node=Path(os.environ.get('SESSION_LINK_NODE',str(Path(os.environ['LOCALAPPDATA'])/'ArchHub/runtime/node.exe')))
    assets=tmp_path/'assets';assets.mkdir()
    (assets/'worker.mjs').write_text("""
process.stdin.once('data',()=>{
 process.stdout.write(JSON.stringify({event:'discovery_snapshot',status:'ok',
 recipients:[{app:'claude',id:'exact-fixture',pid:123}],complete_apps:['claude']})+'\\n');
 setInterval(()=>{},1000);
});
""",encoding='utf8')
    transport=SessionLinkTransport(node_executable=node,state_dir=tmp_path/'state')
    transport._assets=assets
    start=time.monotonic()
    try:
        result=transport._call({'operation':operation},.5,None)
        assert result['worker_stopped'] is True
        assert not transport._processes
        if operation=='discover':
            assert result['status']=='ok' and result['partial'] is True
            assert result['recipients'][0]['id']=='exact-fixture'
            assert result['complete_apps']==['claude']
            assert time.monotonic()-start<2
        else:
            assert result['status']=='uncertain' and 'recipients' not in result
    finally:transport.close()
