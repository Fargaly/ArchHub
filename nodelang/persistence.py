"""Atomic local CDE/WIP snapshots for the one-table application graph."""
from __future__ import annotations

import gzip
import json
import os
import copy
import time
import threading
import uuid
from contextlib import closing, contextmanager, ExitStack
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
        if any(path.is_symlink() or path.is_junction() for path in
               (database, database.parent, database.parent.parent, runtime)):
            raise ValueError('selected authority must not be a link; source preserved')
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


def _legacy_desktop_journal(root):
    local = os.environ.get('LOCALAPPDATA')
    declared = os.environ.get('ARCHHUB_TEST_STATE_DIR')
    if local and (root == (Path(local) / 'ArchHub').resolve()
            or (declared and root == Path(declared).resolve())):
        return Path(local) / 'ArchHub-Test' / 'archhub-test.universal.sqlite3'
    return None


@contextmanager
def _application_journal_reader(path, *, check_budget=lambda: None, timeout_seconds=30.0):
    """Observe a fenced journal without creating or changing its WAL read marks.

    A committed WAL needs a private physical read view: SQLite mode=ro still
    writes shared-memory read marks. This temporary view is never selected or
    opened as a CellStore; the existing recovery publisher remains the copier.
    """
    import sqlite3
    import tempfile
    from .application_recovery_files import _require_disk_reserve
    path = Path(path).resolve()
    wal = Path(str(path) + '-wal')
    view, journal = None, None
    try:
        if wal.is_file() and wal.stat().st_size:
            view = Path(tempfile.mkdtemp(prefix='archhub-journal-read-')).resolve()
            _require_disk_reserve(view, path.stat().st_size + wal.stat().st_size)
            for source, destination in ((path, view / 'graph.sqlite3'),
                                        (wal, view / 'graph.sqlite3-wal')):
                with source.open('rb') as reader, destination.open('xb') as writer:
                    while True:
                        check_budget()
                        block = reader.read(1024 * 1024)
                        if not block:
                            break
                        writer.write(block)
            journal = sqlite3.connect((view / 'graph.sqlite3').as_uri() + '?mode=ro',
                uri=True, isolation_level=None, timeout=timeout_seconds)
        else:
            journal = sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1',
                uri=True, isolation_level=None, timeout=timeout_seconds)
        yield journal
    finally:
        if journal is not None:
            journal.close()
        if view is not None:
            # Exact owned filenames only, never recursive cleanup of a profile.
            for name in ('graph.sqlite3-shm', 'graph.sqlite3-wal', 'graph.sqlite3'):
                (view / name).unlink(missing_ok=True)
            view.rmdir()


def _application_journal_candidates(root):
    """Explicit released locations, ordered only for a committed-time/revision tie."""
    paths = [application_database_path(root), root / 'authority.sqlite3',
             root / 'archhub-test.universal.sqlite3',
             root / 'node-native-wip.json.gz.universal.sqlite3']
    legacy = _legacy_desktop_journal(root)
    if legacy is not None:
        paths.append(legacy)
    found = []
    for path in paths:
        if path.is_symlink() or path.is_junction():
            raise ValueError('retired application journal must not be a link')
        if path.is_file():
            found.append(path.resolve())
    return tuple(dict.fromkeys(found))


def _journal_head(path, *, check_budget=lambda: None, timeout_seconds=30.0):
    import math
    check_budget()
    with _application_journal_reader(path, check_budget=check_budget,
                                      timeout_seconds=timeout_seconds) as journal:
        revision, committed = journal.execute(
            'SELECT revision,committed_at FROM revisions ORDER BY revision DESC LIMIT 1').fetchone()
    check_budget()
    if type(revision) is not int or revision < 0 or not math.isfinite(committed):
        raise ValueError('application journal committed head is invalid; source preserved')
    return committed, revision


def _verify_migrated_application(database, key_provider):
    """Read the original receipt revisions with their original signing custody."""
    from types import SimpleNamespace
    from .universal_cell import CellStore
    from . import universal_application as application
    from .cell_secret_keys import WindowsDpapiSigningKeyProvider
    with CellStore(database) as store:
        snapshot = store.snapshot()
        if 'app:authorization-protocol:root' not in snapshot.cells:
            return
        keys = key_provider if key_provider is not None else WindowsDpapiSigningKeyProvider(
            WindowsDpapiSigningKeyProvider.default_path())
        authorization = application._restore_application_authorization(store, keys)
        protocol = application.open_agent_body_protocol(snapshot,
            prefix=application._AGENT_BODY_PROTOCOL_PREFIX)
        body = application.read_agent_body(snapshot, protocol, authorization.protocol,
            application._AGENT_BODY_ROOT)
        session = application.read_agent_session(snapshot, protocol, authorization.protocol,
            application._AGENT_SESSION_ROOT)
        application._verify_application_agent_receipts(store, authorization,
            SimpleNamespace(protocol=protocol, body=body, session=session))


def prepare_application_database(state_directory, database, *, timeout_seconds=30.0,
                                 key_provider=None):
    """Preserve the newest committed application's entire journal on upgrade.

    A head-only merge into revision one invalidates historical authorization
    receipts. The existing physical recovery/restore owners retain every
    revision, publish verified copies, and leave the retired source untouched.
    Existing files stay untouched. A stale selected authority is superseded only
    by a read-back-verified new physical generation, never a head-only merge.
    """
    from .universal_cell import InterprocessOwnerFence
    root, target = Path(state_directory).resolve(), Path(database).resolve()
    # Preserve the existing invalid-target refusal path; never replace corruption.
    if target.is_file():
        with target.open('rb') as stream:
            if stream.read(16) != b'SQLite format 3\0':
                return {'state': 'existing', 'backup_path': None, 'database_path': str(target)}
    runtime = root / 'unified-authority'
    runtime.mkdir(exist_ok=True)
    deadline = time.monotonic() + timeout_seconds
    def check_budget():
        if time.monotonic() >= deadline:
            raise TimeoutError('application journal migration time budget exceeded')
    with ExitStack() as owners:
        owners.callback(InterprocessOwnerFence(str(runtime / '.provision')).close)
        if application_database_path(root) != target:
            raise ValueError('application recovery required; selected migration target changed')
        paths = _application_journal_candidates(root)
        if not paths:
            return {'state': 'not_required', 'backup_path': None, 'database_path': str(target)}
        for path in paths:
            if path.is_symlink() or path.is_junction():
                raise ValueError('retired application journal must not be a link')
            owners.callback(InterprocessOwnerFence(str(path)).close)
        heads = {path: _journal_head(path, check_budget=check_budget,
                    timeout_seconds=max(0, deadline - time.monotonic())) for path in paths}
        chosen = max(paths, key=heads.__getitem__)
        print('  migration  : candidates ' + '; '.join('%s rev=%d time=%.6f' %
            (path, heads[path][1], heads[path][0]) for path in paths) +
            '; chosen %s (newest committed time, then revision)' % chosen, flush=True)
        if chosen == target:
            return {'state': 'existing', 'backup_path': None, 'database_path': str(target)}
        return _prepare_application_journal(root, target, chosen, heads, deadline, key_provider)


def _prepare_application_journal(root, target, source, heads, deadline, key_provider):
    """The existing recovery/restore cutover, under all candidate owner fences."""
    from types import SimpleNamespace
    from .application_recovery_files import publish_application_recovery
    from .application_recovery_restore_files import prepare_application_restore
    from .backup_retention import backup_policy, _backup_bytes
    from .conversation_content import FRESH_CONTENT_BOOTSTRAP_ROOT, read_fresh_content_bootstrap
    from .universal_cell import Cell, Snapshot, _LazyRevisionCellMap
    from .unified_authority_runtime import _atomic_text

    runtime = root / 'unified-authority'
    current = runtime / 'CURRENT'
    pointer = current.read_bytes() if current.exists() else None
    promote = target.exists() or pointer is not None
    generation_id = str(uuid.uuid4())
    if promote:
        generations = runtime / 'generations'
        generations.mkdir(exist_ok=True)
        destination = generations / generation_id
    else:
        destination = root / ('.application-upgrade-' + uuid.uuid4().hex)

    def check_budget():
        if time.monotonic() >= deadline:
            raise TimeoutError('application journal migration time budget exceeded')

    def check_target():
        check_budget()
        if ((current.read_bytes() if current.exists() else None) != pointer
                or any(_journal_head(path, check_budget=check_budget,
                    timeout_seconds=max(0, deadline - time.monotonic())) != head
                    for path, head in heads.items())
                or (not promote and (target.parent != root or any(
                    os.path.lexists(Path(str(target) + suffix))
                    for suffix in ('', '-wal', '-shm', '-journal'))))):
            raise ValueError('application recovery required; migration target changed or has recovery files')

    check_target()
    with _application_journal_reader(source, check_budget=check_budget) as old:
        old.execute('BEGIN')
        if old.execute("SELECT 1 FROM current_cells WHERE cell_id='app:archhub'").fetchone() is None:
            raise ValueError('retired application root is missing; source preserved')
        bootstrap = old.execute('SELECT cell_id,link0,link1,atom FROM current_cells WHERE cell_id=?',
                                (FRESH_CONTENT_BOOTSTRAP_ROOT,)).fetchone()
        if bootstrap is not None:
            value = read_fresh_content_bootstrap(SimpleNamespace(cells={
                FRESH_CONTENT_BOOTSTRAP_ROOT: Cell(*bootstrap)}))
            if value['state'] == 'pending':
                raise ValueError('fresh conversation recovery required; pending bootstrap custody cannot move')
        revision = old.execute('SELECT MAX(revision) FROM revisions').fetchone()[0]
        digest = _sqlite_source_digest(source, check_budget=check_budget)

        def verify(copies, check_budget):
            check_budget()
            if _sqlite_source_digest(copies['graph'], check_budget=check_budget) != digest:
                raise ValueError('application journal recovery differs; source preserved')
            return {'source_sha256': digest, 'head_revision': revision}

        def admitted():
            check_target()
            if _sqlite_source_digest(source, check_budget=check_budget) != digest:
                raise ValueError('retired application changed during migration; source preserved')

        backups = root / 'backups'
        backups.mkdir(exist_ok=True)
        # Read the retired graph's actual Settings, without opening a
        # second writable store or materialising its whole head.
        policy = backup_policy(Snapshot(revision,
            _LazyRevisionCellMap(old, threading.RLock(), revision)))
        remaining = policy['max_bytes'] - _backup_bytes(backups)
        backup = publish_application_recovery({'graph': old},
            backups / ('journal-migration-' + uuid.uuid4().hex), verify_copies=verify,
            before_publish=admitted, deadline=deadline, max_bytes=remaining)
        prepared = prepare_application_restore(backup,
            destination,
            output_names={'graph': 'authority.sqlite3' if promote else target.name},
            verify_copies=lambda copies, manifest, budget: verify(copies, budget),
            before_publish=admitted, deadline=deadline)
        admitted()
        copied = prepared / ('authority.sqlite3' if promote else target.name)
        _verify_migrated_application(copied, key_provider)
        if _sqlite_source_digest(copied, check_budget=check_budget) != digest:
            raise ValueError('application journal readback changed; source preserved')
        if promote:
            # Anchor this application's own receipts/history. Never borrow
            # the discarded generation's signed manifest or key identity.
            from .authority_adoption import adopt_application_authority
            from .cell_secret_keys import WindowsDpapiSigningKeyProvider
            from .universal_cell import CellStore
            with CellStore(copied) as migrated:
                if 'app:authorization-protocol:root' in migrated.snapshot().cells:
                    keys = key_provider if key_provider is not None else WindowsDpapiSigningKeyProvider(
                        WindowsDpapiSigningKeyProvider.default_path())
                    authority = adopt_application_authority(migrated, keys,
                        source_history_digest=migrated.snapshot_transition().chain_digest)
                    _atomic_text(prepared / 'adoption.json', authority.manifest.to_json())
            # Re-open from disk before publishing CURRENT, using the same
            # verifier and signed commit binding as every subsequent boot.
            if (prepared / 'adoption.json').is_file():
                from .unified_authority import BootstrapManifest, open_unified_authority, bind_signed_commit_owner
                with CellStore(copied) as readback:
                    manifest = BootstrapManifest.from_json((prepared / 'adoption.json').read_text(encoding='utf-8'))
                    bind_signed_commit_owner(open_unified_authority(readback, manifest, keys))
                _verify_migrated_application(copied, keys)
            _atomic_text(prepared / 'migration.json', json.dumps({
                'format': 'archhub-application-journal-migration/v1',
                'generation_id': generation_id, 'source_path': str(source),
                'source_revision': revision, 'source_committed_at': heads[source][0],
                'source_sha256': digest, 'backup_path': str(backup)}, sort_keys=True))
            admitted()
            _atomic_text(current, generation_id)
            target = copied
        else:
            admitted()
            # Windows rename refuses an existing destination; never replace.
            os.rename(copied, target)
        try:
            (prepared / 'restoration.json').unlink()
            if not promote:
                prepared.rmdir()
        except OSError as cleanup:
            print('  migration  : verified preparation metadata retained (%s)' %
                  type(cleanup).__name__, flush=True)
        return {'state': 'migrated', 'backup_path': str(backup), 'database_path': str(target)}


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
    if not current.is_file():
        return False
    if not manifest.is_file():
        migration = path.parent / 'migration.json'
        if not migration.is_file():
            return False
        held = json.loads(migration.read_text(encoding='utf-8'))
        return (current.read_text(encoding='ascii').strip() == path.parent.name
                and held.get('format') == 'archhub-application-journal-migration/v1'
                and held.get('generation_id') == path.parent.name)
    held = json.loads(manifest.read_text(encoding='utf-8'))
    return (current.read_text(encoding='ascii').strip() == path.parent.name
            and held.get('graph_id') == path.parent.name)


def bind_selected_application_authority(store, key_provider):
    """Verify the selected generation once, before its first app migration."""
    if not selected_application_generation(store.database_path):
        return None
    generation = Path(store.database_path).parent
    manifest_path = generation / 'bootstrap.json'
    if not manifest_path.is_file():
        manifest_path = generation / 'adoption.json'
    if not manifest_path.is_file():
        return None
    held = getattr(store, '_signed_commit_authority', None)
    if held is not None:
        return held
    from .unified_authority import BootstrapManifest, open_unified_authority, bind_signed_commit_owner
    from .unified_authority_runtime import _AcceptedSnapshotProof
    manifest = BootstrapManifest.from_json(manifest_path.read_text(encoding='utf-8'))
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
    legacy = _legacy_desktop_journal(root)
    if legacy is not None:
        paths.append(legacy)
    return tuple(dict.fromkeys(p.resolve() for p in paths if p.is_file()))


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
    selected = Path(store.database_path).resolve()
    root = application_state_directory(selected)
    if source in _application_journal_candidates(root):
        source_head, selected_head = _journal_head(source), _journal_head(selected)
        if source_head <= selected_head and (selected_application_generation(selected)
                or source_head < selected_head):
            # The explicit newest-history selection already resolved these
            # released application locations. Never head-merge their conflicts.
            return {'state': 'older_application_journal', 'backup_path': None}
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



def _sqlite_source_digest(path, *, check_budget=lambda: None):
    """Hash committed SQLite content, including WAL, independent of checkpointing."""
    import hashlib
    result = hashlib.sha256()
    with _application_journal_reader(path, check_budget=check_budget) as database:
        database.execute('BEGIN')
        database.set_progress_handler(lambda: (check_budget(), 0)[1], 1000)
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
                check_budget()
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
        # Only verified files take a final name. A deadline/process stop may
        # leave a unique staging file, never a poisoned final recovery copy.
        staged = backup / ('.' + name + '-' + uuid.uuid4().hex + '.staging')
        try:
            if name == 'graph.sqlite3':
                store.backup_to(staged)
            elif connection is not None:
                from .application_recovery_files import _backup_sqlite
                deadline = time.monotonic() + 30.0
                def check_budget():
                    if time.monotonic() >= deadline:
                        raise TimeoutError('migration backup time budget exceeded')
                staged.touch(exist_ok=False)
                _backup_sqlite(connection, staged, check_budget)
            else:
                with staged.open('xb') as destination:
                    destination.write(path.read_bytes())
                    destination.flush()
                    os.fsync(destination.fileno())
            try:
                digest = _sqlite_source_digest(staged) if connection is not None else _file_digest(staged)
            except sqlite3.DatabaseError as error:
                raise ValueError('migration backup verification failed; prior backups preserved') from error
            if digest != fingerprints[name]:
                raise ValueError('migration backup differs; prior backups preserved')
            os.rename(staged, target)
        finally:
            staged.unlink(missing_ok=True)
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
    readers = ExitStack()
    try:
        if "history" in sources:
            source = readers.enter_context(_application_journal_reader(sources["history"]))
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
        readers.close()
