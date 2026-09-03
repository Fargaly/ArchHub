"""Smoke tests for `tools/cdp_grammar_audit.py`.

The audit tool needs a running ArchHub on port 9223 to verify
end-to-end. These tests only smoke-import + check the helper
functions sanity — the live verification happens manually +
in CI via the launch-then-run sequence documented in the module
docstring.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))


def test_cdp_audit_module_imports():
    """The tool module imports cleanly."""
    import cdp_grammar_audit  # noqa: F401


def test_cdp_audit_module_exposes_main():
    import cdp_grammar_audit
    assert callable(cdp_grammar_audit.main)
    assert callable(cdp_grammar_audit.run_audit)
    assert callable(cdp_grammar_audit._cdp_url)


def test_cdp_url_returns_none_when_no_archhub():
    """`_cdp_url(9999)` (unused port) returns None gracefully."""
    import cdp_grammar_audit
    result = cdp_grammar_audit._cdp_url(port=9999)
    assert result is None


def test_audit_tool_documents_launch_command():
    """The module docstring tells the founder how to launch ArchHub
    before running the audit. Sanity-check the relevant tokens."""
    src = (TOOLS / "cdp_grammar_audit.py").read_text(encoding="utf-8")
    assert "QTWEBENGINE_REMOTE_DEBUGGING" in src
    assert "tools/cdp_grammar_audit.py" in src


def test_audit_tool_classifies_drop_violations():
    """The grammar audit's failure classifier covers: master with
    selector, params rendering as <select>, code master visible,
    ai master visible."""
    src = (TOOLS / "cdp_grammar_audit.py").read_text(encoding="utf-8")
    # The four founder-mandated invariants must each be a guarded
    # failure path in run_audit().
    assert "masters_with_selector" in src
    assert "params_render_dropdown" in src
    assert "`code` master visible" in src
    assert "`ai` master visible" in src
