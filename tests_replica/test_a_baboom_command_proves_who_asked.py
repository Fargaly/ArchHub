"""A BABOOM command route answers the founder session, or nobody.

`baboom-command`, `baboom-command-response` and `baboom-command-execute`
read the session the caller supplies and never checked it, so anything that
could reach the local pipe could drive BABOOM -- including asking it to
restart the application into a staged build. The Steward briefing route
beside them has always made exactly this check (audit, 2026-09-07).
"""
from __future__ import annotations

import inspect
import types

import pytest

from nodelang import application_server as server_module


ROUTES = (
    "/api/universal/baboom-command",
    "/api/universal/baboom-command-response",
    "/api/universal/baboom-command-execute",
)


def _dispatch_source() -> str:
    return inspect.getsource(
        server_module.ApplicationServer.dispatch_universal_machine_route
    )


@pytest.mark.parametrize("path", ROUTES)
def test_every_command_route_checks_who_asked(path):
    body = _dispatch_source()
    start = body.index('path == "%s":' % path)
    tail = body[start:start + 1600]
    assert "_require_founder_machine_session(" in tail, (
        "%s must prove the caller holds the founder session" % path
    )


def test_the_check_refuses_a_session_that_is_not_the_founders():
    fake = types.SimpleNamespace(
        universal_registry=types.SimpleNamespace(
            agent_body=types.SimpleNamespace(
                session=types.SimpleNamespace(root_id="session:founder")
            )
        ),
        _resolve_universal_machine_agent_session=lambda request: "session:someone-else",
    )
    check = types.MethodType(
        server_module.ApplicationServer._require_founder_machine_session, fake
    )
    with pytest.raises(server_module.AuthorizationDenied):
        check({"session": {"runtime_id": "x"}}, False, "/api/universal/baboom-command")


def test_the_check_admits_the_founder_session():
    fake = types.SimpleNamespace(
        universal_registry=types.SimpleNamespace(
            agent_body=types.SimpleNamespace(
                session=types.SimpleNamespace(root_id="session:founder")
            )
        ),
        _resolve_universal_machine_agent_session=lambda request: "session:founder",
    )
    check = types.MethodType(
        server_module.ApplicationServer._require_founder_machine_session, fake
    )
    check({"session": {"runtime_id": "x"}}, False, "/api/universal/baboom-command")
    check({}, True, "/api/universal/baboom-command")


def test_the_briefing_route_still_makes_the_same_check():
    """The route this was copied from must not lose it."""
    body = _dispatch_source()
    assert body.count("agent_body.session.root_id") >= 1
