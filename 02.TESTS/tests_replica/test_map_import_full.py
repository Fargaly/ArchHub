"""GATE: the FULL Grand Map imports onto the strict kernel via the ONE authority
(`nodelang.map_import`) -- nodes + every authority param as a node + 309 wire-nodes
+ the 15 domain groups -- and the whole store obeys the one-table law.

This replaces the retired thin `grandmap_on_kernel.py` (inventory-only: no
wires, no params). map_import is the single importer of record; if a future
edit drops the parametric/wired structure or introduces a shell, this goes RED.
"""
import json
import os, sys
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nodelang.core import Store, validate_store, KINDS
from nodelang.map_import import PUBLIC_MAP_PATH, import_grand_map, resolve_map_path


def _built():
    if resolve_map_path() == PUBLIC_MAP_PATH:
        pytest.skip('private founder authority is not configured on this machine')
    s = Store()
    reg = import_grand_map(s)
    return s, reg


def test_bundled_public_runtime_seed_is_portable_parametric_and_wired():
    s = Store()
    reg = import_grand_map(s, PUBLIC_MAP_PATH)
    assert validate_store(s) is True
    assert len(reg['domains']) == 15
    assert len(reg['values']) == 30
    assert len(reg['map_wires']) == 15
    assert sum(len(params) for params in reg['params'].values()) == 90
    assert all(s.pull(node) == 'partial' for node in reg['values'].values())


def test_full_map_validates_on_the_kernel():
    s, _reg = _built()
    assert validate_store(s) is True
    assert all(n['kind'] in KINDS for n in s.nodes.values())


def _authority_param_count():
    with open(resolve_map_path(), encoding='utf-8') as handle:
        data = json.load(handle)
    domains = data if isinstance(data, list) else data.get('domains', [])
    return sum(len(node.get('params', ()))
               for domain in domains for node in domain.get('nodes', ()))


def test_all_authority_params_are_first_class_nodes():
    s, reg = _built()
    expected = _authority_param_count()
    map_param_nodes = [n for n in s.nodes.values()
                       if n['kind'] == 'param'
                       and n['meta'].get('role') not in {
                           'relation_endpoint', 'presentation_label'}]
    assert len(map_param_nodes) == expected
    # every param is actually attached to its value node by name (not orphaned)
    attached = sum(len(reg['params'][mid]) for mid in reg['params'])
    assert attached == expected
    for mid, pdict in reg['params'].items():
        vnode = s.nodes[reg['values'][mid]]
        assert {name: pid for name, pid in vnode['params'].items()
                if name != 'label'} == pdict
        assert vnode['params']['label'] == reg['labels'][mid]


def test_309_map_wires_and_15_domain_groups():
    s, reg = _built()
    assert len(reg['map_wires']) == 309          # the real node-to-node dep graph
    assert len(reg['domains']) == 15
    # every domain id is a real group node in the one table
    for gid in reg['domains'].values():
        assert s.nodes[gid]['kind'] == 'group'
    assert reg['session'] is not None            # the whole map is ONE session node


def test_a_param_is_a_real_editable_node():
    s, reg = _built()
    pid = reg['params']['ui_design_tokens']['accent']
    before = s.pull(pid)
    s.apply_op({'op': 'set', 'id': pid, 'path': ['body', 'floor', 'value'],
                'value': '#123456', 'actor': 'test'})
    assert s.pull(pid) == '#123456' and s.pull(pid) != before
