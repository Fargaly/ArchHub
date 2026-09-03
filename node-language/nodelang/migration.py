"""Versioned migrations between persistent node-native application graphs."""
from __future__ import annotations

import copy
import gzip
import json
import shutil
from pathlib import Path

from .application import APPLICATION_SCHEMA_VERSION, build_archhub_application
from .core import Store, validate_store
from .persistence import registry_from_store, save_snapshot


SUPPORTED_SOURCES = {'2026.07.13.30', '2026.07.13.31'}
STATE_TITLES = {
    'application mode', 'sidebar panel', 'focused node', 'open container',
    'open container title', 'container stack', 'canvas selection',
    'canvas pan x', 'canvas pan y', 'canvas zoom', 'search query',
    'draft node kind', 'draft node title', 'draft node value',
    'selected model id',
}


def _read_snapshot(path):
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        payload = json.load(stream)
    store = Store.load(payload['nodes'])
    validate_store(store)
    return payload, store


def _same_node(old_store, new_store, old_id):
    old = old_store.nodes.get(old_id)
    new = new_store.nodes.get(old_id)
    return bool(old and new and old['kind'] == new['kind']
                and old['title'] == new['title'])


def _owners(store, parameter_id):
    found = []
    for owner_id, owner in store.nodes.items():
        for name, candidate in owner['params'].items():
            if candidate == parameter_id:
                found.append((owner_id, name))
    return found


def _map_node_id(old_store, new_store, old_id):
    if _same_node(old_store, new_store, old_id):
        return old_id
    old = old_store.nodes.get(old_id)
    if old is None:
        raise ValueError('migration source node %r is missing' % old_id)
    owner_matches = _owners(old_store, old_id)
    if len(owner_matches) == 1:
        old_owner_id, name = owner_matches[0]
        new_owner_id = _map_node_id(old_store, new_store, old_owner_id)
        candidate = new_store.nodes[new_owner_id]['params'].get(name)
        if candidate in new_store.nodes:
            return candidate
    matches = [nid for nid, node in new_store.nodes.items()
               if node['kind'] == old['kind'] and node['title'] == old['title']]
    if len(matches) == 1:
        return matches[0]
    raise ValueError('cannot map %s %r (%s candidates)'
                     % (old['kind'], old['title'], len(matches)))


def _map_value(old_store, new_store, value):
    if isinstance(value, str) and value in old_store.nodes:
        return _map_node_id(old_store, new_store, value)
    if isinstance(value, list):
        return [_map_value(old_store, new_store, item) for item in value]
    if isinstance(value, dict):
        return {key: _map_value(old_store, new_store, item)
                for key, item in value.items()}
    return copy.deepcopy(value)


def _migration_targets(old_store):
    targets = {}
    unsupported = []
    for history_id, node in old_store.nodes.items():
        if node['kind'] != 'history':
            continue
        entry = node['body']['floor']['entry']
        actor = entry.get('actor')
        if actor == 'user' and entry.get('op') in {'add_node', 'add_wire',
                                                   'dissolve_group'}:
            unsupported.append((history_id, entry.get('op')))
        target_id = entry.get('id')
        target = old_store.nodes.get(target_id)
        if entry.get('op') not in {'set', 'unset'} or target is None:
            continue
        if actor in {'user', 'schema-migration'} or target['title'] in STATE_TITLES:
            targets[target_id] = entry
    if unsupported:
        raise ValueError('migration refuses unsupported user structural operations: %r'
                         % unsupported)
    return targets


def migrate_snapshot(source_path, target_path=None, backup=True):
    source_path = Path(source_path).expanduser().resolve()
    target_path = Path(target_path or source_path).expanduser().resolve()
    payload, old_store = _read_snapshot(source_path)
    source_schema = payload.get('schema_version')
    if source_schema == APPLICATION_SCHEMA_VERSION:
        return old_store, registry_from_store(old_store), {
            'source_schema': source_schema,
            'target_schema': APPLICATION_SCHEMA_VERSION,
            'migrated': False,
            'operations': [],
            'backup': None,
        }
    if source_schema not in SUPPORTED_SOURCES:
        raise ValueError('unsupported application snapshot schema %r' % source_schema)

    new_store, registry = build_archhub_application()
    transaction = 'migrate:%s->%s' % (source_schema, APPLICATION_SCHEMA_VERSION)
    operations = []
    for old_id, entry in _migration_targets(old_store).items():
        new_id = _map_node_id(old_store, new_store, old_id)
        old_node = old_store.nodes[old_id]
        path = list(entry['path'])
        if entry['op'] == 'unset':
            operation = {'op': 'unset', 'id': new_id, 'path': path}
        else:
            value = old_node
            for key in path:
                value = value[key]
            operation = {'op': 'set', 'id': new_id, 'path': path,
                         'value': _map_value(old_store, new_store, value)}
        operation.update({
            'actor': 'schema-migration',
            'transaction': transaction,
            'source_actor': entry.get('actor'),
            'source_node': old_id,
        })
        new_store.apply_op(operation)
        operations.append({
            'source_node': old_id,
            'target_node': new_id,
            'title': old_node['title'],
            'operation': entry['op'],
        })

    validate_store(new_store)
    backup_path = None
    if backup and target_path == source_path:
        backup_path = source_path.with_name(
            source_path.name + '.schema-' + str(source_schema) + '.bak')
        if not backup_path.exists():
            shutil.copy2(source_path, backup_path)
    save_snapshot(new_store, target_path)
    return new_store, registry, {
        'source_schema': source_schema,
        'target_schema': APPLICATION_SCHEMA_VERSION,
        'migrated': True,
        'operations': operations,
        'backup': str(backup_path) if backup_path else None,
    }
