"""The application's Brain without the graph: the same tool names over one plain owner file.

app_brain answers brain.* from graph cells while a graph is bound in this process. NOGRAPH
binds none, so pipeline_engines._brain_call reaches this owner instead:
settings/brain.json = {"revision": n, "facts": [{id, text, kind, clock, forgotten}]}, replaced
atomically. Forget is soft (the fact is kept, marked forgotten), edit replaces in place,
publish still refuses anything naming the client area and needs the ArchHub cloud review.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import time
from pathlib import Path

BRAIN_NODE = {'id': 'brain.files', 'params': {'list_limit': 500, 'context_limit': 8}}
_FOLDERS = (('user', 'User', ('fact',)), ('feedback', 'Feedback', ('mandate', 'practice')),
            ('projects', 'Projects', ('document',)), ('reference', 'Reference', ('setup', 'spatial', 'hook')))
_WORD = re.compile(r'[a-z0-9]{3,}')
_LOCK = threading.Lock()


def _path():
    return Path(os.environ['LOCALAPPDATA']) / 'ArchHub' / 'settings' / 'brain.json'


def _read():
    try:
        return json.loads(_path().read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {'revision': 0, 'facts': []}


def _save(data):
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data['revision'] += 1
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=1)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _live(data):
    return sorted((f for f in data['facts'] if not f.get('forgotten')), key=lambda f: -f['clock'])


def _record(fact, folder):
    first = fact['text'].strip().splitlines()[0] if fact['text'].strip() else fact['id']
    return {'id': fact['id'], 'name': first[:80], 'desc': first[:160], 'body': fact['text'],
            'type': folder, 'kind': fact['kind'], 'scope': 'user'}


def list_facts(limit, offset=0):
    held = _live(_read())
    page = held[max(0, int(offset)):max(0, int(offset)) + max(1, int(limit))]
    folders, placed = [], set()
    for key, label, kinds in _FOLDERS:
        facts = [f for f in page if f['kind'] in kinds]
        placed.update(f['id'] for f in facts)
        folders.append({'id': key, 'label': label, 'count': len(facts), 'facts': [_record(f, key) for f in facts]})
    rest = [f for f in page if f['id'] not in placed]
    if rest:
        folders.append({'id': 'other', 'label': 'Other', 'count': len(rest), 'facts': [_record(f, 'other') for f in rest]})
    return {'ok': True, 'total': len(page), 'held': len(held), 'offset': int(offset), 'limit': int(limit), 'folders': folders}


def context(prompt, limit):
    wanted = set(_WORD.findall(str(prompt or '').lower()))
    scored = [(-len(wanted & set(_WORD.findall(f['text'].lower()))), -f['clock'], f) for f in _live(_read())] if wanted else []
    scored = sorted((row for row in scored if row[0] < 0), key=lambda row: row[:2])
    return {'facts': [{'id': f['id'], 'text': f['text'], 'kind': f['kind']} for _a, _b, f in scored[:max(1, int(limit))]]}


def _change(fragment_id, change):
    fragment_id = str(fragment_id or '').strip()
    if not fragment_id:
        return {'ok': False, 'error': 'missing fragment_id'}
    with _LOCK:
        data = _read()
        fact = next((f for f in data['facts'] if f['id'] == fragment_id and not f.get('forgotten')), None)
        if fact is None:
            return {'ok': False, 'error': 'no such fact'}
        answer = change(fact)
        if answer.get('ok'):
            fact['clock'] = max(time.time(), fact['clock'] + 1e-6)
            _save(data)
        return answer


def write(ops):
    added = [op['fragment'] for op in (ops or []) if isinstance(op, dict) and str(op.get('op', '')).lower() == 'add'
             and isinstance(op.get('fragment'), dict) and str(op['fragment'].get('text', '')).strip()]
    with _LOCK:
        data = _read()
        for fragment in added:
            data['facts'] = [f for f in data['facts'] if f['id'] != str(fragment['id'])]
            data['facts'].append({'id': str(fragment['id']), 'text': str(fragment['text']).strip(),
                                  'kind': str(fragment.get('kind') or 'fact'), 'clock': time.time()})
        if added:
            _save(data)
    return {'ok': True, 'written': len(added)}


def _publish(fact):
    from .app_brain import names_the_client_area
    if names_the_client_area(fact['text'], fact['id']):
        return {'ok': False, 'error': 'this fact names the client area; it stays on this machine'}
    return {'ok': False, 'error': 'Sharing with the Community Brain needs the ArchHub cloud review; the fact stays on this machine.'}


def call(tool, arguments):
    arguments = dict(arguments or {})
    params = BRAIN_NODE['params']
    if tool == 'brain.health':
        return {'ok': True, 'facts': len(_live(_read())), 'skills': None, 'owner_user': 'local'}
    if tool == 'brain.context':
        return context(arguments.get('prompt', ''), arguments.get('limit', params['context_limit']))
    if tool == 'brain.list_facts':
        return list_facts(arguments.get('limit', params['list_limit']), arguments.get('offset', 0))
    if tool == 'brain.delete_fact':
        return _change(arguments.get('fragment_id'), lambda f: (f.update(forgotten=True), {'ok': True, 'id': f['id']})[1])
    if tool == 'brain.edit_fact':
        text = str(arguments.get('text') or '').strip()
        if not text:
            return {'ok': False, 'error': 'need a fact id and text', 'edited': False}
        return _change(arguments.get('fragment_id'), lambda f: (f.update(text=text), {'ok': True, 'id': f['id'], 'edited': True})[1])
    if tool == 'brain.write':
        return write(arguments.get('ops'))
    if tool == 'brain.publish':
        found = next((f for f in _live(_read()) if f['id'] == str(arguments.get('fragment_id') or '')), None)
        return _publish(found) if found else {'ok': False, 'error': 'no such fact'}
    raise ValueError('the application Brain does not provide %s' % tool)
