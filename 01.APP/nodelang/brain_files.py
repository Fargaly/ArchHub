"""The application's Brain without the graph: one SQLite file, FTS5 + sqlite-vec, beliefs with evidence.

app_brain answers brain.* from graph cells while a graph is bound in this process. NOGRAPH
binds none, so pipeline_engines._brain_call reaches this owner instead. The store is ONE file,
settings/brain.sqlite (decision D-BRAINSTORE):

  beliefs   one row per version of a fact: fact_id, kind, text, valid_from, valid_to, forgotten,
            superseded_by. The current belief of a fact is its row with valid_to NULL (Graphiti's
            validity window); an edit or a later fact that names ``supersedes`` closes the old row
            and opens a new one, so a correction wins and the old text stays as history.
  evidence  why a belief is held (Hindsight's belief/evidence split): source + quote + time.
  chunks    the current beliefs cut into Contextual Retrieval chunks (kind and first line
            prefixed), indexed by chunk_fts (FTS5 bm25) and chunk_vec (sqlite-vec bit[] KNN, rescored by
            int8 cosine on chunks.embedding) and fused by reciprocal rank. Only current beliefs are indexed; ``as_of`` reads history.

Vectors are local hashed word + character-trigram embeddings: no model, no network. Forget is
soft (the version closes, marked forgotten, and stays in history), publish still refuses anything
naming the client area and needs the ArchHub cloud review. The former settings/brain.json is
imported once and renamed brain.json.imported.
"""
from __future__ import annotations

from .user_paths import state_directory

import hashlib
import json
import math
import os
import re
import sqlite3
import sqlite_vec  # requirements.txt pins it; preload at import so Windows DLL init never races HTTP threads
import struct
import threading
import time
import unicodedata
import urllib.parse

BRAIN_NODE = {'id': 'brain.files', 'params': {'list_limit': 500, 'context_limit': 8,
                                              'dimensions': 256, 'chunk_chars': 600}}
_FOLDERS = (('user', 'User', ('fact',)), ('feedback', 'Feedback', ('mandate', 'practice')),
            ('projects', 'Projects', ('document',)), ('reference', 'Reference', ('setup', 'spatial', 'hook')))
_WORD = re.compile(r'\w{2,}', re.UNICODE)
_LOCK = threading.RLock()
_OPEN: dict[str, sqlite3.Connection] = {}
_RRF = 60  # reciprocal-rank-fusion constant (Cormack et al. 2009)
_SCHEMA = """
CREATE TABLE IF NOT EXISTS beliefs(
  id INTEGER PRIMARY KEY, fact_id TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL,
  valid_from REAL NOT NULL, valid_to REAL, forgotten INTEGER NOT NULL DEFAULT 0, superseded_by INTEGER);
CREATE UNIQUE INDEX IF NOT EXISTS beliefs_current ON beliefs(fact_id) WHERE valid_to IS NULL;
CREATE INDEX IF NOT EXISTS beliefs_fact ON beliefs(fact_id, valid_from);
CREATE TABLE IF NOT EXISTS evidence(
  id INTEGER PRIMARY KEY, belief INTEGER NOT NULL REFERENCES beliefs(id), source TEXT NOT NULL,
  quote TEXT NOT NULL, at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS evidence_belief ON evidence(belief);
CREATE INDEX IF NOT EXISTS beliefs_superseded ON beliefs(superseded_by) WHERE superseded_by IS NOT NULL;
CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, belief INTEGER NOT NULL REFERENCES beliefs(id),
  embedding BLOB NOT NULL);
CREATE INDEX IF NOT EXISTS chunks_belief ON chunks(belief);
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(text, tokenize='unicode61 remove_diacritics 2');
"""


def _path():
    return state_directory() / 'settings' / 'brain.sqlite'


def _db():
    """The one Brain connection for the current profile (opened, migrated and indexed once)."""
    path = _path()
    key = str(path)
    connection = _OPEN.get(key)
    if connection is not None:
        return connection
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
    connection.enable_load_extension(True)
    sqlite_vec.load(connection)
    connection.enable_load_extension(False)
    connection.execute('PRAGMA busy_timeout=5000')  # another ArchHub process may hold the write lock
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA foreign_keys=ON')
    connection.executescript(_SCHEMA)
    connection.execute('CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0('
                       'embedding bit[%d])' % BRAIN_NODE['params']['dimensions'])
    _import_json(connection, path.with_name('brain.json'))
    _OPEN[key] = connection
    return connection


def close():
    """Close every open Brain file (shutdown, or a test that swaps profiles)."""
    with _LOCK:
        for connection in _OPEN.values():
            connection.close()
        _OPEN.clear()


def _import_json(connection, legacy):
    """The NOGRAPH brain.json owner this store replaces: imported once, then renamed, never deleted."""
    if not legacy.is_file():
        return
    data = json.loads(legacy.read_text(encoding='utf-8'))
    with _tx(connection):
        for fact in data.get('facts', []):
            belief = _open_belief(connection, str(fact['id']), str(fact.get('kind') or 'fact'), str(fact['text']),
                                  float(fact.get('clock') or time.time()), 'imported from brain.json', str(fact['text']))
            if fact.get('forgotten'):
                _close_belief(connection, belief, float(fact.get('clock') or time.time()), forgotten=True)
    os.replace(legacy, legacy.with_name('brain.json.imported'))


class _tx:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        self.connection.execute('BEGIN IMMEDIATE')

    def __exit__(self, kind, *_):
        self.connection.execute('COMMIT' if kind is None else 'ROLLBACK')


def _normal(text):
    return unicodedata.normalize('NFKC', str(text)).casefold()


def embed(text, dimensions=None):
    """A local hashed embedding: words and character trigrams, signed, L2-normalised."""
    dimensions = dimensions or BRAIN_NODE['params']['dimensions']
    vector = [0.0] * dimensions
    for word in _WORD.findall(_normal(text)):
        padded = '<%s>' % word
        for feature, weight in [('w:' + word, 1.0)] + [('c:' + padded[i:i + 3], 0.5) for i in range(len(padded) - 2)]:
            digest = hashlib.blake2b(feature.encode('utf-8'), digest_size=8).digest()
            slot = int.from_bytes(digest[:4], 'little') % dimensions
            vector[slot] += weight if digest[4] & 1 else -weight
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return struct.pack('%df' % dimensions, *(v / norm for v in vector))


def _chunks(kind, text):
    """Contextual Retrieval: each chunk carries the fact's kind and first line as its context."""
    size = BRAIN_NODE['params']['chunk_chars']
    first = text.strip().splitlines()[0][:160] if text.strip() else ''
    if len(text) <= size:
        return ['%s. %s' % (kind, text)]
    parts, current = [], ''
    for sentence in re.split(r'(?<=[.!?\n])\s+', text):
        if current and len(current) + len(sentence) > size:
            parts.append(current)
            current = ''
        current = (current + ' ' + sentence).strip()
    parts.append(current)
    return ['%s. %s\n%s' % (kind, first, part) for part in parts if part]


def _open_belief(connection, fact_id, kind, text, at, source, quote):
    belief = connection.execute('INSERT INTO beliefs(fact_id, kind, text, valid_from) VALUES (?,?,?,?)',
                                (fact_id, kind, text, at)).lastrowid
    connection.execute('INSERT INTO evidence(belief, source, quote, at) VALUES (?,?,?,?)', (belief, source, quote, at))
    for chunk in _chunks(kind, text):
        vector = embed(chunk)
        row = connection.execute(
            'INSERT INTO chunks(belief, embedding) VALUES (?, vec_quantize_int8(?, \'unit\'))', (belief, vector)).lastrowid
        connection.execute('INSERT INTO chunk_fts(rowid, text) VALUES (?,?)', (row, chunk))
        connection.execute('INSERT INTO chunk_vec(rowid, embedding) VALUES (?, vec_quantize_binary(?))', (row, vector))
    return belief


def _close_belief(connection, belief, at, *, forgotten=False, superseded_by=None):
    """End a belief's validity window and drop it from the search index (history keeps it)."""
    connection.execute('UPDATE beliefs SET valid_to=?, forgotten=?, superseded_by=? WHERE id=?',
                       (at, int(forgotten), superseded_by, belief))
    for (row,) in connection.execute('SELECT id FROM chunks WHERE belief=?', (belief,)).fetchall():
        connection.execute('DELETE FROM chunk_fts WHERE rowid=?', (row,))
        connection.execute('DELETE FROM chunk_vec WHERE rowid=?', (row,))
    connection.execute('DELETE FROM chunks WHERE belief=?', (belief,))


def _current(connection, fact_id):
    return connection.execute('SELECT id, kind, text, valid_from FROM beliefs WHERE fact_id=? AND valid_to IS NULL',
                              (fact_id,)).fetchone()


def _supersede(connection, fact_id, kind, text, source, quote, *, replaces=()):
    """Write a new version of ``fact_id``; every named older belief closes, linked to it."""
    at = time.time()
    olds = [old for old in (_current(connection, fid) for fid in dict.fromkeys((fact_id,) + tuple(replaces))) if old]
    at = max([at] + [old[3] + 1e-6 for old in olds])
    for old in olds:
        _close_belief(connection, old[0], at)
    belief = _open_belief(connection, fact_id, kind, text, at, source, quote)
    for old in olds:
        connection.execute('UPDATE beliefs SET superseded_by=? WHERE id=?', (belief, old[0]))
    return belief


def _evidence(connection, belief):
    return [{'source': s, 'quote': q, 'at': a} for s, q, a in connection.execute(
        'SELECT source, quote, at FROM evidence WHERE belief=? ORDER BY at, id', (belief,))]


def _replaced(connection, belief):
    return [{'id': f, 'text': t, 'valid_from': vf, 'valid_to': vt} for f, t, vf, vt in connection.execute(
        'SELECT fact_id, text, valid_from, valid_to FROM beliefs WHERE superseded_by=? ORDER BY valid_from', (belief,))]


def _live(connection):
    return connection.execute('SELECT id, fact_id, kind, text, valid_from FROM beliefs '
                              'WHERE valid_to IS NULL ORDER BY valid_from DESC').fetchall()


def _record(connection, row, folder):
    belief, fact_id, kind, text, _at = row
    first = text.strip().splitlines()[0] if text.strip() else fact_id
    return {'id': fact_id, 'name': first[:80], 'desc': first[:160], 'body': text, 'type': folder, 'kind': kind,
            'scope': 'user', 'evidence': _evidence(connection, belief), 'replaces': _replaced(connection, belief)}


def list_facts(limit, offset=0):
    with _LOCK:
        connection = _db()
        held = _live(connection)
        page = held[max(0, int(offset)):max(0, int(offset)) + max(1, int(limit))]
        folders, placed = [], set()
        for key, label, kinds in _FOLDERS:
            facts = [row for row in page if row[2] in kinds]
            placed.update(row[1] for row in facts)
            folders.append({'id': key, 'label': label, 'count': len(facts),
                            'facts': [_record(connection, row, key) for row in facts]})
        rest = [row for row in page if row[1] not in placed]
        if rest:
            folders.append({'id': 'other', 'label': 'Other', 'count': len(rest),
                            'facts': [_record(connection, row, 'other') for row in rest]})
        return {'ok': True, 'total': len(page), 'held': len(held), 'offset': int(offset), 'limit': int(limit),
                'folders': folders}


def _fts_query(prompt):
    words = list(dict.fromkeys(_WORD.findall(_normal(prompt))))
    return ' OR '.join('"%s"' % w.replace('"', '""') for w in words)


def search(prompt, limit):
    """Current beliefs ranked by FTS5 bm25 and sqlite-vec cosine, fused by reciprocal rank."""
    query = _fts_query(prompt)
    if not query:
        return []
    connection = _db()
    depth = max(20, 4 * int(limit))
    lexical = [row for (row,) in connection.execute(
        'SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ? ORDER BY bm25(chunk_fts) LIMIT ?', (query, depth))]
    wanted = embed(prompt)
    # Hamming KNN over the 1-bit index picks candidates; int8 cosine on the stored vectors orders them.
    candidates = [row for (row,) in connection.execute(
        'SELECT rowid FROM chunk_vec WHERE embedding MATCH vec_quantize_binary(?) AND k = ?', (wanted, 4 * depth))]
    nearest = [row for row, distance in connection.execute(
        'SELECT id, vec_distance_cosine(vec_int8(embedding), vec_quantize_int8(?, \'unit\')) AS d FROM chunks WHERE id IN (%s) ORDER BY d LIMIT ?'
        % ','.join('?' * len(candidates)), (wanted, *candidates, depth))
        if distance < 0.9] if candidates else []  # cosine distance 0.9 ~ shares nothing but noise
    score = {}
    for ranking in (lexical, nearest):
        for rank, row in enumerate(ranking):
            score[row] = score.get(row, 0.0) + 1.0 / (_RRF + rank + 1)
    beliefs = {}
    for row, value in sorted(score.items(), key=lambda item: -item[1]):
        found = connection.execute('SELECT belief FROM chunks WHERE id=?', (row,)).fetchone()
        if found and found[0] not in beliefs:
            beliefs[found[0]] = value
    return list(beliefs)[:max(1, int(limit))]


def _as_of(connection, prompt, at, limit):
    """What the Brain believed at time ``at`` (history is not indexed; a plain word-overlap scan)."""
    wanted = set(_WORD.findall(_normal(prompt)))
    rows = connection.execute('SELECT id, text, valid_from FROM beliefs WHERE valid_from <= ? AND '
                              '(valid_to IS NULL OR valid_to > ?)', (at, at)).fetchall()
    scored = sorted(((-len(wanted & set(_WORD.findall(_normal(t)))), -vf, b) for b, t, vf in rows), key=lambda r: r[:2])
    return [b for overlap, _vf, b in scored if overlap < 0][:max(1, int(limit))]


def context(prompt, limit, as_of=None):
    with _LOCK:
        connection = _db()
        ids = _as_of(connection, prompt, float(as_of), limit) if as_of is not None else search(prompt, limit)
        facts = []
        for belief in ids:
            fact_id, kind, text, valid_from, valid_to = connection.execute(
                'SELECT fact_id, kind, text, valid_from, valid_to FROM beliefs WHERE id=?', (belief,)).fetchone()
            facts.append({'id': fact_id, 'text': text, 'kind': kind, 'valid_from': valid_from, 'valid_to': valid_to,
                          'evidence': _evidence(connection, belief), 'replaces': _replaced(connection, belief)})
        return {'facts': facts}


def history(fragment_id):
    """Every version of one fact, oldest first, each with its validity window and evidence."""
    with _LOCK:
        connection = _db()
        return {'ok': True, 'id': fragment_id, 'versions': [
            {'text': t, 'kind': k, 'valid_from': vf, 'valid_to': vt, 'forgotten': bool(fg),
             'evidence': _evidence(connection, b)}
            for b, k, t, vf, vt, fg in connection.execute(
                'SELECT id, kind, text, valid_from, valid_to, forgotten FROM beliefs WHERE fact_id=? '
                'ORDER BY valid_from, id', (str(fragment_id or ''),))]}


def write(ops):
    added = [op['fragment'] for op in (ops or []) if isinstance(op, dict) and str(op.get('op', '')).lower() == 'add'
             and isinstance(op.get('fragment'), dict) and str(op['fragment'].get('text', '')).strip()]
    with _LOCK:
        connection = _db()
        with _tx(connection):
            for fragment in added:
                text = str(fragment['text']).strip()
                replaces = fragment.get('supersedes') or ()
                replaces = (replaces,) if isinstance(replaces, str) else tuple(str(r) for r in replaces)
                _supersede(connection, str(fragment['id']), str(fragment.get('kind') or 'fact'), text,
                           str(fragment.get('source') or 'brain.write'), str(fragment.get('evidence') or text),
                           replaces=replaces)
    return {'ok': True, 'written': len(added)}


def _change(fragment_id, change):
    fragment_id = str(fragment_id or '').strip()
    if not fragment_id:
        return {'ok': False, 'error': 'missing fragment_id'}
    with _LOCK:
        connection = _db()
        current = _current(connection, fragment_id)
        if current is None:
            return {'ok': False, 'error': 'no such fact'}
        with _tx(connection):
            return change(connection, fragment_id, current)


def _edit(text):
    def run(connection, fact_id, current):
        _supersede(connection, fact_id, current[1], text, 'corrected by the owner', 'was: ' + current[2])
        return {'ok': True, 'id': fact_id, 'edited': True}
    return run


def _forget(connection, fact_id, current):
    _close_belief(connection, current[0], max(time.time(), current[3] + 1e-6), forgotten=True)
    return {'ok': True, 'id': fact_id}


def _publish(fact_id, text):
    if names_the_client_area(text, fact_id):
        return {'ok': False, 'error': 'this fact names the client area; it stays on this machine'}
    return {'ok': False, 'error': 'Sharing with the Community Brain needs the ArchHub cloud review; the fact stays on this machine.'}


# ------------------------------------------------------------------ account --
# Settings > Account > Brain follows your account: this file and the account's cloud Brain (the existing
# /v1/brain/sync replica that archhub.io reads) converge, last writer wins by time (D-055).
_SYNC = {'last': 0.0, 'running': False, 'again': False}
_PULL_EVERY = 60  # seconds between the pulls a read triggers


def _hlc(at):
    return '%016d.%s' % (int(at * 1000), hashlib.sha256(os.environ.get('COMPUTERNAME', 'pc').encode()).hexdigest()[:8])


def _iso(at):
    return time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(at)) + '.%03dZ' % int(at % 1 * 1000)


def _outgoing(connection, since):
    """Facts changed after ``since`` as cloud fragments; a fact naming the client area never leaves this PC."""
    out = []
    for (fact_id,) in connection.execute('SELECT DISTINCT fact_id FROM beliefs WHERE valid_from > ? OR valid_to > ?',
                                         (since, since)).fetchall():
        kind, text, at, ended = connection.execute(
            'SELECT kind, text, valid_from, valid_to FROM beliefs WHERE fact_id=? ORDER BY valid_from DESC, id DESC '
            'LIMIT 1', (fact_id,)).fetchone()
        if names_the_client_area(text, fact_id):
            continue
        fragment = {'id': fact_id, 'kind': 'fact', 'text': text, 'scope': 'user', 'extra': {'kind': kind},
                    'valid_from': _iso(at), 'hlc': _hlc(ended or at)}
        if ended is not None:
            fragment['valid_until'] = _iso(ended)
        out.append(fragment)
    return out


def _incoming(connection, fragment):
    """One account fragment onto this file when it is newer than what this PC holds; 1 if it changed anything."""
    if (fragment.get('scope') or 'user') not in ('user', 'project') or (fragment.get('kind') or 'fact') != 'fact':
        return 0  # office and community facts are read through their own scopes, not "what agents remember about you"
    fact_id, text = str(fragment.get('id') or ''), str(fragment.get('text') or '').strip()
    try:
        at = int(str(fragment.get('hlc') or '').split('.')[0]) / 1000
    except ValueError:
        return 0
    if not fact_id or not text:
        return 0
    latest = connection.execute('SELECT id, text, valid_from, valid_to FROM beliefs WHERE fact_id=? '
                                'ORDER BY valid_from DESC, id DESC LIMIT 1', (fact_id,)).fetchone()
    if latest and max(latest[2], latest[3] or 0) >= at:
        return 0  # this PC's version is as new or newer
    live = latest is not None and latest[3] is None
    if fragment.get('valid_until'):
        if live:
            _close_belief(connection, latest[0], at, forgotten=True)
        return int(live)
    if live and latest[1] == text:
        return 0
    kind = str((fragment.get('extra') or {}).get('kind') or 'fact')
    if live:
        _close_belief(connection, latest[0], at)
    belief = _open_belief(connection, fact_id, kind, text, at, 'your ArchHub account', text)
    if live:
        connection.execute('UPDATE beliefs SET superseded_by=? WHERE id=?', (belief, latest[0]))
    return 1


def sync_with_account():
    """Push this PC's changed facts, pull the account's: {'ok', 'pushed', 'pulled'} or why nothing moved."""
    from . import account_sync
    from .settings_owner import declared_setting
    if declared_setting('Account.Brain follows your account') is not True:
        return {'ok': False, 'skipped': 'Brain follows your account is off'}
    if not account_sync.signed_in():
        return {'ok': False, 'skipped': 'not signed in'}  # nothing is opened or read for an account that is not here
    started = time.time()
    since = float(account_sync.mark('brain.pushed') or 0)
    with _LOCK:
        fragments = _outgoing(_db(), since)
    # shortcut: every pull reads the whole account Brain (since_hlc ''), so a fact another PC wrote offline with an
    # older clock is never skipped; move to a server-side receive cursor when brains reach tens of thousands of facts.
    code, answer = account_sync.call('POST', '/v1/brain/sync', {'since_hlc': '', 'delta': {'fragments': fragments}})
    if code != 200:
        return {'ok': False, 'status': code}
    merged = (answer.get('merged') or {}).get('fragments') or []
    with _LOCK:
        connection = _db()
        with _tx(connection):
            pulled = sum(_incoming(connection, fragment) for fragment in merged if isinstance(fragment, dict))
    account_sync.mark('brain.pushed', started)
    return {'ok': True, 'pushed': int(answer.get('accepted') or 0), 'pulled': pulled,
            'refused': len(answer.get('rejected') or [])}


def sync_in_background(force=False):
    """A change follows at once (force); a read pulls at most once a minute. Never holds the caller."""
    with _LOCK:
        if _SYNC['running']:
            _SYNC['again'] = _SYNC['again'] or force
            return
        if not force and time.time() - _SYNC['last'] < _PULL_EVERY:
            return
        _SYNC.update(running=True, again=False, last=time.time())

    def work():
        try:
            while True:
                try:
                    sync_with_account()
                except Exception as missed:  # the next change or read retries
                    import logging
                    logging.getLogger(__name__).warning('Brain account sync did not finish (%s)', type(missed).__name__)
                with _LOCK:
                    if not _SYNC['again']:
                        return
                    _SYNC['again'] = False
        finally:
            with _LOCK:
                _SYNC['running'] = False
    threading.Thread(target=work, name='archhub-brain-account', daemon=True).start()


def call(tool, arguments):
    answer = _call(tool, arguments)
    if tool in ('brain.write', 'brain.edit_fact', 'brain.delete_fact') and answer.get('ok'):
        sync_in_background(force=True)
    elif tool in ('brain.list_facts', 'brain.context'):
        sync_in_background()
    return answer


def _call(tool, arguments):
    arguments = dict(arguments or {})
    params = BRAIN_NODE['params']
    if tool == 'brain.health':
        with _LOCK:
            return {'ok': True, 'facts': _db().execute('SELECT count(*) FROM beliefs WHERE valid_to IS NULL').fetchone()[0], 'skills': None, 'owner_user': 'local', 'store': 'sqlite'}
    if tool == 'brain.context':
        from .settings_owner import declared_setting  # Settings › Account › Memories in each request
        return context(arguments.get('prompt', ''), arguments.get('limit', declared_setting('Account.Memories in each request')), arguments.get('as_of'))
    if tool == 'brain.list_facts':
        return list_facts(arguments.get('limit', params['list_limit']), arguments.get('offset', 0))
    if tool == 'brain.history':
        return history(arguments.get('fragment_id'))
    if tool == 'brain.delete_fact':
        return _change(arguments.get('fragment_id'), _forget)
    if tool == 'brain.edit_fact':
        text = str(arguments.get('text') or '').strip()
        if not text:
            return {'ok': False, 'error': 'need a fact id and text', 'edited': False}
        return _change(arguments.get('fragment_id'), _edit(text))
    if tool == 'brain.write':
        return write(arguments.get('ops'))
    if tool == 'brain.publish':
        fact_id = str(arguments.get('fragment_id') or '')
        with _LOCK:
            found = _current(_db(), fact_id)
        return _publish(fact_id, found[2]) if found else {'ok': False, 'error': 'no such fact'}
    raise ValueError('the application Brain does not provide %s' % tool)


_AREAS = ("20.clients", "20clients", "60.personal", "60personal")

_PROJECT_CODE = re.compile(r"(?<![a-z0-9])p[-_]?\d{3,4}(?![a-z0-9])")

_CLIENTS_DIR = "20.CLIENTS"

def _decoded(text):
    text = str(text)
    for _ in range(8):  # %252E, %25252E ...: unquote until nothing changes
        once = urllib.parse.unquote(text)
        if once == text:
            break
        text = once
    return unicodedata.normalize("NFKC", text).casefold()

def _client_folder_forms():
    """The client folders of this workspace, by name only, in every spelling a fact
    might use: 22.BBC4 -> "22.bbc4", "22bbc4", "bbc4". None on a machine without
    the client area. Names shorter than three characters are not matched alone."""
    from .resource_probe import _workspace_root
    try:
        names = [p.name for p in (_workspace_root() / _CLIENTS_DIR).iterdir() if p.is_dir()]
    except OSError:
        return ()
    forms = set()
    for name in names:
        dotted = re.sub(r"[^a-z0-9]+", ".", _decoded(name)).strip(".")
        bare = re.sub(r"^\d+\.", "", dotted)
        for form in (dotted, dotted.replace(".", ""), bare, bare.replace(".", "")):
            if len(form.replace(".", "")) >= 3:
                forms.add(form)
    return tuple(sorted(forms))

def names_the_client_area(*texts):
    forms = _AREAS + _client_folder_forms()
    for text in texts:
        decoded = _decoded(text)
        dotted = "." + re.sub(r"[^a-z0-9]+", ".", decoded).strip(".") + "."
        if any("." + form + "." in dotted for form in forms) or _PROJECT_CODE.search(decoded):
            return True
    return False
