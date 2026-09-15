"""Read-only Stop IPC hosted inside the existing native MCP owner process.

The shell owns no graph client or enrollment. A Windows credential grants only
this local Stop observation; the full Agent Session capability stays in MCP.
"""
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
import threading
import time
import uuid
from multiprocessing.connection import Client

SERVICE = 'ArchHub.NativeStop.v1'
UNAVAILABLE = {'decision':'block','reason':'Native Stop authority is unavailable. Continue through the existing native session to reconcile; do not create a replacement session.'}


def canonical_runtime(vendor):
    if type(vendor) is not str:
        raise ValueError('Invalid native Stop runtime')
    name=vendor.casefold()
    if name in ('claude', 'claude-code', 'claude-code.exe', 'claude-code.cmd'):
        return 'claude'
    raise ValueError('Unsupported native Stop runtime')


def _fingerprint(runtime, session_id):
    if type(session_id) is not str or not session_id or len(session_id.encode()) > 512:
        raise ValueError('Exact native Stop session required')
    if runtime=='claude' and str(uuid.UUID(session_id))!=session_id:
        raise ValueError('Claude Stop session must be its exact UUID')
    return hashlib.sha256((runtime+'\0'+session_id).encode()).hexdigest()


def _ending_turn(value):
    return {'systemMessage':value.get('reason',UNAVAILABLE['reason'])+' This turn may end; Work completion is not declared.'}


def _server_pid(connection):
    import ctypes
    from ctypes import wintypes
    pid=wintypes.ULONG()
    api=ctypes.windll.kernel32.GetNamedPipeServerProcessId
    api.argtypes=[wintypes.HANDLE,ctypes.POINTER(wintypes.ULONG)]
    api.restype=wintypes.BOOL
    if not api(connection.fileno(),ctypes.byref(pid)):
        raise OSError('Native Stop pipe server PID unavailable')
    return pid.value


def _vault():
    if os.name != 'nt':
        raise RuntimeError('Native Stop credentials require Windows DPAPI')
    base=os.environ.get('LOCALAPPDATA')
    if not base or not Path(base).is_absolute():
        raise RuntimeError('Native Stop encrypted custody is unavailable')
    return _DpapiStopStore(Path(base)/'ArchHub'/'runtime-context'/'native-stop')


class _DpapiStopStore:
    """Existing current-user DPAPI primitive; only encrypted IPC records on disk."""
    def __init__(self, directory):
        self.directory=Path(directory)

    def _path(self, service, key):
        if service!=SERVICE or type(key) is not str or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):
            raise ValueError('Invalid Native Stop custody identity')
        return self.directory/(key+'.dpapi')

    def get_password(self, service, key):
        from nodelang.cell_secret_keys import unprotect_current_user_data
        path=self._path(service,key)
        try:
            with path.open('rb') as stream:
                raw=stream.read(32769)
        except FileNotFoundError:
            return None
        if len(raw)>32768:
            raise ValueError('Native Stop custody exceeds bound')
        return unprotect_current_user_data(raw,purpose=SERVICE+':'+key).decode('utf-8')

    def set_password(self, service, key, value):
        from nodelang.cell_secret_keys import protect_current_user_data
        path=self._path(service,key)
        raw=value.encode('utf-8')
        if len(raw)>16384:
            raise ValueError('Native Stop record exceeds bound')
        encrypted=protect_current_user_data(raw,purpose=SERVICE+':'+key)
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_name(path.name+'.'+secrets.token_hex(8)+'.tmp')
        try:
            with temporary.open('xb') as stream:
                stream.write(encrypted)
            os.replace(temporary,path)
        finally:
            temporary.unlink(missing_ok=True)

    def delete_password(self, service, key):
        self._path(service,key).unlink(missing_ok=True)


def _alive(pid, created_at):
    import psutil
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.create_time() == created_at
    except psutil.NoSuchProcess:
        return False


class NativeStopHost:
    """One optional IPC thread in the retained MCP process, no second owner."""
    def __init__(self, owner, *, vault=None):
        self.owner=owner
        self.vault=_vault() if vault is None else vault
        identity=owner._identity
        self.fingerprint=_fingerprint(canonical_runtime(identity.runtime),identity.external_session_id)
        self.listener=None
        self.thread=None
        self.closed=threading.Event()
        self.record=None
        self.last_gate=None

    def start(self):
        import psutil
        if self.listener is not None:
            raise RuntimeError('Native Stop IPC is already started')
        previous=self.vault.get_password(SERVICE,self.fingerprint)
        if previous:
            existing=json.loads(previous)
            if _alive(existing['pid'],existing['created_at']):
                raise RuntimeError('An existing native Stop host owns this session')
        status=self.owner.owner_status()
        if status.get('state')!='bound' or not status.get('agent_session'):
            raise RuntimeError('Native Stop requires its existing bound owner')
        key=secrets.token_bytes(32)
        endpoint=r'\\.\pipe\ArchHub.NativeStop.'+secrets.token_hex(16)
        from .application_machine_transport import _AuthenticatedSecurePipeListener
        self.record={'version':1,'fingerprint':self.fingerprint,'endpoint':endpoint,'key':key.hex(),
            'pid':os.getpid(),'created_at':psutil.Process().create_time(),
            'actor':status['agent_session'],'instance':status['pinned']['instance_digest']}
        self.listener=_AuthenticatedSecurePipeListener(endpoint,key)
        try:
            self.thread=threading.Thread(target=self._serve,daemon=True,name='native-stop-read')
            self.thread.start()
            self.vault.set_password(SERVICE,self.fingerprint,json.dumps(self.record))
        except BaseException:
            self.close()
            raise
        return self

    def _handle(self, request):
        if (type(request) is not dict or set(request)!={'request_id','fingerprint','operation','stop_hook_active'}
                or request['operation']!='stop' or request['fingerprint']!=self.fingerprint
                or type(request['request_id']) is not str or len(request['request_id'])!=32
                or any(c not in '0123456789abcdef' for c in request['request_id'])):
            raise ValueError('Invalid native Stop request')
        if type(request['stop_hook_active']) is not bool:
            raise ValueError('Invalid native Stop continuation marker')
        value=self._observe()
        if value == UNAVAILABLE or (request['stop_hook_active'] and value and value==self.last_gate):
            value=_ending_turn(value)
        else:
            self.last_gate=dict(value)
        return {'request_id':request['request_id'],'fingerprint':self.fingerprint,'result':value}

    def _observe(self):
        from .native_agent_hooks import stop_verdict
        owner=self.owner
        client=None
        active=False
        if not owner._lock.acquire(timeout=0.1):
            return dict(UNAVAILABLE)
        try:
            status=owner.owner_status()
            if (status.get('state')!='bound' or status.get('agent_session')!=self.record['actor']
                    or status.get('pinned',{}).get('instance_digest')!=self.record['instance']
                    or status.get('rebind_pending') or status.get('recovery_required')
                    or owner._active_calls):
                return dict(UNAVAILABLE)
            client=owner._require_bound()
            if not client._request_lock.acquire(blocking=False):
                client=None
                return dict(UNAVAILABLE)
            # Refuse renewal: Stop observes, it never starts a lease mutation.
            if client._agent_session_expires_at <= time.time()+60:
                return dict(UNAVAILABLE)
            owner._active_calls += 1
            active=True
        except Exception:
            return dict(UNAVAILABLE)
        finally:
            owner._lock.release()
            if client is not None and not active:
                client._request_lock.release()
        try:
            # Existing active-call guard prevents owner replacement. The owner
            # lock is free throughout this bounded read; no new client is made.
            value=stop_verdict(client._request_once('GET','/api/universal/work',
                {'projection':'index'},response_timeout_seconds=2.0),client)
        except Exception:
            value=dict(UNAVAILABLE)
        finally:
            # Release client first: ordinary tools take owner then client.
            client._request_lock.release()
            with owner._lock:
                try:
                    if owner._require_bound() is not client:
                        value=dict(UNAVAILABLE)
                except Exception:
                    value=dict(UNAVAILABLE)
                finally:
                    owner._active_calls -= 1
        return value
    def _serve(self):
        while not self.closed.is_set():
            connection=None
            try:
                connection=self.listener.accept(timeout_seconds=0.2, authentication_timeout_seconds=1.0)
                if not connection.poll(2.0):
                    continue
                request=json.loads(connection.recv_bytes(4096))
                response=self._handle(request)
                raw=json.dumps(response,allow_nan=False).encode()
                if len(raw)>8192:
                    raise ValueError('Native Stop response exceeds bound')
                connection.send_bytes(raw)
            except Exception:
                if self.closed.is_set():
                    break
            finally:
                if connection is not None:
                    connection.close()

    def close(self):
        self.closed.set()
        if self.record is not None:
            current=self.vault.get_password(SERVICE,self.fingerprint)
            if current and json.loads(current).get('endpoint')==self.record['endpoint']:
                self.vault.delete_password(SERVICE,self.fingerprint)
        if self.listener is not None:
            self.listener.close()
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        return self.thread is None or not self.thread.is_alive()


def query_stop(payload, *, vendor='claude-code', vault=None, environment=None):
    """One bounded observation; no enrollment, retry, or authority fallback."""
    fingerprint=_fingerprint(canonical_runtime(vendor),payload.get('session_id'))
    environment=os.environ if environment is None else environment
    for name in ('CLAUDE_CODE_SESSION_ID','CLAUDE_SESSION_ID','ARCHHUB_EXTERNAL_SESSION_ID'):
        if environment.get(name) and environment[name]!=payload.get('session_id'):
            raise ValueError('Stop payload and native environment identities disagree')
    repeated=payload.get('stop_hook_active') is True
    unavailable=_ending_turn(UNAVAILABLE)
    vault=_vault() if vault is None else vault
    raw=vault.get_password(SERVICE,fingerprint)
    if not raw or len(raw.encode())>16384:
        return unavailable
    record=json.loads(raw)
    if (record.get('version')!=1 or record.get('fingerprint')!=fingerprint
            or type(record.get('endpoint')) is not str
            or not record['endpoint'].startswith(r'\\.\pipe\ArchHub.NativeStop.')
            or type(record.get('key')) is not str or len(record['key'])!=64
            or not _alive(record.get('pid'),record.get('created_at'))):
        return unavailable
    done=threading.Event(); connected=threading.Event(); cancelled=threading.Event(); result=[]
    request={'request_id':secrets.token_hex(16),'fingerprint':fingerprint,'operation':'stop',
        'stop_hook_active':repeated}
    def receive():
        connection=None
        try:
            connection=Client(record['endpoint'],family='AF_PIPE',authkey=bytes.fromhex(record['key']))
            if cancelled.is_set():
                return
            if _server_pid(connection)!=record['pid']:
                return
            connected.set()
            connection.send_bytes(json.dumps(request).encode())
            if not connection.poll(2.5):
                return
            response=json.loads(connection.recv_bytes(8192))
            value=response.get('result')
            if (response.get('request_id')!=request['request_id'] or response.get('fingerprint')!=fingerprint
                    or type(value) is not dict or (value and not (
                        set(value)=={'decision','reason'} and value['decision']=='block' and type(value['reason']) is str
                        or set(value)=={'systemMessage'} and type(value['systemMessage']) is str))):
                return
            result.append(value)
        except Exception:
            pass
        finally:
            if connection is not None:
                connection.close()
            done.set()
    threading.Thread(target=receive,daemon=True,name='native-stop-query').start()
    if not connected.wait(2.0):
        cancelled.set()
        return unavailable
    done.wait(2.5)
    if not done.is_set():
        cancelled.set()
    return result[0] if result else unavailable


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor',default='claude-code')
    args=parser.parse_args()
    try:
        raw=sys.stdin.buffer.read(65537)
        if len(raw)>65536:
            raise ValueError('Stop input exceeds bound')
        payload=json.loads(raw)
        result=query_stop(payload,vendor=args.vendor)
    except Exception:
        result=_ending_turn(UNAVAILABLE)
    sys.stdout.write(json.dumps(result))
    return 0


if __name__=='__main__':
    # Direct installed script execution imports only this canonical package.
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
