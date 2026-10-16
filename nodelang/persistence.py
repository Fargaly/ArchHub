"""Atomic local CDE/WIP snapshots for the one-table application graph."""
from __future__ import annotations

import gzip
import json
import os
import copy
import time
import threading
import uuid
from contextlib import closing
from pathlib import Path

from .core import Store, validate_store
from .laws_surface import closure


# This reader exists only to recover snapshots from the retired typed runtime.
# Keeping its fixed schema here prevents a Universal Cell process importing that
# runtime merely to discover its old snapshot marker.
LEGACY_SNAPSHOT_SCHEMA_VERSION = '2026.07.13.32'


def default_state_path():
    root = Path(os.environ.get('LOCALAPPDATA') or (Path.home() / 'AppData' / 'Local'))
    return root / 'ArchHub' / 'node-native-wip.json.gz'



def application_database_path(state_directory=None):
    """Locate the one selected application journal; never select an old copy."""
    root = Path(state_directory) if state_directory is not None else Path(
        os.environ.get('ARCHHUB_TEST_STATE_DIR') or
        (Path(os.environ.get('LOCALAPPDATA') or Path.home() / 'AppData' / 'Local') / 'ArchHub'))
    runtime = root / 'unified-authority'
    current = runtime / 'CURRENT'
    if current.exists():
        from .unified_authority_runtime import _generation_id
        selected = _generation_id(current.read_text(encoding='ascii'))
        database = runtime / 'generations' / selected / 'authority.sqlite3'
        if not database.is_file():
            raise ValueError('selected authority is missing; no replacement will be created')
        return database.resolve()
    return (root / 'authority.sqlite3').resolve()


def application_content_path(database):
    """Read-only locator for update admission across the one-time cutover."""
    import sqlite3
    graph = Path(database).resolve()
    if graph.is_file():
        with closing(sqlite3.connect(graph.as_uri() + '?mode=ro', uri=True)) as connection:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name='history_identity'").fetchone():
                return graph
    legacy = Path(str(graph) + '.conversations.sqlite3')
    return legacy if legacy.is_file() else None


def application_state_directory(database):
    """Locate profile metadata beside its validated selected-generation layout."""
    path = Path(database).resolve()
    return path.parents[3] if selected_application_generation(path) else path.parent


def selected_application_generation(database):
    if database is None:
        return False
    path = Path(database).resolve()
    if path.name != 'authority.sqlite3' or path.parent.parent.name != 'generations':
        return False
    runtime = path.parent.parent.parent
    current = runtime / 'CURRENT'
    manifest = path.parent / 'bootstrap.json'
    if not current.is_file() or not manifest.is_file():
        return False
    held = json.loads(manifest.read_text(encoding='utf-8'))
    return (current.read_text(encoding='ascii').strip() == path.parent.name
            and held.get('graph_id') == path.parent.name)


def bind_selected_application_authority(store, key_provider):
    """Verify the selected generation once, before its first app migration."""
    if not selected_application_generation(store.database_path):
        return None
    held = getattr(store, '_signed_commit_authority', None)
    if held is not None:
        return held
    from .unified_authority import BootstrapManifest, open_unified_authority, bind_signed_commit_owner
    from .unified_authority_runtime import _AcceptedSnapshotProof
    generation = Path(store.database_path).parent
    manifest = BootstrapManifest.from_json((generation / 'bootstrap.json').read_text(encoding='utf-8'))
    authority = open_unified_authority(store, manifest, key_provider,
        accepted_proof=_AcceptedSnapshotProof(generation))
    bind_signed_commit_owner(authority)
    return authority


def legacy_application_sources(state_directory):
    """Known retired stores within the declared profile; never a fallback head."""
    root = Path(state_directory).resolve()
    paths = [root / 'archhub-test.universal.sqlite3',
        root / 'node-native-wip.json.gz.universal.sqlite3',
        root / 'agent-coordination-runtime' / 'universal-cells.sqlite3',
        root / 'BABOOM' / 'authority.sqlite3']
    local = os.environ.get('LOCALAPPDATA')
    if local and root == (Path(local) / 'ArchHub').resolve():
        paths.append(Path(local) / 'ArchHub-Test' / 'archhub-test.universal.sqlite3')
    return tuple(p for p in paths if p.is_file())


def migrate_graph_source(store, source_path):
    """Merge a retired Cell journal without overwriting any conflicting truth.

    Legacy data is read-only. Conflicts preserve both sources and refuse boot;
    a selected authority is never silently replaced by whichever copy opens.
    """
    import hashlib
    import sqlite3
    from . import commit_intent
    from .universal_cell import Cell, NULL_CELL_ID
    source = Path(source_path).resolve()
    if source == Path(store.database_path).resolve():
        return {'state': 'selected'}
    marker_id = 'app:retired-store:' + hashlib.sha256(str(source).encode()).hexdigest()
    snapshot = store.snapshot()
    if marker_id in snapshot.cells:
        marker = json.loads(snapshot.cells[marker_id].atom)
        if marker['sha256'] != _sqlite_source_digest(source):
            raise ValueError('retired graph changed; preserve and reconcile it explicitly')
        return {'state': 'already_migrated', 'backup_path': marker['backup_path']}
    source_digest = _sqlite_source_digest(source)
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, isolation_level=None)) as old:
        old.execute('BEGIN')
        if old.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            raise ValueError('retired graph integrity check failed')
        creates = []
        for ident, link0, link1, atom in old.execute('SELECT cell_id,link0,link1,atom FROM current_cells'):
            cell = Cell(str(ident), str(link0), str(link1), bytes(atom))
            held = snapshot.cells.get(cell.id)
            if held is not None and held != cell:
                raise ValueError('conflicting truth in retired graph at ' + cell.id)
            if held is None:
                creates.append(cell)
        backup = _migration_backup(store, {'source.sqlite3': (source, old)}, 'graph-migration')
        if _sqlite_source_digest(backup / 'source.sqlite3') != source_digest:
            raise ValueError('retired graph changed during backup')
    if _sqlite_source_digest(source) != source_digest:
        raise ValueError('retired graph changed during backup')
    stat = source.stat()
    marker = {'path': str(source), 'size': stat.st_size, 'mtime_ns': stat.st_mtime_ns,
              'sha256': source_digest, 'backup_path': str(backup)}
    creates.append(Cell(marker_id, NULL_CELL_ID, NULL_CELL_ID, json.dumps(marker, sort_keys=True).encode()))
    with commit_intent.declare(commit_intent.MIGRATION, actor='app:archhub', reason='merge retired graph without duplicate authority'):
        store.commit(snapshot.revision, create=creates)
    return {'state': 'migrated', 'backup_path': str(backup)}


def _find_one(store, kind, title):
    matches = [nid for nid, node in store.nodes.items()
               if node['kind'] == kind and node['title'] == title]
    if len(matches) != 1:
        raise ValueError('expected one %s titled %r, found %d' % (kind, title, len(matches)))
    return matches[0]


def _reference_target(store, owner_id, name):
    pid = store.nodes[owner_id]['params'][name]
    floor = store.nodes[pid]['body']['floor']
    if floor.get('op') != 'reference' or floor.get('target') not in store.nodes:
        raise ValueError('%s.%s is not a node reference parameter' % (owner_id, name))
    return floor['target']


def registry_from_store(store):
    app = _find_one(store, 'session', 'ArchHub Application')
    website = _find_one(store, 'session', 'ArchHub Website')
    schema_pid = store.nodes[app]['params']['schema_version']
    if store.pull(schema_pid) != LEGACY_SNAPSHOT_SCHEMA_VERSION:
        raise ValueError('snapshot schema does not match this application build')
    website_routes = {'/website': _reference_target(store, app, 'website_root')}
    for name in store.nodes[website]['params']:
        if name.startswith('route:/website/'):
            website_routes[name[len('route:'):]] = _reference_target(store, website, name)
    cockpit = _find_one(store, 'session', 'Founder Cockpit domain')
    cloud_runtime = _find_one(store, 'session', 'Cloud HTTP Runtime')
    cockpit_params = store.nodes[cockpit]['params']
    cockpit_domain = {
        'session': cockpit,
        'command': cockpit_params['command'],
        'submitted_by': cockpit_params['submitted_by'],
        'submitted_at': cockpit_params['submitted_at'],
        'redacted': cockpit_params['redacted'],
        'redaction_reason': cockpit_params['redaction_reason'],
        'redactor': _reference_target(store, cockpit, 'redactor'),
        'selected_route': _reference_target(store, cockpit, 'selected_route'),
        'audit_params': {
            'sequence': cockpit_params['audit_sequence'],
            'last_event': cockpit_params['audit_event'],
        },
    }
    return {
        'app': app,
        'ui_root': _reference_target(store, app, 'ui_root'),
        'focus': store.nodes[app]['params']['focus'],
        'container': store.nodes[app]['params']['container'],
        'container_title': store.nodes[app]['params']['container_title'],
        'container_stack': store.nodes[app]['params']['container_stack'],
        'mode': store.nodes[app]['params']['mode'],
        'website': {
            'session': website,
            'ui_root': _reference_target(store, website, 'ui_root'),
            'routes': website_routes,
        },
        'cockpit_domain': cockpit_domain,
        'cloud_runtime': {'session': cloud_runtime},
    }


def _replace_with_retry(temp, path, attempts=8):
    """Windows readers and security scanners can briefly deny replace access."""
    for attempt in range(attempts):
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if attempt + 1 == attempts:
                raise
            time.sleep(0.02 * (attempt + 1))


def _unique_temp(path, purpose):
    return path.with_name(
        '%s.%s.%s.%s.tmp' % (
            path.name, purpose, threading.get_ident(), uuid.uuid4().hex)
    )


def save_flat_snapshot(nodes, path):
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'schema_version': LEGACY_SNAPSHOT_SCHEMA_VERSION,
        'saved_at': time.time(),
        'nodes': nodes,
    }
    temp = _unique_temp(path, 'snapshot')
    try:
        with gzip.open(temp, 'wt', encoding='utf-8', compresslevel=1) as stream:
            json.dump(payload, stream, separators=(',', ':'))
        _replace_with_retry(temp, path)
    except Exception:
        temp.unlink(missing_ok=True)
        raise
    return path


def save_snapshot(store, path):
    return save_flat_snapshot(store.dump(), path)


def save_snapshot_cooperative(store, path, mutation_lock, expected_revision,
                              current_revision, chunk_size=64):
    """Write a revision-consistent snapshot without monopolising interaction."""
    path = Path(path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = _unique_temp(path, 'cooperative')
    stale = False
    with mutation_lock:
        node_ids = list(store.nodes)
    try:
        with gzip.open(temp, 'wt', encoding='utf-8', compresslevel=1) as stream:
            stream.write('{"schema_version":')
            json.dump(LEGACY_SNAPSHOT_SCHEMA_VERSION, stream, separators=(',', ':'))
            stream.write(',"saved_at":')
            json.dump(time.time(), stream, separators=(',', ':'))
            stream.write(',"nodes":[')
            first = True
            for offset in range(0, len(node_ids), chunk_size):
                with mutation_lock:
                    if current_revision() != expected_revision:
                        stale = True
                        break
                    chunk = [copy.deepcopy(store.nodes[nid])
                             for nid in node_ids[offset:offset + chunk_size]]
                for node in chunk:
                    if not first:
                        stream.write(',')
                    json.dump(node, stream, separators=(',', ':'))
                    first = False
                time.sleep(0.001)
            if not stale:
                stream.write(']}')
        with mutation_lock:
            if stale or current_revision() != expected_revision:
                stale = True
            else:
                _replace_with_retry(temp, path)
        if stale:
            temp.unlink(missing_ok=True)
            return False
        return True
    except Exception:
        temp.unlink(missing_ok=True)
        raise


def load_snapshot(path):
    path = Path(path).expanduser().resolve()
    if not path.exists():
        return None
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        payload = json.load(stream)
    if payload.get('schema_version') != LEGACY_SNAPSHOT_SCHEMA_VERSION:
        return None
    store = Store.load(payload['nodes'])
    validate_store(store)
    return store, registry_from_store(store)


def export_subgraph(store, root_id):
    if root_id not in store.nodes:
        raise KeyError('export root %r is not in the graph' % root_id)
    ids = closure(store, root_id)
    root = store.nodes[root_id]
    tier_param = root['params'].get('privacy_tier')
    classification = store.pull(tier_param) if tier_param in store.nodes else 'T1 INTERNAL'
    return {
        'format': 'archhub-node-graph-v1',
        'root_id': root_id,
        'classification': classification,
        'nodes': [store.nodes[nid] for nid in ids],
    }


LOCAL_TRUTH_MIGRATION_ROOT = "app:local-truth-migration"
IMPORTED_SETTINGS_ROOT = "app:imported-settings"


def _file_digest(path):
    import hashlib
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()



def _sqlite_source_digest(path):
    """Hash committed SQLite content, including WAL, independent of checkpointing."""
    import hashlib
    import sqlite3
    result = hashlib.sha256()
    with closing(sqlite3.connect(Path(path).as_uri() + '?mode=ro', uri=True, isolation_level=None)) as database:
        database.execute('BEGIN')
        for kind, name, sql in database.execute(
                "SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"):
            result.update(repr((kind, name, sql)).encode('utf-8'))
            if kind != 'table' or sql.upper().startswith('CREATE VIRTUAL TABLE'):
                continue
            quoted = '"' + name.replace('"','""') + '"'
            rowid = 'WITHOUT ROWID' not in sql.upper()
            query = 'SELECT ' + ('rowid,*' if rowid else '*') + ' FROM ' + quoted
            rows = database.execute(query + (' ORDER BY rowid' if rowid else ' ORDER BY ' + ','.join(
                str(index + 1) for index in range(len(database.execute(query + ' LIMIT 0').description)))))
            for row in rows:
                encoded = repr(tuple(row)).encode('utf-8')
                result.update(len(encoded).to_bytes(8, 'big'))
                result.update(encoded)
        result.update(repr((database.execute('PRAGMA application_id').fetchone()[0],
                            database.execute('PRAGMA user_version').fetchone()[0])).encode())
    return result.hexdigest()


def _truth_source_digests(sources):
    return {key: _sqlite_source_digest(path) if key == 'history' else _file_digest(path)
            for key, path in sources.items()}


def _safe_settings(value):
    if not isinstance(value, dict):
        raise ValueError("legacy settings must be an object")
    forbidden = {"token", "api_key", "password", "secret", "private_key", "access_token", "refresh_token"}
    def inspect(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if key.casefold() in forbidden:
                    raise ValueError("secret-bearing settings cannot enter the graph")
                inspect(child)
        elif isinstance(item, list):
            for child in item:
                inspect(child)
    inspect(value)
    return value


def _copy_history_tables(source, target):
    """Copy the validated complete schema and rows inside the graph's commit."""
    rows = source.execute("SELECT type,name,sql FROM sqlite_master "
        "WHERE name NOT LIKE 'sqlite_%' AND sql IS NOT NULL ORDER BY rowid").fetchall()
    virtual = {r[1] for r in rows if r[2].upper().startswith("CREATE VIRTUAL TABLE")}
    shadows = {r[1] for r in rows if any(r[1].startswith(v + '_') for v in virtual)}
    tables = [r for r in rows if r[0] == 'table']
    for _, name, sql in tables:
        if name not in shadows:
            target.execute(sql)
    for _, name, _ in tables:
        if name in virtual:
            continue  # External-content FTS reads messages; its full shadows are copied below.
        quoted = '"' + name.replace('"', '""') + '"'
        if name in shadows:
            target.execute("DELETE FROM " + quoted)
        declaration = next(sql for _, table, sql in tables if table == name)
        has_rowid = 'WITHOUT ROWID' not in declaration.upper()
        selected = 'rowid,*' if has_rowid else '*'
        cursor = source.execute("SELECT " + selected + " FROM " + quoted)
        fields = ('rowid,' if has_rowid else '') + ','.join('"' + col[0].replace('"','""') + '"' for col in cursor.description[1 if has_rowid else 0:])
        placeholders = ','.join('?' for _ in cursor.description)
        while batch := cursor.fetchmany(256):
            target.executemany("INSERT INTO " + quoted + '(' + fields + ') VALUES(' + placeholders + ")", batch)
    for kind, _, sql in rows:
        if kind == 'index':
            target.execute(sql)
        elif kind not in ('table', 'index'):
            raise ValueError("unsupported history schema object")
    target.execute("PRAGMA application_id=%d" % source.execute("PRAGMA application_id").fetchone()[0])
    target.execute("PRAGMA user_version=%d" % source.execute("PRAGMA user_version").fetchone()[0])
    if target.execute("PRAGMA foreign_key_check").fetchone() is not None:
        raise ValueError("migrated history has broken references")


def _migration_backup(store, sources, prefix):
    """Reuse an exact failed-attempt snapshot and refuse writes over budget."""
    import hashlib
    import sqlite3
    from .backup_retention import backup_policy, _backup_bytes, prune_backups, protected_update_backups
    graph = Path(store.database_path).resolve()
    descriptors = {'graph.sqlite3': (graph, store.sqlite_storage()[0]), **sources}
    fingerprints = {name: _sqlite_source_digest(path) if connection is not None else _file_digest(path)
                    for name, (path, connection) in descriptors.items()}
    identity = hashlib.sha256(json.dumps(fingerprints, sort_keys=True).encode()).hexdigest()
    directory = graph.parent / 'backups'
    directory.mkdir(parents=True, exist_ok=True)
    backup = directory / (prefix + '-' + identity)
    if backup.is_symlink() or backup.is_junction():
        raise ValueError('migration backup must not be a link')
    policy = backup_policy(store.snapshot())
    required = 0
    for name, (path, connection) in descriptors.items():
        target = backup / name
        if target.exists():
            if target.is_symlink() or target.is_junction():
                raise ValueError('migration backup file must not be a link')
            digest = _sqlite_source_digest(target) if connection is not None else _file_digest(target)
            if digest != fingerprints[name]:
                raise ValueError('previous migration backup differs; preserve it for reconciliation')
        else:
            required += (connection.execute('PRAGMA page_count').fetchone()[0] *
                         connection.execute('PRAGMA page_size').fetchone()[0]) if connection is not None else path.stat().st_size
    if _backup_bytes(directory) + required > policy['max_bytes']:
        raise ValueError('migration backup disk budget exceeded; no migration applied')
    backup.mkdir(exist_ok=True)
    for name, (path, connection) in descriptors.items():
        target = backup / name
        if target.exists():
            continue
        if name == 'graph.sqlite3':
            store.backup_to(target)
        elif connection is not None:
            with closing(sqlite3.connect(target)) as destination:
                connection.backup(destination)
        else:
            target.write_bytes(path.read_bytes())
        try:
            digest = _sqlite_source_digest(target) if connection is not None else _file_digest(target)
        except sqlite3.DatabaseError as error:
            raise ValueError('migration backup verification failed; prior backups preserved') from error
        if digest != fingerprints[name]:
            raise ValueError('migration backup differs; prior backups preserved')
    # The completed snapshot protects every original. Only old recovery copies
    # are eligible for deletion; source data is never a retention candidate.
    state = application_state_directory(graph)
    prune_backups(directory, keep=backup, **policy,
                  protected_names=protected_update_backups(state, directory))
    return backup


def migrate_local_truths(store, *, history_path=None, settings_path=None):
    """Back up then atomically import retired local truths into the graph journal.

    Only the owning boot calls this. Sources stay byte-identical and become
    read-only migration evidence; no runtime writer falls back to either one.
    The marker, settings Cells, and complete indexed history publish together.
    """
    import sqlite3
    from . import commit_intent
    from .conversation_history import ConversationHistoryStore, _APP_ID, _VERSION, _RETENTION_VERSION
    from .conversation_pages import PAGE_PROTECTION_VERSION
    from .universal_cell import Cell, NULL_CELL_ID
    database = store.database_path
    if database is None:
        raise ValueError("local truth migration requires a persistent graph owner")
    graph = Path(database).resolve()
    sources = {key: Path(path).resolve() for key, path in
               (("history", history_path), ("settings", settings_path)) if path is not None}
    if any(path == graph for path in sources.values()):
        raise ValueError("migration source and target must differ")
    if 'settings' in sources and sources['settings'].name in {'graph.sqlite3', 'history.sqlite3'}:
        raise ValueError('settings migration backup name conflicts with a database role')
    if not sources:
        return {"state": "not_required", "backup_path": None}
    digests = _truth_source_digests(sources)
    snapshot = store.snapshot()
    held = snapshot.cells.get(LOCAL_TRUTH_MIGRATION_ROOT)
    if held is not None:
        marker = json.loads(held.atom)
        if marker["digests"] != digests:
            raise ValueError("retired migration source changed; preserve and reconcile it explicitly")
        return {"state": "already_migrated", "backup_path": marker["backup_path"]}
    settings = _safe_settings(json.loads(sources["settings"].read_text(encoding="utf-8-sig"))) if "settings" in sources else None
    source = None
    try:
        if "history" in sources:
            source = sqlite3.connect(sources["history"].as_uri() + "?mode=ro", uri=True, isolation_level=None)
            source.row_factory = sqlite3.Row
            source.execute("BEGIN")
            if source.execute("PRAGMA quick_check").fetchone()[0] != 'ok':
                raise ValueError("legacy history integrity check failed")
            app_id = source.execute("PRAGMA application_id").fetchone()[0]
            version = source.execute("PRAGMA user_version").fetchone()[0]
            if app_id != _APP_ID or version not in (_VERSION, _RETENTION_VERSION, PAGE_PROTECTION_VERSION):
                raise ValueError("unsupported legacy conversation history")
            identity = source.execute("SELECT instance_id FROM history_identity WHERE singleton=1").fetchone()
            if identity is None:
                raise ValueError("legacy history identity is missing")
            validator = object.__new__(ConversationHistoryStore)
            validator._db = source
            validator._embedded = False
            validator.instance_id = identity[0]
            validator._validate_retention_source_schema(version)
        copies = {}
        if source is not None:
            copies['history.sqlite3'] = (sources['history'], source)
        if settings is not None:
            copies[sources['settings'].name] = (sources['settings'], None)
        backup = _migration_backup(store, copies, 'truth-migration')
        if digests != _truth_source_digests(sources):
            raise ValueError("migration source changed during backup")
        marker = {"version": 1, "digests": digests, "backup_path": str(backup),
                  "sources": {k: str(p) for k,p in sources.items()}}
        creates = [Cell(LOCAL_TRUTH_MIGRATION_ROOT, NULL_CELL_ID, NULL_CELL_ID,
                        json.dumps(marker, sort_keys=True).encode('utf-8'))]
        if settings is not None:
            creates.append(Cell(IMPORTED_SETTINGS_ROOT, NULL_CELL_ID, NULL_CELL_ID,
                                json.dumps(settings, sort_keys=True).encode('utf-8')))
        with commit_intent.declare(commit_intent.MIGRATION, actor='app:archhub', reason='retire local settings and conversation stores'):
            store.commit(snapshot.revision, create=creates,
                         physical_write=(lambda connection: _copy_history_tables(source, connection)) if source is not None else None)
        return {"state": "migrated", "backup_path": str(backup)}
    finally:
        if source is not None:
            source.close()
