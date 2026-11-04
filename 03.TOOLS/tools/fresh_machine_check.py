"""Inventory dependencies and test GitHub Latest in a disposable Windows account.

Environment redirection does not isolate Inno's shell folders, HKCU, scheduled
tasks, CNG, or Credential Manager. Refuse an account holding existing ArchHub data.
Run through run-heavy.ps1. The installed shortcut's VBS entry is used headlessly.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.real_app_check.real_app_check import HiddenDesktop, RunJob, free_port, isolated_env


ROOT = Path(__file__).resolve().parents[2]
CHECK_NODE = {'id': 'tool.fresh_machine_check', 'params': {
    'metadata_timeout_seconds': 60, 'install_timeout_seconds': 900,
    'boot_timeout_seconds': 300, 'probe_timeout_seconds': 10, 'poll_seconds': 0.5}}
PATTERNS = {
    'Founder absolute path': r'(?i)(?:[A-Z]:[/\\]+Users[/\\]+fargaly|G:[/\\]+My Drive|E:[/\\])',
    'Workspace governance/tooling': r'00\.GOVERNANCE|50\.TOOLING|agent_onboard|rulesync',
    'Scheduled task': r'(?i)schtasks|scheduled.task|WATCHDOG_TASK',
    'Penpot': r'(?i)penpot',
    'External interpreter/tool': r'(?i)\b(?:pythonw?|node|npm|npx|rulesync|claude|codex|gemini|opencode)(?:\.exe|\.cmd)?\b',
    'Credential boundary': r'(?i)cloud\.json|API_KEY|keyring|CredentialManager',
}
TEXT = {'.py', '.ps1', '.iss', '.vbs', '.bat', '.cmd', '.jsx', '.js', '.mjs', '.cjs',
        '.json', '.jsonc', '.md', '.css', '.html', '.toml'}


def inventory(destination: Path) -> None:
    """Reference locations only: never export matched text or credential values."""
    rows = []
    for base in (ROOT / '01.APP', ROOT / '03.TOOLS/installer'):
        for path in sorted(base.rglob('*')):
            if not path.is_file() or path.suffix not in TEXT or any(
                    part in {'__pycache__', 'node_modules', 'compiled', 'packed'} for part in path.parts):
                continue
            for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
                for category, pattern in PATTERNS.items():
                    if re.search(pattern, line):
                        rows.append((category, path.relative_to(ROOT).as_posix(), number))
    lines = ['# Fresh-machine dependency inventory', '',
             'Generated reference inventory; mentions include comments, examples and optional integrations.',
             'Shipped status below is source/allowlist evidence, not a successful installed-runtime claim.', '',
             '| Dependency | Shipped? | Owner / finding |', '|---|---|---|',
             '| Python 3.14 | No | ArchHub.iss downloads pinned 3.14.7; network required when absent |',
             '| Desktop Python packages | Yes | wheelhouse; colleague_setup creates private .venv |',
             '| Node | Yes | runtime/node.exe, version and digest pinned by build_release.ps1 |',
             '| Goose/BABOOM and secret scanner/compiler | Yes | reviewed runtime payloads; credentials are per user |',
             '| Workspace .rulesync, agent_onboard, filer, persist gate | No | founder workspace; never copy private governance into public source |',
             '| Product agent gates/rules | Yes | installed native_stop_hook + hook_decision; agent_onboard generates from shipped docs/SPEC.md |',
             '| rulesync CLI | No | workspace onboarder requires npm global installation; product fallback uses native renderers |',
             '| OpenCode governance gate | No | assistant_registration.OPENCODE_GOVERNANCE_BLOCKER remains explicit |',
             '| Other external agent CLIs and host applications | No | optional, detected on each PC; cannot inherit founder installations |',
             '| Penpot | No | design references only; inspect locations below for execution reachability |',
             '| Cloud keys/session | No | per-user sign-in/OS credential store; founder keys must never ship |',
             '| Founder paths G:, E:, hard-coded reports | No | hook_decision contains machine-specific protections/optional cleanup and plot defaults |',
             '| Named scheduled tasks | No | retired runtime tasks removed by installer; legacy watchdog probes remain |', '',
             f'Reference rows: {len(rows)}', '', '| Category | Referenced at |', '|---|---|']
    lines.extend(f'| {category} | `{path}:{number}` |' for category, path, number in rows)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(f'INVENTORY: {len(rows)} reference rows -> {destination}')


def require_disposable_account() -> None:
    if os.name != 'nt':
        raise ValueError('fresh-machine installation requires Windows')
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Volatile Environment') as key:
        home = Path(winreg.QueryValueEx(key, 'USERPROFILE')[0])
        local = Path(winreg.QueryValueEx(key, 'LOCALAPPDATA')[0])
    protected = (local / 'ArchHub', local / 'ArchHub-Test', home / '.archhub')
    if any(path.exists() for path in protected):
        raise ValueError('REFUSED: Windows account contains protected ArchHub state; '
                         'environment variables do not isolate installer HKCU/shell folders/tasks')


def latest(output: Path) -> Path:
    result = subprocess.run(['gh', 'api', 'repos/Fargaly/ArchHub/releases/latest'],
                            check=True, capture_output=True, text=True,
                            timeout=CHECK_NODE['params']['metadata_timeout_seconds'])
    release = json.loads(result.stdout)
    assets = [row for row in release['assets'] if re.fullmatch(r'ArchHub-Setup-[\w.-]+\.exe', row['name'])]
    if len(assets) != 1:
        raise ValueError('Latest release must contain exactly one ArchHub setup executable')
    asset = assets[0]
    subprocess.run(['gh', 'release', 'download', release['tag_name'], '--repo', 'Fargaly/ArchHub',
                    '--pattern', asset['name'], '--dir', str(output)], check=True,
                   timeout=CHECK_NODE['params']['install_timeout_seconds'])
    installer = output / asset['name']
    if installer.stat().st_size != asset['size']:
        raise ValueError('Downloaded installer size differs from GitHub release metadata')
    with installer.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    (output / 'release.json').write_text(json.dumps({'tag': release['tag_name'], 'asset': asset['name'],
        'size': asset['size'], 'sha256': digest}, indent=2) + '\n', encoding='utf-8')
    print(f'LATEST: {release["tag_name"]} {asset["name"]} sha256={digest}', flush=True)
    return installer


def check(installer: Path, output: Path) -> None:
    require_disposable_account()
    profile = output / 'profile'
    env = isolated_env(dict(os.environ), profile, lock_port=free_port())
    env.update(ARCHHUB_TEST_NO_OPEN='1', QT_QPA_PLATFORM='offscreen')
    # Do not inherit founder PATH tools or Python user packages.
    env['PATH'] = os.pathsep.join((str(Path(env['SystemRoot']) / 'System32'), env['SystemRoot']))
    for folder in ('.claude', '.codex', '.gemini'):
        (Path(env['USERPROFILE']) / folder).mkdir(parents=True)
    install = profile / 'LOCALAPPDATA/ArchHub'
    subprocess.run([str(installer.resolve()), '/VERYSILENT', '/SUPPRESSMSGBOXES',
                    '/NOCLOSEAPPLICATIONS', '/NORESTARTAPPLICATIONS', '/NORESTART',
                    '/NOICONS', '/TASKS=connectassistants',
                    '/DIR=' + str(install), '/LOG=' + str(output / 'installer.log')],
                   env=env, cwd=output, check=True,
                   timeout=CHECK_NODE['params']['install_timeout_seconds'])
    script_host = Path(env['SystemRoot']) / 'System32/cscript.exe'
    with ExitStack() as cleanup:
        job = RunJob()
        cleanup.callback(job.close)
        desktop = HiddenDesktop(job)
        cleanup.callback(desktop.close)
        app = desktop.spawn(subprocess.list2cmdline(
            [str(script_host), '//B', '//Nologo', str(install / 'ArchHub.vbs')]),
            cwd=str(install), env=env)
        try:
            deadline = time.monotonic() + CHECK_NODE['params']['boot_timeout_seconds']
            last_error = 'HTTP port has not been written'
            while time.monotonic() < deadline:
                if desktop.k32.WaitForSingleObject(app.hProcess, 0) == 0:
                    raise ValueError('Installed shortcut exited before readiness; see installer/launcher logs')
                port_file = Path(env['ARCHHUB_TEST_STATE_DIR']) / 'nograph-http-port'
                if port_file.is_file():
                    port = int(port_file.read_text(encoding='ascii'))
                    try:
                        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/alive',
                            timeout=CHECK_NODE['params']['probe_timeout_seconds']) as response:
                            if response.status == 200:
                                break
                    except OSError as error:
                        last_error = str(error)
                time.sleep(CHECK_NODE['params']['poll_seconds'])
            else:
                raise ValueError('Installed shortcut readiness timed out: ' + last_error)
            if not (install / '.archhub-ready').is_file():
                raise ValueError('First-run readiness marker missing')
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/universal/workshop',
                timeout=CHECK_NODE['params']['probe_timeout_seconds']) as response:
                if json.load(response).get('ok') is not True:
                    raise ValueError('Installed Workshop read failed')
            for relative in ('docs/SPEC.md', 'nodelang/agent_onboard.py', 'nodelang/hook_decision.py',
                             'nodelang/native_stop_hook.py', 'runtime/node.exe'):
                if not (install / relative).is_file():
                    raise ValueError('Missing installed dependency: ' + relative)
            probe = subprocess.run([str(install / '.venv/Scripts/python.exe'), '-E', '-s', '-c',
                'from nodelang.workshop_gateway import stamp; print(stamp())'],
                cwd=install, env=env, capture_output=True, text=True, check=True,
                timeout=CHECK_NODE['params']['metadata_timeout_seconds'])
            if re.fullmatch(r'[0-9a-f]{64}\s*', probe.stdout) is None:
                raise ValueError('Installed governance source stamp unavailable')
            for relative in ('.claude/CLAUDE.md', '.codex/AGENTS.md', '.gemini/GEMINI.md'):
                rules = Path(env['USERPROFILE']) / relative
                if not rules.is_file() or 'ARCHHUB-PRODUCT:BEGIN' not in rules.read_text(encoding='utf-8'):
                    raise ValueError('First-run agent rules missing: ' + relative)
            log = Path(env['ARCHHUB_TEST_STATE_DIR']) / 'launcher.log'
            if log.is_file() and re.search(r'Traceback|ModuleNotFoundError|FileNotFoundError', log.read_text(encoding='utf-8')):
                raise ValueError('Installed launcher logged a missing dependency; see launcher.log')
            print('CLEAN PROFILE: PASS (shortcut, first-run marker, governance stamp, generated rules, Workshop read)')
        finally:
            job.close()
            desktop.k32.CloseHandle(app.hProcess)
            desktop.k32.CloseHandle(app.hThread)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--inventory-only', action='store_true')
    parser.add_argument('--download-only', action='store_true')
    parser.add_argument('--installer', type=Path)
    args = parser.parse_args(argv)
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    inventory(ROOT / '05.EVIDENCE/fresh-machine-dependencies.md')
    if args.inventory_only:
        return 0
    try:
        installer = args.installer or latest(args.out)
        if not args.download_only:
            check(installer, args.out)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        message = str(error)
        (args.out / 'result.json').write_text(json.dumps({'ok': False, 'error': message}, indent=2) + '\n', encoding='utf-8')
        print('CLEAN PROFILE: FAIL: ' + message, flush=True)
        return 1
    if not args.download_only:
        (args.out / 'result.json').write_text('{"ok": true}\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
