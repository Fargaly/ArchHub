"""Generate installed agent rules from the shipped specification; reuse installed gates."""
from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile


CLIENTS = {'claude': 'claude-code', 'claude-code': 'claude-code', 'codex': 'codex',
           'gemini': 'gemini-cli', 'gemini-cli': 'gemini-cli'}
RULE_FILES = {'claude-code': '.claude/CLAUDE.md', 'codex': '.codex/AGENTS.md',
              'gemini-cli': '.gemini/GEMINI.md', 'antigravity': '.gemini/GEMINI.md'}
BEGIN = '<!-- ARCHHUB-PRODUCT:BEGIN -->'
END = '<!-- ARCHHUB-PRODUCT:END -->'


def specification(root: Path) -> Path:
    installed = root / 'docs/SPEC.md'
    return root.parent / '04.DOCS/SPEC.md' if root.name == '01.APP' else installed


def sources(root: Path) -> tuple[Path, ...]:
    return (specification(root), *(root / 'nodelang' / name for name in
            ('agent_onboard.py', 'hook_decision.py', 'native_stop_hook.py', 'workshop_config.py')))


def rule_body(root: Path) -> str:
    return specification(root).read_text(encoding='utf-8').strip()


def install_rules(client: str, root: Path, environment=None) -> Path:
    """Replace only our generated block; preserve user instructions and refuse races."""
    from .client_mcp_installation import _require_plain
    from .workshop_config import _require_single_link
    env = os.environ if environment is None else environment
    home = Path(env['USERPROFILE'])
    target = (Path(env['CODEX_HOME']) / 'AGENTS.md' if client == 'codex' and env.get('CODEX_HOME')
              else home / RULE_FILES[client])
    if not target.is_absolute():
        raise ValueError('agent instruction path must be absolute')
    _require_plain(target, 'file', may_be_absent=True)
    _require_single_link(target)
    if not target.parent.is_dir():
        raise ValueError('agent configuration directory is absent')
    if target.exists() and target.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('agent instructions exceed the supported size')
    before = target.read_bytes() if target.exists() else None
    text = before.decode('utf-8') if before is not None else ''
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise ValueError('ambiguous generated agent rules')
    block = BEGIN + '\n' + rule_body(root) + '\n' + END
    if BEGIN in text:
        start, end = text.index(BEGIN), text.index(END)
        if end < start:
            raise ValueError('invalid generated agent rule markers')
        after = text[:start] + block + text[end + len(END):]
    else:
        after = text.rstrip() + '\n\n' + block + '\n'
    encoded = after.encode('utf-8')
    if encoded == before:
        return target
    descriptor, name = tempfile.mkstemp(prefix='.archhub-rules-', dir=target.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        _require_plain(target, 'file', may_be_absent=True)
        _require_single_link(target)
        if (target.read_bytes() if target.exists() else None) != before:
            raise ValueError('agent instructions changed during setup')
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def main(argv=None) -> int:
    from .assistant_registration import preview_hooks, _repair_hooks, install_roots
    arguments = sys.argv[1:] if argv is None else argv
    client = CLIENTS.get(arguments[0]) if len(arguments) == 1 else None
    if client is None:
        print('Installed governance adapter unavailable for this agent')
        return 2
    root, _state = install_roots()
    plan = preview_hooks(client, include_gate=False, migrate=False)
    if plan['stop_binding'] in ('other_copy', 'stale'):
        print('Existing agent gate belongs to another installation; use Settings to repair')
        return 3
    _repair_hooks(client, consent=True, plan_digest=plan['plan_digest'], include_gate=False, migrate=False)
    install_rules(client, root)
    print(client + ': product rules and installed gates saved; native activation unverified')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
