"""Seed or verify synthetic user data across two official installs on one hosted Windows runner."""
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace


THEME = 'Appearance.Theme'
THEME_VALUES = {'User': 'Light', 'Workspace': 'Dark', 'Session': 'System'}


def snapshot(seed, run, workspace, document_path, state):
    from nodelang import session_files, settings_owner
    from nodelang.nograph_server import JsonFile, NoGraphServer, r_workspace_roots

    scope_owner = getattr(settings_owner, 'PreferenceScope', None)
    if not seed and scope_owner is None:
        raise ValueError('The upgraded Settings owner must support full scope readback.')
    files = {'settings': JsonFile(state / 'settings/settings.json', {}),
             'workspaces': JsonFile(state / 'settings/workspaces.json', {'roots': []})}
    owner = SimpleNamespace(files=files, workspace_built_in=NoGraphServer.workspace_built_in)

    def roots(action, **args):
        return r_workspace_roots(owner, SimpleNamespace(body={'action': action, **args}))

    if seed:
        if document_path.exists() or workspace.exists():
            raise ValueError('Upgrade fixture already exists before the first installation witness.')
        workspace.mkdir(parents=True)
        registered = roots('register', path=str(workspace), privacy='private')['root']
        doc = session_files.new_document('Upgrade verification ' + run)
        doc['properties']['project'] = registered['root_id']
        doc['nodes'].append({'id': 'upgrade-note', 'type': 'note', 'params': {'text': run},
                             'position': {'x': 80, 'y': 120}})
        sessions = session_files.SessionFiles()
        session_files.write_document(document_path, doc)
        sessions.dispatch({'action': 'open', 'path': str(document_path)})
        owners = (files['settings'], files['workspaces'], str(document_path))
        if scope_owner is None:
            settings_owner.appearance_settings('setAppearance', [THEME, THEME_VALUES['User']], settings=files['settings'])
        else:
            for scope, value in THEME_VALUES.items():
                scope_owner(*owners).select(scope, registered['root_id'], doc['id'])
                scope_owner(*owners).change({THEME: value})

    doc = session_files.read_document(document_path)
    matches = [row for row in roots('list')['roots'] if Path(row['path']) == workspace]
    if len(matches) != 1 or matches[0]['root_id'] != doc['properties'].get('project') or not matches[0]['available']:
        raise ValueError('The saved workflow and registered workspace no longer match.')
    if not any(node['type'] == 'note' and node['params'].get('text') == run for node in doc['nodes']):
        raise ValueError('The user-created workflow note was lost.')
    if scope_owner is None:
        rows = settings_owner.appearance_settings(settings=files['settings'])['appearanceSettings']
        theme = next(row for row in rows if row['id'] == THEME)
        values = {'User': theme['value'] if theme['overridden'] else None, 'Workspace': None, 'Session': None}
    else:
        maps = scope_owner(files['settings'], files['workspaces'], str(document_path)).maps()
        values = {scope: maps[scope].get(THEME) for scope in THEME_VALUES}
    return {'document': str(document_path), 'document_id': doc['id'],
            'document_sha256': hashlib.sha256(document_path.read_bytes()).hexdigest(),
            'workspace': str(workspace), 'workspace_id': matches[0]['root_id'],
            'privacy': matches[0]['privacy'], 'setting': THEME, 'values': values, 'state': str(state)}, scope_owner is not None


def main():
    phase, expected_build = sys.argv[1:]
    if (phase not in ('seed', 'verify') or os.name != 'nt' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or os.environ.get('GITHUB_ACTIONS') != 'true'):
        raise RuntimeError('Use the verify-published hosted Windows runner.')
    app = (Path(os.environ['LOCALAPPDATA']) / 'ArchHub').resolve()
    if Path(sys.executable).resolve() != app / '.venv/Scripts/python.exe':
        raise RuntimeError('Run with the installed application interpreter.')
    if (app / 'BUILD_ID').read_text(encoding='utf-8').strip() != expected_build:
        raise RuntimeError('The installed build identity changed before the data check.')
    sys.path.insert(0, str(app))
    from nodelang import session_files
    state = session_files.profile_directory().resolve()
    if state != app or not Path(session_files.__file__).resolve().is_relative_to(app):
        raise RuntimeError('Use the real installed package and its default user state.')
    run = os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
    workspace = Path.home() / 'ArchHub' / ('Upgrade QA ' + run)
    document = session_files.sessions_directory() / ('upgrade-' + run + '.archhub')
    evidence = Path(os.environ['VERIFY_EVIDENCE'])
    receipt = evidence / ('upgrade-' + phase + '.json')
    record = {'phase': phase, 'build': expected_build, 'result': 'FAIL'}
    try:
        data, scoped = snapshot(phase == 'seed', run, workspace, document, state)
        record['snapshot'] = data
        if data['privacy'] != 'private':
            raise ValueError('The registered workspace privacy differs.')
        if phase == 'seed':
            expected = THEME_VALUES if scoped else {'User': 'Light', 'Workspace': None, 'Session': None}
            if data['values'] != expected:
                raise ValueError('The installed Settings owner did not seed the expected overrides.')
        else:
            before = json.loads((evidence / 'upgrade-seed.json').read_text(encoding='utf-8'))
            if before['result'] != 'PASS' or before['snapshot'] != data:
                raise ValueError('Installed owner readback differs from the pre-upgrade evidence.')
        record['preference_checks'] = {scope: 'PASS' if value is not None else 'NOT EXERCISED'
                                       for scope, value in data['values'].items()}
        record['result'] = 'PASS'
    except Exception as exc:
        record['error'] = str(exc)
        raise
    finally:
        receipt.write_text(json.dumps(record, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
