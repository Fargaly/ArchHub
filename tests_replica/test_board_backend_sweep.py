from __future__ import annotations

import hashlib

import pytest

import nodelang.universal_application as ua
from nodelang.cell_attestations import CourtResult
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.cell_runtime_presence import renew_runtime_presence
from nodelang.application_server import ApplicationServer
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    adjudicate_universal_governed_work,
    attest_universal_runtime_compliance,
    begin_universal_runtime_agent_session,
    build_universal_application,
    claim_next_universal_governed_work,
    claim_universal_governed_work,
    create_universal_governed_work,
    dry_run_workshop_board_sweep,
    edit_universal_property,
    project_universal_canvas,
    project_universal_governed_work_status,
    restore_archived_workshop_board_task,
    sweep_workshop_board_tasks,
    transition_universal_governed_work,
)
from nodelang.universal_cell import Cell, NULL_CELL_ID


def _green_runtime_compliance(_invocation):
    return CourtResult(True, {
        "runtime-detected": True,
        "required-hooks": True,
        "schema-valid": True,
        "brain-connected": True,
        "scope-gate": True,
        "workshop-authority": True,
    }, {"adapter": "board-backend-court"})


def _application(tmp_path):
    (tmp_path / "done.flag").write_text("done\n", encoding="utf-8", newline="")
    return build_universal_application(
        resolve_map_path(),
        court_workspace_root=tmp_path,
        runtime_compliance_runner=_green_runtime_compliance,
    )


def _context(registry):
    return registry.authorization.session.context()


def _work(store, registry, title):
    root, _wire, _revision = create_universal_governed_work(
        store,
        registry,
        title=title,
        priority=100,
        structured_references={
            "requirements": {
                "gate": {"kind": "file_exists", "spec": {"path": "done.flag"}},
            },
            "cde-container": {"allowed_paths": ["."]},
        },
        x=500,
        y=500,
        authentication_context=_context(registry),
    )
    return root


def _session(store, registry, label):
    root = "app:agent-session:runtime:board-backend-" + label
    fingerprint = hashlib.sha256(label.encode("utf-8")).hexdigest()
    session, _revision = begin_universal_runtime_agent_session(
        store,
        registry,
        session_root=root,
        runtime="codex",
        external_session_fingerprint=fingerprint,
        authentication_context=_context(registry),
    )
    compliance, _evidence_root, _revision = attest_universal_runtime_compliance(
        store,
        registry,
        agent_session_root=session.root_id,
        runtime="codex",
        external_session_fingerprint=fingerprint,
        authentication_context=_context(registry),
    )
    return session.root_id, compliance.root_id


def _claim(store, registry, work_root, session_root, compliance_root):
    claimed = claim_universal_governed_work(
        store,
        registry,
        agent_session_root=session_root,
        work_root=work_root,
        compliance_observation_root=compliance_root,
        authentication_context=_context(registry),
    )
    assert claimed["work"]["root"] == work_root
    return claimed


def _state(store, registry, work_root):
    status = project_universal_governed_work_status(
        store,
        registry,
        authentication_context=_context(registry),
    )
    return next(
        item["operational"]["current_state_label"].casefold()
        for item in status["items"] if item["root"] == work_root
    )


def _workshop_archive_param(store, registry):
    canvas = project_universal_canvas(
        store,
        registry,
        authentication_context=_context(registry),
    )
    node = next(
        row for row in canvas["nodes"]
        if row["id"] == ua._system_tool_canvas_root("tool_workshop")
    )
    return next(
        row for row in node["params"]
        if row["label"] == "archive_after_idle_days"
    )


def test_board_backend_archive_days_property_round_trips_to_node_and_owner(tmp_path):
    store, registry = _application(tmp_path)
    param = _workshop_archive_param(store, registry)
    assert param["value"] == 20

    edit_universal_property(
        store,
        registry,
        param["relation"],
        "30",
        mutation_route="/api/universal/set-property",
        authentication_context=_context(registry),
    )

    reloaded = _workshop_archive_param(store, registry)
    report = dry_run_workshop_board_sweep(
        store,
        registry,
        authentication_context=_context(registry),
    )
    assert reloaded["value"] == 30
    assert report["archive_after_idle_days"] == 30

    # The accepted history fields follow the same real admitted owner change.
    history = project_universal_canvas(
        store, registry, authentication_context=_context(registry),
    )["action_history"]["transactions"]
    action = next(row for row in history
                  if row["route"] == "POST /api/universal/set-property"
                  and row["state"] == "applied")
    assert action["actor"] == "catalog.configure"
    assert action["target_root"] == ua._system_tool_canvas_root("tool_workshop")
    assert action["target_label"] == "Workshop"


def test_board_backend_tick_archives_idle_done_only_and_restore_returns_done(
    tmp_path,
    monkeypatch,
):
    store, registry = _application(tmp_path)
    server = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
        runtime_compliance_runner=_green_runtime_compliance,
    )
    archive_param = _workshop_archive_param(store, registry)
    edit_universal_property(
        store,
        registry,
        archive_param["relation"],
        "30",
        mutation_route="/api/universal/set-property",
        authentication_context=_context(registry),
    )
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 120_000.0)
    done = _work(store, registry, "tick old done archive")
    done_session, done_compliance = _session(store, registry, "tick-done")
    _claim(store, registry, done, done_session, done_compliance)
    transition_universal_governed_work(
        store,
        registry,
        done,
        "submit",
        agent_session_root=done_session,
        evidence_payload="artifact is ready",
        authentication_context=_context(registry),
    )
    adjudicate_universal_governed_work(
        store,
        registry,
        done,
        requesting_agent_session_root=done_session,
        workspace_root=tmp_path,
        authentication_context=_context(registry),
    )
    review = _work(store, registry, "tick live review kept")
    review_session, review_compliance = _session(store, registry, "tick-review")
    _claim(store, registry, review, review_session, review_compliance)
    transition_universal_governed_work(
        store,
        registry,
        review,
        "submit",
        agent_session_root=review_session,
        evidence_payload="artifact needs review",
        authentication_context=_context(registry),
    )
    assert _state(store, registry, done) == "complete"
    assert _state(store, registry, review) == "review"

    tick_time = 120_000.0 + (31 * 86400)
    _live_presence(store, registry, review_session, now=tick_time)
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: tick_time)
    tick = server.dispatch_universal_machine_route({
        "method": "POST",
        "path": "/api/universal/workshop-board/tick",
        "body": {},
    })
    assert tick["archive_after_idle_days"] == 30
    assert done in tick["archived"]
    assert review not in tick["archived"]
    assert _state(store, registry, done) == "cancelled"
    assert _state(store, registry, review) == "review"

    restored = server.dispatch_universal_machine_route({
        "method": "POST",
        "path": "/api/universal/workshop-board/restore-archived",
        "body": {"root": done},
    })
    assert restored["state"] == "complete"
    assert _state(store, registry, done) == "complete"


def _live_presence(store, registry, session_root, now):
    custody_root = "device-custody:sha256:board-backend-" + hashlib.sha256(
        session_root.encode("utf-8")
    ).hexdigest()
    if custody_root not in store.snapshot().cells:
        store.commit(
            store.revision,
            create=(Cell(custody_root, NULL_CELL_ID, NULL_CELL_ID, b"custody"),),
        )
    renew_runtime_presence(
        store,
        registry.runtime_presence_protocol,
        agent_session_root=session_root,
        device_custody_root=custody_root,
        runtime="codex",
        now=now,
        lease_seconds=900.0,
    )


def test_board_backend_dead_agent_task_leaves_wip_within_one_sweep(tmp_path, monkeypatch):
    store, registry = _application(tmp_path)
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 1_000.0)
    work = _work(store, registry, "dead agent release")
    session, compliance = _session(store, registry, "dead")
    _claim(store, registry, work, session, compliance)

    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 2_901.0)
    result = sweep_workshop_board_tasks(
        store,
        registry,
        authentication_context=_context(registry),
    )

    assert work in result["released"]
    assert _state(store, registry, work) == "open"


def test_board_backend_idle_task_without_live_agent_returns_to_planned(tmp_path, monkeypatch):
    store, registry = _application(tmp_path)
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 10_000.0)
    work = _work(store, registry, "idle agent release")
    session, compliance = _session(store, registry, "idle")
    _claim(store, registry, work, session, compliance)

    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 11_801.0)
    sweep_workshop_board_tasks(store, registry, authentication_context=_context(registry))

    assert _state(store, registry, work) == "open"


def test_board_backend_live_agent_is_untouched(tmp_path, monkeypatch):
    store, registry = _application(tmp_path)
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 20_000.0)
    work = _work(store, registry, "live agent untouched")
    session, compliance = _session(store, registry, "live")
    _claim(store, registry, work, session, compliance)
    _live_presence(store, registry, session, now=21_700.0)

    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 21_801.0)
    result = sweep_workshop_board_tasks(
        store,
        registry,
        authentication_context=_context(registry),
    )

    assert work not in result["released"]
    assert _state(store, registry, work) == "claimed"


def test_board_backend_done_old_archives_and_restore_works(tmp_path, monkeypatch):
    store, registry = _application(tmp_path)
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 30_000.0)
    work = _work(store, registry, "old done archive")
    session, compliance = _session(store, registry, "done")
    _claim(store, registry, work, session, compliance)
    transition_universal_governed_work(
        store,
        registry,
        work,
        "submit",
        agent_session_root=session,
        evidence_payload="artifact is ready",
        authentication_context=_context(registry),
    )
    adjudicate_universal_governed_work(
        store,
        registry,
        work,
        requesting_agent_session_root=session,
        workspace_root=tmp_path,
        authentication_context=_context(registry),
    )
    assert _state(store, registry, work) == "complete"

    monkeypatch.setattr(
        "nodelang.universal_application.time.time",
        lambda: 30_000.0 + (21 * 86400),
    )
    result = sweep_workshop_board_tasks(
        store,
        registry,
        authentication_context=_context(registry),
    )
    assert work in result["archived"]
    assert _state(store, registry, work) == "cancelled"

    restored = restore_archived_workshop_board_task(
        store,
        registry,
        work,
        authentication_context=_context(registry),
    )
    assert restored["state"] == "complete"
    assert _state(store, registry, work) == "complete"


def test_board_backend_no_replay_on_sweep_archive_restore_or_reclaim(
    tmp_path,
    monkeypatch,
):
    store, registry = _application(tmp_path)
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 40_000.0)
    work = _work(store, registry, "no replay")
    session, compliance = _session(store, registry, "noreplay")
    _claim(store, registry, work, session, compliance)
    calls = []

    def forbid_stale_effect_replay(*args, **kwargs):
        from nodelang.cell_state_machine import _read_transition_event

        history_root = kwargs.get("history_root")
        if history_root is None and len(args) >= 5:
            history_root = args[4]
        history = _read_transition_event(
            store.snapshot(),
            registry.standard_library.state_machine_protocol,
            history_root,
        )
        event = store.snapshot().cells[history.event_root].atom.decode("utf-8")
        if event == "claim":
            return None
        calls.append(event)
        raise AssertionError("stale Work release was replayed")

    monkeypatch.setattr(
        "nodelang.universal_application.record_workshop_work_event",
        forbid_stale_effect_replay,
    )
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 41_801.0)
    sweep_workshop_board_tasks(store, registry, authentication_context=_context(registry))
    assert calls == []

    session2, compliance2 = _session(store, registry, "noreplay2")
    claim_next_universal_governed_work(
        store,
        registry,
        agent_session_root=session2,
        compliance_observation_root=compliance2,
        authentication_context=_context(registry),
    )
    assert calls == []


def test_board_backend_dry_run_writes_nothing(tmp_path, monkeypatch):
    store, registry = _application(tmp_path)
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 50_000.0)
    work = _work(store, registry, "dry run")
    session, compliance = _session(store, registry, "dryrun")
    _claim(store, registry, work, session, compliance)
    before = store.revision

    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 51_801.0)
    report = dry_run_workshop_board_sweep(
        store,
        registry,
        authentication_context=_context(registry),
    )

    assert report["wip_dead"] == 1
    assert report["would_release"] == 1
    assert store.revision == before


def test_board_backend_routes_and_archive_param_readback(tmp_path, monkeypatch):
    store, registry = _application(tmp_path)
    server = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
        universal_workspace_root=tmp_path,
        runtime_compliance_runner=_green_runtime_compliance,
    )
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 60_000.0)
    stale = _work(store, registry, "route stale release")
    session, compliance = _session(store, registry, "route-stale")
    _claim(store, registry, stale, session, compliance)

    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 61_801.0)
    released = server.dispatch_universal_machine_route({
        "method": "POST",
        "path": "/api/universal/workshop-board/release-dead-claims",
        "body": {"stale_claim_after_idle_minutes": 30},
    })
    assert stale in released["released"]
    assert _state(store, registry, stale) == "open"

    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 70_000.0)
    done = _work(store, registry, "route old done archive")
    session2, compliance2 = _session(store, registry, "route-done")
    _claim(store, registry, done, session2, compliance2)
    transition_universal_governed_work(
        store,
        registry,
        done,
        "submit",
        agent_session_root=session2,
        evidence_payload="artifact is ready",
        authentication_context=_context(registry),
    )
    adjudicate_universal_governed_work(
        store,
        registry,
        done,
        requesting_agent_session_root=session2,
        workspace_root=tmp_path,
        authentication_context=_context(registry),
    )

    monkeypatch.setattr(
        "nodelang.universal_application.time.time",
        lambda: 70_000.0 + (4 * 86400),
    )
    archived = server.dispatch_universal_machine_route({
        "method": "POST",
        "path": "/api/universal/workshop-board/archive-idle",
        "body": {"archive_after_idle_days": 3},
    })
    assert archived["archive_after_idle_days"] == 3
    assert done in archived["archived"]
    assert dry_run_workshop_board_sweep(
        store,
        registry,
        authentication_context=_context(registry),
    )["archive_after_idle_days"] == 3

    restored = server.dispatch_universal_machine_route({
        "method": "POST",
        "path": "/api/universal/workshop-board/restore-archived",
        "body": {"root": done},
    })
    assert restored["state"] == "complete"


def test_board_backend_new_invalid_param_write_is_admitted_before_mutation(tmp_path):
    store, registry = _application(tmp_path)
    before = store.revision
    before_report = dry_run_workshop_board_sweep(
        store,
        registry,
        authentication_context=_context(registry),
    )

    with pytest.raises(AuthorizationDenied):
        sweep_workshop_board_tasks(
            store,
            registry,
            archive_after_idle_days=7,
            stale_claim_after_idle_minutes=9,
            authentication_context=None,
        )

    after_report = dry_run_workshop_board_sweep(
        store,
        registry,
        authentication_context=_context(registry),
    )
    assert store.revision == before
    assert after_report["archive_after_idle_days"] == before_report["archive_after_idle_days"]
    assert after_report["stale_claim_after_idle_minutes"] == before_report["stale_claim_after_idle_minutes"]


def test_board_backend_new_reading_work_status_does_not_sweep(tmp_path, monkeypatch):
    store, registry = _application(tmp_path)
    server = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
        runtime_compliance_runner=_green_runtime_compliance,
    )
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 80_000.0)
    work = _work(store, registry, "read does not sweep")
    session, compliance = _session(store, registry, "read-nosweep")
    _claim(store, registry, work, session, compliance)
    before = store.revision

    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 81_801.0)
    status = project_universal_governed_work_status(
        store,
        registry,
        authentication_context=_context(registry),
    )
    board = server.dispatch_universal_machine_route({
        "method": "GET",
        "path": "/api/universal/work",
        "body": {},
    })

    assert store.revision == before
    assert _state(store, registry, work) == "claimed"
    assert status["items"]
    assert board["workshop_status"]["root"] == registry.workshop_root


def test_board_backend_new_tick_cadence_is_visible_and_tick_sweeps(tmp_path, monkeypatch):
    store, registry = _application(tmp_path)
    server = ApplicationServer(
        universal_store=store,
        universal_registry=registry,
        runtime_compliance_runner=_green_runtime_compliance,
    )
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 90_000.0)
    work = _work(store, registry, "tick sweep")
    session, compliance = _session(store, registry, "tick")
    _claim(store, registry, work, session, compliance)
    before = dry_run_workshop_board_sweep(
        store,
        registry,
        authentication_context=_context(registry),
    )

    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 91_801.0)
    tick = server.dispatch_universal_machine_route({
        "method": "POST",
        "path": "/api/universal/workshop-board/tick",
        "body": {},
    })

    assert before["tick_cadence_minutes"] == 5
    assert tick["tick_cadence_minutes"] == 5
    assert work in tick["released"]
    assert _state(store, registry, work) == "open"


def test_board_backend_new_archive_rechecks_live_presence_before_effect(tmp_path, monkeypatch):
    store, registry = _application(tmp_path)
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 100_000.0)
    work = _work(store, registry, "archive race")
    session, compliance = _session(store, registry, "archive-race")
    _claim(store, registry, work, session, compliance)
    transition_universal_governed_work(
        store,
        registry,
        work,
        "submit",
        agent_session_root=session,
        evidence_payload="artifact is ready",
        authentication_context=_context(registry),
    )
    adjudicate_universal_governed_work(
        store,
        registry,
        work,
        requesting_agent_session_root=session,
        workspace_root=tmp_path,
        authentication_context=_context(registry),
    )
    _live_presence(store, registry, session, now=100_000.0 + (4 * 86400))
    original = ua.list_active_runtime_presences
    original_claimant = ua._governed_work_claimant_session
    calls = {"count": 0}

    def racing_presence(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return ()
        return original(*args, **kwargs)

    def returned_claimant(snapshot, registry, work_root):
        if work_root == work:
            return session
        return original_claimant(snapshot, registry, work_root)

    monkeypatch.setattr(ua, "list_active_runtime_presences", racing_presence)
    monkeypatch.setattr(ua, "_governed_work_claimant_session", returned_claimant)
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 100_000.0 + (4 * 86400))
    result = sweep_workshop_board_tasks(
        store,
        registry,
        archive_after_idle_days=3,
        authentication_context=_context(registry),
    )

    assert work not in result["archived"]
    assert _state(store, registry, work) == "complete"


def test_board_backend_real_operations_recover_lost_ack_without_replay(tmp_path, monkeypatch):
    store, registry = _application(tmp_path)
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 100_000.0)
    work = _work(store, registry, "lost ack release")
    session, compliance = _session(store, registry, "lost-ack-release")
    _claim(store, registry, work, session, compliance)
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 100_000.0 + 3600)
    release_calls = {"count": 0}
    original_release = ua.founder_release_stale_governed_work_claim

    def lost_release_ack(*args, **kwargs):
        release_calls["count"] += 1
        result = original_release(*args, **kwargs)
        raise RuntimeError("lost release acknowledgement")

    monkeypatch.setattr(ua, "founder_release_stale_governed_work_claim", lost_release_ack)
    with pytest.raises(RuntimeError):
        sweep_workshop_board_tasks(store, registry, stale_claim_after_idle_minutes=1,
                                   authentication_context=_context(registry))
    assert _state(store, registry, work) == "open"
    assert release_calls["count"] == 1
    assert sweep_workshop_board_tasks(store, registry, stale_claim_after_idle_minutes=1,
                                      authentication_context=_context(registry))["released"] == ()
    assert release_calls["count"] == 1
    reclaimed_session, reclaimed_compliance = _session(store, registry, "lost-ack-reclaim")
    _claim(store, registry, work, reclaimed_session, reclaimed_compliance)
    assert _state(store, registry, work) == "claimed"


def test_board_backend_archive_restore_and_reopen_use_real_history_after_lost_ack(tmp_path, monkeypatch):
    store, registry = _application(tmp_path)
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 100_000.0)
    work = _work(store, registry, "lost ack archive")
    session, compliance = _session(store, registry, "lost-ack-archive")
    _claim(store, registry, work, session, compliance)
    transition_universal_governed_work(store, registry, work, "submit",
        agent_session_root=session, evidence_payload="artifact is ready",
        authentication_context=_context(registry))
    adjudicate_universal_governed_work(store, registry, work,
        requesting_agent_session_root=session, workspace_root=tmp_path,
        authentication_context=_context(registry))
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 100_000.0 + (4 * 86400))
    cancel_calls = {"count": 0}
    original_transition = ua._founder_governed_work_evidence_transition

    def lost_cancel_ack(*args, **kwargs):
        if args[3] == "cancel":
            cancel_calls["count"] += 1
            result = original_transition(*args, **kwargs)
            raise RuntimeError("lost archive acknowledgement")
        return original_transition(*args, **kwargs)

    monkeypatch.setattr(ua, "_founder_governed_work_evidence_transition", lost_cancel_ack)
    with pytest.raises(RuntimeError):
        sweep_workshop_board_tasks(store, registry, archive_after_idle_days=3,
                                   authentication_context=_context(registry))
    assert _state(store, registry, work) == "cancelled"
    assert cancel_calls["count"] == 1
    assert sweep_workshop_board_tasks(store, registry, archive_after_idle_days=3,
                                      authentication_context=_context(registry))["archived"] == ()
    assert cancel_calls["count"] == 1
    assert restore_archived_workshop_board_task(store, registry, work,
        authentication_context=_context(registry))["state"] == "complete"

    monkeypatch.setattr(ua, "_founder_governed_work_evidence_transition", original_transition)
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 100_000.0)
    open_work = _work(store, registry, "reopen after archive")
    open_session, open_compliance = _session(store, registry, "reopen-after-archive")
    _claim(store, registry, open_work, open_session, open_compliance)
    transition_universal_governed_work(store, registry, open_work, "release",
        agent_session_root=open_session, evidence_payload="",
        authentication_context=_context(registry))
    monkeypatch.setattr("nodelang.universal_application.time.time", lambda: 100_000.0 + (4 * 86400))
    result = sweep_workshop_board_tasks(store, registry, archive_after_idle_days=3,
                                        authentication_context=_context(registry))
    assert open_work in result["archived"]
    assert restore_archived_workshop_board_task(store, registry, open_work,
        authentication_context=_context(registry))["state"] == "open"
