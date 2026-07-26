"""Atomic local CDE/WIP snapshots for the one-table application graph."""
from __future__ import annotations

import gzip
import json
import os
import copy
import time
import threading
import uuid
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
