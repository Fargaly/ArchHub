"""Regression courts for BABOOM's one-live-authority rule."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

import nodelang.universal_application as universal_application

from nodelang.cell_agent_body import (
    list_agent_body_roots,
    open_agent_body_protocol,
)
from nodelang.cell_agent_body_catalog import list_agent_body_catalog_entries
from nodelang.application_server import ApplicationServer
from nodelang.cell_change_history import read_change_transaction
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.cell_protocols import (
    compose_relation_cells,
    prepare_append_relation_members,
    read_relation,
)
from nodelang.cell_registry_projection import project_state_machine_protocol
from nodelang.cell_state_machine import ROLE_NAMES as STATE_MACHINE_ROLE_NAMES
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    _AGENT_BODY_BABOOM_POLICY_ROOT,
    _AGENT_BODY_BABOOM_ROOT,
    _AGENT_BODY_CATALOG_BABOOM_EXECUTION_ENTRY_ROOT,
    _AGENT_CAPABILITY_BABOOM_EXECUTION_CONTROL_ROOT,
    _BABOOM_LEGACY_MIGRATION_APPROVAL,
    _LEGACY_AGENT_BODY_BABOOM_EXECUTION_POLICY_ROOT,
    _LEGACY_AGENT_BODY_BABOOM_EXECUTION_ROOT,
    _LEGACY_AGENT_CONTROL_BABOOM_EXECUTION_ROOT,
    _ensure_baboom_application_agent_body_variant,
    build_universal_application,
    create_universal_governed_work,
    execute_universal_baboom_utterance,
    inspect_legacy_baboom_execution_migration,
    legacy_baboom_execution_migration_state,
    migrate_legacy_baboom_execution_body,
    migrate_legacy_baboom_execution_from_durable_store,
    project_universal_baboom_companion_directive,
    project_universal_baboom_context,
    project_universal_founder_baboom_capability_report,
    project_universal_founder_baboom_steward_briefing,
    project_universal_founder_model_council_report,
    project_universal_governed_work_status,
    respond_universal_baboom_utterance,
    resolve_universal_baboom_utterance,
    restore_universal_application,
    stage_legacy_baboom_execution_migration,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


NODE_LANGUAGE = Path(__file__).resolve().parents[1]
PRODUCT = NODE_LANGUAGE.parents[0]
_LEGACY_AUTHORITY_MARKERS = (
    "open_baboom_authority",
    "restore_baboom_authority",
    "build_baboom_authority",
    "import_baboom_relay_command",
    "apply_baboom_relay_receipt",
    "baboom_relay",
    "BaboomRelayClient",
    "/v1/baboom",
    "nodelang.baboom_briefs",
    ".baboom_briefs",
)

_RETIRED_LEGACY_PATHS = (
    NODE_LANGUAGE / "nodelang" / "cell_baboom.py",
    NODE_LANGUAGE / "nodelang" / "baboom_briefs.py",
    PRODUCT / "12.PRODUCTION" / "cloud_backend" / "baboom_relay.py",
    PRODUCT / "12.PRODUCTION" / "cloud_backend" / "baboom_relay_protocol.py",
)


def _durable_provider():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"r" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"e" * 32)
    return provider


def _legacy_duplicate_execution_graph(store=None, key_provider=None):
    """Construct the retired two-body shape without touching persisted state."""
    store, registry = build_universal_application(
        resolve_map_path(), store, key_provider=key_provider
    )
    context = registry.authorization.session.context()
    founder_view = registry.view_sessions[registry.authorization.subject_root]
    _ensure_baboom_application_agent_body_variant(
        store,
        registry.authorization,
        founder_view,
        registry.roles,
        registry.standard_library.lifecycle_protocol.states["wip"],
        registry.map.domains["models"],
        registry.governed_work_registry_root,
        registry.map.nodes["orch_baboom_assistant"],
        _LEGACY_AGENT_BODY_BABOOM_EXECUTION_ROOT,
        _LEGACY_AGENT_BODY_BABOOM_EXECUTION_POLICY_ROOT,
        _LEGACY_AGENT_CONTROL_BABOOM_EXECUTION_ROOT,
        lambda action, object_name: (
            "app:agent-body:baboom-execution:rule:%s:%s"
            % (action, object_name)
        ),
        "Legacy BABOOM execution",
        registry.application_root,
    )
    snapshot = store.snapshot()
    catalog = registry.agent_body_catalog.protocol
    members = read_relation(
        snapshot, _AGENT_BODY_CATALOG_BABOOM_EXECUTION_ENTRY_ROOT,
        budget=100_000,
    )
    rewrites = {
        catalog.role("body"): _LEGACY_AGENT_BODY_BABOOM_EXECUTION_ROOT,
        catalog.role("policy"): _LEGACY_AGENT_BODY_BABOOM_EXECUTION_POLICY_ROOT,
        catalog.role("control"): _LEGACY_AGENT_CONTROL_BABOOM_EXECUTION_ROOT,
    }
    replacements = []
    for role_root, target_root in rewrites.items():
        matches = tuple(member for member in members if member.role_id == role_root)
        assert len(matches) == 1
        incidence = snapshot.cells[matches[0].incidence_id]
        replacements.append(Cell(
            incidence.id, incidence.link0, target_root, incidence.atom
        ))
    store.commit(snapshot.revision, replace=tuple(replacements))
    return store, registry, context


def _production_python_sources() -> tuple[Path, ...]:
    roots = (
        NODE_LANGUAGE / "nodelang",
        PRODUCT / "12.PRODUCTION" / "cloud_backend",
        PRODUCT / "12.PRODUCTION" / "app",
        PRODUCT / "12.PRODUCTION" / "personal-brain-mcp" / "src",
        PRODUCT / "12.PRODUCTION" / "node_runtime",
    )
    sources: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if "tests" in path.parts or "tests_replica" in path.parts:
                continue
            sources.append(path)
    return tuple(sorted(sources))


def test_production_baboom_paths_have_no_retired_parallel_authority():
    assert all(not path.exists() for path in _RETIRED_LEGACY_PATHS)

    violations: dict[str, list[str]] = {}
    for path in _production_python_sources():
        source = path.read_text(encoding="utf-8")
        found = [
            marker for marker in _LEGACY_AUTHORITY_MARKERS if marker in source
        ]
        if found:
            violations[str(path.relative_to(PRODUCT))] = found

    assert violations == {}


def test_baboom_presence_and_action_profiles_share_one_agent_body():
    store, registry = build_universal_application(resolve_map_path())
    entries = {
        entry.runtime: entry
        for entry in list_agent_body_catalog_entries(
            store.snapshot(), registry.agent_body_catalog.protocol
        )
    }

    presence = entries["baboom"]
    action = entries["baboom-execution"]

    assert presence.body_root == "app:agent-body:baboom"
    assert action.body_root == presence.body_root
    assert action.policy_root == presence.policy_root
    assert action.control_root != presence.control_root
    assert action.control_root == "app:agent-capability:baboom:execution-control"
    assert action.work_events == ("claim", "submit", "block", "resume", "release")
    assert "app:agent-body:baboom-execution" not in store.snapshot().cells
    assert "app:agent-body:baboom-execution-policy" not in store.snapshot().cells
    assert legacy_baboom_execution_migration_state(store.snapshot()) == "current"


def test_legacy_duplicate_baboom_body_requires_explicit_graph_migration():
    store, registry, context = _legacy_duplicate_execution_graph()
    before = store.snapshot()

    preflight = inspect_legacy_baboom_execution_migration(before, registry)

    assert legacy_baboom_execution_migration_state(before) == "legacy"
    assert preflight.required is True
    assert preflight.legacy_body_root == _LEGACY_AGENT_BODY_BABOOM_EXECUTION_ROOT
    assert preflight.legacy_policy_root == _LEGACY_AGENT_BODY_BABOOM_EXECUTION_POLICY_ROOT
    assert preflight.legacy_control_root == _LEGACY_AGENT_CONTROL_BABOOM_EXECUTION_ROOT
    assert preflight.active_session_roots == ()
    assert preflight.blockers == ()
    assert store.snapshot().revision == before.revision

    with pytest.raises(PermissionError, match="explicit founder approval"):
        migrate_legacy_baboom_execution_body(
            store,
            registry,
            founder_approval="not-approved",
            authentication_context=context,
        )
    assert store.snapshot().revision == before.revision

    result = migrate_legacy_baboom_execution_body(
        store,
        registry,
        founder_approval=_BABOOM_LEGACY_MIGRATION_APPROVAL,
        authentication_context=context,
    )
    snapshot = store.snapshot()

    assert result.migrated is True
    assert result.revision == snapshot.revision
    assert result.receipt_root is not None
    entries = {
        entry.runtime: entry
        for entry in list_agent_body_catalog_entries(
            snapshot, registry.agent_body_catalog.protocol
        )
    }
    assert entries["baboom-execution"].body_root == _AGENT_BODY_BABOOM_ROOT
    assert (
        entries["baboom-execution"].policy_root
        == _AGENT_BODY_BABOOM_POLICY_ROOT
    )
    assert (
        entries["baboom-execution"].control_root
        == _AGENT_CAPABILITY_BABOOM_EXECUTION_CONTROL_ROOT
    )
    assert _LEGACY_AGENT_BODY_BABOOM_EXECUTION_ROOT in snapshot.cells
    assert _LEGACY_AGENT_BODY_BABOOM_EXECUTION_POLICY_ROOT in snapshot.cells
    assert _LEGACY_AGENT_CONTROL_BABOOM_EXECUTION_ROOT in snapshot.cells
    agent_protocol = open_agent_body_protocol(
        snapshot, prefix="app:agent-body-protocol"
    )
    assert _LEGACY_AGENT_BODY_BABOOM_EXECUTION_ROOT not in list_agent_body_roots(
        snapshot, agent_protocol
    )
    for relation_root in (
        registry.map.domains["models"],
        registry.application_root,
    ):
        members = read_relation(snapshot, relation_root, budget=100_000)
        assert not any(
            member.participant_id
            in {
                _LEGACY_AGENT_BODY_BABOOM_EXECUTION_ROOT,
                _LEGACY_AGENT_BODY_BABOOM_EXECUTION_POLICY_ROOT,
                _LEGACY_AGENT_CONTROL_BABOOM_EXECUTION_ROOT,
            }
            for member in members
        )
    receipt = read_change_transaction(
        snapshot, registry.change_history_protocol, result.receipt_root
    )
    assert _LEGACY_AGENT_BODY_BABOOM_EXECUTION_ROOT in receipt.scope_roots
    assert _AGENT_BODY_BABOOM_ROOT in receipt.scope_roots
    assert inspect_legacy_baboom_execution_migration(
        snapshot, registry
    ).required is False
    assert legacy_baboom_execution_migration_state(snapshot) == "current"


def test_legacy_duplicate_baboom_body_refuses_active_session_without_contract():
    store, registry, context = _legacy_duplicate_execution_graph()
    snapshot = store.snapshot()
    agent_protocol = open_agent_body_protocol(
        snapshot, prefix="app:agent-body-protocol"
    )
    session_root = "app:agent-session:runtime:legacy-baboom"
    session = compose_relation_cells(
        (
            (
                agent_protocol.role("session-body"),
                _LEGACY_AGENT_BODY_BABOOM_EXECUTION_ROOT,
            ),
            (agent_protocol.role("session-state"), agent_protocol.state("active")),
        ),
        relation_id=session_root,
    )
    registry_patch = prepare_append_relation_members(
        snapshot,
        agent_protocol.registry("session"),
        ((agent_protocol.role("session-member"), session_root),),
        budget=100_000,
    )
    store.commit(
        snapshot.revision,
        create=(*session.cells, *registry_patch.create),
        replace=registry_patch.replace,
    )
    before = store.snapshot()

    preflight = inspect_legacy_baboom_execution_migration(before, registry)

    assert preflight.active_session_roots == (session_root,)
    assert any("session migration contract" in blocker for blocker in preflight.blockers)
    with pytest.raises(PermissionError, match="migration is blocked"):
        migrate_legacy_baboom_execution_body(
            store,
            registry,
            founder_approval=_BABOOM_LEGACY_MIGRATION_APPROVAL,
            authentication_context=context,
        )
    assert store.snapshot().revision == before.revision


def test_durable_legacy_baboom_repair_stages_before_the_only_write(tmp_path):
    provider = _durable_provider()
    store, registry, context = _legacy_duplicate_execution_graph(
        CellStore(tmp_path / "legacy-baboom.sqlite3"), provider
    )
    before = store.snapshot()

    with pytest.raises(InvalidCell, match="before normal restore"):
        restore_universal_application(
            resolve_map_path(), store, key_provider=provider
        )
    assert store.snapshot().revision == before.revision

    staging = stage_legacy_baboom_execution_migration(
        resolve_map_path(),
        store,
        key_provider=provider,
        staging_path=tmp_path / "legacy-baboom-staging.sqlite3",
    )
    assert staging.source_revision == before.revision
    assert staging.preflight.required is True
    assert staging.preflight.blockers == ()
    assert store.snapshot().revision == before.revision
    with CellStore(tmp_path / "legacy-baboom-staging.sqlite3") as staged_store:
        assert staged_store.revision == staging.staging_revision

    result = migrate_legacy_baboom_execution_from_durable_store(
        resolve_map_path(),
        store,
        key_provider=provider,
        founder_approval=_BABOOM_LEGACY_MIGRATION_APPROVAL,
        authorizing_registry=registry,
        authentication_context=context,
        staging_path=tmp_path / "legacy-baboom-commit-staging.sqlite3",
    )
    assert result.migrated is True
    assert result.receipt_root is not None
    assert result.revision == store.revision

    _, restored = restore_universal_application(
        resolve_map_path(), store, key_provider=provider
    )
    assert inspect_legacy_baboom_execution_migration(
        store.snapshot(), restored
    ).required is False
    store.close()


def test_restore_migration_appends_missing_state_machine_role_as_graph_vocabulary():
    prefix = "app:standard-library:state-machine-protocol"
    missing_role = "required-evidence-admission"
    old_role_names = tuple(
        name for name in STATE_MACHINE_ROLE_NAMES if name != missing_role
    )
    store = CellStore()
    role_cells = tuple(
        Cell(
            "%s:role:%s" % (prefix, name),
            NULL_CELL_ID,
            NULL_CELL_ID,
            name.encode("ascii"),
        )
        for name in old_role_names
    )
    protocol_relation = compose_relation_cells(
        (
            ("%s:role:vocabulary-member" % prefix, cell.id)
            for cell in role_cells
        ),
        relation_id="%s:root" % prefix,
    )
    store.commit(
        store.revision,
        create=(*role_cells, *protocol_relation.cells),
    )
    before = store.snapshot()

    with pytest.raises(
        InvalidCell,
        match="required-evidence-admission",
    ):
        project_state_machine_protocol(before, prefix)

    migrated = (
        universal_application
        ._ensure_standard_library_state_machine_protocol_roles(store)
    )
    snapshot = store.snapshot()
    assert migrated == before.revision + 1
    assert snapshot.revision == before.revision + 1
    protocol = project_state_machine_protocol(snapshot, prefix)
    required_role_root = "%s:role:%s" % (prefix, missing_role)
    assert protocol.role(missing_role) == required_role_root
    assert snapshot.cells[required_role_root].atom == missing_role.encode("ascii")
    assert (
        "%s:role:vocabulary-member" % prefix,
        required_role_root,
    ) in {
        (member.role_id, member.participant_id)
        for member in read_relation(snapshot, "%s:root" % prefix, budget=100_000)
    }

    universal_application._ensure_standard_library_state_machine_protocol_roles(
        store
    )
    assert store.snapshot().revision == snapshot.revision


def test_baboom_context_and_founder_briefing_are_lenses_of_one_graph_revision():
    store, registry = build_universal_application(resolve_map_path())
    context = registry.authorization.session.context()

    baboom_context = project_universal_baboom_context(
        store,
        registry,
        authentication_context=context,
    )
    briefing = project_universal_founder_baboom_steward_briefing(
        store,
        registry,
        authentication_context=context,
    )

    assert baboom_context["cell_native"] is True
    assert baboom_context["context_lens"] == "app:baboom-context:v3"
    assert baboom_context["activity"] == {
        "active_baboom_devices": 0,
        "foreground_apps": {},
    }
    assert baboom_context["meeting_notes"] == {"active_sessions": 0}
    assert baboom_context["persona_form"] == "focus"
    assert baboom_context["device"] == {
        "enrollment_handoff_available": False,
        "current_runtime_proven": False,
        "active_baboom_devices": 0,
        "native_identity_provider_configured": False,
        "issued_cloud_sessions": 0,
        "remote_gateway_serving": False,
    }
    assert briefing["projection"] == "founder-local-baboom-steward-briefing"
    assert briefing["revision"] == store.revision
    assert briefing["context"] == baboom_context
    assert all(
        briefing[name]["revision"] == briefing["revision"]
        for name in ("governed_work", "workshop", "attention")
    )


def test_baboom_companion_directive_is_a_content_free_graph_projection():
    store, registry = build_universal_application(resolve_map_path())
    context = registry.authorization.session.context()

    idle = project_universal_baboom_companion_directive(
        store, registry, authentication_context=context
    )
    assert idle["message"] == "No governed Work needs attention."
    create_universal_governed_work(
        store,
        registry,
        title="Private task name must not reach BABOOM presence",
        description="A private Work description must not become presentation data.",
        priority=20,
        external_key="baboom-directive-content-free",
        references={"scope": registry.map.domains["brain"]},
        x=420.0,
        y=300.0,
        authentication_context=context,
    )
    directive = project_universal_baboom_companion_directive(
        store, registry, authentication_context=context
    )

    assert directive["projection"] == "app:baboom-companion-directive:v1"
    assert directive["revision"] == store.revision
    assert directive["fingerprint"] != idle["fingerprint"]
    assert directive["action"] == "claim-next-governed-work"
    assert directive["motion"] == "working"
    assert directive["message"] == "1 Work item is ready to claim."
    assert "Private task name" not in json.dumps(directive, sort_keys=True)
    assert "private Work description" not in json.dumps(directive, sort_keys=True)

    create_universal_governed_work(
        store,
        registry,
        title="Another private Work title stays outside the directive",
        description="Presence must still expose only aggregate Work state.",
        priority=20,
        external_key="baboom-directive-content-free-two",
        references={"scope": registry.map.domains["brain"]},
        x=440.0,
        y=300.0,
        authentication_context=context,
    )
    updated = project_universal_baboom_companion_directive(
        store, registry, authentication_context=context
    )

    assert updated["message"] == "2 Work items are ready to claim."
    assert updated["fingerprint"] != directive["fingerprint"]
    assert "Another private Work title" not in json.dumps(updated, sort_keys=True)


def test_baboom_utterance_resolution_uses_the_persisted_command_catalog():
    store, registry = build_universal_application(resolve_map_path())
    context = registry.authorization.session.context()
    before = store.snapshot()

    plan = resolve_universal_baboom_utterance(
        store,
        registry,
        utterance="BABOOM, show my plan",
        authentication_context=context,
    )
    task = resolve_universal_baboom_utterance(
        store,
        registry,
        utterance="Assign task: audit the node-native handoff",
        authentication_context=context,
    )
    model = resolve_universal_baboom_utterance(
        store,
        registry,
        utterance="Assign task to Claude: inspect the migration receipt",
        authentication_context=context,
    )

    assert plan == {
        "catalog": "app:baboom-command-catalog:v1",
        "intent": "show-claimed-work-plan",
        "payload": "BABOOM, show my plan",
        "revision": before.revision,
    }
    assert task["intent"] == "assign-task"
    assert task["payload"] == "audit the node-native handoff"
    assert model["intent"] == "model-task"
    assert json.loads(model["payload"]) == {
        "provider": "claude",
        "task": "inspect the migration receipt",
    }
    assert store.snapshot().revision == before.revision
    assert registry.baboom_command_catalog.root_id in before.cells
    assert len(registry.baboom_command_catalog.entries) >= 20


def test_explicit_baboom_task_command_creates_one_unclaimed_graph_work():
    store, registry = build_universal_application(resolve_map_path())
    context = registry.authorization.session.context()

    created = execute_universal_baboom_utterance(
        store,
        registry,
        utterance="BABOOM, assign task: audit the native handoff evidence",
        authentication_context=context,
    )
    replayed = execute_universal_baboom_utterance(
        store,
        registry,
        utterance="Assign task: audit the native handoff evidence",
        authentication_context=context,
    )

    assert created["intent"] == "assign-task"
    assert created["created"] is True
    assert created["state"] == "open"
    assert replayed == {**created, "created": False}
    status = project_universal_governed_work_status(
        store, registry, authentication_context=context
    )
    assert status["counts"]["open"] == 1
    assert status["items"][0]["root"] == created["work"]
    assert status["items"][0]["claimant_session"] is None
    assert (
        status["items"][0]["interfaces"]["description"]["value"]
        == "Founder-assigned through BABOOM.\\n\\naudit the native handoff evidence"
    )
    assert (
        "POST /api/universal/baboom-command-execute"
        in registry.application_http_route_roots
    )

    with pytest.raises(InvalidCell, match="Assign task"):
        execute_universal_baboom_utterance(
            store,
            registry,
            utterance="Assign task to Claude: inspect the handoff evidence",
            authentication_context=context,
        )


def test_baboom_command_response_is_detailed_read_only_graph_context():
    store, registry = build_universal_application(resolve_map_path())
    context = registry.authorization.session.context()
    before = store.revision

    briefing = respond_universal_baboom_utterance(
        store,
        registry,
        utterance="BABOOM, brief me on ArchHub",
        authentication_context=context,
    )
    task = respond_universal_baboom_utterance(
        store,
        registry,
        utterance="Assign task: review current authority evidence",
        authentication_context=context,
    )
    model = respond_universal_baboom_utterance(
        store,
        registry,
        utterance="Assign task to Gemini: compare the current research plan",
        authentication_context=context,
    )
    council = respond_universal_baboom_utterance(
        store,
        registry,
        utterance="BABOOM, model council",
        authentication_context=context,
    )

    assert briefing["command"]["intent"] == "steward-briefing"
    assert briefing["response"]["kind"] == "steward-briefing"
    assert briefing["response"]["data"]["revision"] == before
    assert set(briefing["response"]["data"]) == {
        "projection", "revision", "context", "governed_work", "workshop", "attention",
    }
    assert task["response"] == {
        "kind": "task-confirmation",
        "summary": "Ready to create one open, unclaimed Governed Work.",
        "data": {
            "task": "review current authority evidence",
            "requires": "explicit execute",
        },
    }
    assert model["response"]["kind"] == "model-review-requirement"
    assert model["response"]["data"] == {
        "provider": "gemini",
        "task": "compare the current research plan",
        "requires": "cognition request and founder approval",
    }
    assert council["command"]["intent"] == "model-council-report"
    assert council["response"]["kind"] == "model-council-report"
    assert council["response"]["data"]["admitted_providers"] == [
        "claude", "gemini", "gpt", "local", "openrouter",
    ]
    assert council["response"]["data"]["pending_providers"] == [
        "claude", "gemini", "gpt", "local", "openrouter",
    ]
    assert store.revision == before


def test_model_council_report_is_bounded_and_upgrades_an_existing_catalog(monkeypatch):
    original_specs = universal_application._BABOOM_COMMAND_SPECS
    old_specs = tuple(
        spec for spec in original_specs if spec[0] != "model-council-report"
    )
    monkeypatch.setattr(universal_application, "_BABOOM_COMMAND_SPECS", old_specs)
    key_provider = _durable_provider()
    store, _old_registry = build_universal_application(
        resolve_map_path(), key_provider=key_provider
    )
    old_revision = store.revision
    monkeypatch.setattr(
        universal_application, "_BABOOM_COMMAND_SPECS", original_specs
    )
    store, registry = restore_universal_application(
        resolve_map_path(), store, key_provider=key_provider
    )
    context = registry.authorization.session.context()
    create_universal_governed_work(
        store,
        registry,
        title="Compare current model reviews",
        description="Bound the provider council before a proposed action.",
        priority=70,
        external_key="court:model-council:public",
        x=240,
        y=180,
        authentication_context=context,
    )
    create_universal_governed_work(
        store,
        registry,
        title="60.PERSONAL model material",
        description="This must remain protected from the council report.",
        priority=90,
        external_key="court:model-council:protected",
        x=280,
        y=180,
        authentication_context=context,
    )

    report = project_universal_founder_model_council_report(
        store, registry, authentication_context=context
    )

    assert store.revision > old_revision
    assert "model-council-report" in registry.baboom_command_catalog.entries
    assert report["projection"] == "founder-local-model-council-report"
    assert report["state"] == "research-not-started"
    assert report["work_count"] == 2
    assert any(item["title"] == "Compare current model reviews" for item in report["work"])
    assert "60.PERSONAL" not in json.dumps(report, sort_keys=True)


def test_founder_http_command_route_resolves_then_executes_one_task():
    server = ApplicationServer().start()
    headers = {
        "Content-Type": "application/json",
        "X-ArchHub-Session": server.browser_session_token,
    }
    try:
        resolved_request = urllib.request.Request(
            server.url + "/api/universal/baboom-command",
            method="POST",
            headers=headers,
            data=json.dumps({
                "utterance": "BABOOM, assign task: review the graph evidence",
            }).encode("utf-8"),
        )
        resolved = json.loads(
            urllib.request.urlopen(resolved_request, timeout=10).read()
        )
        assert resolved["ok"] is True
        assert resolved["intent"] == "assign-task"

        response_request = urllib.request.Request(
            server.url + "/api/universal/baboom-command-response",
            method="POST",
            headers=headers,
            data=json.dumps({
                "utterance": "BABOOM, workshop report",
            }).encode("utf-8"),
        )
        response = json.loads(
            urllib.request.urlopen(response_request, timeout=10).read()
        )
        assert response["ok"] is True
        assert response["command"]["intent"] == "workshop-report"
        assert response["response"]["kind"] == "workshop-report"

        execute_request = urllib.request.Request(
            server.url + "/api/universal/baboom-command-execute",
            method="POST",
            headers=headers,
            data=json.dumps({
                "utterance": "Assign task: review the graph evidence",
            }).encode("utf-8"),
        )
        created = json.loads(
            urllib.request.urlopen(execute_request, timeout=10).read()
        )
        replayed = json.loads(
            urllib.request.urlopen(execute_request, timeout=10).read()
        )
        assert created["ok"] is True
        assert created["created"] is True
        assert created["state"] == "open"
        assert replayed == {**created, "created": False}
    finally:
        server.close()


def test_baboom_capability_map_is_a_single_revision_graph_projection():
    store, registry = build_universal_application(resolve_map_path())

    report = project_universal_founder_baboom_capability_report(store, registry)

    assert report["projection"] == "founder-local-baboom-capability-report"
    assert report["revision"] == store.revision
    assert {
        entry["root"] for entry in report["models"]
    } == set(registry.baboom_model_provider_roots.values())
    assert {
        entry["root"] for entry in report["connectors"]
    } == set(registry.baboom_connector_provider_roots.values())
    assert {
        entry["operation"] for entry in report["connectors"]
    } == {
        "archhub.department.run_once",
        "notion.append_blocks",
        "teams.list_meetings",
        "teams.open_meeting",
    }
    assert "GET /api/universal/baboom-capabilities" in report["routes"]
    assert report["routes"] == sorted(set(report["routes"]))
