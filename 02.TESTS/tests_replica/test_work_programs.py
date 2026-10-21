"""Court: a task names the programs it may use, and that choice reaches the host gate.

The only place a task's host admission lives is its existing requirements
interface (``requirements.hosts``): written at creation through
structured_references and changed through the existing Work configuration
path. These courts refuse an unknown or repeated program, and prove end to end
on a real application server and machine transport that the programs chosen at
creation are what the claiming session's configuration read returns.
"""
from __future__ import annotations

import pytest

from nodelang.universal_cell import InvalidCell


def test_only_the_five_known_programs_are_admitted():
    from nodelang.existing_workshop_project_revision import WORK_PROGRAMS, validate_work_hosts
    assert list(WORK_PROGRAMS) == ["revit", "acad", "max", "rhino", "blender"]
    validate_work_hosts({"hosts": ["revit", "max"]})
    validate_work_hosts({"hosts": []})
    validate_work_hosts({"gate": {}})
    for bad in (["paint"], ["revit", "revit"], "revit", [1]):
        with pytest.raises(InvalidCell, match="Programs"):
            validate_work_hosts({"hosts": bad})


def test_the_configuration_path_refuses_an_unknown_program(tmp_path):
    from nodelang.existing_workshop_project_revision import validate_work_configuration
    with pytest.raises(InvalidCell, match="Programs"):
        validate_work_configuration(None, None, "work", purpose="general", current={},
            proposed={"requirements": {"hosts": ["paint"]}}, workspace_root=tmp_path, context=None)


def _server(tmp_path):
    from nodelang.application_machine_transport import UniversalRuntimeClient
    from nodelang.application_server import ApplicationServer
    from nodelang.cell_secret_keys import MemorySigningKeyProvider
    from tests_replica.test_application_machine_transport import _green_runtime_compliance
    descriptor = tmp_path / "active-universal-runtime.json"
    provider = MemorySigningKeyProvider("archhub.local.universal-runtime-pipe", b"q" * 32)
    server = ApplicationServer(enable_machine_transport=True, machine_descriptor_path=descriptor,
        machine_key_provider=provider, universal_workspace_root=tmp_path,
        runtime_compliance_runner=_green_runtime_compliance).start()
    return server, UniversalRuntimeClient(descriptor, provider)


def test_programs_chosen_at_creation_reach_the_claiming_session(tmp_path):
    from nodelang.universal_application import create_universal_governed_work
    server, client = _server(tmp_path)
    try:
        with pytest.raises(InvalidCell, match="Programs"):
            create_universal_governed_work(server.universal_store, server.universal_registry,
                title="Refused", description="", priority=1, external_key="court:programs:bad",
                structured_references={"requirements": {"hosts": ["paint"]}}, x=0, y=0)
        work, _wire, _revision = create_universal_governed_work(
            server.universal_store, server.universal_registry,
            title="Count the doors", description="Read the open model.", priority=10,
            external_key="court:programs:v1",
            structured_references={
                "requirements": {"hosts": ["revit"],
                                 "gate": {"kind": "file_exists", "spec": {"path": "green.flag"}}},
                "cde-container": {"container_id": "court-programs", "allowed_paths": ["."]},
            }, x=320, y=240)
        (tmp_path / "green.flag").write_text("green", encoding="utf-8")
        client.bind_agent_session(runtime="codex", external_session_id="court-programs")
        client.request("POST", "/api/universal/work-transition",
                       {"root": work, "event": "claim", "evidence": "", "projection": "receipt-v1"})
        read = client.current_work_configuration()
        assert read["work"]["root"] == work
        assert read["work"]["configuration"]["fields"]["requirements"]["value"]["hosts"] == ["revit"]
    finally:
        server.close()
