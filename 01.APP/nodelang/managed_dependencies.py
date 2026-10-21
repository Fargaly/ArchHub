"""Managed npm dependencies from the existing model-router CLI catalogue.

No package state is stored here: npm and the executable on disk are the owners.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess

from .model_router import SUBSCRIPTION_CLIS, find_assistant

# Publisher-owned package IDs; never interpolate a UI package name into a command.
PACKAGES = {'claude-code': '@anthropic-ai/claude-code', 'codex': '@openai/codex',
            'gemini-cli': '@google/gemini-cli', 'opencode': 'opencode-ai'}


class ManagedDependencies:
    def __init__(self, *, run=None, find=None, timeout_seconds=180):
        self.run = run or self._run
        self.timeout_seconds = timeout_seconds
        self.find = find or find_assistant

    def _run(self, args):
        npm = shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
        if not npm:
            raise ValueError('Install Node.js with npm, reopen ArchHub and check dependencies again.')
        try:
            result = subprocess.run([npm, *args], capture_output=True, text=True,
                                    encoding='utf-8', errors='replace', timeout=self.timeout_seconds,
                                    creationflags=(subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS) if os.name == 'nt' else 0)
        except (OSError, subprocess.TimeoutExpired):
            raise ValueError('The package manager could not confirm completion. Check the dependency inventory before retrying.') from None
        if result.returncode:
            raise ValueError('npm refused the operation. Open dependency logs, resolve the reported package error and retry: ' + result.stderr[-1500:])
        return result.stdout

    def check(self):
        data = json.loads(self.run(['ls', '--global', '--depth=0', '--json']))
        root = Path(self.run(['root', '--global']).strip())
        if not root.is_absolute():
            raise ValueError('npm returned an invalid installation root. Repair Node.js and check again.')
        installed = data.get('dependencies', {})
        rows = []
        try:
            import psutil
            processes = [(p.info.get('cmdline') or [], p.info.get('memory_info'))
                         for p in psutil.process_iter(['cmdline', 'memory_info'])]
        except (ImportError, OSError):
            processes = None
        for id, name, executable in SUBSCRIPTION_CLIS:
            if id not in PACKAGES:
                continue
            package = PACKAGES[id]
            held = installed.get(package, {})
            path = root / package
            disk = sum(p.stat().st_size for p in path.rglob('*') if p.is_file() and not p.is_symlink()) if path.is_dir() else 0
            latest = json.loads(self.run(['view', package, 'version', '--json']))
            found = self.find(executable)
            version = held.get('version')
            state = 'Not installed' if not found else 'Needs repair' if not version else 'Ready' if version == latest else 'Update ready'
            ram = None if processes is None else sum(m.rss for cmd, m in processes if m and any(package.casefold() in arg.replace('\\', '/').casefold() for arg in cmd)) / 1048576
            rows.append({'id': id, 'name': name, 'group': 'Agents', 'version': version or ('External installation' if found else ''),
                         'availableVersion': latest, 'diskMb': round(disk / 1048576, 1), 'ramMb': ram,
                         'state': state, 'description': package, 'usedBy': ['BABOOM'],
                         'integrity': 'npm inventory and executable discovery',
                         'logs': [package + ': ' + state, 'Executable found' if found else 'Executable absent from discovery']})
        return rows

    def manage(self, id, action):
        if id not in PACKAGES or action not in ('Check', 'Install', 'Update', 'Repair', 'Remove'):
            raise ValueError('Choose a listed dependency and a supported operation.')
        if action != 'Check':
            # Only npm-owned installations can be changed here; never remove vendor/native installs.
            inventory = json.loads(self.run(['ls', '--global', '--depth=0', '--json']))
            if action in ('Remove', 'Repair', 'Update') and PACKAGES[id] not in inventory.get('dependencies', {}):
                raise ValueError('This tool is managed by its native installer. Use that installer, then Check again.')
            command = ['uninstall' if action == 'Remove' else 'install', '--global', PACKAGES[id] + ('' if action == 'Remove' else '@latest')]
            if action == 'Repair':
                command.append('--force')
            self.run(command)
        rows = self.check()
        row = next(r for r in rows if r['id'] == id)
        if action == 'Remove' and row['state'] != 'Not installed':
            raise ValueError('Another installation remains on PATH. Review dependency logs before removing it.')
        if action in ('Install', 'Update', 'Repair') and row['state'] != 'Ready':
            raise ValueError('Installation has not passed readback. Check dependency logs and retry Check.')
        return {'dependencies': rows, 'message': row['name'] + ': ' + row['state']}
