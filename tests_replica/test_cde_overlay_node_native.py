"""The Grand Map CDE overlay must route work only into the new runtime."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelang.cde_overlay import ROOT, build_overlay  # noqa: E402
from nodelang.map_import import load_map  # noqa: E402


def test_overlay_covers_every_map_node_with_executable_node_native_gate():
    overlay = build_overlay()
    expected = sum(len(domain['nodes']) for domain in load_map())
    assert len(overlay['containers']) == expected == 282
    for container in overlay['containers'].values():
        assert container['tier'] == 'T1'
        assert container['gate_kind'] == 'pytest'
        assert container['gate_spec']['command'].startswith('python -m pytest ')
        assert container['allowed_paths']
        assert all(path.startswith(ROOT) for path in container['allowed_paths'])
        assert all('12.PRODUCTION' not in path for path in container['allowed_paths'])


def test_overlay_is_domain_routed_not_one_workspace_wide_scope():
    overlay = build_overlay()['containers']
    ui = set(overlay['ui_design_tokens']['allowed_paths'])
    cloud = set(overlay['cloud_fly_app']['allowed_paths'])
    assert ui != cloud
    assert any(path.endswith('nodelang/application.py') for path in ui)
    assert any(path.endswith('nodelang/domains/cloud.py') for path in cloud)
