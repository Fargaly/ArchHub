"""Generate installed agent rules from the shipped specification; reuse installed gates."""
from __future__ import annotations

import os
from pathlib import Path
import re
import sys
import tempfile


# One row per agent: the folder that means it is installed, the instruction file it reads (both under the
# user's home), the header a new instruction file needs, and whether ArchHub's hook adapter installs its gates.
# A new agent is one row; an agent with no row gets the generic path in rule_target().
AGENTS = {
    'claude-code': ('.claude', '.claude/CLAUDE.md', '', True),
    'codex': ('.codex', '.codex/AGENTS.md', '', True),
    'gemini-cli': ('.gemini', '.gemini/GEMINI.md', '', True),
    'antigravity': ('.gemini', '.gemini/GEMINI.md', '', True),
    # cursor-agent and Cursor read every ~/.cursor/rules/*.mdc as a user rule.
    'cursor': ('.cursor', '.cursor/rules/archhub-product.mdc',
               '---\ndescription: ArchHub product rules\nalwaysApply: true\n---\n', False),
    'opencode': ('.config/opencode', '.config/opencode/AGENTS.md', '', False),
    'goose': ('.config/goose', '.config/goose/.goosehints', '', False),
}
CLIENTS = {'claude': 'claude-code', 'claude-code': 'claude-code', 'codex': 'codex',
           'gemini': 'gemini-cli', 'gemini-cli': 'gemini-cli', 'antigravity': 'antigravity',
           'antigravity-ide': 'antigravity', 'antigravity-cli': 'antigravity', 'cursor': 'cursor',
           'cursor-agent': 'cursor', 'opencode': 'opencode', 'goose': 'goose'}
GATES = 'end-of-turn check, tool-call decision'
_NAME = re.compile(r'[a-z0-9][a-z0-9._-]{0,40}')
BEGIN = '<!-- ARCHHUB-PRODUCT:BEGIN -->'
END = '<!-- ARCHHUB-PRODUCT:END -->'


def rule_target(client: str, env) -> tuple[Path, Path, str] | None:
    """(installed-folder, instruction file, new-file header) for this agent, or None when none is known.
    An agent without a row that keeps a ~/.<name> folder gets ~/.<name>/AGENTS.md, the cross-agent file."""
    home = Path(env['USERPROFILE'])
    if client == 'codex' and env.get('CODEX_HOME'):
        return Path(env['CODEX_HOME']), Path(env['CODEX_HOME']) / 'AGENTS.md', ''
    folder, rules, header, _hooks = AGENTS.get(client, ('.' + client, '.%s/AGENTS.md' % client, '', False))
    return home / folder, home / rules, header


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
    folder, target, header = rule_target(client, env)
    if not target.is_absolute():
        raise ValueError('agent instruction path must be absolute')
    if not folder.is_dir():
        raise ValueError('agent configuration directory is absent')
    if not target.parent.is_dir() and target.parent.parent == folder:
        target.parent.mkdir()  # e.g. ~/.cursor/rules inside an installed ~/.cursor
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
    elif before is None and header:
        after = header + '\n' + block + '\n'
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


def _gates(client: str) -> str:
    """Install this agent's gates where ArchHub's adapter supports it; say plainly what it cannot run."""
    from .assistant_registration import preview_hooks, _repair_hooks
    from .workshop_config import WorkshopConfigRefused
    if not AGENTS.get(client, (None, None, None, False))[3]:
        return 'ArchHub installs no gates for this agent; it cannot run: ' + GATES
    try:
        plan = preview_hooks(client, include_gate=False, migrate=False)
        if plan['stop_binding'] in ('other_copy', 'stale'):
            return 'existing agent gate belongs to another installation; use Settings to repair'
        _repair_hooks(client, consent=True, plan_digest=plan['plan_digest'], include_gate=False, migrate=False)
    except (WorkshopConfigRefused, OSError, ValueError) as error:
        return 'gates not installed (%s); it cannot run: %s' % (error, GATES)
    return 'installed gates saved; native activation unverified'


def main(argv=None) -> int:
    from .assistant_registration import install_roots
    arguments = sys.argv[1:] if argv is None else argv
    name = arguments[0].strip().lower() if len(arguments) == 1 else ''
    if not _NAME.fullmatch(name):
        print('usage: python -m nodelang.agent_onboard <agent name: letters, digits, . _ ->')
        return 2
    client = CLIENTS.get(name, name)
    root, _state = install_roots()
    try:
        rules = 'product rules saved to %s' % install_rules(client, root)
    except (OSError, ValueError) as error:
        rules ='product rules not saved (%s); they are in %s' % (error, specification(root))
    print('%s: %s; %s' % (client, rules, _gates(client)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
