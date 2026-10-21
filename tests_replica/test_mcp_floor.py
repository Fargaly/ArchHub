"""Generic MCP floor forcing: reads are live, writes are frozen by default."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang import Store, validate_store  # noqa: E402
from nodelang import governance_probe  # noqa: E402


def test_mcp_read_node_calls_configured_tool_and_is_volatile(monkeypatch):
    calls = []

    def fake(name, args, url, timeout):
        calls.append((name, args, url, timeout))
        return {'sequence': len(calls)}

    monkeypatch.setattr(governance_probe, '_mcp_tool', fake)
    store = Store()
    node = store.add('op', 'MCP read', floor={
        'op': 'mcp', 'url': 'http://brain/mcp', 'tool': 'brain.read',
        'args': {'owner_user': 'founder'}, 'effectful': False, 'timeout': 2,
    })
    assert store.pull(node) == {'sequence': 1}
    assert store.pull(node) == {'sequence': 2}
    assert calls[0][0:3] == ('brain.read', {'owner_user': 'founder'}, 'http://brain/mcp')
    assert validate_store(store) is True


def test_effectful_mcp_node_fails_closed_until_audited_unfreeze(monkeypatch):
    calls = []
    monkeypatch.setattr(governance_probe, '_mcp_tool',
                        lambda name, args, url, timeout: calls.append(name) or {'ok': True})
    store = Store()
    node = store.add('op', 'MCP write', floor={
        'op': 'mcp', 'tool': 'brain.record', 'args': {'record': 'x'},
        'effectful': True,
    }, frozen=True)
    assert store.pull(node) == {'fired': False, 'dry_run': True, 'tool': 'brain.record'}
    assert calls == []
    store.apply_op({'op': 'unfreeze', 'id': node, 'actor': 'user'})
    assert store.pull(node) == {'fired': True, 'result': {'ok': True}}
    assert calls == ['brain.record']
    assert validate_store(store) is True
