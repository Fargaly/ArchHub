"""The founder's own BABOOM companion can drive BABOOM's commands; nobody else can.

2026-10-01 real-app acceptance (installed build 20261001-1423-a9e534e, fresh
isolated graph): every BABOOM command from the companion -- "repo status", any
interrupt -- answered "BABOOM could not read the graph response.". The
swallowed error was "founder-local BABOOM command requires the founder session".
35393a5b gave BABOOM its own auditable runtime body (a runtime never acts WITH
the founder body) and, in the same commit, made the three BABOOM command routes
admit only the founder body's session -- which the companion never holds. The
founder's live graph shows the same: BABOOM acts as an app:agent-session:runtime
session, never app:agent-session:founder.

The gate now also admits exactly one other caller: the full-access,
device-proof session of the graph's "baboom" (companion) catalog entry whose
device custody the founder's application committed for this machine (the
custody _machine_agent_binding_for_request already proves active). That is the
graph-recorded delegation, not a runtime name: a session merely calling itself
baboom, a recovery capability, the baboom-execution worker, another or wildcard
entry, a machine-transport body or an unlisted custody is still refused.
"""
from __future__ import annotations

import types

import pytest

from nodelang import application_server as server_module
from nodelang.cell_agent_body_catalog import AgentBodyCatalogEntry

FOUNDER = "app:agent-session:founder"
BABOOM_SESSION = "app:agent-session:runtime:" + "d" * 32
ENTRY = "app:agent-body-catalog:entry:baboom"
CUSTODY = "app:device-custody:" + "c" * 32
PATH = "/api/universal/baboom-command-response"


def entry(**changes):
    values = dict(root_id=ENTRY, body_root="app:agent-body:baboom", control_root="app:agent-control:baboom",
                  policy_root="app:agent-policy:baboom", runtime="baboom",
                  grand_map_node_root="app:grand-map:baboom", credential_mode="device-proof",
                  device_custody_roots=(CUSTODY,), work_events=())
    values.update(changes)
    return AgentBodyCatalogEntry(**values)


def baboom_binding(**changes):
    binding = {"runtime": "baboom", "catalog_entry": ENTRY, "device_custody": CUSTODY,
               "external_session_fingerprint": "f" * 64, "issued_at": 0.0, "expires_at": 9e18}
    binding.update(changes)
    return binding


def gate(monkeypatch, *, session_root=BABOOM_SESSION, binding=None, catalog=None, bound=True):
    calls = []

    def bind(request):
        calls.append(request)
        if not bound:
            raise server_module.AuthorizationDenied("a bound runtime Agent Session is required")
        return session_root, dict(baboom_binding() if binding is None else binding)

    monkeypatch.setattr(server_module, "_agent_body_catalog_entry_for_runtime",
                        lambda snapshot, registry, runtime: catalog or entry())
    fake = types.SimpleNamespace(
        universal_registry=types.SimpleNamespace(
            agent_body=types.SimpleNamespace(session=types.SimpleNamespace(root_id=FOUNDER))),
        universal_store=types.SimpleNamespace(snapshot=lambda: object()),
        _machine_agent_binding_for_request=bind,
        _resolve_universal_machine_agent_session=lambda request: bind(request)[0],
    )
    check = types.MethodType(server_module.ApplicationServer._require_founder_machine_session, fake)
    return check, calls


SIGNED = {"method": "POST", "path": PATH, "session": {"root": BABOOM_SESSION, "proof": "p"}}


def test_the_founders_baboom_companion_session_is_admitted(monkeypatch):
    check, calls = gate(monkeypatch)
    check(SIGNED, False, PATH)
    assert len(calls) == 1


def test_the_founder_session_and_the_direct_founder_entry_are_still_admitted(monkeypatch):
    check, _ = gate(monkeypatch, session_root=FOUNDER, binding={"runtime": "founder"})
    check(SIGNED, False, PATH)
    check({}, True, PATH)


@pytest.mark.parametrize("why,kwargs", [
    ("another runtime (codex)", dict(session_root="app:agent-session:runtime:" + "1" * 32,
                                     binding={"runtime": "codex", "catalog_entry": "app:agent-body-catalog:entry:codex",
                                              "device_custody": None})),
    ("a recovery-read capability of the BABOOM session", dict(binding=baboom_binding(access="recovery-read"))),
    ("another catalog entry", dict(binding=baboom_binding(catalog_entry="app:agent-body-catalog:entry:other"))),
    ("a custody the entry does not list", dict(binding=baboom_binding(device_custody="app:device-custody:" + "e" * 32))),
    ("no custody at all", dict(binding=baboom_binding(device_custody=None))),
    ("a machine-transport baboom entry", dict(catalog=entry(credential_mode="machine-transport"))),
    ("the baboom-execution worker session", dict(binding=baboom_binding(runtime="baboom-execution",
                                                                   catalog_entry="app:agent-body-catalog:entry:baboom-execution"))),
    ("the wildcard catalog entry", dict(catalog=entry(runtime="*"))),
    ("a session that only names itself baboom", dict(binding={"runtime": "baboom"})),
])
def test_everything_else_is_refused(monkeypatch, why, kwargs):
    check, _ = gate(monkeypatch, **kwargs)
    with pytest.raises(server_module.AuthorizationDenied, match="requires the founder session"):
        check(SIGNED, False, PATH)


def test_an_unbound_caller_is_refused_and_an_empty_session_command_is_never_the_founder(monkeypatch):
    check, _ = gate(monkeypatch, bound=False)
    with pytest.raises(server_module.AuthorizationDenied):
        check({"method": "POST", "path": PATH, "session": {}}, False, PATH)
    with pytest.raises(server_module.AuthorizationDenied):
        check(SIGNED, False, PATH)


# -- end to end: a real server, the real signed transport, real device proof ---

def test_over_the_real_transport_the_founders_baboom_session_is_answered_and_a_codex_session_is_not(tmp_path):
    from nodelang.application_machine_transport import MachineResponseError
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from tests_replica.test_application_machine_transport import (
        _FounderLocalClient, _bind_runtime_device, _device_credential, _runtime_device_key,
    )

    descriptor_path = tmp_path / "baboom-founder-device-runtime.json"
    provider = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"f" * 32)
    server = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor_path,
                               machine_key_provider=provider).start()
    try:
        key, reference = _runtime_device_key()
        custody_root = _bind_runtime_device(server, reference, runtime="baboom")
        external = "founder-desktop-baboom"
        baboom = _FounderLocalClient(server, descriptor_path, provider)
        enrolled = baboom.bind_agent_session(
            runtime="baboom", external_session_id=external,
            device_credential_provider=lambda challenge: _device_credential(key, custody_root, challenge, external))
        assert enrolled["agent_session"].startswith("app:agent-session:runtime:")
        assert enrolled["agent_session"] != server.universal_registry.agent_body.session.root_id
        answered = baboom.respond_baboom_command(utterance="interrupt claude")
        assert answered["command"]["intent"] == "agent-interrupt"
        assert answered["response"]["kind"] == "agent-interrupt-ready"

        codex = _FounderLocalClient(server, descriptor_path, provider)
        codex.bind_agent_session(runtime="codex", external_session_id="codex-court-session")
        with pytest.raises(MachineResponseError, match="requires the founder session"):
            codex.respond_baboom_command(utterance="interrupt claude")
        with pytest.raises(MachineResponseError, match="requires the founder session"):
            codex.execute_baboom_command(utterance="interrupt claude")
    finally:
        server.close()


# -- what the founder reads when a confirmed act is refused --------------------

def test_the_companion_shows_the_graphs_own_refusal_and_keeps_other_failures_generic():
    import inspect
    from nodelang import baboom_native_companion as companion
    from nodelang.application_machine_transport import MachineResponseError, MachineTransportError
    codex = ("Codex agents can't be interrupted: Codex Desktop does not expose "
             "interrupt to other apps. Nothing was sent.")
    assert companion.baboom_execution_error_text(MachineResponseError(codex)) == codex
    generic = "BABOOM could not create the task."
    assert companion.baboom_execution_error_text(MachineResponseError("")) == generic
    assert companion.baboom_execution_error_text(MachineTransportError("pipe closed")) == generic
    assert companion.baboom_execution_error_text(RuntimeError("Traceback internals")) == generic
    source = inspect.getsource(companion)
    assert 'result = {"error": baboom_execution_error_text(error)}' in source
    assert 'error.strip() if isinstance(error, str) and error.strip()' in source
