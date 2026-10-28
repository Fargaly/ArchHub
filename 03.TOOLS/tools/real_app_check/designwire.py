"""Built studio on the real ApplicationServer, one disposable lane profile, no install."""
from pathlib import Path
import argparse, json, os, secrets, subprocess, sys
from urllib.request import Request, urlopen

def main():
 parser=argparse.ArgumentParser()
 parser.add_argument('--out',required=True)
 parser.add_argument('--reference',required=True)
 parser.add_argument('--modules',required=True)
 parser.add_argument('--timeout',type=float,required=True,help='Total verification budget in seconds')
 args=parser.parse_args()
 if args.timeout<=0:parser.error('--timeout must be positive')
 root=Path(__file__).resolve().parents[2]
 out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
 profile=out.parent/'FIXTURE';profile.mkdir(exist_ok=True)
 browsers=os.environ.get('PLAYWRIGHT_BROWSERS_PATH',str(Path(os.environ['LOCALAPPDATA'])/'ms-playwright'))
 for name in tuple(os.environ):
  if name.startswith(('ARCHHUB_','CODEX_','CLAUDE_','WORKSHOP_','OPENCODE_','GEMINI_')):os.environ.pop(name)
 for name in ('LOCALAPPDATA','APPDATA','TEMP','TMP','USERPROFILE','HOME'):os.environ[name]=str(profile)
 os.environ['PLAYWRIGHT_BROWSERS_PATH']=browsers
 os.environ['PYTHONDONTWRITEBYTECODE']='1'
 sys.path.insert(0,str(root))
 from nodelang.application_server import ApplicationServer
 # The desktop delegates workspace custody to its existing clean graph owner.
 # Give the isolated rig that real owner too; only its HTTP destination is injected.
 sys.path.insert(0,str(root/'tests_replica'))
 from test_clean_server_admission import _provision_clean_runtime, _start_clean_server, _issue_clean_session
 from nodelang import workspace_roots_catalogue as roots
 built,provider=_provision_clean_runtime(profile,root_name='owner')
 graph_owner=_start_clean_server(built,provider,scope_root=built.grand_map.root_id,private_root_grants_path=profile/'private-root-grants.json')
 owner_token,owner_csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32)
 _issue_clean_session(built,token=owner_token,csrf=owner_csrf,lifetime=600)
 original_forward=roots.forward_workspace_settings
 def forward_workspace_settings(body):
  request=Request(graph_owner.url+'/api/universal/workspace-roots',data=json.dumps(body).encode('utf-8'),
   headers={'Content-Type':'application/json','X-ArchHub-Session':owner_token,'X-ArchHub-CSRF':owner_csrf},method='POST')
  with urlopen(request,timeout=args.timeout) as response:return json.loads(response.read().decode('utf-8'))
 roots.forward_workspace_settings=forward_workspace_settings
 workspace=profile/'workspace';workspace.mkdir(exist_ok=True)
 app=ApplicationServer(universal_workspace_root=workspace,universal_state_path=profile/'graph.sqlite3',enable_machine_transport=False,
  enable_universal_cloud_gateway=False,enable_brain_cloud_sync=False,enable_machine_projection_prewarm=False,live_watch=False).start()
 try:
  env={**os.environ,'DESIGNWIRE_TIMEOUT_MS':str(args.timeout*1000),'DESIGNWIRE_URL':app.bootstrap_url.replace('/?bootstrap=','/studio?bootstrap='),'DESIGNWIRE_OUT':str(out),'DESIGNWIRE_REFERENCE':str(Path(args.reference).resolve()),'DESIGNWIRE_MODULES':str(Path(args.modules).resolve()),'DESIGNWIRE_PROFILE':str(profile/'b')}
  result=subprocess.run(['node',str(Path(__file__).with_suffix('.mjs'))],env=env,cwd=root,timeout=args.timeout)
  return result.returncode
 finally:
  app.close()
  roots.forward_workspace_settings=original_forward
  graph_owner.close()
  built.location.authority.store.close()

if __name__=='__main__':raise SystemExit(main())
