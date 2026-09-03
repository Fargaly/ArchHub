"""Court for Cell-native shared Workshop work assignments."""
from __future__ import annotations

import pytest
import nodelang.universal_application as universal_application_module

from nodelang.application_machine_transport import (
    MachineTransportError,
    UniversalRuntimeClient,
)
from nodelang.application_server import ApplicationServer
from nodelang.cell_attention import read_obligation
from nodelang.cell_attestations import CourtResult
from nodelang.cell_deliberation import read_deliberation_space
from nodelang.cell_protocols import read_relation
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.universal_application import (
    create_universal_governed_work,
    project_universal_canvas,
    set_universal_scope,
)


def _green_runtime_compliance(_invocation):
    return CourtResult(
        True,
        {
            "runtime-detected": True,
            "required-hooks": True,
            "schema-valid": True,
            "brain-connected": True,
            "scope-gate": True,
            "workshop-authority": True,
        },
        {"adapter": "test-runtime-auditor"},
    )


def _assign(server, *, assignment_id, work_root, agent_session_root):
    """Exercise the graph-routed founder assignment action directly."""
    return server.dispatch_universal_machine_route({
        "method": "POST",
        "path": "/api/universal/workshop-assignment",
        "body": {
            "assignment_id": assignment_id,
            "work": work_root,
            "agent_session": agent_session_root,
        },
    })


def _endpoint_owner(snapshot, registry, member):
    """Resolve a relation incidence through its real interface when present."""
    interface = universal_application_module._project_canvas_interface(
        snapshot,
        registry.assembly_protocol,
        member.participant_id,
    )
    return str(interface["owner"]) if interface is not None else member.participant_id


def test_shared_workshop_assignments_are_atomic_and_gate_claims(tmp_path):
    descriptor_path = tmp_path / "workshop-assignments-runtime.json"
    provider = MemorySigningKeyProvider(
        "archhub.local.universal-runtime-pipe", b"a" * 32
    )
    server = ApplicationServer(
        enable_machine_transport=True,
        machine_descriptor_path=descriptor_path,
        machine_key_provider=provider,
        universal_workspace_root=tmp_path,
        runtime_compliance_runner=_green_runtime_compliance,
    ).start()
    try:
        work_root, _wire, _revision = create_universal_governed_work(
            server.universal_store,
            server.universal_registry,
            title="Coordinate one shared Cell-native work item",
            description="Two agents need plan, source evidence, and review.",
            priority=100,
            external_key="court:workshop:shared-assignment",
            x=480,
            y=320,
        )
        agent_a = UniversalRuntimeClient(descriptor_path, provider)
        agent_b = UniversalRuntimeClient(descriptor_path, provider)
        agent_c = UniversalRuntimeClient(descriptor_path, provider)
        session_a = agent_a.bind_agent_session(
            runtime="codex",
            external_session_id="court-workshop-assignment-a",
        )["agent_session"]
        session_b = agent_b.bind_agent_session(
            runtime="claude",
            external_session_id="court-workshop-assignment-b",
        )["agent_session"]
        session_c = agent_c.bind_agent_session(
            runtime="gemini",
            external_session_id="court-workshop-assignment-c",
        )["agent_session"]
        workshop_space = read_deliberation_space(
            server.universal_store.snapshot(),
            server.universal_registry.deliberation_protocol,
            server.universal_registry.workshop_root,
        )
        assert set(workshop_space.participant_roots) >= {
            server.universal_registry.authorization.subject_root,
            session_a,
            session_b,
            session_c,
        }

        before_assignment = server.universal_store.revision
        assigned_a = _assign(
            server,
            assignment_id="app:workshop-assignment:court-a",
            work_root=work_root,
            agent_session_root=session_a,
        )
        assert assigned_a["work"] == work_root
        assert assigned_a["agent_session"] == session_a
        assert server.universal_store.revision == before_assignment + 1

        snapshot = server.universal_store.snapshot()
        members = read_relation(snapshot, assigned_a["root"], budget=64)
        roles = server.universal_registry.roles
        assert {
            member.role_id: (
                _endpoint_owner(snapshot, server.universal_registry, member)
                if member.role_id in {roles["source"], roles["target"]}
                else member.participant_id
            ) for member in members
        } == {
            roles["source"]: work_root,
            roles["target"]: session_a,
            roles["authority"]: assigned_a["obligation"],
            roles["scope"]: server.universal_registry.workshop_root,
        }
        obligation = read_obligation(
            snapshot,
            server.universal_registry.attention_protocol,
            assigned_a["obligation"],
        )
        assert obligation.subject_root == work_root
        assert obligation.owner_root == session_a
        assert obligation.court_roots == (
            server.universal_registry.work_completion_court_root,
        )
        assignment_members = {
            member.participant_id
            for member in read_relation(
                snapshot,
                server.universal_registry.workshop_assignment_registry_root,
                budget=100_000,
            )
            if member.role_id == roles["member"]
        }
        assert assignment_members == {assigned_a["root"]}

        repeated = _assign(
            server,
            assignment_id="app:workshop-assignment:court-a",
            work_root=work_root,
            agent_session_root=session_a,
        )
        assert repeated == {
            **assigned_a,
            "revision": server.universal_store.revision,
        }
        assert server.universal_store.revision == before_assignment + 1

        assigned_b = _assign(
            server,
            assignment_id="app:workshop-assignment:court-b",
            work_root=work_root,
            agent_session_root=session_b,
        )
        assert assigned_b["work"] == work_root
        workbench = read_relation(
            server.universal_store.snapshot(),
            server.universal_registry.workshop_workbench_root,
            budget=100_000,
        )
        assert {
            item.participant_id for item in workbench
            if item.role_id == roles["member"]
        } >= {
            work_root,
            session_a,
            session_b,
            server.universal_registry.work_completion_court_root,
        }
        assignment_relation_roots = {
            item.participant_id for item in workbench
            if item.role_id == roles["relation"]
        }
        assert {assigned_a["root"], assigned_b["root"]} <= assignment_relation_roots
        direct_relations = {
            root: read_relation(
                server.universal_store.snapshot(), root, budget=64
            ) for root in assignment_relation_roots
        }
        assert any(
            {
                item.role_id: (
                    _endpoint_owner(
                        server.universal_store.snapshot(),
                        server.universal_registry,
                        item,
                    ) if item.role_id in {roles["source"], roles["target"]}
                    else item.participant_id
                ) for item in members
            }.get(roles["source"]) == work_root
            and {
                item.role_id: (
                    _endpoint_owner(
                        server.universal_store.snapshot(),
                        server.universal_registry,
                        item,
                    ) if item.role_id in {roles["source"], roles["target"]}
                    else item.participant_id
                ) for item in members
            }.get(roles["target"])
            == server.universal_registry.work_completion_court_root
            for members in direct_relations.values()
        )
        with pytest.raises(MachineTransportError, match="assigned to a different"):
            agent_c.claim_work(work_root)
        with pytest.raises(MachineTransportError, match="plan and source-backed research"):
            agent_a.claim_work(work_root)

        before_plan = server.universal_store.revision
        plan = agent_a.request("POST", "/api/universal/workshop", {
            "category": "plan",
            "text": "Plan the shared assignment before claiming it.",
            "refs": [work_root],
            "evidence": [],
            "recipients": [],
            "reply_to": None,
            "idempotency_key": "court:workshop-assignment:plan",
            "created_at": "2026-07-21T10:00:00+00:00",
        })
        assert server.universal_store.revision == before_plan + 1
        before_research = server.universal_store.revision
        research = agent_b.request("POST", "/api/universal/workshop", {
            "category": "research",
            "text": "Attach the source-backed research needed for coordination.",
            "refs": [work_root],
            "evidence": [server.universal_registry.map.grand_map_root],
            "recipients": [],
            "reply_to": None,
            "idempotency_key": "court:workshop-assignment:research",
            "created_at": "2026-07-21T10:01:00+00:00",
        })
        assert server.universal_store.revision == before_research + 1
        assert plan["root"] != research["root"]
        workbench_after_evidence = read_relation(
            server.universal_store.snapshot(),
            server.universal_registry.workshop_workbench_root,
            budget=100_000,
        )
        assert {
            item.participant_id for item in workbench_after_evidence
            if item.role_id == roles["member"]
        } >= {
            plan["root"],
            research["root"],
            server.universal_registry.map.grand_map_root,
        }
        evidence_relation_roots = {
            item.participant_id for item in workbench_after_evidence
            if item.role_id == roles["relation"]
        }
        evidence_relations = {
            root: read_relation(
                server.universal_store.snapshot(), root, budget=64
            ) for root in evidence_relation_roots
        }
        endpoints = {
                (
                    _endpoint_owner(
                        server.universal_store.snapshot(),
                        server.universal_registry,
                        next(
                            item for item in members
                            if item.role_id == roles["source"]
                        ),
                    ),
                    _endpoint_owner(
                        server.universal_store.snapshot(),
                        server.universal_registry,
                        next(
                            item for item in members
                            if item.role_id == roles["target"]
                        ),
                    ),
            )
            for members in evidence_relations.values()
            if sum(item.role_id == roles["source"] for item in members) == 1
            and sum(item.role_id == roles["target"] for item in members) == 1
        }
        assert {
            (work_root, plan["root"]),
            (work_root, research["root"]),
            (research["root"], server.universal_registry.map.grand_map_root),
        } <= endpoints
        set_universal_scope(
            server.universal_store,
            server.universal_registry,
            server.universal_registry.map.domains["brain"],
        )
        set_universal_scope(
            server.universal_store,
            server.universal_registry,
            server.universal_registry.workshop_workbench_root,
        )
        canvas = project_universal_canvas(
            server.universal_store, server.universal_registry
        )
        ports = {
            (node["id"], port["id"]): port
            for node in canvas["nodes"]
            for port in node["ports"]
        }
        assert canvas["wires"]
        for wire in canvas["wires"]:
            assert wire["source_interface"]
            assert wire["target_interface"]
            assert wire["source_incidence"] in ports[
                (wire["source"], wire["source_interface"])
            ]["endpoint_incidences"]
            assert wire["target_incidence"] in ports[
                (wire["target"], wire["target_interface"])
            ]["endpoint_incidences"]
        claimed = agent_a.claim_work(work_root)
        assert claimed["claimed"] is True
        assert claimed["work"]["claimant_session"] == session_a

        projected = server.dispatch_universal_machine_route({
            "method": "GET",
            "path": "/api/universal/workshop-assignments",
            "body": {},
        })
        assert projected["registry"] == (
            server.universal_registry.workshop_assignment_registry_root
        )
        assert {
            (item["work"], item["agent_session"])
            for item in projected["assignments"]
        } == {(work_root, session_a), (work_root, session_b)}
    finally:
        server.close()
