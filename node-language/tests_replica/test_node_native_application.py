"""Forcing tests for the new application super-node and relation-driven UI."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang.application import (APPLICATION_SCHEMA_VERSION,
                                  build_archhub_application, navigate_container_back,
                                  project_container_on_canvas)  # noqa: E402
from nodelang.application_server import ApplicationServer  # noqa: E402
from nodelang.core import (relation_sources, relation_stages, relation_targets,
                           validate_store)  # noqa: E402
from nodelang.ui_runtime import activate_ui, edit_ui_binding, project_document  # noqa: E402


@pytest.fixture(scope='module')
def application():
    return build_archhub_application()


def _server_page(server):
    return urllib.request.urlopen(urllib.request.Request(
        server.url + '/',
        headers={'X-ArchHub-Session': server.browser_session_token},
    ), timeout=10).read().decode('utf-8')


def test_application_is_a_super_node_over_map_state_presentation_and_ui(application):
    store, reg = application
    app = store.nodes[reg['app']]
    assert app['kind'] == 'session'
    assert app['title'] == 'ArchHub Application'
    assert reg['grand']['session'] in app['body']['inner']
    assert reg['state'] in app['body']['inner']
    assert reg['presentation'] in app['body']['inner']
    assert reg['ui_root'] in app['body']['inner']
    assert store.pull(app['params']['ui_root']) == 'div'
    assert app['params']['mode'] == reg['mode']
    assert validate_store(store) is True


def test_new_ui_has_no_hidden_children_or_bind_arrays(application):
    store, reg = application
    app_ui_ids = {nid for nid, node in store.nodes.items()
                  if node['kind'] == 'ui' and nid != reg['grand']['report']}
    assert app_ui_ids
    for nid in app_ui_ids:
        assert 'children' not in store.nodes[nid]['params']
        assert 'bind' not in store.nodes[nid]['params']

    child_relations = []
    for relation in store.nodes.values():
        if relation['kind'] != 'wire':
            continue
        sources = relation_sources(store.nodes, relation)
        targets = relation_targets(store.nodes, relation)
        if any(endpoint.get('port_id') == 'children' for endpoint in sources) \
                and any(endpoint.get('port_id') == 'parent' for endpoint in targets):
            child_relations.append(relation)
    assert len(child_relations) > len(app_ui_ids) // 2
    assert all('order' in relation['params'] for relation in child_relations)


def test_projection_matches_reference_shell_geometry_and_real_controls(application):
    store, reg = application
    page = project_document(store, reg['app'], reg['ui_root'])
    assert 'grid-template-columns:292px minmax(0,1fr)' in page
    assert 'grid-template-columns:minmax(0,1fr) 320px' in page
    assert 'grid-template-rows:36px minmax(0,1fr)' in page
    assert 'class="inspector"' in page
    assert 'class="property-input"' in page
    assert page.count('class="graph-node"') == len(reg['cards'])
    assert page.count('class="inspector-panel"') == len(reg['inspector_panels'])
    assert 'Arch</span><strong' in page and '>Hub</strong>' in page
    assert 'Save as skill' in page and '>Save</button>' in page
    assert '::-webkit-scrollbar-thumb{background:var(--line)' in page
    assert 'location.reload()' not in page
    assert 'reconcileProjection' in page
    assert 'wire-preview' in page
    assert 'requestAnimationFrame' in page
    assert "document.addEventListener('wheel'" in page
    assert 'marqueeHits' in page and 'crossing ? intersects' in page
    assert 'event.shiftKey' in page and 'event.ctrlKey || event.metaKey' in page
    assert 'class="selection-box"' in page
    assert 'marker-end="url(#archhub-wire-arrow)"' in page
    assert 'class="wire-arrow"' in page
    assert '.node-select{display:none}' in page
    assert '.graph-node{--node-color:var(--ink-soft);border-width:2px 1px 1px' in page
    assert 'border-radius:9px' in page
    assert '.node-port{position:absolute;top:56px;width:22px;height:22px' in page
    assert 'data-node-kind="group"' in page
    assert '12.PRODUCTION' not in page


def test_canvas_selection_view_and_relation_direction_are_graph_native(application):
    store, reg = application
    canvas = next(nid for nid, node in store.nodes.items()
                  if node['kind'] == 'ui' and node['title'] == 'Node canvas')
    selection_relations = [
        store.nodes[rid] for rid in store.nodes[canvas]['relations']
        if any(endpoint['node_id'] == canvas
               and endpoint.get('port_id') == 'view.selection'
               for endpoint in relation_targets(store.nodes, store.nodes[rid]))]
    assert len(selection_relations) == 1
    assert relation_sources(store.nodes, selection_relations[0])[0]['node_id'] == \
        store.nodes[reg['app']]['params']['selection']
    assert store.nodes[reg['selection_box']]['kind'] == 'ui'
    assert store.pull(reg['selection_count']) == 0
    assert store.pull(reg['selection_label']) == '0 selected'
    assert all(store.pull(store.nodes[rid]['params']['width']) == pytest.approx(2.1)
               for rid in reg['wire_authorities'])
    page = project_document(store, reg['app'], reg['ui_root'])
    assert page.count('data-selected="False"') == len(reg['cards'])


def test_structured_selection_commit_is_one_projection_free_graph_write():
    store, reg = build_archhub_application()
    server = ApplicationServer(
        store=store, registry=reg, allow_legacy_mutations=True
    ).start()
    canvas = next(nid for nid, node in store.nodes.items()
                  if node['kind'] == 'ui' and node['title'] == 'Node canvas')
    selected = list(reg['cards'])[:3]
    try:
        request = urllib.request.Request(
            server.url + '/api/edit', method='POST',
            headers={'Content-Type': 'application/json',
                     'X-ArchHub-Session': server.browser_session_token},
            data=json.dumps({
                'ui_id': canvas, 'port': 'view.selection',
                'value': json.dumps(selected), 'projection': False,
                'transaction': 'cad-window-selection-1',
            }).encode('utf-8'))
        response = json.loads(urllib.request.urlopen(request, timeout=20).read())
        assert response['ok'] is True
        assert 'projection' not in response
        selection = store.nodes[reg['app']]['params']['selection']
        assert store.pull(selection) == selected
        assert store.pull(reg['selection_count']) == len(selected)
        assert store.pull(reg['selection_label']) == '3 selected'
        page = project_document(store, reg['app'], reg['ui_root'])
        markup = page.split('</style></head><body>', 1)[1].split('<script>', 1)[0]
        assert markup.count('data-selected="True"') == len(selected)
        assert '>3 selected</span>' in markup
        assert validate_store(store) is True
    finally:
        server.close()


def test_brain_governance_cde_and_grand_map_share_the_operating_graph(application):
    store, reg = application
    operating = store.nodes[reg['canvas_session']]
    assert reg['brain'] in operating['body']['inner']
    assert reg['governance']['session'] in operating['body']['inner']
    assert reg['cde'] in operating['body']['inner']
    assert reg['grand']['grand'] in operating['body']['inner']
    assert len(reg['integration_relations']) == 4
    assert all(store.nodes[rid]['kind'] == 'wire' for rid in reg['integration_relations'])
    assert store.nodes[reg['session_catalog']]['kind'] == 'group'
    assert store.nodes[reg['models']['session']]['kind'] == 'session'
    assert store.pull(reg['selected_model_id']) in ('model-fast', 'model-deep')
    assert reg['models']['session'] in reg['home_cards']
    assert reg['selfext']['session'] in operating['body']['inner']
    assert reg['selfext']['session'] in reg['home_cards']
    assert store.nodes[reg['selfext']['install_effect']]['meta']['frozen'] is True
    assert store.nodes[reg['selfext']['rollback_effect']]['meta']['frozen'] is True
    assert reg['monetization']['session'] in operating['body']['inner']
    assert reg['monetization']['session'] in reg['home_cards']
    assert store.nodes[reg['monetization']['billing_effect']]['meta']['frozen'] is True
    assert reg['cloud']['session'] in operating['body']['inner']
    assert reg['cloud']['session'] in reg['home_cards']
    assert reg['cockpit_domain']['session'] in operating['body']['inner']
    assert reg['cockpit_domain']['session'] in reg['home_cards']
    assert reg['community']['session'] in operating['body']['inner']
    assert reg['community']['session'] in reg['home_cards']
    assert reg['resources']['session'] in operating['body']['inner']
    assert reg['resources']['session'] in reg['home_cards']
    assert len(reg['resources']['connections']) == 12
    assert len(reg['domain_integration_relations']) == 24 + len(reg['resources']['connections'])
    assert all(store.nodes[rid]['kind'] == 'wire'
               for rid in reg['domain_integration_relations'])
    assert len(reg['monetization_surface_relations']) == 2
    page = project_document(store, reg['app'], reg['ui_root'])
    assert 'Brain' in page and 'Desktop Launch Governance' in page and 'Active CDE' in page
    assert 'LIVE PROBE NODES' in page and '4 COURT PROBES' in page and 'WIP / T1' in page


def test_cockpit_command_surface_is_wired_to_ephemeral_policy_submission(application):
    store, reg = application
    relation = store.nodes[reg['cockpit_command_relation']]
    assert relation_sources(store.nodes, relation)[0]['node_id'] == reg['cockpit_command_input']
    assert relation_targets(store.nodes, relation)[0]['node_id'] == reg['cockpit_command_submit']
    assert reg['cockpit_surface_relation'] in reg['domain_integration_relations']
    page = project_document(store, reg['app'], reg['ui_root'])
    fragment = page[page.index('data-node="%s"' % reg['cockpit_command_input']):][:400]
    assert 'data-edit="true"' not in fragment
    assert 'placeholder="Direct the operating graph"' in page


def test_home_workspace_session_loop_is_an_audited_node_transaction(application):
    store, reg = build_archhub_application()
    home_action = next(nid for nid, node in store.nodes.items()
                       if node['kind'] == 'ui' and node['title'] == 'Home action')
    activate_ui(store, home_action)
    assert store.pull(reg['mode']) == 'home'
    home_page = project_document(store, reg['app'], reg['ui_root'])
    assert 'class="archhub-app"' in home_page
    assert 'data-mode="home"' in home_page
    assert 'class="home-surface"' in home_page
    assert 'NODE-NATIVE OPERATING SYSTEM' in home_page

    brain_card = reg['home_cards'][reg['brain']]
    before_history = sum(1 for node in store.nodes.values() if node['kind'] == 'history')
    activate_ui(store, brain_card)
    assert store.pull(reg['mode']) == 'workspace'
    assert store.pull(reg['container']) == reg['canvas_session']
    assert store.pull(reg['focus']) == reg['brain']
    after_history = sum(1 for node in store.nodes.values() if node['kind'] == 'history')
    assert after_history == before_history + 3


def test_cockpit_mode_and_live_court_sample_are_graph_operations(application):
    store, reg = build_archhub_application()
    cockpit_action = next(nid for nid, node in store.nodes.items()
                           if node['kind'] == 'ui' and node['title'] == 'Cockpit action')
    activate_ui(store, cockpit_action)
    assert store.pull(reg['mode']) == 'cockpit'
    page = project_document(store, reg['app'], reg['ui_root'])
    assert 'data-mode="cockpit"' in page
    assert 'class="cockpit-surface"' in page
    assert 'EXPLICIT COURT SAMPLES' in page
    assert 'NOT RUN' in page

    for probe in reg['governance']['probes']:
        check = store.nodes[probe]['body']['floor']['spec']['check']
        store.edit(probe, ['body', 'floor'],
                   {'op': 'value', 'value': {'ok': True, 'check': check, 'detail': 'test'}})
    before_history = sum(1 for node in store.nodes.values() if node['kind'] == 'history')
    activate_ui(store, reg['cockpit_run'])
    results = reg['cockpit_results']
    assert store.pull(results['brain'])['ok'] is True
    assert store.pull(results['hooks'])['ok'] is True
    assert store.pull(results['governance']) == pytest.approx(1.0)
    after_history = sum(1 for node in store.nodes.values() if node['kind'] == 'history')
    assert after_history == before_history + 3


def test_brain_surface_samples_confirmed_mcp_report_into_field_nodes(monkeypatch):
    store, reg = build_archhub_application()
    brain_action = next(nid for nid, node in store.nodes.items()
                        if node['kind'] == 'ui' and node['title'] == 'Brain action')
    activate_ui(store, brain_action)
    assert store.pull(reg['mode']) == 'brain'
    page = project_document(store, reg['app'], reg['ui_root'])
    assert 'data-mode="brain"' in page
    assert 'LIVE COMPLIANCE / WORK / CDE / HISTORY' in page
    assert 'NOT RUN' in page

    report = {
        'ok': True,
        'active_cde': {'scope': '10.PRODUCT/13.NODE-LANGUAGE', 'stage': 'WIP'},
        'work': {'leaf': 'application-parity'},
        'hook_coverage': {'status': 'green'},
        'history': {'count': 12},
        'last_gate_decision': {'allow': True},
        'run_reports': {'total': 1, 'reports': [{'report_id': 'rr-1'}]},
    }
    from nodelang import governance_probe
    monkeypatch.setattr(governance_probe, '_mcp_tool',
                        lambda name, args, url, timeout: report)
    before_history = sum(1 for node in store.nodes.values() if node['kind'] == 'history')
    activate_ui(store, reg['brain_sync'])
    assert store.pull(reg['brain_report_result']) == report
    assert store.pull(reg['brain_fields']['active_cde'])['stage'] == 'WIP'
    assert store.pull(reg['brain_fields']['hook_coverage'])['status'] == 'green'
    assert store.pull(reg['brain_fields']['run_reports'])['total'] == 1
    after_history = sum(1 for node in store.nodes.values() if node['kind'] == 'history')
    assert after_history == before_history + 1


def test_brain_claim_assigns_the_real_cde_fields_and_refreezes_effect(monkeypatch):
    store, reg = build_archhub_application()
    report = {
        'ok': True,
        'active_cde': {
            'runtime': 'archhub-app',
            'container': {
                'container_id': 'GM.ui.ui_design_tokens',
                'lifecycle_state': 'WIP',
                'tier': 'T1',
                'allowed_paths': [
                    '10.PRODUCT/13.NODE-LANGUAGE/nodelang/application.py'],
            },
        },
        'work': {'counts': {'open': 281, 'claimed': 1}},
        'hook_coverage': {'status': 'green'},
        'history': {'count': 513},
        'last_gate_decision': {'allow': True},
    }

    def fake_tool(name, args, url, timeout):
        if name == 'brain.work_assigned_block':
            return {'ok': True, 'blocked': False,
                    'leaf': {'leaf_id': 'leaf-1',
                             'cde_container': report['active_cde']['container']}}
        return report

    from nodelang import governance_probe
    monkeypatch.setattr(governance_probe, '_mcp_tool', fake_tool)
    assert store.nodes[reg['brain_work_claim']]['meta']['frozen'] is True
    activate_ui(store, reg['brain_claim'])
    assert store.nodes[reg['brain_work_claim']]['meta']['frozen'] is True
    cde = store.nodes[reg['cde']]
    assert store.pull(cde['params']['container_id']) == 'GM.ui.ui_design_tokens'
    assert store.pull(cde['params']['stage']) == 'WIP'
    assert store.pull(cde['params']['privacy_tier']) == 'T1'
    assert store.pull(cde['params']['scope']) == [
        '10.PRODUCT/13.NODE-LANGUAGE/nodelang/application.py']
    assert store.pull(cde['params']['runtime']) == 'archhub-app'
    assert store.pull(reg['brain_work_claim_result'])['result']['blocked'] is False


def test_live_watcher_samples_only_the_open_operating_view(monkeypatch):
    store, reg = build_archhub_application()
    report = {
        'ok': True,
        'active_cde': {'runtime': 'archhub-app', 'container': {
            'container_id': 'GM.nodes.nodes_kernel', 'lifecycle_state': 'WIP',
            'tier': 'T1', 'allowed_paths': ['10.PRODUCT/13.NODE-LANGUAGE/nodelang/core.py']}},
        'work': {'counts': {'open': 281, 'claimed': 1}},
        'hook_coverage': {'status': 'green'}, 'history': {'count': 514},
        'last_gate_decision': {'allow': True},
    }
    from nodelang import governance_probe
    monkeypatch.setattr(governance_probe, '_mcp_tool',
                        lambda name, args, url, timeout: report)
    server = ApplicationServer(
        store=store, registry=reg, allow_legacy_mutations=True
    ).start()
    try:
        assert server.refresh_live_state('workspace') is False
        assert server.refresh_live_state('brain') is True
        cde = store.nodes[reg['cde']]
        assert store.pull(cde['params']['container_id']) == 'GM.nodes.nodes_kernel'
        assert store.pull(cde['params']['scope']) == [
            '10.PRODUCT/13.NODE-LANGUAGE/nodelang/core.py']
        task = reg['orchestration']['task_params']['task-build']
        assert store.pull(task['brain_connected']) is True
        assert store.pull(task['hooks_ready']) is True
        assert store.pull(reg['orchestration']['safety_nodes']['task-build']) == 0

        for probe in reg['governance']['probes']:
            check = store.nodes[probe]['body']['floor']['spec']['check']
            store.edit(probe, ['body', 'floor'],
                       {'op': 'value', 'value': {'ok': True, 'check': check}})
        assert server.refresh_live_state('cockpit') is True
        assert store.pull(reg['cockpit_results']['governance']) == pytest.approx(1.0)
    finally:
        server.close()


def test_production_rail_search_share_and_settings_are_real_node_surfaces(application):
    store, reg = build_archhub_application()
    rail_titles = {'Home action', 'Search action', 'Share action', 'Settings action'}
    assert rail_titles <= {node['title'] for node in store.nodes.values()
                           if node['kind'] == 'ui'}
    assert not any(node['title'] == 'Graph action' for node in store.nodes.values())

    search_action = next(nid for nid, node in store.nodes.items()
                         if node['kind'] == 'ui' and node['title'] == 'Search action')
    activate_ui(store, search_action)
    assert store.pull(reg['sidebar_panel']) == 'search'
    edit_ui_binding(store, reg['search_input'], 'Brain')
    page = project_document(store, reg['app'], reg['ui_root'])
    brain_row = reg['search_rows'][reg['brain']]
    assert 'data-visible="True" class="library-row search-result" data-node="%s"' \
        % brain_row in page
    hidden = next(row for node_id, row in reg['search_rows'].items()
                  if 'brain' not in store.nodes[node_id]['title'].lower())
    assert 'data-visible="False" class="library-row search-result" data-node="%s"' \
        % hidden in page

    share_action = next(nid for nid, node in store.nodes.items()
                        if node['kind'] == 'ui' and node['title'] == 'Share action')
    activate_ui(store, share_action)
    assert store.pull(reg['sidebar_panel']) == 'share'
    page = project_document(store, reg['app'], reg['ui_root'])
    assert 'data-download="%s"' % reg['app'] in page
    assert 'data-navigate="/website"' in page

    settings_action = next(nid for nid, node in store.nodes.items()
                           if node['kind'] == 'ui' and node['title'] == 'Settings action')
    activate_ui(store, settings_action)
    assert store.pull(reg['mode']) == 'settings'
    edit_ui_binding(store, reg['settings_inputs']['accent'], '#0088aa')
    page = project_document(store, reg['app'], reg['ui_root'])
    assert '--accent:#0088aa;' in page


def test_http_export_returns_reloadable_node_subgraph(application):
    store, reg = build_archhub_application()
    server = ApplicationServer(
        store=store, registry=reg, allow_legacy_mutations=True
    ).start()
    try:
        request = urllib.request.Request(
            server.url + '/api/export?node_id=' + reg['canvas_session'],
            headers={'X-ArchHub-Session': server.browser_session_token},
        )
        response = urllib.request.urlopen(request, timeout=10)
        payload = json.loads(response.read())
        assert payload['format'] == 'archhub-node-graph-v1'
        assert payload['root_id'] == reg['canvas_session']
        assert payload['classification'] == 'T1 INTERNAL'
        assert response.headers['X-ArchHub-Classification'] == 'T1 INTERNAL'
        assert any(node['id'] == reg['canvas_session'] for node in payload['nodes'])
        assert response.headers['Content-Disposition'].endswith('.archhub.json"')
    finally:
        server.close()


def test_visible_ports_create_an_authoritative_relation_and_bezier_projection():
    store, reg = build_archhub_application()
    source_id, target_id = list(reg['cards'])[:2]
    server = ApplicationServer(
        store=store, registry=reg, allow_legacy_mutations=True
    ).start()

    def activate(ui_id):
        request = urllib.request.Request(
            server.url + '/api/activate', method='POST',
            headers={'Content-Type': 'application/json',
                     'X-ArchHub-Session': server.browser_session_token},
            data=json.dumps({'ui_id': ui_id}).encode('utf-8'))
        return json.loads(urllib.request.urlopen(request, timeout=10).read())

    try:
        activate(reg['ports'][source_id]['output'])
        wire_source = store.nodes[reg['app']]['params']['wire_source']
        assert store.pull(wire_source) == {'node_id': source_id, 'port_id': 'value'}
        response = activate(reg['ports'][target_id]['input'])
        relation_id = response['touched']
        assert store.nodes[relation_id]['kind'] == 'wire'
        assert relation_sources(store.nodes, store.nodes[relation_id])[0]['node_id'] == source_id
        assert relation_targets(store.nodes, store.nodes[relation_id])[0]['node_id'] == target_id
        relation = store.nodes[relation_id]
        assert {'color', 'width', 'dash', 'hidden', 'payload'} <= set(relation['params'])
        payload_param = relation['params']['payload']
        payload_group = store.nodes[payload_param]['body']['floor']['target']
        assert store.nodes[payload_group]['kind'] == 'group'
        store.edit(relation['params']['color'], ['body', 'floor', 'value'], '#0088aa')
        store.edit(relation['params']['dash'], ['body', 'floor', 'value'], '5 3')
        assert store.pull(reg['focus']) == relation_id
        page = project_document(store, reg['app'], reg['ui_root'])
        assert 'data-relation="%s"' % relation_id in page
        assert '<path ' in page and ' C ' in page
        fragment = page[page.index('data-relation="%s"' % relation_id):][:700]
        assert 'stroke:#0088aa' in fragment and 'stroke-dasharray:5 3' in fragment
        encrypt = max((nid for nid, node in store.nodes.items()
                       if node['kind'] == 'ui'
                       and node['title'] == 'Encode and encrypt relation'),
                      key=lambda nid: store.nodes[nid]['meta']['seq'])
        activate(encrypt)
        stages = relation_stages(store.nodes, store.nodes[relation_id])
        assert len(stages) == 2
        assert all(store.nodes[stage['node_id']]['kind'] == 'group' for stage in stages)
        assert store.pull(store.nodes[relation_id]['params']['encoding']) == 'json'
        assert store.pull(store.nodes[relation_id]['params']['encryption']) == 'AES-GCM'
        assert 'Inspector: User relation' in {
            node['title'] for node in store.nodes.values() if node['kind'] == 'ui'}
        assert validate_store(store) is True
    finally:
        server.close()


def test_canvas_pan_zoom_and_fit_are_graph_state_not_static_toolbar_text():
    store, reg = build_archhub_application()
    server = ApplicationServer(
        store=store, registry=reg, allow_legacy_mutations=True
    ).start()

    def post(path, payload):
        request = urllib.request.Request(
            server.url + path, method='POST',
            headers={'Content-Type': 'application/json',
                     'X-ArchHub-Session': server.browser_session_token},
            data=json.dumps(payload).encode('utf-8'))
        return json.loads(urllib.request.urlopen(request, timeout=10).read())

    try:
        zoom_in = next(nid for nid, node in store.nodes.items()
                       if node['kind'] == 'ui' and node['title'] == 'Zoom in')
        fit = next(nid for nid, node in store.nodes.items()
                   if node['kind'] == 'ui' and node['title'] == 'Fit canvas')
        post('/api/activate', {'ui_id': zoom_in})
        assert store.pull(reg['canvas_view']['zoom']) == pytest.approx(1.1)

        post('/api/edit', {'ui_id': next(nid for nid, node in store.nodes.items()
                                         if node['kind'] == 'ui'
                                         and node['title'] == 'Node canvas'),
                           'port': 'view.pan_x', 'value': '125'})
        assert store.pull(reg['canvas_view']['pan_x']) == pytest.approx(125)

        post('/api/activate', {'ui_id': fit})
        assert store.pull(reg['canvas_view']['zoom']) == pytest.approx(.72)
        assert store.pull(reg['canvas_view']['pan_x']) == pytest.approx(18)
        page = project_document(store, reg['app'], reg['ui_root'])
        assert 'data-pan-x="18"' in page
        assert 'translate(18.0px,18.0px) scale(0.72)' in page
    finally:
        server.close()


def test_new_node_flow_creates_one_universal_node_and_all_live_lenses():
    store, reg = build_archhub_application()
    server = ApplicationServer(
        store=store, registry=reg, allow_legacy_mutations=True
    ).start()

    def post(path, payload):
        request = urllib.request.Request(
            server.url + path, method='POST',
            headers={'Content-Type': 'application/json',
                     'X-ArchHub-Session': server.browser_session_token},
            data=json.dumps(payload).encode('utf-8'))
        return json.loads(urllib.request.urlopen(request, timeout=10).read())

    try:
        post('/api/activate', {'ui_id': reg['new_node_button']})
        assert store.pull(reg['mode']) == 'create'
        edit_ui_binding(store, next(nid for nid, node in store.nodes.items()
                                    if node['kind'] == 'ui'
                                    and node['title'] == 'New node title input'),
                        'Area Schedule')
        edit_ui_binding(store, next(nid for nid, node in store.nodes.items()
                                    if node['kind'] == 'ui'
                                    and node['title'] == 'New node value input'),
                        '{"level":"L02","area":812.5}')
        post('/api/activate', {'ui_id': reg['kind_buttons']['value']})
        created = post('/api/activate', {'ui_id': reg['create_submit']})['touched']

        assert store.nodes[created]['kind'] == 'value'
        assert store.nodes[created]['title'] == 'Area Schedule'
        assert store.pull(created) == {'level': 'L02', 'area': 812.5}
        assert created in store.nodes[reg['canvas_session']]['body']['inner']
        assert store.pull(reg['focus']) == created
        assert store.pull(reg['mode']) == 'workspace'
        assert any(node['title'] == 'Canvas node: Area Schedule'
                   for node in store.nodes.values())
        assert any(node['title'] == 'Inspector: Area Schedule'
                   for node in store.nodes.values())
        assert any(node['title'] == 'Search result: ' + created
                   for node in store.nodes.values())
        page = project_document(store, reg['app'], reg['ui_root'])
        assert 'Area Schedule' in page
        assert validate_store(store) is True
    finally:
        server.close()


def test_multi_selection_groups_nodes_without_deleting_the_members():
    store, reg = build_archhub_application()
    server = ApplicationServer(
        store=store, registry=reg, allow_legacy_mutations=True
    ).start()

    def activate(ui_id):
        request = urllib.request.Request(
            server.url + '/api/activate', method='POST',
            headers={'Content-Type': 'application/json',
                     'X-ArchHub-Session': server.browser_session_token},
            data=json.dumps({'ui_id': ui_id}).encode('utf-8'))
        return json.loads(urllib.request.urlopen(request, timeout=10).read())

    first, second = list(reg['cards'])[:2]
    try:
        activate(reg['selection_buttons'][first])
        activate(reg['selection_buttons'][second])
        selection = store.nodes[reg['app']]['params']['selection']
        assert store.pull(selection) == [first, second]
        group_id = activate(reg['group_selection'])['touched']
        assert store.nodes[group_id]['kind'] == 'group'
        assert store.nodes[group_id]['body']['inner'] == [first, second]
        assert first in store.nodes and second in store.nodes
        operating = store.nodes[reg['canvas_session']]['body']['inner']
        assert group_id in operating and first not in operating and second not in operating
        assert store.pull(selection) == []
        assert store.pull(reg['focus']) == group_id
        assert any(node['title'] == 'Canvas node: Group (2 nodes)'
                   for node in store.nodes.values())
        assert validate_store(store) is True
    finally:
        server.close()


def test_card_action_rewires_visible_focus_and_right_rail(application):
    store, reg = build_archhub_application()
    node_id = list(reg['cards'])[3]
    card_ui = reg['cards'][node_id]
    assert store.pull(reg['focus']) != node_id
    activate_ui(store, card_ui)
    assert store.pull(reg['focus']) == node_id
    page = project_document(store, reg['app'], reg['ui_root'])
    panel = reg['inspector_panels'][node_id]
    marker = 'data-visible="True" class="inspector-panel" data-node="%s"' % panel
    assert marker in page


def test_property_input_edits_real_parameter_and_moves_card(application):
    store, reg = build_archhub_application()
    node_id = next(iter(reg['cards']))
    x_param = reg['positions'][node_id]['x']
    x_input = reg['property_inputs'][node_id]['position_x']
    assert store.pull(x_param) == 60
    edit_ui_binding(store, x_input, '128')
    assert store.pull(x_param) == 128
    page = project_document(store, reg['app'], reg['ui_root'])
    card = reg['cards'][node_id]
    start = page.index('data-node="%s"' % card)
    fragment = page[start:start + 180]
    assert 'left:128px' in fragment
    assert validate_store(store) is True


def test_visible_name_is_one_parameter_node_wired_to_card_library_search_and_rail():
    store, reg = build_archhub_application()
    node_id = next(iter(reg['cards']))
    label_param = store.nodes[node_id]['params']['label']
    label_input = reg['property_inputs'][node_id]['label']
    edit_ui_binding(store, label_input, 'Envelope Systems')
    assert store.pull(label_param) == 'Envelope Systems'
    page = project_document(store, reg['app'], reg['ui_root'])
    assert page.count('Envelope Systems') >= 4
    card = reg['cards'][node_id]
    fragment = page[page.index('data-node="%s"' % card):][:800]
    assert 'Envelope Systems' in fragment


def test_drag_ports_write_same_position_parameters(application):
    store, reg = build_archhub_application()
    node_id = next(iter(reg['cards']))
    card = reg['cards'][node_id]
    edit_ui_binding(store, card, '144', port='style.left')
    edit_ui_binding(store, card, '212', port='style.top')
    assert store.pull(reg['positions'][node_id]['x']) == 144
    assert store.pull(reg['positions'][node_id]['y']) == 212
    page = project_document(store, reg['app'], reg['ui_root'])
    fragment = page[page.index('data-node="%s"' % card):][:220]
    assert 'left:144px' in fragment and 'top:212px' in fragment


def test_cable_click_selects_relation_and_endpoint_lens_rewires_it(application):
    store, reg = build_archhub_application()
    relation_id = reg['wire_authorities'][0]
    line_ui = reg['wire_ui'][0]
    activate_ui(store, line_ui)
    assert store.pull(reg['focus']) == relation_id
    panel = reg['inspector_panels'][relation_id]
    page = project_document(store, reg['app'], reg['ui_root'])
    assert 'data-visible="True" class="inspector-panel" data-node="%s"' % panel in page

    endpoint = store.endpoints(relation_id)[0]
    alternate = next(nid for nid in reg['grand']['values'].values()
                     if nid != endpoint['node_id'])
    endpoint_input = reg['property_inputs'][relation_id]['endpoint:000.node_id']
    edit_ui_binding(store, endpoint_input, alternate, port='value.node_id')
    assert store.endpoints(relation_id)[0]['node_id'] == alternate
    assert relation_id in store.nodes[alternate]['relations']
    assert validate_store(store) is True


def test_http_application_drives_same_graph(application):
    store, reg = build_archhub_application()
    server = ApplicationServer(
        store=store, registry=reg, allow_legacy_mutations=True
    ).start()
    try:
        page = _server_page(server)
        assert 'class="archhub-app"' in page
        state_request = urllib.request.Request(
            server.url + '/api/state',
            headers={'X-ArchHub-Session': server.browser_session_token},
        )
        state = json.loads(urllib.request.urlopen(state_request, timeout=10).read())
        assert state['application_node'] == (
            server.universal_registry.application_root
        )
        assert state['schema_version'] == 'universal-cell-v1'
        assert state['legacy']['application_node'] == reg['app']
        assert state['legacy']['schema_version'] == APPLICATION_SCHEMA_VERSION
        assert state['valid'] is True

        node_id = list(reg['cards'])[2]
        request = urllib.request.Request(
            server.url + '/api/activate', method='POST',
            headers={'Content-Type': 'application/json',
                     'X-ArchHub-Session': server.browser_session_token},
            data=json.dumps({'ui_id': reg['cards'][node_id]}).encode('utf-8'))
        response = json.loads(urllib.request.urlopen(request, timeout=10).read())
        assert response['ok'] is True
        assert 'class="archhub-app"' in response['projection']
        card_fragment = response['projection'][
            response['projection'].index('data-graph-node="%s"' % node_id):][:500]
        assert 'data-focused="True"' in card_fragment
        assert store.pull(reg['focus']) == node_id

        secret_command = 'change api_key=must-not-persist'
        request = urllib.request.Request(
            server.url + '/api/activate', method='POST',
            headers={'Content-Type': 'application/json',
                     'X-ArchHub-Session': server.browser_session_token},
            data=json.dumps({
                'ui_id': reg['cockpit_command_submit'],
                'input_value': secret_command,
                'projection': False,
            }).encode('utf-8'))
        response = json.loads(urllib.request.urlopen(request, timeout=10).read())
        assert response['ok'] is True
        assert store.pull(reg['cockpit_domain']['command']) == '[REDACTED BY COCKPIT POLICY]'
        assert secret_command not in repr(store.nodes)
    finally:
        server.close()


def test_group_double_activation_materializes_and_opens_its_inner_nodes():
    store, reg = build_archhub_application()
    resource_session = reg['resources']['session']
    card = reg['cards'][resource_session]
    before = project_document(store, reg['app'], reg['ui_root'])
    assert 'data-double-action="true"' in before

    activate_ui(
        store, card, event='double_activate', transaction='open-resource-session',
        command_handler=lambda operation: project_container_on_canvas(
            store, operation['args']['container_id']),
    )

    children = set(store.nodes[resource_session]['body']['inner'])
    projected = set()
    for node in store.nodes.values():
        if node['kind'] != 'ui' or 'attrs' not in node['params']:
            continue
        attrs = store.pull(node['params']['attrs'])
        if attrs.get('data-container-id') == resource_session and attrs.get('data-graph-node'):
            projected.add(attrs['data-graph-node'])
    assert children <= projected
    assert store.pull(reg['container']) == resource_session
    assert store.pull(reg['container_title']) == 'External resources'
    assert store.pull(reg['container_stack']) == [reg['canvas_session'], resource_session]
    governance = reg['resources']['resources']['governance-standard']['adapter']
    project_container_on_canvas(store, governance)
    assert store.pull(reg['container']) == governance
    assert navigate_container_back(store) == resource_session
    assert store.pull(reg['container']) == resource_session
    assert store.pull(reg['container_stack']) == [reg['canvas_session'], resource_session]
    page = project_document(store, reg['app'], reg['ui_root'])
    container_tab = next(
        node for node in store.nodes.values()
        if node['kind'] == 'ui' and node['title'] == 'Current container tab')
    title_bindings = [
        store.nodes[relation_id]
        for relation_id in container_tab['relations']
        if any(endpoint['node_id'] == container_tab['id']
               and endpoint.get('port_id') == 'text'
               for endpoint in relation_targets(store.nodes,
                                                store.nodes[relation_id]))]
    assert len(title_bindings) == 1
    assert [endpoint['node_id']
            for endpoint in relation_sources(store.nodes, title_bindings[0])] == [
                reg['container_title']]
    assert '>External resources</button>' in page
    assert 'Workspace governance authority' in page
    assert 'User identity database' in page
    assert 'data-container-id="%s"' % resource_session in page
    assert validate_store(store) is True


def test_undo_and_redo_replay_a_whole_graph_gesture_transaction():
    store, reg = build_archhub_application()
    server = ApplicationServer(
        store=store, registry=reg, allow_legacy_mutations=True
    ).start()

    def post(path, payload):
        request = urllib.request.Request(
            server.url + path, method='POST',
            headers={'Content-Type': 'application/json',
                     'X-ArchHub-Session': server.browser_session_token},
            data=json.dumps(payload).encode('utf-8'))
        return json.loads(urllib.request.urlopen(request, timeout=20).read())

    try:
        node_id = next(iter(reg['cards']))
        card = reg['cards'][node_id]
        x_param = reg['positions'][node_id]['x']
        y_param = reg['positions'][node_id]['y']
        original = (store.pull(x_param), store.pull(y_param))
        transaction = 'gesture-move-1'
        post('/api/batch', {
            'transaction': transaction, 'projection': False,
            'operations': [
                {'kind': 'edit', 'ui_id': card, 'port': 'style.left', 'value': '333'},
                {'kind': 'edit', 'ui_id': card, 'port': 'style.top', 'value': '244'},
            ],
        })
        assert (store.pull(x_param), store.pull(y_param)) == (333, 244)

        undo = next(nid for nid, node in store.nodes.items()
                    if node['kind'] == 'ui' and node['title'] == 'Undo graph transaction')
        redo = next(nid for nid, node in store.nodes.items()
                    if node['kind'] == 'ui' and node['title'] == 'Redo graph transaction')
        post('/api/activate', {'ui_id': undo, 'projection': False})
        assert (store.pull(x_param), store.pull(y_param)) == original
        post('/api/activate', {'ui_id': redo, 'projection': False})
        assert (store.pull(x_param), store.pull(y_param)) == (333, 244)

        entries = [node['body']['floor']['entry'] for node in store.nodes.values()
                   if node['kind'] == 'history']
        assert sum('undo_of' in entry for entry in entries) == 2
        assert sum('redo_of' in entry for entry in entries) == 2
        assert validate_store(store) is True
    finally:
        server.close()
