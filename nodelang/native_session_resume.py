"""First-step transport resume for an explicitly configured existing native session."""
import json
import os
from pathlib import Path
import subprocess


def resume_existing_links(environment=None):
    env=dict(os.environ if environment is None else environment)
    state=env.get('SESSION_LINK_STATE_DIR')
    node=env.get('SESSION_LINK_NODE') or env.get('CODEX_MCP_NODE_PATH')
    if not state or not node:
        return {'status':'not_configured','work_recovery_required':True}
    if not Path(state).is_absolute() or not Path(node).is_absolute() or not Path(node).is_file():
        return {'status':'recovery_required','reason':'invalid_transport_configuration'}
    if not any(env.get(name) for name in ('CODEX_THREAD_ID','CLAUDE_CODE_SESSION_ID','CLAUDE_SESSION_ID')):
        return {'status':'recovery_required','reason':'native_session_identity_unavailable'}
    try:
        result=subprocess.run([node,str(Path(__file__).parent/'session_link'/'bridge.mjs'),
            'resume','--current'],env=env,capture_output=True,text=True,timeout=4,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode or len(result.stdout)>65536:
            return {'status':'recovery_required','reason':'transport_resume_unconfirmed'}
        rows=json.loads(result.stdout)
        if type(rows) is not list or any(type(row) is not dict for row in rows):
            raise ValueError('Invalid resume result')
        return {'status':'observed','connections':rows,'work_recovery_required':True}
    except Exception:
        # Timeout never triggers another start or message replay.
        return {'status':'recovery_required','reason':'transport_resume_unconfirmed'}
