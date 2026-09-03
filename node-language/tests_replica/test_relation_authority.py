"""Forcing tests for the universal objectified relation authority."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang import (  # noqa: E402
    Store,
    append_endpoint,
    attach_payload,
    build_payload_envelope,
    clear_relation_stage,
    relation_sources,
    relation_stages,
    remove_endpoint,
    rewire_endpoint,
    set_relation_stage,
    validate_store,
)


def _value(store, value, title):
    return store.add('value', title, floor={'op': 'value', 'value': value})


def test_rewiring_endpoint_parameter_changes_real_producer_and_incidence():
    store = Store()
    a = _value(store, 2, 'a')
    b = _value(store, 9, 'b')
    sink = store.add('op', 'sink', floor={'op': 'math', 'fn': '+'})
    relation = store.wire(a, sink)
    source = relation_sources(store.nodes, store.nodes[relation])[0]

    assert store.pull(sink) == 2
    rewire_endpoint(store, relation, source['endpoint_param'], node_id=b,
                    port_id='alternate')
    assert store.pull(sink) == 9
    assert relation not in store.nodes[a]['relations']
    assert relation in store.nodes[b]['relations']
    assert store.endpoints(relation)[0]['port_id'] == 'alternate'
    assert validate_store(store) is True


def test_append_remove_endpoint_drives_real_multi_source_flow():
    store = Store()
    a = _value(store, 3, 'a')
    b = _value(store, 4, 'b')
    sink = store.add('op', 'sum list', floor={'op': 'reduce', 'mode': 'sum'})
    relation = store.wire(a, sink)
    extra = append_endpoint(store, relation, {
        'role': 'source', 'direction': 'out', 'node_id': b,
        'port_id': 'value', 'cardinality': 'one',
    })

    assert store.pull(relation) == [3, 4]
    assert store.pull(sink) == 7
    remove_endpoint(store, relation, extra)
    assert store.pull(relation) == 3
    assert store.pull(sink) == 3
    assert validate_store(store) is True


def test_stage_assignment_is_a_node_and_transform_executes_then_detaches():
    store = Store()
    source = _value(store, 3, 'source')
    sink = store.add('op', 'sink', floor={'op': 'math', 'fn': '+'})
    relation = store.wire(source, sink)

    item = store.add('op', 'stage input', floor={'op': 'item'})
    factor = _value(store, 2, 'factor')
    multiply = store.add('op', 'multiply', floor={'op': 'math', 'fn': '*'})
    store.wire(item, multiply)
    store.wire(factor, multiply)
    transform = store.add('group', 'Scale payload', inner=[item, factor, multiply])

    set_relation_stage(store, relation, 'transform', transform, mode='map')
    stages = relation_stages(store.nodes, store.nodes[relation])
    assert len(stages) == 1
    assert store.nodes[stages[0]['assignment_param']]['kind'] == 'param'
    assert stages[0]['assignment_param'] in store.open(relation)
    assert transform in store.open(relation)
    assert store.pull(sink) == 6

    store.edit(factor, ['body', 'floor', 'value'], 4)
    assert store.pull(sink) == 12

    clear_relation_stage(store, relation, 'transform')
    assert store.pull(sink) == 3
    assert not relation_stages(store.nodes, store.nodes[relation])
    assert validate_store(store) is True


def test_payload_envelope_is_open_generic_parameters_not_a_type_catalogue():
    store = Store()
    content = _value(store, 'sha256:abc123', 'content reference')
    sink = store.add('op', 'sink', floor={'op': 'math', 'fn': '+'})
    relation = store.wire(content, sink)
    envelope = build_payload_envelope(store, {
        'logical_type': 'urn:example:geometry:mesh',
        'schema_ref': 'https://example.test/schema/mesh/v7',
        'schema_version': '7',
        'media_type': 'model/gltf-binary',
        'mode': 'reference',
        'value_ref': content,
        'coordinate_system': 'urn:ogc:def:crs:EPSG::4978',
        'digest': 'sha256:abc123',
        'byte_size': 981273,
    })
    payload_param = attach_payload(store, relation, envelope)

    descriptor = store.pull(envelope)
    assert descriptor['logical_type'] == 'urn:example:geometry:mesh'
    assert descriptor['media_type'] == 'model/gltf-binary'
    assert descriptor['coordinate_system'].endswith('4978')
    assert descriptor['mode'] == 'reference'
    assert store.pull(payload_param) == descriptor
    assert envelope in store.open(relation)
    assert store.nodes[relation]['params']['payload'] == payload_param

    media_param = store.nodes[envelope]['params']['media_type']
    store.edit(media_param, ['body', 'floor', 'value'], 'image/avif')
    assert store.pull(envelope)['media_type'] == 'image/avif'
    assert validate_store(store) is True


def test_removing_last_source_or_target_is_rejected():
    store = Store()
    source = _value(store, 1, 'source')
    sink = store.add('op', 'sink', floor={'op': 'math', 'fn': '+'})
    relation = store.wire(source, sink)
    endpoint = relation_sources(store.nodes, store.nodes[relation])[0]
    with pytest.raises(ValueError):
        remove_endpoint(store, relation, endpoint['endpoint_param'])
    assert validate_store(store) is True
