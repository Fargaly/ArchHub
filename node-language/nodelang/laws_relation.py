"""Universal relation laws over the one node table.

Endpoints, payload descriptors, stage assignments, and exposed properties are
ordinary nodes. The visible cable is only a projection produced by graph_api.
"""
from __future__ import annotations

from .core import (
    Store,
    relation_endpoints,
    relation_sources,
    relation_targets,
    validate_node,
)


def _relation(store, relation_id):
    relation = store.nodes[relation_id]
    if relation['kind'] != 'wire':
        raise ValueError('%s is not a relation-role node' % relation_id)
    return relation


def append_endpoint(store, relation_id, endpoint, actor=None):
    """Append one ordered endpoint parameter to an existing relation."""
    relation = _relation(store, relation_id)
    endpoint = dict(endpoint)
    if endpoint.get('node_id') not in store.nodes:
        raise KeyError('endpoint participant %r is not in the one table'
                       % endpoint.get('node_id'))
    if not endpoint.get('port_id'):
        raise ValueError('endpoint requires a port_id')
    indexes = [int(name.split(':', 1)[1]) for name in relation['params']
               if name.startswith('endpoint:') and name.split(':', 1)[1].isdigit()]
    name = 'endpoint:%03d' % ((max(indexes) + 1) if indexes else 0)
    pid = store.add('param', name, floor={'op': 'value', 'value': endpoint}, actor=actor)
    params = dict(relation['params'])
    params[name] = pid
    store.edit(relation_id, ['params'], params, actor=actor)
    store.edit(relation_id, ['body', 'inner'], relation['body']['inner'] + [pid], actor=actor)
    participant = store.nodes[endpoint['node_id']]
    if relation_id not in participant['relations']:
        participant['relations'].append(relation_id)
    validate_node(store.nodes, relation)
    return pid


def remove_endpoint(store, relation_id, endpoint_param, actor=None):
    """Detach an endpoint parameter while preserving a valid source/target relation."""
    relation = _relation(store, relation_id)
    endpoint = next((item for item in relation_endpoints(store.nodes, relation)
                     if item['endpoint_param'] == endpoint_param
                     or item['endpoint_name'] == endpoint_param), None)
    if endpoint is None:
        raise KeyError('endpoint %r is not owned by relation %s'
                       % (endpoint_param, relation_id))
    remaining = [item for item in relation_endpoints(store.nodes, relation)
                 if item['endpoint_param'] != endpoint['endpoint_param']]
    if len(remaining) < 2:
        raise ValueError('a relation must retain at least two endpoints')
    has_source = any(item.get('role') == 'source'
                     or item.get('direction') in ('out', 'read', 'source')
                     for item in remaining)
    has_target = any(item.get('role') == 'target'
                     or item.get('direction') in ('in', 'write', 'target')
                     for item in remaining)
    if not has_source or not has_target:
        raise ValueError('a relation must retain a source and a target')
    params = {name: pid for name, pid in relation['params'].items()
              if pid != endpoint['endpoint_param']}
    store.edit(relation_id, ['params'], params, actor=actor)
    store.edit(relation_id, ['body', 'inner'],
               [nid for nid in relation['body']['inner']
                if nid != endpoint['endpoint_param']], actor=actor)
    participant = store.nodes.get(endpoint.get('node_id'))
    if participant and not any(item.get('node_id') == endpoint.get('node_id')
                               for item in relation_endpoints(store.nodes, relation)):
        participant['relations'] = [rid for rid in participant['relations']
                                    if rid != relation_id]
    validate_node(store.nodes, relation)
    return endpoint['endpoint_param']


def rewire_endpoint(store, relation_id, endpoint_param, *, node_id=None,
                    port_id=None, actor=None):
    """Edit the authoritative endpoint parameter; derived incidence follows."""
    relation = _relation(store, relation_id)
    endpoint = next((item for item in relation_endpoints(store.nodes, relation)
                     if item['endpoint_param'] == endpoint_param
                     or item['endpoint_name'] == endpoint_param), None)
    if endpoint is None:
        raise KeyError('endpoint %r is not owned by relation %s'
                       % (endpoint_param, relation_id))
    spec = {key: value for key, value in endpoint.items()
            if key not in ('endpoint_param', 'endpoint_name')}
    if node_id is not None:
        if node_id not in store.nodes:
            raise KeyError('participant %r is not in the one table' % node_id)
        spec['node_id'] = node_id
    if port_id is not None:
        if not port_id:
            raise ValueError('port_id cannot be empty')
        spec['port_id'] = port_id
    store.edit(endpoint['endpoint_param'], ['body', 'floor', 'value'], spec, actor=actor)
    validate_node(store.nodes, relation)
    return endpoint['endpoint_param']


def set_relation_parameter(store, relation_id, name, value, actor=None):
    """Create or edit an exposed property parameter owned by a relation."""
    relation = _relation(store, relation_id)
    name = str(name)
    if name.startswith(('endpoint:', 'stage:')):
        raise ValueError('reserved relation parameter name %r' % name)
    pid = relation['params'].get(name)
    if pid is None:
        pid = store.add('param', name, floor={'op': 'value', 'value': value}, actor=actor)
        params = dict(relation['params'])
        params[name] = pid
        store.edit(relation_id, ['params'], params, actor=actor)
        store.edit(relation_id, ['body', 'inner'],
                   relation['body']['inner'] + [pid], actor=actor)
    else:
        store.edit(pid, ['body', 'floor', 'value'], value, actor=actor)
    validate_node(store.nodes, relation)
    return pid


def append_stage(store, relation_id, stage_id, mode='map', actor=None):
    """Append an executable guard/map/tap stage assignment to a relation."""
    relation = _relation(store, relation_id)
    if stage_id not in store.nodes:
        raise KeyError('relation stage %r is not in the one table' % stage_id)
    if mode not in ('guard', 'map', 'tap'):
        raise ValueError('unknown relation stage mode %r' % mode)
    indexes = [int(name.split(':', 1)[1]) for name in relation['params']
               if name.startswith('stage:') and name.split(':', 1)[1].isdigit()]
    name = 'stage:%03d' % ((max(indexes) + 1) if indexes else 0)
    spec = {'node_id': stage_id, 'mode': mode}
    assignment = store.add('param', name, floor={'op': 'value', 'value': spec},
                           actor=actor)
    store.nodes[assignment]['meta'].update({
        'role': 'relation_stage', 'stage_index': int(name.split(':')[1])})
    params = dict(relation['params'])
    params[name] = assignment
    store.edit(relation_id, ['params'], params, actor=actor)
    store.edit(relation_id, ['body', 'inner'],
               list(dict.fromkeys(relation['body']['inner'] +
                                  [assignment, stage_id])), actor=actor)
    validate_node(store.nodes, relation)
    return assignment


def build_payload_envelope(store, descriptor, title='Payload envelope', actor=None):
    """Build an open descriptor group from arbitrary namespaced parameters.

    The kernel does not enumerate geometry, image, BIM, document, or future
    types. Their logical/schema/media descriptors are editable parameter nodes.
    """
    descriptor = dict(descriptor)
    required = {
        'logical_type': 'urn:archhub:type:any',
        'schema_ref': '',
        'schema_version': '',
        'media_type': 'application/x-archhub-value',
        'mode': 'inline',
        'value_ref': '',
    }
    values = dict(required)
    values.update(descriptor)
    fields = {}
    for name, value in values.items():
        fields[name] = store.add(
            'param', name, floor={'op': 'value', 'value': value}, actor=actor)
    keys = list(values)
    keys_param = store.add('param', 'record keys',
                           floor={'op': 'value', 'value': keys}, actor=actor)
    assembler = store.add(
        'op', 'assemble payload descriptor',
        floor={'op': 'merge', 'fn': 'record', 'keys': {'$param': 'keys'}},
        params={'keys': keys_param}, actor=actor)
    for field_id in fields.values():
        store.wire(field_id, assembler, actor=actor)
    envelope = store.add(
        'group', title, inner=list(fields.values()) + [assembler],
        params=fields, actor=actor)
    return envelope


def attach_payload(store, relation_id, envelope_id, actor=None):
    """Expose a payload-envelope group through the relation's own parameters."""
    relation = _relation(store, relation_id)
    if envelope_id not in store.nodes or 'inner' not in store.nodes[envelope_id]['body']:
        raise ValueError('payload envelope must be an openable node group')
    payload_param = relation['params'].get('payload')
    if payload_param:
        store.edit(payload_param, ['body', 'floor'],
                   {'op': 'reference', 'target': envelope_id}, actor=actor)
    else:
        payload_param = store.add(
            'param', 'payload', floor={'op': 'reference', 'target': envelope_id}, actor=actor)
        params = dict(relation['params'])
        params['payload'] = payload_param
        store.edit(relation_id, ['params'], params, actor=actor)
    inner = list(relation['body']['inner'])
    inner.extend([payload_param, envelope_id])
    store.edit(relation_id, ['body', 'inner'], list(dict.fromkeys(inner)), actor=actor)
    validate_node(store.nodes, relation)
    return payload_param


def build_json_codec_stage(store, action, title=None, actor=None):
    """Build an openable JSON encode/decode stage around the codec floor."""
    if action not in ('json_encode', 'json_decode'):
        raise ValueError('unsupported JSON codec action %r' % action)
    item = store.add('op', 'stage input', floor={'op': 'item'}, actor=actor)
    codec = store.add('op', action, floor={'op': 'codec', 'action': action}, actor=actor)
    store.wire(item, codec, actor=actor)
    return store.add('group', title or action, inner=[item, codec], actor=actor)


def build_aead_stage(store, action, secret_ref, *, aad='', title=None, actor=None):
    """Build an openable AES-GCM stage whose key remains outside the graph."""
    if action not in ('encrypt', 'decrypt'):
        raise ValueError('unsupported AEAD action %r' % action)
    if isinstance(secret_ref, str):
        secret_ref = store.add('secret_ref', 'encryption key',
                               floor={'op': 'secret_ref', 'ref': secret_ref}, actor=actor)
    if secret_ref not in store.nodes or store.nodes[secret_ref]['kind'] != 'secret_ref':
        raise ValueError('AEAD key must be a secret_ref node')
    key_param = store.add('param', 'key reference',
                          floor={'op': 'reference', 'target': secret_ref}, actor=actor)
    aad_param = store.add('param', 'authenticated context',
                          floor={'op': 'value', 'value': aad}, actor=actor)
    item = store.add('op', 'stage input', floor={'op': 'item'}, actor=actor)
    crypto = store.add(
        'op', 'authenticated %s' % action,
        floor={'op': 'aead', 'action': action,
               'key_ref': {'$param': 'key_ref'}, 'aad': {'$param': 'aad'}},
        params={'key_ref': key_param, 'aad': aad_param}, actor=actor)
    store.wire(item, crypto, actor=actor)
    return store.add(
        'group', title or ('AES-GCM %s' % action),
        inner=[secret_ref, key_param, aad_param, item, crypto],
        params={'key_ref': key_param, 'aad': aad_param}, actor=actor)
