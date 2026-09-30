"""Studio Settings > Workspaces: the owner's one place to add and remove governed folders.

Read from the Studio source and its compiled output (the compiled file is what the
application serves). The route itself is proven in test_workspace_roots_owner_route.py.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parents[1] / "nodelang" / "studio"
PROMISE = ("Removing a workspace only stops ArchHub from governing it. "
           "Your files are never deleted.")


def _source() -> str:
    return (STUDIO / "studio-lm.jsx").read_text(encoding="utf-8")


def _panel() -> str:
    source = _source()
    start = source.index("const SettingsWorkspaces = () => {")
    return source[start:source.index("const SettingsHosts = () => {", start)]


def test_settings_offers_a_workspaces_tab_that_renders_the_panel():
    source = _source()
    assert "['workspaces',  'Workspaces',  null]," in source
    assert "{tab === 'workspaces'  && <SettingsWorkspaces/>}" in source


def test_the_panel_speaks_only_to_the_owner_route_with_the_session():
    panel = _source()[_source().index("async function workspaceRoots(body, renewed)"):]
    panel = panel[:panel.index("const SettingsWorkspaces")]
    assert "fetch('/api/universal/workspace-roots'" in panel
    assert "method:'POST'" in panel
    assert "'X-ArchHub-Session':s.token" in panel and "'X-ArchHub-CSRF':s.csrf" in panel
    assert len(re.findall(r"fetch\(", panel)) == 1
    # A refused session is renewed once through the Studio's own sign-in, then retried once.
    assert "response.status === 403 && !renewed" in panel
    assert "return workspaceRoots(body, true);" in panel


def test_the_panel_asks_for_exactly_the_actions_the_route_admits():
    panel = _panel()
    actions = set(re.findall(r"action:'([a-z]+)'", panel))
    assert actions == {"list", "register", "unregister", "republish", "browse"}
    # Browse only fills the path in: the dialog answer goes to setPath, never to register.
    assert "const picked = await workspaceRoots({ action:'browse' }); if (picked.path) setPath(picked.path);" in panel
    assert "aria-label=\"Browse for a folder\"" in panel
    assert "profile:'client'" in panel and "writers:['claude']" in panel
    assert '<option value="private">' in panel and '<option value="public">' in panel


def test_the_promise_is_shown_and_nothing_offers_to_delete_files():
    source = _source()
    assert "const WORKSPACE_PROMISE = '%s';" % PROMISE in source
    panel = _panel()
    assert panel.count("{WORKSPACE_PROMISE}") >= 2  # the confirmation and the footer
    assert not re.search(r"\bdelete\b|\bDelete\b|rmdir|unlink", panel)


def test_the_built_in_root_is_shown_and_cannot_be_removed():
    panel = _panel()
    built_in = panel[panel.index("<div style={{ fontSize:13, fontWeight:500 }}>00.ARCHUB</div>"):]
    built_in = built_in[:built_in.index("{registered.map(")]
    assert "built in" in built_in and "Remove" not in built_in


def test_changes_are_offered_only_when_the_check_and_the_read_agree():
    """Behaviour is proven in tests_js/studio_workspaces_settings.test.cjs; here, that
    every mutation path is guarded by the same readiness, not only its button."""
    panel = _panel()
    assert ("const ready = !!view && (boot === 'match' || boot === 'missing') "
            "&& view.projection === boot;") in panel
    assert "if (!ready || busy) return;" in panel  # Add and Stop governing
    assert "if (ready && !busy) setConfirming(r);" in panel  # Remove
    assert panel.count("disabled={!!busy || !ready") == 3  # Remove, Stop governing, Add
    assert "{view.key_pinned && (" in panel  # Republish only when something is registered
    assert "Read again" in panel


def test_the_served_compiled_studio_carries_the_panel():
    """The compiled Studio is a build output (packaging/compile_studio.cjs)."""
    target = STUDIO / "compiled" / "studio-lm.js"
    if not target.exists():
        pytest.skip("no compiled Studio in this tree; the build produces it")
    compiled = target.read_text(encoding="utf-8")
    assert "SettingsWorkspaces" in compiled and "/api/universal/workspace-roots" in compiled
    manifest = json.loads((STUDIO / "compiled" / "manifest.json").read_text(encoding="utf-8"))
    assert "studio-lm.jsx" in json.dumps(manifest)


def test_the_panel_behaves_by_the_registry_state_in_the_shipped_studio():
    """Run the behavioural court (tests_js/studio_workspaces_settings.test.cjs) in Node."""
    import shutil
    import subprocess

    node = shutil.which("node")
    assert node, "Node is required for the shipped Studio Workspaces court"
    if not (STUDIO / "compiled" / "studio-lm.js").exists():
        pytest.skip("no compiled Studio in this tree; the build produces it")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, "--test", "tests_js/studio_workspaces_settings.test.cjs"],
        cwd=root, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
