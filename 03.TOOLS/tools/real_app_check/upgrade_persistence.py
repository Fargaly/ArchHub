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


def hosted_guest(app, evidence):
    import ctypes
    from ctypes import wintypes
    name = ctypes.create_unicode_buffer(257)
    size = wintypes.DWORD(len(name))
    if not ctypes.windll.advapi32.GetUserNameW(name, ctypes.byref(size)) or name.value.lower() != 'runneradmin':
        raise RuntimeError('Upgrade fixtures require the disposable Windows runner account.')
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


def plain_path(path):
    import stat
    if not path.is_absolute() or '..' in path.parts:
        raise RuntimeError('Unexpected relative guest path.')
    for part in (*reversed(path.parents), path):
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT):
            raise RuntimeError('Redirected guest path refused.')
    return path


def persisted_workshop_bindings(app, previous):
    import sqlite3
    from contextlib import closing

    tasks = previous['tasks']
    ids = [task['task_id'] for task in tasks]
    if len(ids) != 2 or ids[0] == ids[1]:
        raise ValueError('Invalid seeded Workshop task identities.')
    database = plain_path(app / 'workshop/messages.sqlite3')
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as db:
        bindings = dict(db.execute('SELECT id, session_path FROM workshop_tasks WHERE id IN (?, ?)', ids))
    for task in tasks:
        path = plain_path(Path(task['path']))
        if (not path.is_relative_to(Path.home()) or path.suffix != '.archhub'
                or bindings.get(task['task_id']) != str(path) or not path.is_file()):
            raise ValueError('Original Workshop task-to-file binding or file missing before owner reopen.')
    return bindings



def workshop_snapshot(app, run, previous=None):
    from nodelang import session_files, workshop_mailbox as mailbox, workshop_tasks as tasks

    sessions = session_files.sessions_directory().resolve()
    if (mailbox.profile_database().resolve() != app / 'workshop/messages.sqlite3'
            or not sessions.is_relative_to(Path.home().resolve())
            or not all(Path(module.__file__).resolve().is_relative_to(app) for module in (mailbox, tasks, session_files))):
        raise RuntimeError('Workshop witness requires the installed owners and disposable guest paths.')
    titles = ['Upgrade Workshop ' + run, 'Upgrade isolation ' + run]
    posts = [('QA author', 'Question ' + run), ('QA reviewer', 'Reply ' + run), ('QA control', 'Isolated ' + run)]
    with mailbox.application_history() as history:
        if previous is None:
            if any(row['title'] in titles for row in tasks.rows(history)):
                raise ValueError('Synthetic Workshop task already exists before seed.')
            ids = [tasks.create_session(history, title, 'QA author', select=False)['taskId'] for title in titles]
            message_ids = []
            for i, (author, text) in enumerate(posts):
                message = history.append(mailbox.ROOM, author=author, content=text, category=mailbox.CATEGORY,
                                         refs=[ids[1] if i == 2 else ids[0]], reply_to=message_ids[0] if i == 1 else None,
                                         reply_principal=author, idempotency_key='upgrade-' + run + '-' + str(i))
                message_ids.append(message['id'])
        else:
            ids = [task['task_id'] for task in previous['tasks']]
            message_ids = [m['id'] for task in previous['tasks'] for m in task['messages']]
        if len(set(ids)) != 2 or len(set(message_ids)) != 3:
            raise ValueError('Workshop fixture identities are not distinct.')
        result = []
        for i, task_id in enumerate(ids):
            row = tasks.get(history, task_id)
            if not row or row['title'] != titles[i] or not row.get('session_path'):
                raise ValueError('Workshop task or its attached session is missing.')
            path = Path(row['session_path']).resolve()
            if (not path.is_relative_to(sessions) or path.suffix != '.archhub' or not path.is_file()
                    or (previous and str(path) != previous['tasks'][i]['path'])):
                raise ValueError('The task no longer owns the same guest .archhub file.')
            view = tasks.open_session(history, task_id, select=False)
            doc = session_files.read_document(path)
            if (view['taskId'] != task_id or Path(view['path']).resolve() != path
                    or view['id'] != doc['id'] or doc['properties']['taskContext']['task'] != task_id):
                raise ValueError('Reopened Workshop session and attached document disagree.')
            indices = (2,) if i else (0, 1)
            thread = tasks._bound_messages(history, task_id)
            if [(m['id'], m['who'], m['text']) for m in thread] != [(message_ids[j], *posts[j]) for j in indices]:
                raise ValueError('Task thread lost, reordered or exposed messages from another task.')
            messages = []
            for j in indices:
                author, text = posts[j]
                m = history.get(mailbox.ROOM, message_ids[j], principal=author)
                if (not m or m['author'] != author or m['content'] != text or m['refs'] != [task_id]
                        or m['reply_to'] != (message_ids[0] if j == 1 else None)):
                    raise ValueError('Stored Workshop author, body, task reference or reply linkage differs.')
                messages.append({'id': m['id'], 'author': author, 'content': text, 'reply_to': m['reply_to']})
            result.append({'task_id': task_id, 'path': str(path), 'document_id': view['id'],
                           'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'messages': messages})
    if result[0]['path'] == result[1]['path'] or result[0]['document_id'] == result[1]['document_id']:
        raise ValueError('Separate Workshop tasks share the same session file.')
    observed = {'fixture': 'Synthetic guest Workshop threads', 'run': run, 'tasks': result}
    if previous is not None and previous != observed:
        raise ValueError('Workshop thread or attached file changed across the upgrade.')
    return observed


def main():
    phase, expected_build = sys.argv[1:]
    if (phase not in ('seed', 'verify') or os.name != 'nt' or os.environ.get('RUNNER_ENVIRONMENT') != 'github-hosted'
            or os.environ.get('GITHUB_ACTIONS') != 'true'):
        raise RuntimeError('Use the verify-published hosted Windows runner.')
    app = Path(os.environ['LOCALAPPDATA']) / 'ArchHub'
    evidence = Path(os.environ['VERIFY_EVIDENCE'])
    hosted_guest(app, evidence)
    if (Path(os.environ['RUNNER_TEMP']) != Path(r'D:\a\_temp')
            or evidence != Path(os.environ['RUNNER_TEMP']) / 'archhub-verify-published'
            or not plain_path(evidence).is_dir()):
        raise RuntimeError('Unexpected Windows runner evidence destination.')
    receipt = plain_path(evidence / ('upgrade-' + phase + '.json'))
    if receipt.exists():
        raise RuntimeError('Refusing to overwrite an existing upgrade receipt.')
    plain_path(app / 'BUILD_ID')
    plain_path(Path(sys.executable))
    for module in ('session_files', 'workshop_tasks', 'workshop_mailbox'):
        if not plain_path(app / 'nodelang' / (module + '.py')).is_file():
            raise RuntimeError('Expected installed application modules are missing.')
    if Path(sys.executable).resolve() != app / '.venv/Scripts/python.exe':
        raise RuntimeError('Run with the installed application interpreter.')
    if (app / 'BUILD_ID').read_text(encoding='utf-8').strip() != expected_build:
        raise RuntimeError('The installed build identity changed before the data check.')
    install_file = plain_path(evidence / ('previous-install.json' if phase == 'seed' else 'install.json'))
    install = json.loads(install_file.read_text(encoding='utf-8-sig'))
    if (install.get('setup_verified') is not True or install.get('install_exit') != 0
            or install.get('first_run_exit') != 0 or install.get('installed_build') != expected_build
            or Path(install.get('installed_root') or '') != app or not install.get('setup_sha256')
            or install['setup_sha256'] != install.get('expected_sha256')):
        raise RuntimeError('Missing verified Setup provenance for this guest phase.')
    record = {'phase': phase, 'build': expected_build, 'result': 'FAIL'}
    try:
        if phase == 'verify':
            seed = json.loads(plain_path(evidence / 'upgrade-seed.json').read_text(encoding='utf-8'))
            if seed['result'] != 'PASS' or seed['workshop']['run'] != os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']:
                raise ValueError('Missing matching hosted Workshop seed.')
            record['workshop_bindings_before_reopen'] = persisted_workshop_bindings(app, seed['workshop'])
        sys.path.insert(0, str(app))
        from nodelang import session_files
        if Path(session_files.__file__).resolve() != app / 'nodelang/session_files.py':
            raise RuntimeError('Unexpected installed session module.')
        state = session_files.profile_directory().resolve()
        if state != app:
            raise RuntimeError('Use the real installed package and its default user state.')
        run = os.environ['GITHUB_RUN_ID'] + '-' + os.environ['GITHUB_RUN_ATTEMPT']
        workspace = Path.home() / 'ArchHub' / ('Upgrade QA ' + run)
        document = session_files.sessions_directory() / ('upgrade-' + run + '.archhub')
        if os.environ.get('VERIFY_CONNECTORS', '').lower() == 'true':
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
        record['workshop'] = workshop_snapshot(app, run, None if phase == 'seed' else before['workshop'])
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
