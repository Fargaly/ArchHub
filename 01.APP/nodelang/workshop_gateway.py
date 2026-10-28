"""The Workshop is the gateway: an agent that connects gets the hooks and rules applied.

Founder 2026-10-28: any agent on the PC that connects to the Workshop gets the hooks
and rules applied automatically. On connector start this checks the runtime's
governance stamp (sha256 of .rulesync/hooks.jsonc + .rulesync/rules/archhub-ledger.md).
If it is not current, it starts the existing agent_onboard.py (owned by 717)
detached at BelowNormal and never waits for it. A detached finisher records the
outcome in settings/governance-stamps.json and posts one Workshop line
"<agent> joined - rules+hooks applied (35 rules, N hooks)". The agent is never blocked.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

RUNTIMES = ('claude', 'codex', 'cursor', 'gemini', 'copilot', 'opencode', 'kiro', 'goose', 'qwen', 'grok', 'antigravity')


def governance_dir():
    override = os.environ.get('ARCHHUB_GOVERNANCE_HOOKS_DIR')
    if override:
        return Path(override)
    from .workspace_roots_catalogue import built_in_path
    return Path(built_in_path()) / '00.GOVERNANCE' / '03.AGENT-HOOKS'


def _sources():
    root = governance_dir() / '.rulesync'
    return root / 'hooks.jsonc', root / 'rules' / 'archhub-ledger.md'


def stamp():
    digest = hashlib.sha256()
    for path in _sources():
        digest.update(path.read_bytes())
    return digest.hexdigest()


def counts():
    hooks, rules = _sources()
    text = re.sub(r'^\s*//.*$', '', hooks.read_text(encoding='utf-8'), flags=re.M)
    hook_count = len(re.findall(r'"command"\s*:', text))
    rule_count = len(re.findall(r'^\s*(?:\d+\.|-)\s', rules.read_text(encoding='utf-8'), flags=re.M))
    return rule_count, hook_count


def _store():
    return Path(os.environ['LOCALAPPDATA']) / 'ArchHub' / 'settings' / 'governance-stamps.json'


_LOCK = threading.Lock()
# Gateway onboarding node: its typed parameters.
GATEWAY_NODE = {'id': 'workshop.gateway', 'params': {'onboard_timeout_seconds': 900}}


def read_states():
    try:
        return json.loads(_store().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _write_state(runtime, **values):
    from .nograph_server import JsonFile
    with _LOCK:
        held = read_states()
        held[runtime] = {**held.get(runtime, {}), **values, 'at': datetime.now(timezone.utc).isoformat()}
        JsonFile(_store(), {}).write(held)
    return held[runtime]


def detect_runtime():
    """The agent that started this connector: env first, then the parent process chain."""
    vendor = os.environ.get('ARCHHUB_COORDINATION_VENDOR', '').casefold()
    for name in RUNTIMES:
        if vendor.startswith(name):
            return name
    try:
        import psutil
        process = psutil.Process().parent()
        for _ in range(6):
            if process is None:
                break
            text = (process.name() + ' ' + ' '.join(process.cmdline()[:3])).casefold()
            for name in RUNTIMES:
                if name in text:
                    return name
            process = process.parent()
    except Exception:  # noqa: BLE001 - unknown runtime is still served, just not onboarded
        return ''  # '' is the typed unknown-runtime answer on_connect reports
    return ''


def on_connect(runtime=None):
    """Called at connector start in a thread; returns at once. Never raises into the agent."""
    try:
        runtime = runtime or detect_runtime()
        if not runtime:
            return {'state': 'unknown-runtime'}
        current = stamp()
        held = read_states().get(runtime, {})
        if held.get('stamp') == current and held.get('state') in ('current', 'applying'):
            return held
        _write_state(runtime, stamp=current, state='applying', reason='')
        flags = 0x00004000 | 0x00000008 | 0x00000200  # BELOW_NORMAL | DETACHED | NEW_PROCESS_GROUP
        subprocess.Popen([sys.executable, '-I', '-c',
                          'import runpy,sys;sys.path.insert(0,sys.argv.pop(1));sys.argv=[sys.argv[0]]+sys.argv[1:];'
                          'runpy.run_module("nodelang.workshop_gateway",run_name="__main__")',
                          str(Path(__file__).resolve().parents[1]), 'apply', runtime, current],
                         creationflags=flags if os.name == 'nt' else 0, close_fds=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {'state': 'applying', 'stamp': current}
    except Exception as error:  # noqa: BLE001 - governance never blocks an agent
        try:
            _write_state(runtime or 'unknown', state='failed', reason=str(error)[:200])
        except Exception as unrecorded:  # noqa: BLE001
            return {'state': 'failed', 'reason': str(error), 'unrecorded': str(unrecorded)}
        return {'state': 'failed', 'reason': str(error)}


def apply(runtime, current):
    """Detached: run the existing onboarder, then record the outcome and the Workshop join line."""
    onboard = governance_dir() / 'agent_onboard.py'
    try:
        done = subprocess.run([sys.executable, str(onboard)], capture_output=True, text=True, timeout=GATEWAY_NODE['params']['onboard_timeout_seconds'],
                              creationflags=0x00004000 | 0x08000000 if os.name == 'nt' else 0)
        ok = done.returncode == 0
        reason = '' if ok else (done.stderr or done.stdout or 'agent_onboard.py exit %d' % done.returncode).strip()[-300:]
    except Exception as error:  # noqa: BLE001
        ok, reason = False, str(error)[:300]
    rules, hooks = counts()
    _write_state(runtime, stamp=current, state='current' if ok else 'failed', reason=reason, rules=rules, hooks=hooks)
    line = ('%s joined - rules+hooks applied (%d rules, %d hooks, stamp %s)' % (runtime, rules, hooks, current[:12]) if ok
            else '%s joined - governance failed: %s' % (runtime, reason[:160]))
    from .workshop_mailbox import application_history, ROOM, CATEGORY
    with application_history() as history:
        history.append(ROOM, author='Workshop gateway', content='To Ahmed:\n' + line, category=CATEGORY, recipients=(),
                       reply_principal='Workshop gateway', idempotency_key='gateway:%s:%s:%s' % (runtime, current, int(time.time())))


if __name__ == '__main__' and len(sys.argv) == 4 and sys.argv[1] == 'apply':
    apply(sys.argv[2], sys.argv[3])
