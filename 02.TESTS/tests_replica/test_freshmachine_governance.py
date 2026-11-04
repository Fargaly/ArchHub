"""Installed governance must not require the builder's workspace."""
from pathlib import Path

import pytest

from nodelang import workshop_gateway


def test_colleague_gateway_uses_shipped_sources(monkeypatch, tmp_path):
    from nodelang import workspace_roots_catalogue
    (tmp_path / '00.GOVERNANCE/03.AGENT-HOOKS').mkdir(parents=True)
    monkeypatch.delenv('ARCHHUB_GOVERNANCE_HOOKS_DIR', raising=False)
    monkeypatch.setattr(workspace_roots_catalogue, 'built_in_path', lambda: str(tmp_path))
    assert workshop_gateway.governance_dir() == Path(workshop_gateway.__file__).parent
    assert len(workshop_gateway.stamp()) == 64


def test_explicit_workspace_governance_is_preserved(monkeypatch, tmp_path):
    monkeypatch.setenv('ARCHHUB_GOVERNANCE_HOOKS_DIR', str(tmp_path))
    assert workshop_gateway.governance_dir() == tmp_path


def test_generated_rules_preserve_user_text_and_update_once(tmp_path):
    from nodelang.agent_onboard import install_rules
    root = tmp_path / 'install'
    (root / 'docs').mkdir(parents=True)
    spec = root / 'docs/SPEC.md'
    spec.write_text('1. Everything is a node.\n', encoding='utf-8')
    home = tmp_path / 'profile'
    (home / '.codex').mkdir(parents=True)
    target = home / '.codex/AGENTS.md'
    target.write_text('My own instructions.\n', encoding='utf-8')
    env = {'USERPROFILE': str(home)}
    install_rules('codex', root, env)
    first = target.read_bytes()
    install_rules('codex', root, env)
    assert target.read_bytes() == first
    spec.write_text('1. Files are portable.\n', encoding='utf-8')
    install_rules('codex', root, env)
    text = target.read_text(encoding='utf-8')
    assert text.startswith('My own instructions.\n')
    assert text.count('ARCHHUB-PRODUCT:BEGIN') == 1
    assert 'Files are portable.' in text and 'Everything is a node.' not in text


def test_damaged_rule_markers_are_left_untouched(tmp_path):
    from nodelang.agent_onboard import install_rules
    home = tmp_path / 'profile'
    (home / '.claude').mkdir(parents=True)
    target = home / '.claude/CLAUDE.md'
    original = b'personal\n<!-- ARCHHUB-PRODUCT:BEGIN -->\n'
    target.write_bytes(original)
    with pytest.raises(ValueError, match='ambiguous'):
        install_rules('claude-code', tmp_path, {'USERPROFILE': str(home)})
    assert target.read_bytes() == original
