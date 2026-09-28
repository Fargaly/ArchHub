"""Read-only Stop IPC hosted inside the existing native MCP owner process.

The shell owns no graph client or enrollment. A Windows credential grants only
this local Stop observation; the full Agent Session capability stays in MCP.
"""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
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
    # Codex Stop and Gemini AfterAgent speak the same wire: input session_id,
    # transcript_path, stop_hook_active; output decision=block+reason or
    # systemMessage (codex.exe stop.command.output; gemini-cli AfterAgentHookOutput).
    if name in ('codex', 'codex.exe', 'codex-cli'):
        return 'codex'
    if name in ('gemini', 'gemini-cli', 'antigravity'):
        return 'gemini'
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
        if value != UNAVAILABLE:
            try:
                _remember_verdict(self.fingerprint, value)
            except Exception:
                pass
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


# Automatic follow-up (founder order 2026-09-28): an agent that asked another
# agent for a reply may not end a turn while that reply is overdue. This reads
# only the session's own transcript and a small per-session guard file. It
# never sends, retries or replays anything: it tells the agent to send the next
# numbered follow-up itself.
FOLLOWUP_DUE_SECONDS = 600
_FOLLOWUP_WINDOW_SECONDS = 24 * 3600
_FOLLOWUP_TAIL_BYTES = 4 * 1024 * 1024
_ASKS_REPLY = re.compile(r'\?|\b(reply|respond|answer|confirm)\b', re.IGNORECASE)
_NO_REPLY = re.compile(r"\bno (reply|response|answer)\b|\bno need to (reply|respond|answer)\b"
                       r"|\b(reply|response|answer) not needed\b|\bdo not (reply|respond)\b"
                       r"|\bdon't (reply|respond)\b|\bfyi\b", re.IGNORECASE)
_LOCAL_AGENT = re.compile(r'^a[0-9a-f]{16}$')
# One session answers under several addresses: its pipe (cc-msg-<id>), its local_<uuid>
# and its name, which ListAgents may suffix with a [ref]. Every form is folded to one key.
_SESSION_KEY = re.compile(r'cc-msg-[0-9a-f]{32}|local_[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
                          re.IGNORECASE)
_NAME_REF = re.compile(r'\s*\[[0-9a-f]{4,}\]$')


def _timestamp(value):
    if type(value) is not str:
        return None
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def _address(value):
    from urllib.parse import unquote
    return unquote(value.strip()).casefold() if type(value) is str and value.strip() else None


def _asks_reply(to, message):
    """Only explicit requests count; FYIs, no-reply notes and in-process agents do not."""
    if _address(to) in (None, 'main') or _LOCAL_AGENT.match(to.strip()):
        return False
    return bool(_ASKS_REPLY.search(message)) and not _NO_REPLY.search(message)


def _tool_result(content):
    if isinstance(content, list):
        content = ''.join(part.get('text', '') for part in content if type(part) is dict)
    try:
        value = json.loads(content) if type(content) is str else None
    except ValueError:
        return {}
    return value if type(value) is dict else {}


def _transcript_tail(path, limit=_FOLLOWUP_TAIL_BYTES):
    with open(path, 'rb') as stream:
        stream.seek(0, os.SEEK_END)
        start = max(0, stream.tell() - limit)
        stream.seek(start)
        lines = stream.read(limit).split(b'\n')
    for raw in (lines[1:] if start else lines):
        try:
            entry = json.loads(raw)
        except ValueError:
            continue
        if type(entry) is dict and not entry.get('isSidechain'):
            yield entry


def _peer_key(value):
    address = _address(value)
    if address is None:
        return None
    found = _SESSION_KEY.search(address)
    return found.group(0).casefold() if found else _NAME_REF.sub('', address)


def followup_items(entries, now):
    """Overdue requests this session sent, and whether the founder is waiting on this turn."""
    pending, sent, replies, last_prompt, alias = {}, [], [], None, {}

    def root(key):
        while alias.get(key, key) != key:
            key = alias[key]
        return key

    def link(*values):
        keys = {root(key) for key in map(_peer_key, values) if key}
        for key in keys:
            alias[key] = min(keys)  # the smallest key names the session, so it stays stable

    for entry in entries:
        moment = _timestamp(entry.get('timestamp'))
        content = (entry.get('message') or {}).get('content')
        if moment is None:
            continue
        if entry.get('type') == 'assistant' and isinstance(content, list):
            for block in content:
                if type(block) is dict and block.get('type') == 'tool_use' and block.get('name') == 'SendMessage':
                    request = block.get('input') or {}
                    to, message = request.get('to'), request.get('message')
                    if type(to) is str and type(message) is str and _asks_reply(to, message):
                        pending[block.get('id')] = (to, moment)
        elif entry.get('type') == 'user':
            for block in content if isinstance(content, list) else ():
                if type(block) is dict and block.get('type') == 'tool_result' and block.get('tool_use_id') in pending:
                    to, sent_at = pending.pop(block['tool_use_id'])
                    result = _tool_result(block.get('content'))
                    if result.get('success') is True:
                        reference = result.get('msg_id') or result.get('message_id')
                        sent.append((to, sent_at, reference if type(reference) is str else ''))
                        link(to, *_SESSION_KEY.findall(json.dumps(result)))
            origin = entry.get('origin') or {}
            if origin.get('kind') == 'peer':
                forms = (origin.get('from'), origin.get('name'), origin.get('fromSession'))
                link(*forms)
                replies.append((forms, moment))
            if origin.get('kind') in ('human', 'peer', 'task-notification'):
                last_prompt = origin['kind']
    heard = {}
    for forms, moment in replies:
        for key in {root(key) for key in map(_peer_key, forms) if key}:
            heard[key] = max(heard.get(key, 0), moment)
    open_requests = {}
    for to, sent_at, message_id in sent:
        key = root(_peer_key(to))
        if heard.get(key, 0) < sent_at:
            open_requests.setdefault(key, []).append((sent_at, message_id, to))
    items = []
    for key, requests in sorted(open_requests.items()):
        latest, message_id, to = max(requests)
        if now - latest >= FOLLOWUP_DUE_SECONDS and now - min(requests)[0] <= _FOLLOWUP_WINDOW_SECONDS:
            # Cross-session sends may return no id; name the request by peer and send time.
            reference = message_id or '%s @ %s' % (to, time.strftime('%H:%MZ', time.gmtime(latest)))
            items.append({'key': key + '|' + repr(latest), 'to': to, 'message_id': reference,
                          'count': len(requests), 'minutes': int((now - latest) // 60)})
    return items, last_prompt == 'human'


def _followup_state_path(session_id, directory=None):
    if directory is None:
        base = os.environ.get('LOCALAPPDATA')
        if not base or not Path(base).is_absolute():
            raise RuntimeError('Follow-up guard location is unavailable')
        directory = Path(base) / 'ArchHub' / 'runtime-context' / 'native-stop-followup'
    return Path(directory) / (hashlib.sha256(str(session_id).encode()).hexdigest() + '.json')


def _load_guard(path):
    try:
        raw = path.read_bytes()
        value = json.loads(raw) if len(raw) <= 65536 else {}
    except (OSError, ValueError):
        value = {}
    return value if type(value) is dict else {}


def _save_guard(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    try:
        temporary.write_text(json.dumps(value), encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def followup_decision(payload, *, now=None, guard_directory=None):
    """At most one block per overdue item per window, never twice in a row, never on a founder turn."""
    path, session = payload.get('transcript_path'), payload.get('session_id')
    if type(path) is not str or type(session) is not str or not Path(path).is_file():
        return None
    now = time.time() if now is None else now
    items, founder_turn = followup_items(_transcript_tail(path), now)
    guard_path = _followup_state_path(session, guard_directory)
    guard = _load_guard(guard_path)
    marks = {key: dict(value) for key, value in guard.items()
             if key in {item['key'] for item in items} and type(value) is dict}
    decision = None
    if payload.get('stop_hook_active') is True or founder_turn:
        fresh = [item for item in items if item['key'] not in marks]
        for item in items:
            mark = marks.setdefault(item['key'], {'at': now, 'last': 'queued'})
            if mark.get('last') == 'block':
                mark.update(at=now, last='pass')  # the cadence counts from the pass
        if founder_turn and fresh:
            decision = {'systemMessage': 'Follow-up queued (founder turn, not blocked): ' + '; '.join(
                '%s re %s' % (item['to'], item['message_id']) for item in fresh)}
    else:
        due = []
        for item in items:
            mark = marks.get(item['key'])
            if mark is None or mark.get('last') == 'queued' or (
                    mark.get('last') == 'pass' and now - mark.get('at', 0) >= FOLLOWUP_DUE_SECONDS):
                due.append(item)
                marks[item['key']] = {'at': now, 'last': 'block'}
            elif mark.get('last') == 'block':
                mark.update(at=now, last='pass')
        if due:
            lines = ['FOLLOW-UP DUE before this turn ends (founder order: agents chase every unanswered request).']
            for item in due:
                lines.append('- %s: %d unanswered request(s), last sent %d min ago (msg %s). Send FOLLOW-UP #%d re %s '
                             'restating the one question. Re-resolve the address with ListAgents; on the 2nd '
                             'silence use another live channel; on the 3rd escalate to the coordinator.' % (
                                 item['to'], item['count'], item['minutes'], item['message_id'],
                                 item['count'], item['message_id']))
            lines.append('Send numbered follow-ups only; never resend an effect. This block fires once per item.')
            decision = {'decision': 'block', 'reason': '\n'.join(lines)}
    if marks != guard:
        _save_guard(guard_path, marks)
    return decision


def _merge_followup(result, followup):
    if not followup:
        return result
    merged = dict(result or {})
    if 'decision' in followup:
        if merged.get('decision') == 'block':
            merged['reason'] = merged['reason'] + '\n\n' + followup['reason']
        else:
            merged.update(decision='block', reason=followup['reason'])
    elif 'systemMessage' in followup:
        merged['systemMessage'] = ((merged['systemMessage'] + ' ') if merged.get('systemMessage') else '') \
            + followup['systemMessage']
    return merged


# No idle turn end (founder order 2026-09-28): the Work authority answers only while
# the session holds its lease, and an idle session loses it (900 s) or its app
# restarts. Then this hook used to let the turn end with open Work. The host now
# records every verdict it really observed; with the authority unreachable, a
# recorded open-Work block holds the turn end once, with the way back.
NO_IDLE_WINDOW_SECONDS = 24 * 3600
NO_IDLE_REASON = (' The Work authority cannot be reached now (lease expired or app restarted): '
                  'run native_owner_status, then native_owner_rebind with the exact owners it reports, '
                  'and continue this Work. Do not end the turn idle with Work open.')


def _verdict_path(fingerprint, directory=None):
    if directory is None:
        base = os.environ.get('LOCALAPPDATA')
        if not base or not Path(base).is_absolute():
            raise RuntimeError('Stop verdict location is unavailable')
        directory = Path(base) / 'ArchHub' / 'runtime-context' / 'native-stop-verdict'
    if type(fingerprint) is not str or len(fingerprint) != 64:
        raise ValueError('Stop verdict needs its session fingerprint')
    return Path(directory) / (fingerprint + '.json')


def _remember_verdict(fingerprint, value, *, now=None, directory=None):
    """The last verdict the Work authority really gave this session: block or clear."""
    if value and not (set(value) == {'decision', 'reason'} and value['decision'] == 'block'):
        return
    record = {'at': time.time() if now is None else now, 'verdict': dict(value)}
    _save_guard(_verdict_path(fingerprint, directory), record)


def no_idle_decision(payload, vendor, *, now=None, directory=None):
    """Hold one turn end on recorded open Work while the authority is unreachable."""
    if payload.get('stop_hook_active') is True:
        return None
    fingerprint = _fingerprint(canonical_runtime(vendor), payload.get('session_id'))
    record = _load_guard(_verdict_path(fingerprint, directory))
    verdict, at = record.get('verdict'), record.get('at')
    now = time.time() if now is None else now
    if (type(verdict) is not dict or verdict.get('decision') != 'block' or type(verdict.get('reason')) is not str
            or type(at) not in (int, float) or not 0 <= now - at <= NO_IDLE_WINDOW_SECONDS):
        return None
    return {'decision': 'block', 'reason': verdict['reason'][:4000] + NO_IDLE_REASON}


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor',default='claude-code')
    args=parser.parse_args()
    payload=None
    try:
        raw=sys.stdin.buffer.read(65537)
        if len(raw)>65536:
            raise ValueError('Stop input exceeds bound')
        payload=json.loads(raw)
        result=query_stop(payload,vendor=args.vendor)
    except Exception:
        result=_ending_turn(UNAVAILABLE)
    if type(payload) is dict and result==_ending_turn(UNAVAILABLE):
        try:
            result=no_idle_decision(payload,args.vendor) or result
        except Exception:
            pass
    if type(payload) is dict:
        try:
            result=_merge_followup(result,followup_decision(payload))
        except Exception:
            pass
    sys.stdout.write(json.dumps(result))
    return 0


if __name__=='__main__':
    # Direct installed script execution imports only this canonical package.
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
