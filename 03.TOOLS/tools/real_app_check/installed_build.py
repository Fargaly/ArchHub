"""Install a built release the way a colleague gets it, into an isolated temp profile.

The release gate's installed-build mode. It compiles the release's OWN
installer script (source/selected/installer/ArchHub.iss) and payload with
every per-user location redirected into ``<work>/profile``, runs it silently,
runs the first-open setup (colleague_setup.py: the private venv from the
release wheelhouse), then checks the installed nodelang files byte-for-byte
against the release's source manifest. The gate then boots that installed
folder with its own venv python.

Never touches %LOCALAPPDATA%\\ArchHub, the Start menu, the Desktop, the Apps &
Features entry, scheduled tasks or host add-in folders: those constants are
rewritten into the temp profile, the AppId is the gate's own and no uninstall
key is written. Shortcut: the compiled setup is not byte-identical to the
shipped ArchHub-Setup-0.exe (paths and compression differ); the payload is,
and the manifest check proves it. Upgrade to the shipped exe once Windows
Sandbox or a second Windows account is available to the rig.

Usage: python -m tools.real_app_check.installed_build <release> <work> --python <py3.14>
       python -m tools.real_app_check.installed_build --clean <work>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

ISCC = Path(os.environ.get('ProgramFiles(x86)', r'C:\Program Files (x86)')) / 'Inno Setup 6' / 'ISCC.exe'
GATE_APP_ID = '{{9E1C55A2-0C1B-4C55-9F7A-C0C47A11E9A1}'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
# The installed-build gate node: its typed parameters.
GATE_NODE = {'id': 'release.installed_build', 'params': {'step_timeout_seconds': 1800}}


def profile_dirs(work: Path) -> dict:
    base = work / 'profile'
    dirs = {'LOCALAPPDATA': base / 'Local', 'APPDATA': base / 'Roaming', 'USERPROFILE': base / 'Home',
            'TEMP': base / 'Temp', 'SHELL': base / 'Shell'}
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def isolated_env(dirs: dict) -> dict:
    env = dict(os.environ)
    env.update(LOCALAPPDATA=str(dirs['LOCALAPPDATA']), APPDATA=str(dirs['APPDATA']),
               USERPROFILE=str(dirs['USERPROFILE']), HOME=str(dirs['USERPROFILE']),
               TEMP=str(dirs['TEMP']), TMP=str(dirs['TEMP']), PYTHONDONTWRITEBYTECODE='1')
    for name in ('ARCHHUB_STATE_DIR', 'ARCHHUB_TEST_STATE_DIR', 'PYTHONPATH', 'PYTHONHOME'):
        env.pop(name, None)
    return env


def _redirect(text: str, dirs: dict) -> str:
    text = text.replace('\r\n', '\n')
    for constant, target in (('{localappdata}', dirs['LOCALAPPDATA']), ('{userappdata}', dirs['APPDATA']),
                             ('{autodesktop}', dirs['SHELL'] / 'Desktop'), ('{group}', dirs['SHELL'] / 'StartMenu')):
        text = text.replace(constant, str(target))
    return text


def isolated_script(text: str, installer_dir: Path, dirs: dict, python: str, work: Path) -> str:
    """The release's own ArchHub.iss (and its includes) with every user-global effect in the temp profile."""
    text = _redirect(text, dirs)
    find = re.search(r'function FindPython\(\): String;\nbegin\n.*?\nend;\n', text, re.S)
    if find is None:
        raise ValueError('installer script has no FindPython to pin')
    text = text.replace(find.group(0),
        "function FindPython(): String;\nbegin\n  Result := '%s';\nend;\n" % python.replace("'", "''"))
    # The retired-task sweep runs schtasks against the real account; the gate never does.
    text = re.sub(r'^\s*RemoveRetiredRuntimeTask\((CleanCoordinationTask|UniversalRuntimeTask)\);\n', '', text, flags=re.M)
    text = re.sub(r'^AppId=.*$', lambda _match: 'AppId=' + GATE_APP_ID, text, count=1, flags=re.M)
    text = re.sub(r'^Compression=.*$', 'Compression=none', text, count=1, flags=re.M)
    text = re.sub(r'^SolidCompression=.*$', 'SolidCompression=no', text, count=1, flags=re.M)
    setup = '[Setup]\nSourceDir=%s\nCreateUninstallRegKey=no\nUsePreviousAppDir=no\n' % installer_dir
    text = re.sub(r'^\[Setup\]\n', lambda _match: setup, text, count=1, flags=re.M)
    def includes(source):  # nested includes too (legacy_sweep.iss includes legacy_v1_files.iss)
        return re.sub(r'^#include "([^"]+)"', included, source, flags=re.M)

    def included(match):
        target = work / match.group(1)
        target.write_text(includes(_redirect((installer_dir / match.group(1)).read_text(encoding='utf-8'), dirs)),
                          encoding='utf-8-sig')
        return '#include "%s"' % target
    text = includes(text)
    every = text + ''.join(path.read_text(encoding='utf-8-sig') for path in work.glob('*.iss'))
    leftover = re.findall(r'\{(localappdata|userappdata|autodesktop|group|commondesktop|userstartup)\}', every)
    if leftover or 'RemoveRetiredRuntimeTask(C' in text or 'RemoveRetiredRuntimeTask(U' in text:
        raise ValueError('installer script still reaches the real account: %s' % sorted(set(leftover)))
    return text


def manifest_check(release: Path, app: Path) -> dict:
    """Installed nodelang files against the release's source manifest (sha256)."""
    rows = [line.split('\t') for line in (release / 'source-manifest.tsv').read_text(encoding='utf-8').splitlines()]
    checked, mismatched = 0, []
    for row in rows:
        if len(row) != 4 or row[0] != 'selected' or not row[1].startswith('nodelang/'):
            continue
        installed = app / row[1]
        checked += 1
        if not installed.is_file() or hashlib.sha256(installed.read_bytes()).hexdigest() != row[3]:
            mismatched.append(row[1])
    return {'checked': checked, 'mismatched': mismatched[:20], 'ok': checked > 0 and not mismatched}


def install(release: Path, work: Path, python: str) -> dict:
    release, work = release.resolve(), work.resolve()
    started = time.time_ns()
    meta = json.loads((release / 'release.json').read_text(encoding='utf-8'))
    selected = release / 'source' / 'selected'
    installer_dir = selected / 'installer'
    dirs = profile_dirs(work)
    script = work / 'ArchHub.isolated.iss'
    script.write_text(isolated_script((installer_dir / 'ArchHub.iss').read_text(encoding='utf-8'), installer_dir, dirs,
                                      python, work), encoding='utf-8-sig')
    requirements = hashlib.sha256((selected / 'requirements.txt').read_bytes()).hexdigest()
    node = shutil.which('node.exe') or shutil.which('node')
    defines = {'BuildId': meta['build_id'], 'RequirementsSha256': requirements,
               'BuildMetadataPath': release / 'BUILD_METADATA.json', 'NodeRuntimePath': node,
               'NodeLicensePath': selected / 'packaging/windows/licenses/Node-v24.13.0-LICENSE.txt',
               'GoosePayloadPath': release / 'goose-payload', 'CompilerPayloadPath': selected / 'runtime/acompiler',
               'WheelhousePath': release / 'wheelhouse', 'HostPayloadPath': release / 'hostpayload'}
    out = work / 'setup'
    compiled = subprocess.run([str(ISCC), '/Qp', *('/D%s=%s' % item for item in defines.items()), '/O' + str(out), str(script)],
                              capture_output=True, text=True, timeout=GATE_NODE['params']['step_timeout_seconds'], creationflags=NO_WINDOW)
    if compiled.returncode:
        raise RuntimeError('ISCC failed: ' + (compiled.stdout + compiled.stderr)[-1500:])
    setup = next(out.glob('*.exe'))
    env = isolated_env(dirs)
    ran = subprocess.run([str(setup), '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/NOCLOSEAPPLICATIONS',
                          '/NORESTARTAPPLICATIONS', '/TASKS=', '/LOG=' + str(work / 'setup.log')],
                         env=env, capture_output=True, timeout=GATE_NODE['params']['step_timeout_seconds'], creationflags=NO_WINDOW)
    app = dirs['LOCALAPPDATA'] / 'ArchHub'
    build_id = (app / 'BUILD_ID').read_text(encoding='utf-8').strip() if (app / 'BUILD_ID').is_file() else ''
    first_open = subprocess.run([python, '-E', '-s', 'colleague_setup.py'], cwd=str(app), env=env,
                                capture_output=True, text=True, timeout=GATE_NODE['params']['step_timeout_seconds'], creationflags=NO_WINDOW) \
        if ran.returncode == 0 else None
    venv = app / '.venv' / 'Scripts' / 'python.exe'
    result = {'build_id': meta['build_id'], 'setup_exit': ran.returncode, 'installed_build_id': build_id,
              'first_open_exit': None if first_open is None else first_open.returncode,
              'first_open_tail': '' if first_open is None else (first_open.stdout + first_open.stderr)[-800:],
              'app': str(app), 'python': str(venv), 'profile': str(work / 'profile'),
              'manifest': manifest_check(release, app) if ran.returncode == 0 else {'ok': False}}
    result['ok'] = (ran.returncode == 0 and build_id == meta['build_id'] and result['first_open_exit'] == 0
                    and venv.is_file() and result['manifest']['ok'])
    _record(result, started)
    return result


def _record(result, started):
    app = Path(__file__).resolve().parents[3] / '01.APP'
    if str(app) not in sys.path:
        sys.path.insert(0, str(app))
    try:
        from nodelang import span_stream
    except ImportError:
        return
    span_stream.emit('release_gate install', {
        'gen_ai.operation.name': 'evaluate', 'archhub.build_id': result['build_id'],
        'archhub.setup_exit': result['setup_exit'], 'archhub.first_open_exit': result['first_open_exit'],
        'archhub.manifest_checked': result['manifest'].get('checked'),
        'archhub.manifest_mismatched': len(result['manifest'].get('mismatched') or ()),
    }, start_ns=started, ok=result['ok'])


def clean(work: Path):
    """The gate's install is temporary: removed after the run (F15/F17)."""
    work = work.resolve()
    if not (work / 'ArchHub.isolated.iss').is_file():
        raise ValueError('refusing to delete a folder this tool did not create: %s' % work)
    def writable(function, path, _error):  # Windows marks shell folders read-only
        os.chmod(path, stat.S_IWRITE)
        function(path)
    shutil.rmtree(work, onexc=writable)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', nargs='+', help='<release> <work>, or <work> with --clean')
    parser.add_argument('--python')
    parser.add_argument('--clean', action='store_true')
    args = parser.parse_args(argv)
    if args.clean:
        clean(Path(args.paths[-1]))
        print('INSTALLED-BUILD CLEANED ' + args.paths[-1])
        return 0
    if len(args.paths) != 2:
        parser.error('install needs <release> <work>')
    result = install(Path(args.paths[0]), Path(args.paths[1]), args.python or sys.executable)
    print('INSTALLED-BUILD ' + json.dumps(result))
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
