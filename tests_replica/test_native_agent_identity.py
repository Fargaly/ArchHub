import pytest

from nodelang.native_agent_session import resolve_native_agent_identity


def test_claude_desktop_bare_selected_session_is_not_identity_proof():
    with pytest.raises(ValueError, match="requires live owner proof"):
        resolve_native_agent_identity({
            "ARCHHUB_COORDINATION_VENDOR": "claude",
            "ARCHHUB_COORDINATION_SESSION": "desktop-chat-1",
        })


def test_claude_desktop_selector_cannot_override_inherited_identity_without_proof():
    with pytest.raises(ValueError, match="requires live owner proof"):
        resolve_native_agent_identity({
            "ARCHHUB_COORDINATION_VENDOR": "claude",
            "ARCHHUB_COORDINATION_SESSION": "desktop-chat-2",
            "CODEX_THREAD_ID": "parent-codex-thread",
        })


def test_connector_session_never_selects_a_vendor_by_itself():
    with pytest.raises(ValueError, match="requires live owner proof"):
        resolve_native_agent_identity({"ARCHHUB_COORDINATION_SESSION": "desktop-chat-3"})


def test_connector_selected_session_conflict_is_refused_before_identity_use():
    with pytest.raises(ValueError, match="requires live owner proof"):
        resolve_native_agent_identity({
            "ARCHHUB_COORDINATION_VENDOR": "claude",
            "ARCHHUB_COORDINATION_SESSION": "desktop-chat-4",
            "CLAUDE_CODE_SESSION_ID": "other",
        })
