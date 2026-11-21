"""Windows guest PDF verification using the selected installation's isolated Python."""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch


def verify(install):
    from nodelang import clean_revit_adapter, enforce, library_engines, session_files, settings_owner

    from nodelang import canvas_tools, native_agent_mcp

    for module in (canvas_tools, native_agent_mcp, clean_revit_adapter, enforce, library_engines, session_files, settings_owner):
        assert Path(module.__file__).resolve().is_relative_to(install), module.__file__

    server = native_agent_mcp.build_server()

    def canvas(tool, **args):
        response = asyncio.run(server.call_tool(tool, args))
        if isinstance(response, tuple):
            result = response[1]
            return result.get('result', result)
        return json.loads(response[0].text)

    setting = "Projects.Sheet set"
    settings_owner.preference_settings('setAppearance', [setting, 'Office issue set'])
    for item_id in ('o_pdf', 'o_pdf_handoff'):
        pdf_root = Path(os.environ['ARCHHUB_TEST_STATE_DIR']) / 'pdf'
        requested_folder = pdf_root / item_id
        assert not pdf_root.exists() and not requested_folder.exists()
        path = str(session_files.sessions_directory() / (item_id + '.archhub'))
        canvas('canvas.new', path=path, title=item_id)
        pdf = canvas('canvas.add_node', path=path, type=item_id)['node']
        canvas('canvas.set_param', path=path, node=pdf, key='folder', value=str(requested_folder))
        session_files.SessionFiles().dispatch({'action': 'open', 'path': str(path)})
        scope = settings_owner.preference_scope(None)
        scope.select('Session', expected=session_files.read_document(path)['id'])
        settings_owner.preference_scope(None).change({setting: 'Current sheet only'})
        reopened = session_files.read_document(path)
        assert session_files.resolve_setting(reopened, setting) == {'scope': 'session', 'value': 'Current sheet only'}
        assert settings_owner.preference_setting(setting)['value'] == 'Office issue set'
        pdf_node = next(node for node in reopened['nodes'] if node['id'] == pdf)
        assert pdf_node['item'] == item_id and pdf_node['params']['sheet_set'] == 'From Projects'
        assert pdf_node['params']['folder'] == str(requested_folder)

        observed = []
        def invoke(engine, effect, params, feeds):
            if engine == 'library.publish_pdf':
                observed.append(feeds.get('sheet_set'))
            return enforce.guard_effect(engine, effect, params, feeds)

        with patch.object(clean_revit_adapter, '_execute', side_effect=AssertionError('Unexpected Revit call')) as host:
            with patch.object(clean_revit_adapter, 'sole_session', return_value=(None, 'No QA host')) as discovery:
                result = session_files.run_document(reopened, invoke=invoke)['results'][pdf]
                assert observed == ['Current sheet only'] and result['display'] == 'No QA host', result
                discovery.assert_called_once_with()
            with patch.object(clean_revit_adapter, 'sole_session', side_effect=AssertionError('Unexpected discovery')) as discovery:
                for value in ('', [], '[null]'):
                    session_files.write_document(path, reopened)
                    kind = 'list' if isinstance(value, list) else 'text'
                    source = canvas('canvas.add_node', path=path, type='param.value',
                                    params={'type': kind})['node']
                    canvas('canvas.set_param', path=path, node=source, key='value',
                           value=json.dumps(value) if kind == 'list' else value)
                    canvas('canvas.wire', path=path, source=source + '.value', target=pdf + '.sheets')
                    results = session_files.run_document(session_files.read_document(path), invoke=invoke)['results']
                    result = results[pdf]
                    assert results[source]['output']['value'] == value, results
                    # The exporter appends a timestamp and run ID under this same root.
                    assert not requested_folder.exists() and not pdf_root.exists(), (item_id, value, pdf_root)
                    assert result['output'] == {'out': []} and 'select' in result['display'].lower(), result
                discovery.assert_not_called()
            host.assert_not_called()
        print('PASS', item_id, 'session setting reopened, PDF input resolved, invalid wires stopped before host discovery.')


if __name__ == '__main__':
    install = Path(sys.executable).resolve().parents[2]
    assert sys.flags.isolated and sys.dont_write_bytecode and not sys.flags.optimize
    build = (install / 'BUILD_ID').read_text().strip()
    assert build == os.environ['PUBLISHED_BUILD'], build
    sys.path.insert(0, str(install))
    with tempfile.TemporaryDirectory(prefix='archhub-installed-pdf-') as temp:
        for key in ('USERPROFILE', 'HOME', 'LOCALAPPDATA', 'APPDATA', 'ARCHHUB_TEST_STATE_DIR'):
            folder = Path(temp) / key
            folder.mkdir()
            os.environ[key] = str(folder)
        verify(install)
    print('BUILD', build, '| signed-in UI and disposable-model Revit export unexercised')
