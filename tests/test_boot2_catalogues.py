"""BOOT2 catalogue skips use source digests and current graph generation."""
from __future__ import annotations

import json
import pytest

from nodelang import clean_coordination_host as host_module
from nodelang import base_universal_catalogue as base_module
from nodelang import unified_authority as ua
from nodelang.clean_coordination_host import CleanCoordinationHost
from tests_replica.test_coordination_workshop import _authority, _Caller


class _Keys:
    def bind_bootstrap(self, authority, key_id):
        return _Caller(authority)


def test_unchanged_host_reopen_skips_installers(tmp_path, monkeypatch):
    authority = _authority()
    first = CleanCoordinationHost(authority, _Keys(), runtime_root=tmp_path)
    revision = authority.store.revision
    ua._CATALOGUE_NAME_INDEX.clear()

    def forbidden(*args, **kwargs):
        raise AssertionError("unchanged boot entered cold catalogue installation")

    monkeypatch.setattr(host_module, "install_agent_session_catalogue", forbidden)
    monkeypatch.setattr(host_module, "install_workshop_catalogue", forbidden)
    monkeypatch.setattr(base_module, "install_base_universal_catalogue", forbidden)
    second = CleanCoordinationHost(authority, _Keys(), runtime_root=tmp_path)
    assert second._sessions == first._sessions
    assert second._workshop == first._workshop
    assert second._base_catalogue == first._base_catalogue
    assert authority.store.revision == revision


@pytest.mark.parametrize("invalid", ["source", "malformed", "generation", "missing-state", "graph"])
def test_catalogue_generation_invalidates_fail_closed(tmp_path, monkeypatch, invalid):
    authority = _authority()
    host = CleanCoordinationHost(authority, _Keys(), runtime_root=tmp_path)
    cache = tmp_path / "catalogue-generation.json"
    if invalid == "source":
        monkeypatch.setattr(host_module, "_boot_catalogue_source_hash", lambda: "changed source")
    elif invalid == "malformed":
        cache.write_text("{broken", encoding="utf-8")
    elif invalid == "generation":
        body = json.loads(cache.read_text(encoding="utf-8"))
        body["generation"] = "changed graph"
        cache.write_text(json.dumps(body), encoding="utf-8")
    elif invalid == "missing-state":
        cache.unlink()
    else:
        ua.declare_definition(authority, "New catalogue entry", caller=host._founder,
                              command_id="579a0c0c-0e2a-4ac9-a2f0-5ca95d13fcda")
    revision = authority.store.revision
    ua._CATALOGUE_NAME_INDEX.clear()
    session_install = host_module.install_agent_session_catalogue
    workshop_install = host_module.install_workshop_catalogue
    calls = []

    def sessions(*args, **kwargs):
        calls.append("sessions")
        return session_install(*args, **kwargs)

    def workshop(*args, **kwargs):
        calls.append("workshop")
        return workshop_install(*args, **kwargs)

    monkeypatch.setattr(host_module, "install_agent_session_catalogue", sessions)
    monkeypatch.setattr(host_module, "install_workshop_catalogue", workshop)
    reopened = CleanCoordinationHost(authority, _Keys(), runtime_root=tmp_path)
    assert calls == ["sessions", "workshop"]
    assert reopened._sessions == host._sessions
    assert reopened._workshop == host._workshop
    assert authority.store.revision == revision
    assert ua.published_definition_named(authority, "Agent session state",
                                         caller=host._founder) == host._sessions.definition_root


def test_cached_catalogue_still_authenticates_caller(tmp_path):
    authority = _authority()
    host = CleanCoordinationHost(authority, _Keys(), runtime_root=tmp_path)
    caller = _Caller(authority)
    caller.public_key = b"x" * 32
    assert ua.published_definition_named(authority, "Agent session state", caller=caller) is None
    assert host._sessions.definition_root


def test_named_lookup_authenticates_only_matching_candidates(tmp_path, monkeypatch):
    authority = _authority()
    host = CleanCoordinationHost(authority, _Keys(), runtime_root=tmp_path)
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
    host = CleanCoordinationHost(authority, _Keys(), runtime_root=tmp_path)
    denied = host._sessions.definition_root
    authenticate = ua._authorize_semantic_read

    def policy(*args, **kwargs):
        if kwargs.get("object_root") == denied:
            raise InvalidCell("semantic read is not authorized by graph policy")
        return authenticate(*args, **kwargs)

    monkeypatch.setattr(ua, "_authorize_semantic_read", policy)
    assert denied not in _published_definitions(authority, host._founder)
    assert ua.published_definition_named(authority, "Agent session state", caller=host._founder) is None
