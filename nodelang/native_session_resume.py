"""First-step transport resume for an explicitly configured existing native session."""
import json
import os
from pathlib import Path
import subprocess


def resume_existing_links(environment=None, *, required_connections=None):
    env=dict(os.environ if environment is None else environment)
    state=env.get('SESSION_LINK_STATE_DIR')
    node=env.get('SESSION_LINK_NODE') or env.get('CODEX_MCP_NODE_PATH')
    if not state or not node:
        return {'status':'not_configured','work_recovery_required':True}
    if not Path(state).is_absolute() or not Path(node).is_absolute() or not Path(node).is_file():
        return {'status':'recovery_required','reason':'invalid_transport_configuration'}
    try:
        from .native_agent_session import resolve_native_agent_identity
        identity=resolve_native_agent_identity(env)
    except (ValueError,TypeError):
        return {'status':'recovery_required','reason':'native_session_identity_unavailable'}
    current=identity.external_session_id
    env['ARCHHUB_AGENT_RUNTIME']=identity.runtime
    required=required_connections
    if required is None:
        required=env.get('SESSION_LINK_REQUIRED_CONNECTIONS','').split(',')
    if (type(required) not in (tuple,list) or not required or len(required)>16
            or any(type(value) is not str or len(value)!=16 or any(c not in '0123456789abcdef' for c in value) for value in required)
            or len(set(required))!=len(required)):
        return {'status':'recovery_required','reason':'current_required_connections_not_configured'}
    try:
        result=subprocess.run([node,str(Path(__file__).parent/'session_link'/'bridge.mjs'),
            'resume','--current','--connections',','.join(required)],env=env,capture_output=True,text=True,timeout=8,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode:
            reason='required_endpoint_discovery_unavailable' if result.stderr.strip()=='required_endpoint_discovery_unavailable' else 'transport_resume_failed'
            return {'status':'recovery_required','reason':reason}
        if len(result.stdout)>65536:
            return {'status':'recovery_required','reason':'transport_resume_response_oversized'}
        rows=json.loads(result.stdout)
        if type(rows) is not list or any(type(row) is not dict for row in rows):
            raise ValueError('Invalid resume result')
        if len(rows)!=len(required) or {row.get('id') for row in rows}!=set(required):
            raise ValueError('Required connection result is missing or duplicated')
        for row in rows:
            if row.get('status') not in {'already_connected','restored'}:
                return {'status':'recovery_required','reason':'saved_link_not_restored','work_recovery_required':True}
            if row.get('endpoints_observed') is not True:
                raise ValueError('Required native endpoints were not observed')
            connection=row.get('connection')
            role_matches=(type(connection) is dict and (
                connection.get('codex')==current if identity.runtime=='codex' else
                connection.get('remoteApp')==identity.runtime and connection.get('remoteId')==current))
            if (type(connection) is not dict or connection.get('id')!=row.get('id') or not role_matches):
                raise ValueError('Resume result does not belong to current native session')
        return {'status':'observed','connections':rows,'work_recovery_required':True}
    except subprocess.TimeoutExpired:
        return {'status':'recovery_required','reason':'transport_resume_timeout','timeout_seconds':8}
    except Exception:
        # Timeout never triggers another start or message replay.
        return {'status':'recovery_required','reason':'transport_resume_unconfirmed'}
