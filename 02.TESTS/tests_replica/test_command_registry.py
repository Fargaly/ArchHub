"""One action catalogue; no live profile or host is opened by these courts."""
import sys
import asyncio
import json
import subprocess
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / '01.APP'))


def test_registry_contexts_and_read_only():
    from nodelang.command_registry import commands_for_context, payload
    data = payload()
    assert data['commands']
    assert len({row['id'] for row in data['commands']}) == len(data['commands'])
    for row in data['commands']:
        assert {'id', 'label', 'group', 'contexts', 'action', 'effect', 'approve',
                'agent_callable', 'read_only', 'operation', 'enabled_when'} <= row.keys()
    for context in data['contexts']:
        assert all(row['read_only'] for row in commands_for_context(context, {'readOnly': True}))
    assert all(row['group'] in data['groups'] for row in data['commands'])
    assert all(set(row['contexts']) <= set(data['contexts']) for row in data['commands'])
    assert all(row['operation'] in ('search', 'read', 'write', 'delete') for row in data['commands'])
    assert all(not row['enabled_when'] or row['enabled_when']['reason'] for row in data['commands'])
    assert all('params' not in row and 'defaults' not in row for row in data['commands'])
    output = Path(__file__).resolve().parents[2] / '.cache' / 'testiso-commandregistry'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'commands.json').write_text(json.dumps(data), encoding='utf-8')
    print('REGISTRY contexts: ' + json.dumps({context: len(commands_for_context(context)) for context in data['contexts']}))


def test_agent_tools_come_from_registry():
    from nodelang.command_registry import agent_commands
    from nodelang.native_agent_mcp import build_server
    full = build_server(mailbox_call=lambda *args, **kwargs: {})
    readonly = build_server(mailbox_call=lambda *args, **kwargs: {}, read_only=True)
    rows = agent_commands()
    assert {row['action']['tool'] for row in rows} == {tool.name for tool in full._tool_manager.list_tools()}
    assert {row['action']['tool'] for row in rows if row['read_only']} == {
        tool.name for tool in readonly._tool_manager.list_tools()}
    assert all(row['approve'] for row in rows if row['effect'])


def test_every_preexisting_agent_tool_keeps_its_schema_and_callable():
    from nodelang.native_agent_mcp import build_server
    source = subprocess.check_output(['git', 'show', 'e100ce93:01.APP/nodelang/native_agent_mcp.py'],
                                     text=True, stdin=subprocess.DEVNULL, stderr=subprocess.PIPE)
    baseline = types.ModuleType('nodelang._command_registry_baseline')
    baseline.__file__ = str(Path(__file__).resolve().parents[2] / '01.APP/nodelang/native_agent_mcp.py')
    exec(compile(source, baseline.__file__, 'exec'), baseline.__dict__)
    before = baseline.build_server(mailbox_call=lambda *args, **kwargs: {})
    after = build_server(mailbox_call=lambda *args, **kwargs: {})
    previous = {tool.name: tool for tool in before._tool_manager.list_tools()}
    current = {tool.name: tool for tool in after._tool_manager.list_tools()}
    assert previous.keys() <= current.keys()
    assert current.keys() - previous.keys() <= {'social.whatsapp_messages', 'max_render_view', 'rhino_bake_geometry', 'blender_render_scene'}
    grown_optional = {
        'declare': {'continue_task'},
        'task.create': {'parent', 'canvas_task', 'piece', 'continue_task', 'intent'},
        'task.release': {'reason', 'handover'},
        'task.set_session': {'begin_write', 'reconcile', 'acceptance', 'handover'},
    }
    for tool_name, added_keys in grown_optional.items():
        prior_schema = previous.pop(tool_name).parameters
        now_schema = current[tool_name].parameters
        kept_prior = {k: v for k, v in prior_schema['properties'].items() if k not in added_keys}
        kept_now = {k: v for k, v in now_schema['properties'].items() if k not in added_keys}
        assert kept_now == kept_prior, tool_name
        assert now_schema.get('required', []) == prior_schema.get('required', []), tool_name
        assert not (added_keys & set(now_schema.get('required', []))), tool_name
    now = current['task.create'].parameters
    assert now['properties']['parent'] == {'default': '', 'title': 'Parent', 'type': 'string'}
    assert 'parent' not in now.get('required', [])
    sent = []
    recording = build_server(mailbox_call=lambda method, body, context, **kwargs: sent.append((method, body, context)) or {})
    create = recording._tool_manager.get_tool('task.create').fn
    meta = types.SimpleNamespace(model_dump=lambda **kwargs: {'claude/sessionID': 'registry-test'})
    ctx = types.SimpleNamespace(request_context=types.SimpleNamespace(meta=meta))
    create(title='Tower drawings', ctx=ctx)
    create(title='Sections', ctx=ctx, parent='abc123')
    who = {'claude/sessionID': 'registry-test'}
    assert sent == [('task_create', {'title': 'Tower drawings'}, who), ('task_create', {'title': 'Sections', 'parent': 'abc123'}, who)]
    for name, tool in previous.items():
        assert current[name].parameters == tool.parameters, name
        assert current[name].description == tool.description, name
        assert current[name].fn.__code__.co_code == tool.fn.__code__.co_code, name
    print('MAPPED existing agent tools: ' + str(len(previous)) + '; unmapped: 0')


def test_read_only_refuses_hidden_calls_and_write_dispatch_keeps_permission(monkeypatch):
    from nodelang.native_agent_mcp import build_server
    from nodelang import native_host_tools
    from mcp.server.fastmcp.exceptions import ToolError
    import pytest
    calls = []
    monkeypatch.setattr(native_host_tools, '_broker', lambda *args, **kwargs: calls.append(args))
    readonly = build_server(mailbox_call=lambda *args, **kwargs: {}, read_only=True)
    with pytest.raises(ToolError, match='Unknown tool'):
        asyncio.run(readonly.call_tool('revit_execute_csharp', {'code': 'result=1;'}))
    full = build_server(mailbox_call=lambda *args, **kwargs: {})
    with pytest.raises(ToolError, match='permission is disabled'):
        asyncio.run(full.call_tool('revit_execute_csharp', {'code': 'result=1;'}))
    assert not calls
    monkeypatch.setenv('ARCHHUB_CONNECTOR_TOOLS', 'library.')
    scoped = build_server(mailbox_call=lambda *args, **kwargs: {})
    assert {tool.name for tool in scoped._tool_manager.list_tools()} == {'library.search'}
    with pytest.raises(ToolError, match='Unknown tool'):
        asyncio.run(scoped.call_tool('revit_open_document', {'path': 'synthetic.rvt'}))


def test_served_registry_is_the_same_owner(tmp_path):
    from nodelang.nograph_server import NoGraphServer
    from nodelang.command_registry import payload
    import urllib.request
    server = NoGraphServer(tmp_path / 'server')
    try:
        import threading
        server.thread = threading.Thread(target=server.httpd.serve_forever, daemon=True)
        server.thread.start()
        request = urllib.request.Request(server.public_url + '/api/commands', headers={
            'X-ArchHub-Session': server.browser_session_token, 'X-ArchHub-CSRF': server.browser_csrf_token})
        with urllib.request.urlopen(request, timeout=10) as response:
            assert json.load(response) == payload()
    finally:
        server.close()


def test_agent_host_effect_stops_at_existing_approve_card(monkeypatch):
    from nodelang.native_agent_mcp import build_server
    from nodelang import native_host_tools
    calls = []
    monkeypatch.setattr(native_host_tools, '_allow_effect', lambda host: None)
    monkeypatch.setattr(native_host_tools, '_broker', lambda *args, **kwargs: calls.append(args) or {'ok': True})
    server = build_server(mailbox_call=lambda *args, **kwargs: {})
    answer = asyncio.run(server.call_tool('revit_open_document', {'path': 'synthetic.rvt'}))
    value = answer[1] if isinstance(answer, tuple) else json.loads(answer[0].text)
    assert value['approvalId']
    assert value['status'] == 'Waiting for approval'
    assert not calls
    from nodelang.hook_decision import ask_reviews, ask_apply
    import pytest
    from mcp.server.fastmcp.exceptions import ToolError
    before = [row['id'] for row in ask_reviews()]
    with pytest.raises(ToolError, match='Extra inputs are not permitted'):
        asyncio.run(server.call_tool('revit_open_document', {'path': 'synthetic.rvt', 'invented': True}))
    assert [row['id'] for row in ask_reviews()] == before and not calls
    card = next(row for row in ask_reviews() if row['id'] == value['approvalId'])
    approved = ask_apply(card['id'], card['input_digest'], 'approve', decided_by='isolated test')
    assert approved['status'] == 'approved'
    assert len(calls) == 1 and calls[0][:2] == ('revit', '/open')
    assert calls[0][2]['path'] == 'synthetic.rvt'
    again = ask_apply(card['id'], card['input_digest'], 'approve', decided_by='isolated test')
    assert again['status'] == 'approved' and len(calls) == 1


def test_approval_replays_the_original_tool_not_a_parallel_engine_adapter(monkeypatch):
    from nodelang import native_host_tools
    from nodelang.native_agent_mcp import build_server
    from nodelang.hook_decision import ask_reviews, ask_apply
    calls = []
    def register(server):
        @server.tool(name='revit_open_document')
        def original(path: str, activate: bool = True, view: str | None = None, port: int | None = None) -> dict:
            calls.append((path, activate, view, port))
            return {'ok': True, 'original': True}
    monkeypatch.setattr(native_host_tools, 'register_host_tools', register)
    monkeypatch.setattr(native_host_tools, '_allow_effect', lambda host: None)
    monkeypatch.setattr(native_host_tools, '_broker', lambda *args, **kwargs: {'ok': True})
    server = build_server(mailbox_call=lambda *args, **kwargs: {})
    answer = asyncio.run(server.call_tool('revit_open_document', {'path': 'original.rvt', 'activate': False}))
    value = answer[1] if isinstance(answer, tuple) else json.loads(answer[0].text)
    assert value['approvalId'] and not calls
    card = next(row for row in ask_reviews() if row['id'] == value['approvalId'])
    ask_apply(card['id'], card['input_digest'], 'approve', decided_by='isolated test')
    assert calls == [('original.rvt', False, None, None)]


def test_approved_replay_has_no_direct_call_bypass():
    from nodelang.command_registry import invoke_approved
    import pytest
    with pytest.raises(ValueError, match='Approve this action first'):
        invoke_approved('revit_open_document', {'path': 'synthetic.rvt'})


def test_group_context_keeps_every_former_frame_command():
    from nodelang.command_registry import commands_for_context, payload
    data = payload()
    expected = {'menu.rename.25', 'menu.colour', 'menu.select.contents', 'menu.remove.frame.keep.nodes',
                'menu.group.freeze', 'menu.group.bypass', 'menu.group.arrange'}
    embed_expected = {'menu.open', 'menu.embed.run', 'menu.embed.update', 'menu.embed.tab',
                      'menu.rename.25', 'menu.colour', 'menu.embed.detach', 'menu.delete.50'}
    assert 'frame' not in data['contexts']
    assert 'embed' in data['contexts']
    assert all('frame' not in row['contexts'] for row in data['commands'])
    assert expected <= {row['id'] for row in commands_for_context('group')}
    assert embed_expected <= {row['id'] for row in commands_for_context('embed')}
    assert len({row['id'] for row in data['commands']}) == len(data['commands'])


def test_the_doors_that_left_the_library_shelf_are_command_list_rows():
    """MCP tools and Share session: one row each, naming the Studio action it runs (run in command_registry.test.cjs)."""
    from nodelang.command_registry import commands_for_context
    rows = {row['id']: row for row in commands_for_context('palette')}
    tools, share = rows['palette.mcp_tools'], rows['palette.share_session']
    assert (tools['label'], tools['action'], tools['paletteGroup']) == (
        'MCP tools', {'client': 'projects.ds_library.MCPTools.10'}, 'Hosts')
    assert (share['label'], share['action'], share['paletteGroup']) == (
        'Share session', {'client': 'projects.ds_library.ExportRecipe.8'}, 'Workflows')
    assert tools['enabled'] and share['enabled']
    # Looking is allowed in a read-only selection; writing a copy of the session is not.
    read_only = {row['id'] for row in commands_for_context('palette', {'readOnly': True})}
    assert 'palette.mcp_tools' in read_only and 'palette.share_session' not in read_only
