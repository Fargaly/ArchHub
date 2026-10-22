"""BOOT2 catalogue skips use source digests and current graph generation."""
from __future__ import annotations


from nodelang import unified_authority as ua
from tests_replica.test_coordination_workshop import _authority, _Caller


def _catalogue_owner(authority):
    from types import SimpleNamespace
    from nodelang.agent_session_catalogue import install_agent_session_catalogue
    caller = _Caller(authority)
    sessions = install_agent_session_catalogue(authority,
        operation_id='f1a14bbe-b124-47f0-b86b-38a302104d2b', caller=caller)
    return SimpleNamespace(_founder=caller, _sessions=sessions)


def test_cached_catalogue_still_authenticates_caller(tmp_path):
    authority = _authority()
    host = _catalogue_owner(authority)
    caller = _Caller(authority)
    caller.public_key = b"x" * 32
    assert ua.published_definition_named(authority, "Agent session state", caller=caller) is None
    assert host._sessions.definition_root


def test_named_lookup_authenticates_only_matching_candidates(tmp_path, monkeypatch):
    authority = _authority()
    host = _catalogue_owner(authority)
    ua._CATALOGUE_NAME_INDEX.clear()
    authenticate = ua._authorize_semantic_read
    calls = []

    def counted(*args, **kwargs):
        calls.append(kwargs["object_root"])
        return authenticate(*args, **kwargs)

    monkeypatch.setattr(ua, "_authorize_semantic_read", counted)
    assert ua.published_definition_named(authority, "Agent session state",
                                         caller=host._founder) == host._sessions.definition_root
    assert calls == [host._sessions.definition_root]


def test_cached_catalogue_filters_denied_definition_from_derived_controls(tmp_path, monkeypatch):
    from nodelang.clean_scope_interactions import _published_definitions
    from nodelang.universal_cell import InvalidCell

    authority = _authority()
    host = _catalogue_owner(authority)
    denied = host._sessions.definition_root
    authenticate = ua._authorize_semantic_read

    def policy(*args, **kwargs):
        if kwargs.get("object_root") == denied:
            raise InvalidCell("semantic read is not authorized by graph policy")
        return authenticate(*args, **kwargs)

    monkeypatch.setattr(ua, "_authorize_semantic_read", policy)
    assert denied not in _published_definitions(authority, host._founder)
    assert ua.published_definition_named(authority, "Agent session state", caller=host._founder) is None
