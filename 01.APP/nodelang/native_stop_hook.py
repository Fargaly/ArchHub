"""Native hook entry using the current Workshop and declaration owners."""
from datetime import datetime

import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
import uuid

if not globals().get("__package__"):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    __package__ = "nodelang"

from .user_paths import state_directory

SERVICE = 'ArchHub.NativeStop.v1'
UNAVAILABLE = {'decision':'block','reason':'Native Stop authority is unavailable. Continue through the existing native session to reconcile; do not create a replacement session.'}
# The CDE write gate is a separate command-hook process. While this owner holds
# the session's live binding, the gate's own bind_agent_session is refused
# ("identity is already bound; renew it instead"; live 717, 2026-10-01), so the
# gate asks for the exact permit or receipt through this same per-session pipe
# and the owner's bound client. Exact fields only; session and vendor select
# the owner and are never forwarded.
_WRITE_NAMES = {'brain.universal_cde_write_permit': 'cde_write_permit',
                'native.hook_user_prompt_submit': 'user_prompt_submit',
                'brain.universal_cde_write_receipt': 'cde_write_receipt',
                'brain.private_root_grant_status': 'private_root_grant_status'}
_WRITE_OPERATIONS = {
    'user_prompt_submit': (None, frozenset({'prompt_sha256'})),
    'cde_write_permit': ('issue_cde_write_permit',
                         frozenset({'operation', 'path', 'content_digest', 'request_id', 'nonce'})),
    'cde_write_receipt': ('consume_cde_write_permit',
                          frozenset({'operation', 'path', 'content_digest', 'request_id', 'permit'})),
    'private_root_grant_status': ('private_root_grant_status',
                                  frozenset({'operation', 'path'})),
}
_WRITE_REQUEST_BYTES = 65536
_WRITE_TIMEOUT_SECONDS = 25.0


class OwnerAbsent(RuntimeError):
    """Pre-dispatch: no live owner pipe took the request; nothing was sent.

    Only this outcome lets a caller use another route.
    """


class OwnerWriteFailed(RuntimeError):
    """Post-dispatch: the request was sent and no exact result came back.

    A timeout, a closed pipe, a mismatched or malformed reply: the permit or
    receipt may exist. Fail closed; never enroll, retry or replay.
    """


class OwnerWriteDenied(OwnerWriteFailed):
    """Post-dispatch: the owner answered with a refusal (the application's, or its own)."""


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








def _alive(pid, created_at):
    import psutil
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.create_time() == created_at
    except psutil.NoSuchProcess:
        return False






def _recovery_path(fingerprint, directory=None):
    return _verdict_path(fingerprint, directory).with_suffix('.recovery.json')


def _told_path(fingerprint, directory=None):
    return _verdict_path(fingerprint, directory).with_suffix('.told.json')




# The session variables each runtime itself sets; another runtime's variable in
# the same environment is an inherited parent's, never this payload's identity.
_STOP_IDENTITY_ENV={'claude':('CLAUDE_CODE_SESSION_ID','CLAUDE_SESSION_ID'),'codex':('CODEX_THREAD_ID',)}






def query_stop(payload, *, vendor, vault=None, environment=None):
    from .baboom_reactions import emit
    emit({**payload, 'hook_event_name': payload.get('hook_event_name') or 'Stop'}, vendor, environment=environment)
    from .native_agent_hooks import declare_session
    declare_session(payload, vendor)
    return {}


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
# A reply that lands mid-turn is queued, not prompted: an attachment (queued_command)
# or a queue-operation whose text carries the cross-session tag with the sender forms.
_QUEUED_TAG = re.compile(r'<\\?~?cross-session-message\b([^>]*)>')
_TAG_ATTR = re.compile(r'\b(from|from-session|from-name|name)="([^"]*)"')


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


_LOCAL_IDLE_ASK = re.compile(r'(want me to|should i|do you want|let me know if|تحب|عايزني)', re.IGNORECASE)
_LOCAL_IDLE_DEFERRED = re.compile(r'\bdeferred:\s*needs\s+\S+', re.IGNORECASE)
_LOCAL_IDLE_FOLLOWED = re.compile(r'\bFOLLOW-UP\s+#?(\d+)\b', re.IGNORECASE)
_LOCAL_IDLE_STOP = re.compile(r'(?<![A-Za-z])(STOP|PAUSE|HOLD)(?![A-Za-z])', re.IGNORECASE)
_LOCAL_QUEUE = re.compile(r'(?im)^\s*(sent-but-unanswered|adopted-not-installed)\s*:\s*(.+?)\s*$')
_LOCAL_IDLE_REASON = ('Continue the work instead of ending on a question or offer. '
                      'If blocked, state the exact deferred need as "deferred: needs <thing>".')
_LOCAL_QUEUE_REASON = ('Resolve the local follow-up queue before ending: %s. '
                       'Follow it up or write "deferred: needs <thing>".')


def _text_parts(value):
    if type(value) is str:
        yield value
        return
    if isinstance(value, list):
        for item in value:
            if type(item) is str:
                yield item
            elif type(item) is dict:
                text = item.get('text')
                if type(text) is str:
                    yield text


def _entry_human_text(entry):
    if entry.get('type') != 'user':
        return None
    content = (entry.get('message') or {}).get('content')
    if isinstance(content, list) and any(type(item) is dict and item.get('type') == 'tool_result'
                                        for item in content):
        return None
    text = ' '.join(part for part in _text_parts(content) if part.strip())
    return text or None


def _entry_assistant_text(entry):
    content = (entry.get('message') or {}).get('content')
    if entry.get('type') == 'assistant':
        text = ' '.join(part for part in _text_parts(content) if part.strip())
        return text or None
    if entry.get('type') in _CODEX_ENTRY_TYPES and type(entry.get('payload')) is dict:
        payload = entry['payload']
        if payload.get('role') == 'assistant' and payload.get('channel', 'final') == 'final':
            text = ' '.join(part for part in _text_parts(payload.get('content')) if part.strip())
            if text:
                return text
        item = payload.get('item') if type(payload.get('item')) is dict else None
        if item and item.get('role') == 'assistant' and item.get('channel', 'final') == 'final':
            text = ' '.join(part for part in _text_parts(item.get('content')) if part.strip())
            if text:
                return text
    return None


def _last_assistant_text(entries):
    text = None
    for entry in entries:
        human = _entry_human_text(entry)
        if human is not None:
            if _LOCAL_IDLE_STOP.search(human):
                return None
            text = None
            continue
        current = _entry_assistant_text(entry)
        if current:
            text = current
    return text


def local_idle_stop_decision(payload, vendor):
    """Transcript-only idle guard: ending on a question/offer is still live work."""
    if payload.get('stop_hook_active') is True:
        return None
    path = payload.get('transcript_path')
    if type(path) is not str or not Path(path).is_file():
        return None
    canonical_runtime(vendor)
    text = _last_assistant_text(_transcript_tail(path))
    if type(text) is not str:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    queued = [(str(index + 1), ': '.join(match))
              for index, match in enumerate(_LOCAL_QUEUE.findall(stripped))]
    if queued:
        followed = {match.group(1) for match in _LOCAL_IDLE_FOLLOWED.finditer(stripped)}
        remaining = [text for item_id, text in queued if item_id not in followed]
        if remaining:
            return {'decision': 'block', 'reason': _LOCAL_QUEUE_REASON % '; '.join(remaining[:8])}
        return None
    if _LOCAL_IDLE_DEFERRED.search(stripped):
        return None
    if stripped.endswith(('?', '؟')) or _LOCAL_IDLE_ASK.search(stripped):
        return {'decision': 'block', 'reason': _LOCAL_IDLE_REASON}
    return None


def _peer_key(value):
    address = _address(value)
    if address is None:
        return None
    found = _SESSION_KEY.search(address)
    return found.group(0).casefold() if found else _NAME_REF.sub('', address)


# Codex rollouts (vendor codex): {timestamp, type, payload}. Sends are collaboration
# send_message/followup_task {target, message}, send_message_to_thread {threadId,
# prompt}, or an exec running workshop.ps1 send <connection> --file <text>.
# Replies from Claude carry the bridge header (workshop/bridge.mjs) naming the
# Claude session and the link. /root/... targets are the task's own subagents.
_CODEX_ENTRY_TYPES = ('response_item', 'event_msg', 'compacted')
_CODEX_LINK_SEND = re.compile(r'workshop\.ps1\W{0,6}\s+send\s+\W?([0-9a-f]{16})\W?\s+--file\s+\W?([A-Za-z]:[^\x27"\r\n]+?)\W?(?:\s|$)')
_CODEX_REPLY = re.compile(r'\[From Claude Code: [^;\]]*; session ([0-9a-f-]{36}); link ([0-9a-f]{16}); message')


def _message_roots():
    import tempfile
    return (Path(tempfile.gettempdir()).resolve(), (Path.home() / '00.ARCHUB' / '70.COMPANY/72.HANDOFFS').resolve())


def _message_file(path, sent_at=None):
    """The text a Workshop send carried: only a message file under the temp or
    handoff roots, where agents write them. Any other path is never opened."""
    try:
        target = Path(path).resolve()
        if (target.is_absolute() and any(target.is_relative_to(root) for root in _message_roots())
                and target.is_file() and target.stat().st_size <= 65536
                # Changed after the send: its text is no longer what was sent; skip it.
                and (sent_at is None or target.stat().st_mtime <= sent_at + 2)):
            return target.read_text(encoding='utf-8', errors='replace')
    except (OSError, ValueError):
        pass
    return None


def _codex_output_ok(payload):
    """A send counts only when it did not fail, as on the Claude path: an exec of
    workshop carries no failure marker; a collaboration send answers empty."""
    output = payload.get('output')
    if isinstance(output, list):
        return bool(output) and 'error' not in json.dumps(output).lower()
    if not isinstance(output, str):
        return False
    if payload.get('type') == 'custom_tool_call_output':
        text = output[:65536]
        exit_code = re.search(r'Exit code:\s*(-?\d+)', text)
        return not ('Script failed' in text or '"ok": false' in text or (exit_code and exit_code.group(1) != '0'))
    return output == ''


def _codex_events(payload, moment=None):
    """Normalised sends, send results and replies from one Codex rollout payload."""
    kind, call = payload.get('type'), payload.get('call_id')
    if kind == 'function_call':
        try:
            args = json.loads(payload.get('arguments') or '{}')
        except ValueError:
            args = {}
        to = text = None
        if type(args) is dict and payload.get('name') in ('send_message', 'followup_task'):
            to, text = args.get('target'), args.get('message')
        elif type(args) is dict and payload.get('name') == 'send_message_to_thread':
            to, text = args.get('threadId'), args.get('prompt')
        if type(to) is str and type(text) is str and not to.startswith('/'):
            yield 'send', call, to, text
        return
    if kind == 'custom_tool_call':
        found = _CODEX_LINK_SEND.search(str(payload.get('input') or '')[:65536])
        text = _message_file(found.group(2).strip(), moment) if found else None
        if text is not None:
            yield 'send', call, found.group(1), text
        return
    if kind in ('function_call_output', 'custom_tool_call_output'):
        yield 'result', call, _codex_output_ok(payload)
        return
    # Only an inbound bridge delivery answers a request: never the task's own
    # messages, reasoning, commands or edits that merely quote the header.
    item = payload.get('item') if kind == 'item_completed' and isinstance(payload.get('item'), dict) else None
    if item is not None and item.get('type') in ('FunctionCallOutput', 'UserMessage'):
        for session, link in _CODEX_REPLY.findall(json.dumps(item)[:262144]):
            yield 'reply', (link, session, 'local_' + session)


def _peer_registry(directory):
    """Name, pipe and local_ id of each live Claude-side peer (~/.claude/sessions/*.json).

    A Workshop bridge registers there under its peer name; its replies arrive
    from its pipe alone, so this is what ties the two together. Read-only, bounded.
    """
    try:
        import psutil
        records = sorted(Path(directory).glob('*.json'))[:256]
    except (ImportError, OSError):
        return []
    newest = {}
    for record in records:
        try:
            if record.stat().st_size > 65536:
                continue
            value = json.loads(record.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if (type(value) is not dict or type(value.get('name')) is not str
                or type(value.get('messagingSocketPath')) is not str or type(value.get('pid')) is not int):
            continue
        # A stale file of an exited session must never vouch for a live one.
        if not psutil.pid_exists(value['pid']):
            continue
        started = value.get('startedAt') if type(value.get('startedAt')) is int else 0
        name = _address(value['name'])
        if name and (name not in newest or started > newest[name][0]):
            session = value.get('sessionId')
            newest[name] = (started, (value['name'], value['messagingSocketPath'],
                                      'local_' + session if type(session) is str else None))
    # One record per name: two different pipes are never tied together through a name.
    return [forms for _, forms in newest.values()]


def _queued_replies(entry):
    """The sender forms of peer replies that arrived mid-turn and were queued."""
    attachment = entry.get('attachment') if type(entry.get('attachment')) is dict else {}
    found = []
    origin = attachment.get('origin')
    if type(origin) is dict and origin.get('kind') == 'peer':
        found.append((origin.get('from'), origin.get('name'), origin.get('fromSession')))
    for text in (attachment.get('prompt'), entry.get('content')):
        found.extend(_tag_forms(text))
    return found


def _tag_forms(text):
    """Sender forms in cross-session tags; host-injected replies name the sender as name=."""
    forms = []
    if type(text) is str:
        for tag in _QUEUED_TAG.findall(text[:65536]):
            attrs = dict(_TAG_ATTR.findall(tag))
            forms.append((attrs.get('from'), attrs.get('from-name') or attrs.get('name'), attrs.get('from-session')))
    return forms


_CLOSED_WORD = re.compile(r'(?<![A-Za-z])CLOSED(?![A-Za-z])')
_REASSIGNED = re.compile(r'reassign', re.IGNORECASE)


def _closed(key, sent_at, message_id, closes, unreachable, root):
    """A later message to the same peer closed this request, or the peer is gone."""
    for to, said_at, message in closes:
        if said_at <= sent_at or root(_peer_key(to)) != key:
            continue
        if _REASSIGNED.search(message) and not _asks_reply(to, message):
            # A reassignment notice (itself not a new question) hands the work on.
            return True
        if message_id and message_id in message and (_CLOSED_WORD.search(message) or _NO_REPLY.search(message)):
            return True
    return any(said_at > sent_at and root(_peer_key(to)) == key for to, said_at in unreachable)


def followup_items(entries, now, *, registry=()):
    """Overdue requests this session sent, and whether the founder is waiting on this turn."""
    pending, sent, replies, last_prompt, alias = {}, [], [], None, {}
    notes, closes, unreachable = {}, [], []

    def root(key):
        while alias.get(key, key) != key:
            key = alias[key]
        return key

    def link(*values):
        keys = {root(key) for key in map(_peer_key, values) if key}
        for key in keys:
            alias[key] = min(keys)  # the smallest key names the session, so it stays stable

    for forms in registry:
        link(*forms)
    for entry in entries:
        moment = _timestamp(entry.get('timestamp'))
        content = (entry.get('message') or {}).get('content')
        if moment is None:
            continue
        if entry.get('type') in _CODEX_ENTRY_TYPES and type(entry.get('payload')) is dict:
            for event in _codex_events(entry['payload'], moment):
                if event[0] == 'send' and _asks_reply(event[2], event[3]):
                    pending[event[1]] = (event[2], moment)
                elif event[0] == 'result' and event[1] in pending:
                    to, sent_at = pending.pop(event[1])
                    if event[2]:
                        sent.append((to, sent_at, ''))
                elif event[0] == 'reply':
                    link(*event[1])
                    replies.append((event[1], moment))
            continue
        if entry.get('type') == 'assistant' and isinstance(content, list):
            for block in content:
                if type(block) is dict and block.get('type') == 'tool_use' and block.get('name') == 'SendMessage':
                    request = block.get('input') or {}
                    to, message = request.get('to'), request.get('message')
                    if type(to) is str and type(message) is str:
                        notes[block.get('id')] = (to, message, moment)
                    if type(to) is str and type(message) is str and _asks_reply(to, message):
                        pending[block.get('id')] = (to, moment)
        elif entry.get('type') in ('attachment', 'queue-operation'):
            for forms in _queued_replies(entry):
                link(*forms)
                replies.append((forms, moment))
        elif entry.get('type') == 'user':
            for block in content if isinstance(content, list) else ():
                if type(block) is dict and block.get('type') == 'tool_result' and block.get('tool_use_id') in notes:
                    # Every send is also read for closure: a message naming a request
                    # as CLOSED (or no reply needed), a reassignment notice, or a send
                    # the transport reports as unreachable.
                    to, message, said_at = notes.pop(block['tool_use_id'])
                    result = _tool_result(block.get('content'))
                    if result.get('success') is True:
                        closes.append((to, said_at, message))
                    elif any(word in json.dumps(result).casefold() for word in ('reachable', 'enoinbox', 'socket path is stale')):
                        unreachable.append((to, said_at))
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
                # A host-injected reply carries only from=local_ in its origin; its
                # tag in the prompt text also names the sender.
                for tagged in _tag_forms(content):
                    link(*tagged)
                    replies.append((tagged, moment))
            if origin.get('kind') in ('human', 'peer', 'task-notification'):
                last_prompt = origin['kind']
    heard = {}
    for forms, moment in replies:
        for key in {root(key) for key in map(_peer_key, forms) if key}:
            heard[key] = max(heard.get(key, 0), moment)
    open_requests = {}
    for to, sent_at, message_id in sent:
        key = root(_peer_key(to))
        if _closed(key, sent_at, message_id, closes, unreachable, root):
            continue
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
        directory = state_directory() / 'runtime-context' / 'native-stop-followup'
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


def followup_decision(payload, *, now=None, guard_directory=None, registry_directory=None):
    """At most one block per overdue item per window, never twice in a row, never on a founder turn."""
    path, session = payload.get('transcript_path'), payload.get('session_id')
    if type(path) is not str or type(session) is not str or not Path(path).is_file():
        return None
    now = time.time() if now is None else now
    items, founder_turn = followup_items(_transcript_tail(path), now,
                                         registry=_peer_registry(registry_directory) if registry_directory else ())
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
            decision = {'systemMessage': 'Follow-up queued (your turn, not blocked): ' + '; '.join(
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
            lines = ['Follow-up due: an agent request you sent has no reply yet. Before this turn ends:']
            for item in due:
                lines.append('- %s: %d unanswered request(s), last sent %d min ago (msg %s). Send FOLLOW-UP #%d re %s '
                             'restating the one question. Re-resolve the address with ListAgents; on the 2nd '
                             'silence use another live channel; on the 3rd escalate to the coordinator.' % (
                                 item['to'], item['count'], item['minutes'], item['message_id'],
                                 item['count'], item['message_id']))
            lines.append('Send numbered follow-ups only; never resend an effect. This repeats every %d minutes '
                         'while an item stays open; to close one, message that peer naming its msg id with '
                         'CLOSED or "no reply needed".' % (FOLLOWUP_DUE_SECONDS // 60))
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
# The native owner process reconnects the same actor itself (recover_same_actor);
# the agent is never sent to a tool that may be unreachable, and this is said once.
NO_IDLE_REASON = (' The Work authority cannot be reached now (the application restarted or the lease '
                  'expired). ArchHub reconnects this session to its same actor automatically; there is '
                  'nothing to run. Continue this Work once it answers. This is said once.')
IMPOSSIBLE_REASON = (' ArchHub could not reconnect this session to its actor automatically: %s. '
                     'This is said once.')


def _verdict_path(fingerprint, directory=None):
    if directory is None:
        base = os.environ.get('LOCALAPPDATA')
        if not base or not Path(base).is_absolute():
            raise RuntimeError('Stop verdict location is unavailable')
        directory = state_directory() / 'runtime-context' / 'native-stop-verdict'
    if type(fingerprint) is not str or len(fingerprint) != 64 or not set(fingerprint) <= set('0123456789abcdef'):
        raise ValueError('Stop verdict needs its session fingerprint')
    return Path(directory) / (fingerprint + '.json')


def _remember_verdict(fingerprint, value, *, now=None, directory=None):
    """The last verdict the Work authority really gave this session: block or clear."""
    if value and not (set(value) == {'decision', 'reason'} and value['decision'] == 'block'):
        return
    record = {'at': time.time() if now is None else now, 'verdict': dict(value)}
    _save_guard(_verdict_path(fingerprint, directory), record)


def no_idle_decision(payload, vendor, *, now=None, directory=None):
    """While the authority is unreachable, say what is known once per episode.

    Recorded open Work holds the first turn end, with what the native owner
    process is doing about it: reconnecting the same actor, or the one step it
    could not take. Every later turn end of the same episode is quiet ({}); a
    new verdict or a new recovery outcome is a new episode. None when there is
    nothing to say (no open Work, an old record, or the turn's second Stop).
    """
    if payload.get('stop_hook_active') is True:
        return None
    fingerprint = _fingerprint(canonical_runtime(vendor), payload.get('session_id'))
    record = _load_guard(_verdict_path(fingerprint, directory))
    verdict, at = record.get('verdict'), record.get('at')
    now = time.time() if now is None else now
    open_work = (type(verdict) is dict and verdict.get('decision') == 'block' and type(verdict.get('reason')) is str
                 and type(at) in (int, float) and 0 <= now - at <= NO_IDLE_WINDOW_SECONDS)
    recovery = _load_guard(_recovery_path(fingerprint, directory))
    impossible = recovery.get('state') == 'impossible' and type(recovery.get('reason')) is str
    episode = [at if open_work else None, recovery.get('state'), recovery.get('reason')]
    told_path = _told_path(fingerprint, directory)
    if _load_guard(told_path).get('episode') == episode:
        return {}                              # said once already: this turn may end quietly
    _save_guard(told_path, {'episode': episode, 'at': now})
    if not open_work:
        if impossible:
            return {'systemMessage': (IMPOSSIBLE_REASON % recovery['reason'][:600]).strip()}
        return None                            # the plain "unavailable" notice, this once
    suffix = IMPOSSIBLE_REASON % recovery['reason'][:600] if impossible else NO_IDLE_REASON
    return {'decision': 'block', 'reason': verdict['reason'][:4000] + suffix}


def _declaration_notice(payload, vendor, *, directory=None):
    """Use the existing local Stop guards; an advisory is shown once per session."""
    if type(payload) is not dict or not payload.get('session_id'):
        return ''
    fingerprint = _fingerprint(canonical_runtime(vendor), payload['session_id'])
    path = _verdict_path(fingerprint, directory).with_suffix('.declaration.json')
    if _load_guard(path).get('shown'):
        return ''
    from nodelang.agent_declarations import reminder
    notice = reminder(mailbox=lambda: {"declarations": []})
    _save_guard(path, {'shown': True})
    return notice


def main():
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--vendor',default='claude-code')
    parser.add_argument('--session-start', action='store_true')
    args=parser.parse_args()
    if args.session_start:
        try:
            from nodelang.native_agent_hooks import declare_session
            declare_session(json.loads(sys.stdin.buffer.read(65537) or b'{}'), args.vendor)
        except Exception as failure:
            print('Workshop session declaration failed (%s); retry declare in the session. Startup continues.'
                  % type(failure).__name__, file=sys.stderr)
        sys.stdout.write('{}\n')
        return 0
    if args.vendor == 'cursor':
        raw=sys.stdin.buffer.read(65537)
        if len(raw)>65536:
            sys.stdout.write('{}\n')
            return 0
        try:
            payload=json.loads(raw or b'{}')
        except ValueError:
            payload={}
        from .native_agent_hooks import emit_cursor_hook
        return emit_cursor_hook(payload if type(payload) is dict else {})
    payload=None
    try:
        raw=sys.stdin.buffer.read(65537)
        if len(raw)>65536:
            raise ValueError('Stop input exceeds bound')
        payload=json.loads(raw)
        result=query_stop(payload,vendor=args.vendor)
    except Exception:
        result=_ending_turn(UNAVAILABLE)
    if type(payload) is dict:
        try:
            decision=local_idle_stop_decision(payload,args.vendor)
            if decision is not None:
                result=decision
        except Exception:
            pass
    if type(payload) is dict and result==_ending_turn(UNAVAILABLE):
        try:
            decision=no_idle_decision(payload,args.vendor)
            if decision is not None:
                result=decision
        except Exception:
            pass
    if type(payload) is dict:
        try:
            result=_merge_followup(result,followup_decision(payload,registry_directory=Path.home()/'.claude'/'sessions'))
        except Exception:
            pass
    usage_failure = ''
    if type(payload) is dict and args.vendor == 'claude-code':
        # shortcut: Claude transcripts only; Codex/OpenCode usage needs their own transcript readers.
        try:
            from nodelang.agent_budget import record_entries
            record_entries(_transcript_tail(payload['transcript_path']),
                           canonical_runtime(args.vendor) + ':' + payload['session_id'])
        except Exception as exc:
            usage_failure = 'Token usage for this turn was not recorded (%s); it is retried next turn.' % type(exc).__name__
    try:
        notice = _declaration_notice(payload, args.vendor)
    except (OSError, ValueError, RuntimeError):
        notice = ''
    notice = ' '.join(filter(None, (notice, usage_failure)))
    if notice:
        result = {**result, "systemMessage": " ".join(filter(None, (result.get("systemMessage"), notice)))}
    sys.stdout.write(json.dumps(result))
    return 0


if __name__=='__main__':
    # Direct installed script execution imports only this canonical package.
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    raise SystemExit(main())
