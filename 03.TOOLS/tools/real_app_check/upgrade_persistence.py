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



STALE_CONNECTOR = b'# Synthetic hosted upgrade witness. No connector is started.\n'


def connector_guest(app, evidence):
    import ctypes
    from ctypes import wintypes
    name = ctypes.create_unicode_buffer(257)
    size = wintypes.DWORD(len(name))
    if not ctypes.windll.advapi32.GetUserNameW(name, ctypes.byref(size)) or name.value.lower() != 'runneradmin':
        raise RuntimeError('Connector fixtures require the disposable Windows runner account.')
    home = Path(r'C:\Users\runneradmin')
    if (os.environ.get('GITHUB_REPOSITORY', '').lower() != 'fargaly/archhub'
            or os.environ.get('RUNNER_OS') != 'Windows' or not sys.flags.isolated or not sys.dont_write_bytecode
            or Path.home() != home or app != home / 'AppData/Local/ArchHub'
            or evidence.resolve() != Path(os.environ['RUNNER_TEMP']).resolve() / 'archhub-verify-published'
            or any(os.environ.get(key) for key in ('CODEX_HOME', 'GEMINI_CLI_HOME', 'ARCHHUB_TEST_STATE_DIR', 'ARCHHUB_STATE_DIR'))):
        raise RuntimeError('Unexpected hosted guest profile or upgrade evidence location.')


def connector_snapshot(seed, app, run, before=None):
    import tempfile
    from nodelang import assistant_registration as registration
    from nodelang.client_mcp_installation import RUNTIME_FOLDER, _require_plain, base_python
    from nodelang.workshop_config import settings_target

    root, state = registration.install_roots()
    if root != app or state != app or not Path(registration.__file__).resolve().is_relative_to(app):
        raise RuntimeError('Connector evidence requires the installed registration owner.')
    home = Path.home()
    configs = {'codex': home / '.codex/config.toml', 'gemini': settings_target('gemini-cli', home=home)}
    if configs['gemini'] != home / '.gemini/settings.json':
        raise RuntimeError('Unexpected Gemini profile target.')
    runtime = state.parent / RUNTIME_FOLDER / 'mcp_supervisor.py'
    source = app / 'nodelang/mcp_supervisor.py'
    _require_plain(source, 'file')
    _require_plain(runtime, 'file', may_be_absent=seed)
    for path in configs.values():
        _require_plain(path, 'file', may_be_absent=seed)
    shipped = source.read_bytes()
    def digest(data):
        return hashlib.sha256(data).hexdigest()
    if seed:
        if any(p.exists() for p in configs.values()) or (runtime.exists() and runtime.read_bytes() != shipped):
            raise RuntimeError('Refusing to replace any pre-existing client config or unmanaged supervisor.')
        # The previous installed owner supplies its exact registered entries.
        # No credentials, actual vendor process, or network session are involved.
        codex = registration.codex_entry(root, state)
        gemini = registration.mcp_server_spec('gemini-cli')['add']
        texts = {'codex': registration._codex_block(codex),
                 'gemini': json.dumps({'mcpServers': gemini}, indent=2)}
        if str(runtime) not in codex['args'] or not any(str(runtime) in e['args'] for e in gemini.values()):
            raise RuntimeError('Previous Setup does not support the managed supervisor entry.')
        for vendor, path in configs.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open('x', encoding='utf-8') as stream:
                stream.write(texts[vendor])
        runtime.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=runtime.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(STALE_CONNECTOR)
        try:
            os.replace(temporary, runtime)
        finally:
            temporary.unlink(missing_ok=True)
    observed = runtime.read_bytes()
    records = {key: {'sha256': digest(path.read_bytes()), 'mtime_ns': path.stat().st_mtime_ns}
               for key, path in configs.items()}
    result = {'fixture': 'Synthetic enrolled Codex and Gemini records on a hosted Windows guest', 'run': run,
              'config_files': records, 'shipped_sha256': digest(shipped), 'runtime_sha256': digest(observed)}
    if seed:
        if observed != STALE_CONNECTOR or shipped == observed:
            raise ValueError('Missing distinct stale connector witness before upgrade.')
        return result
    if (not before or before['run'] != run or before['config_files'] != records
            or before['runtime_sha256'] != digest(STALE_CONNECTOR) or observed != shipped or observed == STALE_CONNECTOR):
        raise ValueError('Installed Setup or first-run failed to refresh the supervisor and preserve both client records.')

    # Exercise the installed readiness entry in a separate disposable profile,
    # leaving the upgraded runtime and its two client registrations in place.
    with tempfile.TemporaryDirectory(dir=os.environ['RUNNER_TEMP']) as temp:
        profile = Path(temp)
        scratch = profile / 'local/ArchHub'
        env = dict(USERPROFILE=temp, LOCALAPPDATA=str(scratch.parent), APPDATA=str(profile / 'roaming'),
                   CODEX_HOME=str(profile / '.codex'), ARCHHUB_TEST_STATE_DIR=str(scratch), PATH='')
        if registration.install_roots(env) != (app, scratch):
            raise RuntimeError('Readiness did not select the isolated state owner.')
        probe = scratch.parent / RUNTIME_FOLDER / runtime.name
        base = base_python(app)
        if base is None or not base.is_absolute() or base.resolve().is_relative_to(app):
            raise ValueError('Installed venv has no external base interpreter for the managed launch.')
        def inspect():
            clients = {row['client']: row for row in registration.readiness(environment=env)['clients']}
            for vendor in ('claude-code', 'codex'):
                row = clients[vendor]
                entry = row.get('entry') or {}
                if (row['state'] == 'install_incomplete' or entry.get('command') != str(base)
                        or entry.get('args') != ['-I', '-B', str(probe), str(app)]):
                    raise ValueError('Installed readiness did not return the usable ' + vendor + ' launch specification.')
        inspect()
        if probe.parent.exists():
            raise ValueError('Installed readiness created an absent supervisor directory.')
        probe.parent.mkdir(parents=True)
        probe.write_bytes(STALE_CONNECTOR)
        stamp = probe.stat().st_mtime_ns
        inspect()
        if probe.read_bytes() != STALE_CONNECTOR or probe.stat().st_mtime_ns != stamp:
            raise ValueError('Installed readiness replaced or touched the stale supervisor.')
    result['readiness'] = {'absent_remains_absent': True, 'stale_bytes_and_mtime_preserved': True,
                           'launch_specs_verified_in_both_states': ['claude-code', 'codex'], 'base_python': str(base)}
    return result


def verify_setup_observation(post, run, build, seeded, shipped):
    if (post['stage'] != 'after_native_setup_before_launcher_setup' or post['run'] != run
            or post['build'] != build or post['seeded_sha256'] != seeded
            or post['result'] != 'PASS' or post['runtime_sha256'] != shipped
            or post['shipped_sha256'] != shipped):
        raise ValueError('Native Setup refresh was not proved before the separate launcher setup call.')


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
        if os.environ.get('VERIFY_CONNECTORS', '').lower() == 'true':
            connector_guest(app, evidence)
            previous = None
            if phase == 'verify':
                seed = json.loads((evidence / 'upgrade-seed.json').read_text(encoding='utf-8'))
                if seed['result'] != 'PASS' or 'connectors' not in seed:
                    raise ValueError('Missing successful pre-upgrade connector evidence.')
                previous = seed['connectors']
            record['connectors'] = connector_snapshot(phase == 'seed', app, run, previous)
            if phase == 'verify':
                post = json.loads((evidence / 'upgrade-post-setup.json').read_text(encoding='utf-8-sig'))
                record['connectors']['after_native_setup'] = post
                record['connectors']['after_launcher_setup_sha256'] = record['connectors']['runtime_sha256']
                verify_setup_observation(post, run, expected_build, previous['runtime_sha256'],
                                         record['connectors']['shipped_sha256'])
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
