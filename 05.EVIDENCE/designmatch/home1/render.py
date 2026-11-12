"""Home 1 court: synthetic 146-file volume, real owners, disposable profile."""
import os,sys,json,subprocess,tempfile,shutil,time
from pathlib import Path
from datetime import datetime,timedelta,timezone
import psutil
root=Path(__file__).resolve().parents[3]
profile=Path(tempfile.mkdtemp(prefix='home1-',dir=root/'.cache'))
for key in ('USERPROFILE','HOME','LOCALAPPDATA','APPDATA','TEMP','TMP'):
 path=profile/key;path.mkdir();os.environ[key]=str(path)
os.environ.update(ARCHHUB_TEST_STATE_DIR=str(profile/'state'),ARCHHUB_TEST_NO_OPEN='1',ARCHHUB_TEST_SECRET_STORE='memory')
sys.path[:0]=[str(root/'01.APP'),str(root/'02.TESTS/tests')]
from nodelang import nograph_server,workshop_tasks,workshop_mailbox,session_files,canvas_documents
from test_task_session_roundtrip import _Studio
nograph_server.NoGraphServer._probe_hosts=staticmethod(lambda:[])
nograph_server._list_agents=lambda:[]
server=nograph_server.NoGraphServer(profile/'state').start();client=_Studio(server)
try:
 state=profile/'state';(state/'settings').mkdir(exist_ok=True)
 (state/'settings/workspaces.json').write_text(json.dumps({'roots':[{'root_id':'studio','label':'Registered studio','path':str(profile/'workspace')}]}),encoding='utf-8')
 (profile/'workspace').mkdir()
 ids=[];paths=[];now=datetime.now(timezone.utc)
 with workshop_mailbox.application_history() as history:
  workshop_tasks._ensure(history)
  history._db.execute('CREATE TABLE IF NOT EXISTS workshop_declarations(root TEXT PRIMARY KEY,record TEXT NOT NULL CHECK(json_valid(record))) STRICT')
  for i in range(146):
   workflow=i>=115
   agent=('Claude Code' if i%2 else 'Codex')+' / Registered studio / Agent '+str(i+1)
   title=('Saved workflow '+str(i-114)) if workflow else ('Agent '+str(i+1)+' review session')
   row=workshop_tasks.create(history,title,'fixture',agent='' if workflow else agent,workspace='studio' if i%3==0 else '')
   ids.append(row['id']);paths.append(row['session_path'])
   doc=session_files.read_document(row['session_path']);context=doc['properties']['taskContext']
   doc['properties']['kind']='workflow' if workflow else 'agent-session'
   context['messages']=[{'id':'message-'+str(i),'who':agent,'text':'Reviewed '+str(i+1)+' files. The index is ready.'}]
   if workflow:
    context.update(plan=['Read index','Check files','Save report'],progress={'Read index':'done','Check files':'working'})
   session_files.write_document(row['session_path'],doc)
   age=0 if i<3 else 2 if i<12 else 4+(i%4) if i<117 else 10
   stamp=(now-timedelta(days=age)).isoformat();os.utime(row['session_path'],(now.timestamp()-age*86400,)*2)
   history._db.execute('UPDATE workshop_tasks SET status=?,owner=?,owner_label=?,lease_until=?,updated_at=?,created_at=?,archived=?,project=? WHERE id=?',('claimed' if i<16 else 'done','fixture-'+str(i),agent,time.time()+3600,stamp,stamp,int(57<=i<115),'Registered studio' if i%3==0 else None,row['id']))
   if i<16:
    declaration={'root':'fixture-root-'+str(i),'session':'fixture-'+str(i),'agent':agent,'display_name':'Agent '+str(i+1),'runtime':'claude' if i%2 else 'codex','status':'working' if i<14 else 'blocked','request_id':row['id'],'task':title,'paths':[str(profile/'workspace')],'pid':os.getpid(),'created_at':psutil.Process().create_time(),'updated_at':now.isoformat()}
    history._db.execute('INSERT INTO workshop_declarations VALUES(?,?)',(declaration['root'],json.dumps(declaration)))
 client.workshop('setTaskSession',ids[0],{'messages':[{'id':'fixture-thread','who':'Agent 1','text':'Reviewed 42 files. The index is ready.'}]})
 for i in (14,15):
  doc=session_files.read_document(paths[i]);doc['nodes'].append({'id':'approval','type':'approval.gate','params':{},'position':{'x':450,'y':80}})
  client.files('save',path=paths[i],document=doc);held=client.files('run',path=paths[i],document=doc);assert held['approvalId']
 print('OWNER',len(client.workshop('listTasks',True)),flush=True)
 result=subprocess.run(['node',str(Path(__file__).with_suffix('.cjs'))],input=json.dumps({'url':server.public_url,'cookie':server._cookie_token,'planless':ids[0],'workflow':ids[115]}),text=True,cwd=root)
 assert result.returncode==0
finally:
 client.close();server.close()
 assert profile.parent==root/'.cache' and profile.name.startswith('home1-') and not profile.is_symlink()
 for attempt in range(30):
  try:
   shutil.rmtree(profile);break
  except OSError:
   if attempt==29:raise
   time.sleep(canvas_documents.DOCUMENT_NODE['params']['lock_poll_seconds'])
