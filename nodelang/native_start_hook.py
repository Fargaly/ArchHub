"""Codex and Claude command SessionStart transport recovery, with no native enrollment.

The existing native owner must recover original Work before dependent effects.
This context hook is not itself an authorization or execution gate.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import uuid


def recover_start(payload, *, state_directory, node_executable, environment=None,
                  runtime='claude', expected_session=None, workspace=None, required_connections=None):
    from nodelang.native_session_resume import resume_existing_links
    if type(payload) is not dict or payload.get('hook_event_name')!='SessionStart':
        raise ValueError('Exact SessionStart event required')
    session=payload.get('session_id')
    if expected_session is not None and session!=expected_session:
        return {}
    if workspace is not None and Path(str(payload.get('cwd',''))).resolve()!=Path(workspace).resolve():
        return {}
    if type(session) is not str or str(uuid.UUID(session))!=session:
        raise ValueError('Exact native session identity required')
    env=dict(os.environ if environment is None else environment)
    identity_keys=('CODEX_THREAD_ID',) if runtime=='codex' else ('CLAUDE_CODE_SESSION_ID','CLAUDE_SESSION_ID','ARCHHUB_EXTERNAL_SESSION_ID')
    for key in identity_keys:
        if env.get(key) and env[key]!=session:
            raise ValueError('Native hook identity conflict')
    env.update(ARCHHUB_AGENT_RUNTIME=runtime,ARCHHUB_EXTERNAL_SESSION_ID=session,
               SESSION_LINK_STATE_DIR=str(state_directory),
               SESSION_LINK_NODE=str(node_executable))
    env['CODEX_THREAD_ID' if runtime=='codex' else 'CLAUDE_CODE_SESSION_ID']=session
    result=resume_existing_links(env,required_connections=required_connections)
    ready=result.get('status')=='observed'
    text=('Session Link transport was checked for this exact existing session. '
          if ready else 'Session Link recovery is unresolved: '+str(result.get('reason') or result.get('status'))+'. ')
    text+=('Before dependent work, use the retained native owner to recover this same actor and read its original '
           'Work assignment, then reconcile pending receipts. Do not create a replacement actor, replay an '
           'uncertain message or treat this startup context as execution approval. Discovery and recovery remain available.')
    return {'hookSpecificOutput':{'hookEventName':'SessionStart','additionalContext':text}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-dir',required=True)
    parser.add_argument('--node',required=True)
    parser.add_argument('--runtime',choices=('claude','codex'),default='claude')
    parser.add_argument('--session',required=True)
    parser.add_argument('--workspace',required=True)
    parser.add_argument('--connection',action='append',required=True)
    args=parser.parse_args()
    try:
        raw=sys.stdin.buffer.read(65537)
        if len(raw)>65536:raise ValueError('Startup input too large')
        result=recover_start(json.loads(raw),state_directory=args.state_dir,node_executable=args.node,
            runtime=args.runtime,expected_session=args.session,workspace=args.workspace,required_connections=args.connection)
    except Exception:
        result={'hookSpecificOutput':{'hookEventName':'SessionStart','additionalContext':
            'Startup recovery could not be verified. Use existing session recovery before dependent work; no enrollment or replay was attempted by this hook.'}}
    print(json.dumps(result))
    return 0


if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
