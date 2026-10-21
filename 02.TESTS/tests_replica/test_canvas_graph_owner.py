"""Canvas graph operations write the ONE graph store, nothing else."""
import os
import secrets
from datetime import datetime
from pathlib import Path

import pytest

from nodelang import commit_intent, universal_application as app
from nodelang.application_server import ApplicationServer
from nodelang.canvas_graph_owner import CanvasOwner, CanvasRefused
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.universal_pipeline import create_engine_node


@pytest.fixture(scope="module")
def ops(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("CANVAS", numbered=False)
    os.environ["ARCHHUB_GRAND_MAP_PATH"] = str(Path(app.__file__).parent / "data/public_runtime_map.json")
    keys = MemorySigningKeyProvider("archhub.local.relationship-authority", secrets.token_bytes(32))
    keys.add_key("archhub.local.court-attestation", secrets.token_bytes(32))
    from nodelang.pipeline_engines import PIPELINE_ENGINES
    server = ApplicationServer(universal_state_path=tmp / "app.sqlite3", universal_key_provider=keys,
        universal_workspace_root=tmp, enable_machine_transport=False,
        enable_universal_cloud_gateway=False, enable_machine_projection_prewarm=False,
        pipeline_effect_engines=PIPELINE_ENGINES,
        live_watch=False).start()
    binding = server._resolve_browser_session(server.browser_session_token)
    with commit_intent.declare(commit_intent.USER_ACTION,
            actor=server.universal_registry.authorization.subject_root, reason="canvas test"):
        owner = CanvasOwner(server.universal_store, server.universal_registry, binding.context)
        owner.server = server
        owner.add_graph("Canvas test graph")
        yield owner
    server.close()


@pytest.fixture
def tmp_path(tmp_path_factory, request):
    return tmp_path_factory.mktemp(request.node.name.upper(), numbered=False)


def node(ops, title, **params):
    return create_engine_node(ops.store, ops.registry, title=title, engine="library.think",
        properties=params, authentication_context=ops.context)["root"]


def rows(ops, root):
    return {label: row["value"] for label, row in ops._rows(None, root).items()}


def test_ops_interface_element_is_persisted_and_validated(ops):
    made = ops.dispatch('add_interface_element', ['Button'])
    assert rows(ops, made['id'])['element'] == 'Button'
    revision = ops.store.revision
    with pytest.raises(CanvasRefused):
        ops.dispatch('add_interface_element', ['script'])
    assert ops.store.revision == revision


def test_ops_versions_restore_saved_content_without_appending_to_current_graph(ops):
    source = node(ops, 'Version source', prompt='Saved prompt')
    target = node(ops, 'Version target')
    ops._connect(source, target)
    ops.set_node_flags(source, frozen=True, pinned=True)
    version = ops.dispatch('save_graph_version', [])
    ops.set_property(source, 'prompt', 'Changed prompt')
    made = ops.dispatch('restore_graph_version', [version['id']])
    assert source not in {n['id'] for n in ops.canvas()['nodes']}
    assert any(rows(ops, root).get('prompt') == 'Saved prompt' for root in made['nodes'])
    restored = next(root for root in made['nodes'] if rows(ops, root).get('prompt') == 'Saved prompt')
    assert rows(ops, restored)['pinned'] == 'true' and rows(ops, restored)['frozen'] == 'true'
    assert len(made['wires']) == len(version['wires'])
    assert ops.project_state()['versions'][-1]['id'] == version['id']


def test_ops_community_toggle_and_judgement_use_existing_brain_owner(ops):
    from nodelang import cell_brain_community as community
    from nodelang.brain_community_sync import join
    peer = join(ops.store, 'ops-fixture')
    assert peer in community.subscriptions(ops.store.snapshot())
    ops.dispatch('subscribe_community', [peer])
    assert peer not in community.subscriptions(ops.store.snapshot())
    # An unsubscribed peer remains a real graph record and can be subscribed again.
    assert peer in {p['id'] for p in ops.community_state()['peers']}
    ops.dispatch('subscribe_community', [peer])
    incoming = community.receive(ops.store, peer_root=peer, claim='A reusable non-secret pattern')
    result = ops.dispatch('review_community_pattern', [incoming, 'Accept'])
    assert next(r for r in result['patterns'] if r['id'] == incoming)['status'] == 'Accepted'


def test_ops_research_decisions_require_captured_license_evidence(ops):
    from nodelang.social_research_community_backend import SocialResearchCommunityBackend
    backend = SocialResearchCommunityBackend(ops.store, ops.registry, ops.context)
    row = {'id': 'ops-source', 'title': 'LICENSE', 'source': 'fixture', 'sha256': 'captured',
           'summary': 'MIT License', 'transcript': ['MIT License'], 'status': 'Source read'}
    backend._record_source(row)
    with pytest.raises(ValueError, match='actual permissive'):
        backend.save_research_decision(row['id'], {'decision': 'Adopt', 'license': 'MIT', 'why': 'Reuse'})
    assert backend.check_research_license(row['id'])['licenseEvidence'] == ['MIT License']
    saved = backend.save_research_decision(row['id'], {'decision': 'Adopt', 'license': 'MIT', 'why': 'Reuse'})
    assert saved['decision'] == 'Adopt'
    assert 'requires reviewed work' in saved['status']
    revision = ops.store.revision
    with pytest.raises(ValueError, match='actual admitted'):
        backend.bind_research_work(row['id'], 'missing-work')
    assert ops.store.revision == revision


def test_ops_unconfigured_model_and_mcp_refuse_without_fabricating_results(ops):
    revision = ops.store.revision
    with pytest.raises(CanvasRefused, match='No model check has run'):
        ops.dispatch('review_model', ['Clash & Issues'])
    with pytest.raises(CanvasRefused, match='Connect the MCP server'):
        ops.dispatch('discover_mcp_tools', ['missing', 'Tools'])
    assert ops.store.revision == revision


def test_ops_mod_review_install_import_disable_remove_and_changed_package(ops, tmp_path, monkeypatch):
    import json
    from nodelang.domains.selfext import review_mod_package, install_mod_package, mods_rows, set_mod_enabled, remove_mod_package
    folder = tmp_path / 'PACKAGE'
    folder.mkdir()
    manifest = folder / 'manifest.json'
    content = {'name': 'Count rows', 'nodes': [{'title': 'Count', 'behavior': {'engine': 'shape.count'}, 'params': {}}]}
    manifest.write_text(json.dumps(content), encoding='utf-8')
    reviewed = review_mod_package(folder)
    manifest.write_text(json.dumps({**content, 'version': '2'}), encoding='utf-8')
    before = ops.store.revision
    with pytest.raises(ValueError, match='changed'):
        install_mod_package(ops.store, folder, reviewed_digest=reviewed['digest'])
    assert ops.store.revision == before
    reviewed = review_mod_package(folder)
    installed = install_mod_package(ops.store, folder, reviewed_digest=reviewed['digest'])
    assert installed['id'] == reviewed['id'] and installed['enabled']
    made = ops.import_mod_node(installed['id'], installed['nodes'][0]['id'])
    assert rows(ops, made['id'])['engine'] == 'shape.count'
    set_mod_enabled(ops.store, installed['id'], False)
    with pytest.raises(CanvasRefused, match='Enable'):
        ops.import_mod_node(installed['id'], installed['nodes'][0]['id'])
    set_mod_enabled(ops.store, installed['id'], True)
    assert remove_mod_package(ops.store, installed['id'])['removed']
    assert installed['id'] not in {r['id'] for r in mods_rows(ops.store)['rows']}
    # Removal is a state in the existing owner, so its manifest remains recoverable.
    assert any(reviewed['digest'].encode() in bytes(c.atom) for c in ops.store.snapshot().cells.values())
    original_read = Path.read_bytes
    def swap_after_read(path):
        raw = original_read(path)
        if path == manifest:
            manifest.write_text(json.dumps({**content, 'name': 'Swapped package'}), encoding='utf-8')
        return raw
    monkeypatch.setattr(Path, 'read_bytes', swap_after_read)
    receipt = review_mod_package(folder)
    assert receipt['name'] == 'Count rows'


def test_ops_socket_and_parameter_presentation_are_read_back_from_the_owner(ops):
    root = node(ops, 'Presentation', prompt='Actual input')
    port = next(n for n in ops.canvas()['nodes'] if n['id'] == root)['ports'][0]['id']
    ops.dispatch('set_port_visibility', [root, port, 'Faint'])
    ops.dispatch('set_promoted_parameter', [root, 'prompt', {'hidden': True, 'order': 2}])
    import json
    assert json.loads(rows(ops, root)['port_visibility'])[port] == 'Faint'
    assert json.loads(rows(ops, root)['parameter_presentation'])['prompt']['hidden']


def test_ops_compatible_add_uses_library_identity_and_creates_a_real_wire(ops):
    root = node(ops, 'Compatible source')
    port = next(p for n in ops.canvas()['nodes'] if n['id'] == root for p in n['ports'] if p['side'] == 'source')
    entry = next(r for r in ops.library_ports() if any(p['type'] != 'unknown' and
        (p['type'] == (port.get('value_type') or 'any') or 'any' in (p['type'], port.get('value_type') or 'any'))
        for p in r['ports']['target']))
    made = ops.add_compatible_node({'id': root, 'side': 'out', 'port': port['id']}, entry['id'], {'x': 600, 'y': 300})
    assert rows(ops, made['id'])['engine'] == entry['engine']
    assert any(w['id'] == made['wire'] and w['source'] == root and w['target'] == made['id'] for w in ops.canvas()['wires'])


def test_ops_convert_runs_actual_values_and_rolls_back_a_refused_second_connection(ops, monkeypatch):
    from nodelang.pipeline_engines import PIPELINE_ENGINES
    convert = PIPELINE_ENGINES['data.convert']
    assert convert({'target_type': 'number'}, {'in': '12.5'})[0] == {'out': 12.5}
    assert convert({'target_type': 'boolean'}, {'in': 'false'})[0] == {'out': False}
    with pytest.raises(ValueError, match='finite'):
        convert({'target_type': 'number'}, {'in': 'NaN'})
    source, target = node(ops, 'Rollback source'), node(ops, 'Rollback target')
    wire = ops._connect(source, target)
    connect = ops._connect
    calls = []
    def refuse_second(*args, **kwargs):
        calls.append(args)
        if len(calls) == 2:
            raise CanvasRefused('Target changed. Refresh Canvas.')
        return connect(*args, **kwargs)
    monkeypatch.setattr(ops, '_connect', refuse_second)
    before = {n['id'] for n in ops.canvas()['nodes']}
    with pytest.raises(CanvasRefused, match='Target changed'):
        ops.insert_convert(wire)
    after = ops.canvas()
    assert {n['id'] for n in after['nodes']} == before
    assert any(w['source'] == source and w['target'] == target for w in after['wires'])


def test_ops_file_nodes_hold_a_reference_without_copying_or_deleting_the_file(ops, tmp_path):
    path = tmp_path / 'SOURCE.md'
    path.write_text('Actual local content', encoding='utf-8')
    made = ops.dispatch('add_file', [str(path)])
    assert made['path'] == str(path.resolve())
    assert ops.dispatch('add_file', [str(path)])['id'] == made['id']
    from nodelang.universal_pipeline import retract_universal_node
    retract_universal_node(ops.store, ops.registry, made['id'], authentication_context=ops.context)
    assert path.read_text(encoding='utf-8') == 'Actual local content'
    assert made['id'] not in {r['id'] for r in ops.project_files()}


def test_ops_model_check_http_returns_the_actual_run_and_issue_edits_persist(ops):
    import json
    from urllib.request import Request, urlopen
    made = create_engine_node(ops.store, ops.registry, title='Naming Check', engine='data.constant',
        properties={'value': 'Actual check input'}, authentication_context=ops.context)['root']
    request = Request(ops.server.public_url + '/api/universal/canvas-op',
        data=json.dumps({'op': 'review_model', 'args': ['Naming Check']}).encode(), method='POST',
        headers={'Content-Type': 'application/json', 'X-ArchHub-Session': ops.server.browser_session_token,
                 'X-ArchHub-CSRF': ops.server.browser_csrf_token})
    with urlopen(request, timeout=30) as response:
        result = json.load(response)['result']
    assert result['modelReview']['operation'] == 'Naming Check'
    assert result['run']['ran'] == 1 and result['run']['outputs'][made]['value'] == 'Actual check input'
    record = ops.record_model_review('Naming Check', {'revision': ops.store.revision,
        'outputs': {made: {'issues': [{'title': 'Measured fixture issue', 'status': 'Open'}]}}})
    identity = record['modelReview']['issues'][0]['id']
    ops.update_review_issue(identity, {'severity': 'High', 'status': 'In review'})
    assert ops.project_state()['modelReview']['issues'][0]['severity'] == 'High'
    with pytest.raises(CanvasRefused):
        ops.update_review_issue(identity, {'status': 'Invented pass'})


def test_no_second_database_exists():
    import nodelang.canvas_graph_owner as module
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert "sqlite" not in source.lower()


def test_fork_copies_parameters_into_a_new_node_in_the_same_store(ops):
    a = node(ops, "Source", model="m-1")
    revision = ops.store.revision
    forked = ops.fork_node(a)["id"]
    assert forked != a and ops.store.revision > revision
    assert rows(ops, forked)["model"] == "m-1" and rows(ops, forked)["title"] == "Source copy"
    assert forked in {n["id"] for n in ops.canvas()["nodes"]}


def test_flags_are_properties_and_freeze_is_kept_out_of_run_to_here(ops):
    a, b = node(ops, "A"), node(ops, "B")
    ops._connect(a, b)
    assert ops.run_to_here(b)["roots"] == [a, b]
    ops.set_node_flags(a, frozen=True)
    assert rows(ops, a)["frozen"] == "true"
    assert ops.run_to_here(b) == {"roots": [b], "frozen_kept": [a]}
    ops.set_node_flags(a, frozen=False)
    assert ops.run_to_here(b)["roots"] == [a, b]


def test_insert_convert_replaces_the_wire_with_a_converter(ops):
    a, b = node(ops, "A"), node(ops, "B")
    wire = ops._connect(a, b)
    result = ops.insert_convert(wire)
    canvas = ops.canvas()
    pairs = {(w["source"], w["target"]) for w in canvas["wires"]}
    assert wire not in {w["id"] for w in canvas["wires"]}
    assert (a, result["converter"]) in pairs and (result["converter"], b) in pairs
    assert rows(ops, result["converter"])["engine"] == "data.convert"


def test_trace_both_directions(ops):
    a, b, c = node(ops, "A"), node(ops, "B"), node(ops, "C")
    ops._connect(a, b)
    ops._connect(b, c)
    assert [r["id"] for r in ops.trace_node(c, "back")] == [b, a]
    assert [r["id"] for r in ops.trace_node(a, "forward")] == [b, c]


def test_recurring_schedule_is_a_node_and_runs_once_a_day(ops):
    target = node(ops, "Report")
    schedule = ops.add_schedule(target, "08:00")["id"]
    assert rows(ops, schedule)["engine"] == "trigger.schedule"
    assert (schedule, target) in {(w["source"], w["target"]) for w in ops.canvas()["wires"]}
    early, later = datetime(2026, 10, 20, 7, 0), datetime(2026, 10, 20, 8, 5)
    assert schedule not in ops.due_schedules(early)
    assert schedule in ops.due_schedules(later)
    ops.mark_schedule_ran(schedule, later)
    assert schedule not in ops.due_schedules(later)
    assert schedule in ops.due_schedules(datetime(2026, 10, 21, 8, 5))
    ops.set_schedule_enabled(schedule, False)
    assert schedule not in ops.due_schedules(datetime(2026, 10, 21, 8, 5))
    ops.set_schedule_time(schedule, "09:30")
    assert rows(ops, schedule)["time"] == "09:30"
    ops.remove_schedule(schedule)
    assert schedule not in {n["id"] for n in ops.canvas()["nodes"]}
    with pytest.raises(CanvasRefused):
        ops.add_schedule(target, "25:99")


def test_one_schedule_can_repeat_a_workflow_with_multiple_outputs(ops):
    first, second = node(ops, 'First output'), node(ops, 'Second output')
    schedule = ops.add_schedule([first, second], '08:30')['id']
    wires = {(w['source'], w['target']) for w in ops.canvas()['wires']}
    assert (schedule, first) in wires and (schedule, second) in wires


def test_import_recipe_creates_nodes_and_wires_and_refuses_unknown_engines(ops):
    recipe = {"nodes": [{"engine": "library.think", "title": "R1"},
                        {"engine": "library.think", "title": "R2", "params": {"model": "x"}}],
              "wires": [[0, 1]]}
    made = ops.import_recipe(recipe)
    assert len(made["nodes"]) == 2 and len(made["wires"]) == 1
    assert rows(ops, made["nodes"][1])["model"] == "x"
    before = ops.store.revision
    with pytest.raises(CanvasRefused):
        ops.import_recipe({"nodes": [{"engine": "node-red.inject"}], "wires": []})
    with pytest.raises(CanvasRefused):
        ops.import_recipe({"nodes": [{"engine": "library.think"}] * 101, "wires": []})
    assert ops.store.revision == before


def test_yaml_recipe_parses_and_rejects_unsafe_or_invalid_yaml_before_writing(ops):
    imported = ops.import_recipe('nodes:\n  - engine: library.think\n    title: From YAML\nwires: []\n')
    assert rows(ops, imported['nodes'][0])['title'] == 'From YAML'
    before = ops.store.revision
    for invalid in ['nodes: [', '!!python/object/apply:os.system [echo BAD]',
                    'nodes: [{engine: library.think, params: []}]']:
        with pytest.raises(CanvasRefused):
            ops.import_recipe(invalid)
        assert ops.store.revision == before


def test_skill_is_saved_in_existing_library_and_reopened_as_real_nodes(ops):
    source = node(ops, 'Saved source', prompt='Retain this parameter')
    skill = ops.save_skill('My workflow')
    assert skill in ops.list_skills()
    assert any(n['params'].get('prompt') == 'Retain this parameter' for n in skill['recipe']['nodes'])
    opened = ops.open_skill(skill['id'])
    assert opened['nodes']
    assert source not in opened['nodes']
    assert any(rows(ops, root).get('prompt') == 'Retain this parameter' for root in opened['nodes'])


def test_scheduler_tick_calls_real_runner_and_only_marks_confirmed_runs(ops):
    target = node(ops, 'Tick target')
    schedule = ops.add_schedule(target, '08:00')['id']
    for row in ops.project_schedules():
        if row['id'] != schedule:
            ops.set_schedule_enabled(row['id'], False)
    now, calls = datetime(2026, 10, 22, 9, 0), []
    def pending(roots):
        calls.append(roots)
        return {'pending': {'task': 'approval'}, 'ran': 1}
    with pytest.raises(CanvasRefused, match='needs attention'):
        ops.tick_schedules(now, pending)
    assert schedule not in ops.due_schedules(now)
    assert rows(ops, schedule).get('last_run') != '2026-10-22'
    ops.set_schedule_enabled(schedule, True)
    def confirmed(roots):
        calls.append(roots)
        return {'pending': {}, 'ran': len(roots), 'results': {root: 'answer' for root in roots}}
    result = ops.tick_schedules(now, confirmed)
    assert schedule in {row['id'] for row in result}
    assert any(target in roots and schedule in roots for roots in calls)
    assert schedule not in ops.due_schedules(now)
    assert ops.tick_schedules(now, confirmed) == []


def test_graph_lifecycle_rename_pin_remove(ops):
    created = ops.add_graph("Second graph")
    graph = created["id"]
    updated = ops.update_graph(graph, name="Renamed", pinned=True)
    assert updated == {"id": graph, "name": "Renamed", "pinned": True}
    from nodelang.universal_graphs import project_graph_index
    listing = project_graph_index(ops.store, ops.registry, authentication_context=ops.context)
    assert next(row for row in listing["graphs"] if row["id"] == graph)["pinned"] is True
    ops.remove_graph(graph)
    assert graph not in {n["id"] for n in ops.canvas()["nodes"]}
    with pytest.raises(CanvasRefused):
        ops.remove_graph(ops.registry.canvas_root)


def test_failed_converter_creation_keeps_the_original_wire(ops, monkeypatch):
    import nodelang.canvas_graph_owner as module
    source, target = node(ops, "Failure source"), node(ops, "Failure target")
    wire = ops._connect(source, target)
    before = ops.store.revision
    def refuse(*args, **kwargs):
        raise CanvasRefused("Converter creation refused")
    monkeypatch.setattr(module, "create_engine_node", refuse)
    with pytest.raises(CanvasRefused, match="Converter creation refused"):
        ops.insert_convert(wire)
    assert wire in {row["id"] for row in ops.canvas()["wires"]}
    assert ops.store.revision == before


def test_canvas_operation_route_uses_the_selected_store_and_refuses_unknown_calls(ops):
    import json
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError
    source = node(ops, "HTTP source", model="original-model")
    def post(body):
        request = Request(ops.server.public_url + '/api/universal/canvas-op',
            data=json.dumps(body).encode(),headers={'Content-Type':'application/json',
            'X-ArchHub-Session':ops.server.browser_session_token,
            'X-ArchHub-CSRF':ops.server.browser_csrf_token},method='POST')
        with urlopen(request,timeout=20) as response:
            return json.load(response)
    result = post({'op':'fork_node','args':[source]})
    assert result['ok'] is True
    clone = result['result']['id']
    assert clone != source and rows(ops, clone)['model'] == 'original-model'
    before = ops.store.revision
    for body in ({'op':'reset','args':[]},{'op':'fork_node','args':[]},{'op':'fork_node','args':'bad'}):
        with pytest.raises(HTTPError) as refused:
            post(body)
        assert refused.value.code in (400,409)
        assert ops.store.revision == before


def test_http_scheduler_reuses_admitted_pipeline_and_does_not_replay(ops):
    import json
    from urllib.request import Request, urlopen
    target = create_engine_node(ops.store, ops.registry, title='Scheduled event',
        engine='trigger.emit', authentication_context=ops.context)['root']
    schedule = ops.add_schedule(target, '00:00')['id']
    # Hold other schedules created by earlier checks; this exercise owns this target only.
    for row in ops.project_schedules():
        if row['id'] != schedule:
            ops.set_schedule_enabled(row['id'], False)
    def tick():
        from urllib.error import HTTPError
        request = Request(ops.server.public_url + '/api/universal/canvas-op',
            data=json.dumps({'op':'scheduler_tick','args':[]}).encode(),
            headers={'Content-Type':'application/json',
                     'X-ArchHub-Session':ops.server.browser_session_token,
                     'X-ArchHub-CSRF':ops.server.browser_csrf_token},method='POST')
        try:
            with urlopen(request, timeout=30) as response:
                return json.load(response)
        except HTTPError as failure:
            return pytest.fail(failure.read().decode('utf-8'))
    first = tick()
    assert first['ok'] is True
    assert schedule in {row['id'] for row in first['result']}
    assert rows(ops, schedule)['last_run'] == datetime.now().strftime('%Y-%m-%d')
    assert tick()['result'] == []


def test_office_actions_use_existing_authenticated_company_owner_and_reject_invalid_targets(ops, monkeypatch):
    from nodelang import cloud_signin
    calls = []
    company = {'id':'office-1','name':'Test office','plan':'studio','seat_limit':2,
               'members':[{'user_id':'member-1','email':'member@example.test','role':'member'}]}
    monkeypatch.setattr(cloud_signin, 'read_cloud_session', lambda path: {'token':'fixture-session'})
    def cloud(method, url, *, body=None, headers=None):
        calls.append((method,url,body))
        assert headers and headers.get('Authorization')
        if url.endswith('/mine'):
            return 200, {'companies':[{'id':'office-1','is_current':True}]}
        if url.endswith('/seats'):
            company['seat_limit'] = body['seats']
        return 200, company.copy()
    monkeypatch.setattr(cloud_signin, 'http_json', cloud)
    assert ops.set_account_seats(3, 'office-1')['seat_limit'] == 3
    assert any(method=='POST' and url.endswith('/office-1/seats') and body=={'seats':3}
               for method,url,body in calls)
    before = len(calls)
    with pytest.raises(CanvasRefused):
        ops.set_account_seats(-1, 'office-1')
    assert len(calls) == before
    with pytest.raises(CanvasRefused, match='existing member'):
        ops.transfer_ownership('foreign-member', 'office-1')
    assert not any(url.endswith('/transfer-ownership') for _,url,_ in calls)
    ops.transfer_ownership('member-1', 'office-1')
    assert any(method=='POST' and url.endswith('/transfer-ownership') and body=={'new_owner_user_id':'member-1'}
               for method,url,body in calls)
    before = sum(method == 'POST' for method,_,_ in calls)
    with pytest.raises(CanvasRefused, match='selected office changed'):
        ops.set_account_seats(4, 'another-office')
    assert sum(method == 'POST' for method,_,_ in calls) == before
