"""Tests for personal_brain.server tool functions.

Tool functions are tested directly (without FastMCP transport) — the
transport layer is shallow and adds little to test. FastMCP integration
is verified via MCP Inspector in the slice-1 acceptance demo.
"""
from __future__ import annotations

from personal_brain.models import (
    Fragment,
    FragmentKind,
    Provenance,
    Scope,
    SecretRef,
    Skill,
    WiringAnnounceRequest,
    WiringEntry,
    WriteOp,
    WriteOpType,
)
from personal_brain.server import (
    announce_wiring,
    apply_write,
    build_server,
    make_context_payload,
    queue_skill_mint,
)
from personal_brain.storage import BrainStore

from datetime import datetime, timezone


def test_brain_liveness_never_reads_the_persistent_store(tmp_path, monkeypatch):
    store = BrainStore.open(tmp_path / "brain.sqlite3")
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        def persistent_read_is_forbidden(*_args, **_kwargs):
            raise AssertionError("liveness must not read diagnostic store state")

        monkeypatch.setattr(store, "count_skills", persistent_read_is_forbidden)
        monkeypatch.setattr(store, "count_fragments", persistent_read_is_forbidden)
        monkeypatch.setattr(store, "list_wiring", persistent_read_is_forbidden)

        result = mcp._tools["brain.liveness"].handler()

        assert result["ok"] is True
        assert isinstance(result["server_pid"], int)
        assert "engine" in result
        assert "facts" not in result
        assert "skills" not in result
        assert "wiring_active" not in result
    finally:
        store.close()


def _prov():
    return Provenance(
        contributing_agent="claude-sonnet-4.7",
        contributing_user="founder",
        created_at=datetime.now(timezone.utc),
    )


def _store_with_seeded_skills():
    s = BrainStore.open(":memory:")
    s.upsert_skill(Skill(
        id="sk-1",
        name="revit_takeoff",
        description=(
            "Extract wall, floor, room counts and areas from the active "
            "Revit document and return as a structured table for QTO."
        ),
        triggers=["wall count", "takeoff"],
        requires_mcps=["revit-mcp"],
        body="# Revit takeoff\nrevit_info → revit_execute_csharp → summarise",
        examples=[{"input": "wall count", "output": "247"}],
        owner_user="founder",
        provenance=_prov(),
    ))
    s.upsert_skill(Skill(
        id="sk-2",
        name="notion_summarise",
        description=(
            "Read a Notion page by URL or id and produce a 5-bullet "
            "executive summary saved back to the same workspace as a child page."
        ),
        triggers=["summarize notion", "notion summary"],
        requires_mcps=["notion-mcp"],
        body="# Notion summarise\n1. fetch\n2. summarise\n3. create_page",
        examples=[{"input": "summarize notion page", "output": "summary"}],
        owner_user="founder",
        provenance=_prov(),
    ))
    s.write_fragment(Fragment(
        id="f-1", kind=FragmentKind.FACT, text="user prefers metric units",
        owner_user="founder", provenance=_prov(),
    ))
    s.write_fragment(Fragment(
        id="f-2", kind=FragmentKind.FACT,
        text="Tower-A wall type is Generic-200mm",
        owner_user="founder", provenance=_prov(),
    ))
    return s


def test_context_returns_relevant_skills_and_facts():
    store = _store_with_seeded_skills()
    try:
        resp = make_context_payload(
            store=store,
            prompt="Give me the wall takeoff for Tower-A",
            owner_user="founder",
        )
        assert resp.skills, "expected at least one skill retrieved"
        names = {s.name for s in resp.skills}
        assert "revit_takeoff" in names
        assert resp.retrieval_ms >= 0.0
        assert "<brain_context>" in resp.injection
        assert "revit_takeoff" in resp.injection
        assert "Tower-A" in resp.injection or "wall" in resp.injection.lower()
    finally:
        store.close()


def test_context_logs_access():
    store = _store_with_seeded_skills()
    try:
        make_context_payload(
            store=store,
            prompt="Tower-A walls metric",
            owner_user="founder",
        )
        log = store.access_log_for("f-1")
        log2 = store.access_log_for("f-2")
        assert any(row["purpose"] == "brain.context" for row in log + log2), \
            "context retrieval must log access (arXiv 2505.18279)"
    finally:
        store.close()


def test_context_does_not_fallback_to_legacy_room_when_cell_workshop_unwired(
    monkeypatch,
):
    from personal_brain import cell_room_wiring
    from personal_brain.meeting_room import room_say

    store = BrainStore.open(":memory:")
    try:
        room_say(
            store,
            frm="legacy-room",
            kind="plan",
            text="legacy context must not leak",
        )
        monkeypatch.setattr(cell_room_wiring, "cell_room_enabled", lambda: True)
        monkeypatch.setattr(cell_room_wiring, "cell_room_is_wired", lambda: False)

        resp = make_context_payload(
            store=store,
            prompt="read the workshop",
            owner_user="founder",
        )

        assert (
            'authority="application-owned Universal Cell Workshop"'
            in resp.injection
        )
        assert "Universal Workshop is enabled but not wired" in resp.injection
        assert "legacy context must not leak" not in resp.injection
    finally:
        store.close()


def test_write_ops_apply():
    store = BrainStore.open(":memory:")
    try:
        f = Fragment(
            id="w-1", kind=FragmentKind.FACT, text="firm uses pnpm",
            owner_user="founder", provenance=_prov(),
        )
        ops = [WriteOp(op=WriteOpType.ADD, fragment=f)]
        resp = apply_write(store=store, ops=ops)
        assert resp.fragments_added == 1
        assert resp.ops_applied == 1
        assert store.count_fragments() == 1
    finally:
        store.close()


class _ObserveCellBridge:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.created = []
        self.deliberations = []

    def deliberation_append(self, **kwargs):
        if self.fail:
            raise RuntimeError("cell unavailable")
        record = {
            "root": f"app:brain-control-ledger:v1:entry:{len(self.deliberations) + 1}",
            **kwargs,
        }
        self.deliberations.append(record)
        return record

    def assembly_create(
        self,
        *,
        definition_key,
        fields,
        structured_fields=None,
        idempotency_field=None,
        x=0.0,
        y=0.0,
    ):
        if self.fail:
            raise RuntimeError("cell unavailable")
        record = {
            "created_root": f"assembly-instance:observe-{len(self.created) + 1}",
            "definition_key": definition_key,
            "fields": dict(fields or {}),
            "structured_fields": dict(structured_fields or {}),
            "idempotency_field": idempotency_field,
        }
        self.created.append(record)
        return record


def test_firm_create_cell_unavailable_does_not_create_legacy_firm(monkeypatch):
    from personal_brain import universal_runtime as ur
    from personal_brain.firm import current_firm

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.firm_create"].handler(
            name="Founder Practice",
            created_by="founder",
        )

        assert result["ok"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        assert current_firm(store) is None
        assert mcp._tools["brain.firm_seats"].handler()["seats"] == []
    finally:
        store.close()


def test_community_subscribe_cell_unavailable_does_not_write_subscription(
    monkeypatch,
):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.community_subscribe"].handler(
            actor_url="https://relay.example.invalid/outbox/founder",
            display_name="Founder outbox",
        )

        assert result["ok"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        assert mcp._tools["brain.community_list"].handler()["subscriptions"] == []
    finally:
        store.close()


def test_community_create_cell_unavailable_does_not_create_legacy_group(
    monkeypatch,
):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.community_create"].handler(
            name="Design Community",
            created_by="founder",
            transport_kind="disk",
        )

        assert result["ok"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        assert mcp._tools["brain.community_groups"].handler()["communities"] == []
    finally:
        store.close()


def test_community_poll_now_cell_failure_does_not_update_subscription_stats(
    monkeypatch,
):
    from personal_brain import community as community_mod
    from personal_brain import universal_runtime as ur
    from personal_brain.community import subscribe

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))

    fake_outbox = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "type": "OrderedCollection",
        "totalItems": 0,
        "orderedItems": [],
    }

    def fake_fetch(actor_url, *, timeout_s=5.0, http_client=None):
        return fake_outbox

    monkeypatch.setattr(community_mod, "fetch_outbox", fake_fetch)
    try:
        subscribe(
            store,
            actor_url="http://peer.test/actor",
            display_name="Peer",
            owner_user="founder",
        )
        mcp = build_server(store=store, default_owner_user="founder")

        poll = mcp._tools["brain.community_poll_now"].handler()

        assert poll["ok"] is True
        assert len(poll["results"]) == 1
        result = poll["results"][0]
        assert result["ok"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        listed = mcp._tools["brain.community_list"].handler()
        assert listed["subscriptions"][0]["last_poll_at"] is None
        assert listed["subscriptions"][0]["last_accepted"] == 0
        assert listed["subscriptions"][0]["last_quarantined"] == 0
        assert listed["subscriptions"][0]["last_rejected"] == 0
    finally:
        store.close()


def test_organize_cell_failure_prevents_maintenance_writes(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        store.write_fragment(Fragment(
            id="organize-denied",
            kind=FragmentKind.FACT,
            text="A memory fact that would normally receive a half life",
            owner_user="founder",
            provenance=_prov(),
        ))
        before_half_life = store.get_fragment("organize-denied").half_life_days
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.organize"].handler()

        assert result["ok"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        assert store.get_meta("organize.clusters") is None
        assert store.get_meta("organize.last_run") is None
        assert store.get_fragment("organize-denied").half_life_days == before_half_life
    finally:
        store.close()


def test_reembed_cell_failure_prevents_embedding_writes(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        store.write_fragment(Fragment(
            id="reembed-denied",
            kind=FragmentKind.FACT,
            text="A fact with enough text to embed",
            owner_user="founder",
            provenance=_prov(),
        ))
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.reembed"].handler()

        assert result["ok"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        assert store.get_meta("embed.backend") is None
        assert store.get_meta("embed.dim") is None
        assert store.get_meta("reembed.last_run") is None
        assert store.get_fragment("reembed-denied").embedding is None
    finally:
        store.close()


def test_promote_tool_cell_first_before_fragment_projection(monkeypatch):
    import json
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    source_text = "private client budget is AED 123456 and should not leak"
    try:
        store.write_fragment(Fragment(
            id="promote-source",
            kind=FragmentKind.FACT,
            text=source_text,
            owner_user="founder",
            provenance=_prov(),
        ))
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.promote"].handler(
            fragment_id="promote-source",
            target_scope="project",
            owner_user="founder",
            target_project_id="P-1",
        )

        assert result["ok"] is True
        assert result["promoted"] is True
        assert result["cell_first"] is True
        assert result["brain_written"] is True
        assert result["cell_record_root"] == "assembly-instance:observe-1"
        promoted = store.get_fragment(result["promoted_id"])
        assert promoted is not None
        assert promoted.scope == Scope.PROJECT
        assert promoted.project_id == "P-1"
        claims = json.loads(bridge.created[0]["fields"]["claims"])
        assert claims["operation"] == "brain.promote"
        assert claims["source_scope"] == "user"
        assert claims["target_scope"] == "project"
        assert claims["source_text_len"] == len(source_text)
        assert "source_text_sha256" in claims
        assert source_text not in bridge.created[0]["fields"]["claims"]
        assert "P-1" not in bridge.created[0]["fields"]["claims"]
    finally:
        store.close()


def test_promote_tool_cell_failure_prevents_fragment_projection(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        store.write_fragment(Fragment(
            id="promote-denied-source",
            kind=FragmentKind.FACT,
            text="private note that must not be projected without Cell",
            owner_user="founder",
            provenance=_prov(),
        ))
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.promote"].handler(
            fragment_id="promote-denied-source",
            target_scope="project",
            owner_user="founder",
            target_project_id="P-1",
        )

        assert result["ok"] is False
        assert result["promoted"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        assert store.get_fragment("promote-denied-source") is not None
        assert store.get_fragment("promoted-827089ea7db5f242") is None
        assert store.count_fragments() == 1
    finally:
        store.close()


def _skill_harvest_fragment(fid: str, skill_name: str, text: str) -> Fragment:
    return Fragment(
        id=fid,
        kind=FragmentKind.SKILL,
        text=text,
        subject=skill_name,
        predicate="procedure",
        object="archhub-host /run",
        scope=Scope.USER,
        owner_user="founder",
        provenance=_prov(),
        extra={
            "category": "skill",
            "source": "session-harvest",
            "skill_name": skill_name,
            "triggers": [f"run {skill_name.lower()}"],
            "requires_mcps": ["archhub-host /run"],
            "body": (
                f"TRIGGER: run {skill_name}.\n"
                "BROKER/TOOL: archhub-host /run.\n"
                "STEPS: inspect; execute; verify."
            ),
            "examples": "YES",
        },
    )


def test_promote_skills_tool_cell_first_before_upsert_delete(monkeypatch):
    import json
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    try:
        store.write_fragment(_skill_harvest_fragment(
            "harvest:cell-first",
            "Coordinate Model Export",
            "Export a coordinated model package after checking links and "
            "recording verification evidence for the project team.",
        ))
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.promote_skills"].handler(dry_run=False)

        assert result["ok"] is True
        assert result["cell_first"] is True
        assert result["brain_written"] is True
        assert result["promoted"] == 1
        assert result["deleted_fragments"] == 1
        assert store.get_fragment("harvest:cell-first") is None
        assert store.get_skill("coordinate_model_export") is not None
        claims = json.loads(bridge.created[0]["fields"]["claims"])
        assert claims["operation"] == "brain.promote_skills"
        assert claims["planned_promoted"] == 1
        assert claims["planned_total_candidates"] == 1
        assert "plan_sha256" in claims
        assert "Coordinate Model Export" not in bridge.created[0]["fields"]["claims"]
        assert "inspect; execute; verify" not in bridge.created[0]["fields"]["claims"]
    finally:
        store.close()


def test_promote_skills_tool_cell_failure_prevents_upsert_delete(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        store.write_fragment(_skill_harvest_fragment(
            "harvest:blocked-cell",
            "Blocked Skill Promotion",
            "A harvested procedure that should remain a fragment if the Cell "
            "authority cannot record the promotion.",
        ))
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.promote_skills"].handler(dry_run=False)

        assert result["ok"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert result["promoted"] == 0
        assert result["deleted_fragments"] == 0
        assert "cell unavailable" in result["errors"][0]
        assert store.get_fragment("harvest:blocked-cell") is not None
        assert store.get_skill("blocked_skill_promotion") is None
    finally:
        store.close()


def test_fanout_apply_cell_first_before_inbound_fragment_write(monkeypatch):
    import json
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    try:
        mcp = build_server(store=store, default_owner_user="founder")
        inbound_text = "remote firm coordination note with client detail"

        result = mcp._tools["brain.fanout_apply"].handler(
            fragments=[{
                "id": "fanout-cell-first",
                "kind": "fact",
                "text": inbound_text,
                "scope": "firm",
                "visibility": "shared_company",
                "owner_user": "remote-user",
                "firm_id": "firm-alpha",
                "hlc": "000000000000000a",
            }],
        )

        assert result["ok"] is True
        assert result["cell_first"] is True
        assert result["brain_written"] is True
        assert result["applied"] == 1
        assert result["cell_record_root"] == "assembly-instance:observe-1"
        stored = store.get_fragment("fanout-cell-first")
        assert stored is not None
        assert stored.scope == Scope.FIRM
        assert stored.firm_id == "firm-alpha"
        claims = json.loads(bridge.created[0]["fields"]["claims"])
        assert claims["operation"] == "brain.fanout_apply"
        assert claims["candidate_count"] == 1
        assert claims["fragments"][0]["scope"] == "firm"
        raw_claims = bridge.created[0]["fields"]["claims"]
        assert inbound_text not in raw_claims
        assert "firm-alpha" not in raw_claims
        assert "remote-user" not in raw_claims
    finally:
        store.close()


def test_fanout_apply_cell_failure_prevents_inbound_fragment_write(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.fanout_apply"].handler(
            fragments=[{
                "id": "fanout-denied-cell",
                "kind": "fact",
                "text": "must not land without Cell authority",
                "scope": "community",
                "visibility": "shared_public",
                "owner_user": "remote-user",
                "firm_id": "firm-alpha",
                "hlc": "000000000000000b",
            }],
        )

        assert result["ok"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert result["applied"] == 0
        assert "cell unavailable" in result["error"]
        assert store.get_fragment("fanout-denied-cell") is None
    finally:
        store.close()


def test_dataset_export_cell_first_before_filesystem_write(monkeypatch, tmp_path):
    import json
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    export_root = tmp_path / "exports"
    private_text = "private exportable training fact"
    try:
        store.write_fragment(Fragment(
            id="export-cell-first",
            kind=FragmentKind.FACT,
            text=private_text,
            owner_user="founder",
            provenance=_prov(),
        ))
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.dataset_export"].handler(
            out_dir=str(export_root),
            dataset_name="sensitive-dataset",
            scopes=["user"],
            owner_user="founder",
        )

        assert result["ok"] is True
        assert result["cell_first"] is True
        assert result["brain_written"] is True
        assert result["cell_record_root"] == "assembly-instance:observe-1"
        assert result["row_count"] == 1
        assert (export_root / "sensitive-dataset" / "manifest.json").exists()
        assert (export_root / "sensitive-dataset" / "fragments.jsonl").exists()
        claims = json.loads(bridge.created[0]["fields"]["claims"])
        assert claims["operation"] == "brain.dataset_export"
        assert claims["scopes"] == ["user"]
        assert claims["training_target"] == "firm_private"
        raw_claims = bridge.created[0]["fields"]["claims"]
        assert private_text not in raw_claims
        assert "sensitive-dataset" not in raw_claims
        assert str(export_root) not in raw_claims
    finally:
        store.close()


def test_dataset_export_cell_failure_prevents_filesystem_write(
    monkeypatch,
    tmp_path,
):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    export_root = tmp_path / "exports"
    try:
        store.write_fragment(Fragment(
            id="export-denied-cell",
            kind=FragmentKind.FACT,
            text="must not export without Cell authority",
            owner_user="founder",
            provenance=_prov(),
        ))
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.dataset_export"].handler(
            out_dir=str(export_root),
            dataset_name="blocked-dataset",
            scopes=["user"],
            owner_user="founder",
        )

        assert result["ok"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        assert not (export_root / "blocked-dataset").exists()
    finally:
        store.close()


def test_cloud_archive_cell_first_before_upload(monkeypatch, tmp_path):
    import json
    from personal_brain import cloud_archive as ca
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    monkeypatch.setattr(ca, "_is_boto3_available", lambda: True)
    calls = []

    def fake_upload(local_dir, **kwargs):
        calls.append({"local_dir": local_dir, "kwargs": kwargs})
        return {
            "ok": True,
            "uploaded_count": 1,
            "total_bytes": 12,
            "bucket": kwargs["bucket"],
            "prefix": kwargs["prefix"],
            "dataset_name": kwargs["dataset_name"] or local_dir.name,
            "uploaded_keys": ["archhub/datasets/ds/manifest.json"],
            "more_keys_omitted": 0,
        }

    monkeypatch.setattr(ca, "upload_dataset", fake_upload)
    local_dir = tmp_path / "ds"
    local_dir.mkdir()
    (local_dir / "manifest.json").write_text("{}", encoding="utf-8")
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.cloud_archive"].handler(
            local_dir=str(local_dir),
            bucket="private-bucket",
            endpoint_url="https://example.invalid",
            access_key_ref="op://vault/archive/access",
            secret_key_ref="op://vault/archive/secret",
            prefix="archhub",
            dataset_name="ds",
        )

        assert result["ok"] is True
        assert result["cell_first"] is True
        assert result["brain_written"] is True
        assert result["cell_record_root"] == "assembly-instance:observe-1"
        assert len(calls) == 1
        claims = json.loads(bridge.created[0]["fields"]["claims"])
        assert claims["operation"] == "brain.cloud_archive"
        assert claims["region"] == "auto"
        raw_claims = bridge.created[0]["fields"]["claims"]
        assert "private-bucket" not in raw_claims
        assert "op://vault/archive/access" not in raw_claims
        assert "op://vault/archive/secret" not in raw_claims
        assert str(local_dir) not in raw_claims
    finally:
        store.close()


def test_cloud_archive_cell_failure_prevents_upload(monkeypatch, tmp_path):
    from personal_brain import cloud_archive as ca
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    monkeypatch.setattr(ca, "_is_boto3_available", lambda: True)
    calls = []
    monkeypatch.setattr(
        ca,
        "upload_dataset",
        lambda *args, **kwargs: calls.append((args, kwargs)) or {"ok": True},
    )
    local_dir = tmp_path / "ds"
    local_dir.mkdir()
    (local_dir / "manifest.json").write_text("{}", encoding="utf-8")
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.cloud_archive"].handler(
            local_dir=str(local_dir),
            bucket="private-bucket",
            access_key_ref="op://vault/archive/access",
            secret_key_ref="op://vault/archive/secret",
        )

        assert result["ok"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        assert calls == []
    finally:
        store.close()


def test_observe_hook_creates_cell_record_before_brain_fragment(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.observe"].handler(
            tool_name="Write",
            tool_input={"path": "10.PRODUCT/12.PRODUCTION/app.py"},
            tool_response={"ok": True},
            session_id="codex-session-1",
            cwd="C:/Users/fargaly/00.ARCHUB",
        )

        assert result["ok"] is True
        assert result["cell_first"] is True
        assert result["brain_written"] is True
        assert result["cell_record_root"] \
            == "app:brain-control-ledger:v1:entry:1"
        assert bridge.created == []
        receipt = bridge.deliberations[0]
        assert receipt["space"] == "app:brain-control-ledger:v1"
        assert receipt["category"] \
            == "app:brain-control-ledger:v1:category:compliance-event"
        assert receipt["payload"]["operation"] == "brain.observe"
        assert receipt["idempotency_key"].startswith(
            "brain-control:observe:"
        )
        assert store.count_fragments() == 1
        stored = store.search_fragments("Write", k=1)[0]
        assert stored.extra["cell_record_root"] \
            == "app:brain-control-ledger:v1:entry:1"
        assert stored.extra["cell_record_source"].startswith(
            "brain-control:observe:"
        )
    finally:
        store.close()


def test_observe_hook_cell_failure_prevents_brain_fragment(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.observe"].handler(
            tool_name="Write",
            tool_input={"path": "10.PRODUCT/12.PRODUCTION/app.py"},
            tool_response={"ok": True},
            session_id="codex-session-1",
        )

        assert result["ok"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert result["ops_applied"] == 0
        assert "cell unavailable" in result["error"]
        assert store.count_fragments() == 0
    finally:
        store.close()


def test_brain_write_tool_creates_compact_cell_receipt_before_projection(
    monkeypatch,
):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    try:
        mcp = build_server(store=store, default_owner_user="founder")
        fragment = Fragment(
            id="write-cell-1",
            kind=FragmentKind.FACT,
            text="private turn memory",
            owner_user="founder",
            provenance=_prov(),
        )

        result = mcp._tools["brain.write"].handler(
            ops=[{
                "op": "add",
                "fragment": fragment.model_dump(mode="json"),
            }],
        )

        assert result["ops_applied"] == 1
        assert result["cell_first"] is True
        assert result["brain_written"] is True
        assert result["cell_record_root"] \
            == "app:brain-control-ledger:v1:entry:1"
        assert bridge.created == []
        assert len(bridge.deliberations) == 1
        receipt = bridge.deliberations[0]
        assert receipt["space"] == "app:brain-control-ledger:v1"
        assert receipt["category"] \
            == "app:brain-control-ledger:v1:category:compliance-event"
        assert receipt["idempotency_key"].startswith("brain-control:write:")
        claims = receipt["payload"]
        assert claims["operation"] == "brain.write"
        assert claims["ops"][0]["fragment_id"] == "write-cell-1"
        assert claims["ops"][0]["text_len"] == len("private turn memory")
        assert "private turn memory" not in str(claims)
        assert store.count_fragments() == 1
    finally:
        store.close()


def test_brain_write_tool_cell_failure_prevents_projection(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        mcp = build_server(store=store, default_owner_user="founder")
        fragment = Fragment(
            id="write-cell-denied",
            kind=FragmentKind.FACT,
            text="must not land in Brain",
            owner_user="founder",
            provenance=_prov(),
        )

        result = mcp._tools["brain.write"].handler(
            ops=[{
                "op": "add",
                "fragment": fragment.model_dump(mode="json"),
            }],
        )

        assert result["ok"] is False
        assert result["ops_applied"] == 0
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        assert store.count_fragments() == 0
    finally:
        store.close()


def test_set_owner_creates_cell_receipt_before_binding(monkeypatch):
    import json
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.set_owner"].handler(
            user_id="u_abc123",
            email="alice@corp.com",
            display_name="Alice",
        )

        assert result["ok"] is True
        assert result["cell_first"] is True
        assert result["brain_written"] is True
        assert result["cell_record_root"] == "assembly-instance:observe-1"
        assert store.get_meta("bound_owner_user") == "u_abc123"
        claims = json.loads(bridge.created[0]["fields"]["claims"])
        assert claims["operation"] == "brain.set_owner"
        assert claims["target_owner_len"] == len("u_abc123")
        raw_claims = bridge.created[0]["fields"]["claims"]
        assert "u_abc123" not in raw_claims
        assert "alice@corp.com" not in raw_claims
        assert "Alice" not in raw_claims
    finally:
        store.close()


def test_set_owner_cell_failure_prevents_binding(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.set_owner"].handler(
            user_id="u_denied",
            email="denied@corp.com",
        )

        assert result["ok"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        assert store.get_meta("bound_owner_user") in (None, "")
        assert mcp._tools["brain.get_owner"].handler()["bound"] is False
    finally:
        store.close()


def test_clear_owner_creates_cell_receipt_before_unbinding(monkeypatch):
    import json
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    try:
        mcp = build_server(store=store, default_owner_user="founder")
        assert mcp._tools["brain.set_owner"].handler(
            user_id="u_abc123",
            email="alice@corp.com",
        )["ok"] is True

        result = mcp._tools["brain.clear_owner"].handler()

        assert result["ok"] is True
        assert result["cell_first"] is True
        assert result["brain_written"] is True
        assert result["previously"] == "u_abc123"
        assert result["cell_record_root"] == "assembly-instance:observe-2"
        assert store.get_meta("bound_owner_user") in (None, "")
        claims = json.loads(bridge.created[1]["fields"]["claims"])
        assert claims["operation"] == "brain.clear_owner"
        assert claims["had_binding"] is True
        assert "u_abc123" not in bridge.created[1]["fields"]["claims"]
    finally:
        store.close()


def test_clear_owner_cell_failure_preserves_binding(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    try:
        mcp = build_server(store=store, default_owner_user="founder")
        assert mcp._tools["brain.set_owner"].handler(user_id="u_abc123")[
            "ok"
        ] is True
        monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
            fail=True,
        ))

        result = mcp._tools["brain.clear_owner"].handler()

        assert result["ok"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert result["cleared"] is False
        assert "cell unavailable" in result["error"]
        assert store.get_meta("bound_owner_user") == "u_abc123"
        assert mcp._tools["brain.get_owner"].handler()["bound"] is True
    finally:
        store.close()


def test_a11y_prefs_get_is_read_only(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.a11y_prefs"].handler(mode="get")

        assert result["ok"] is True
        assert result["mode"] == "get"
        assert result["cell_first"] is False
        assert result["brain_written"] is False
        assert bridge.created == []
    finally:
        store.close()


def test_a11y_prefs_set_creates_cell_receipt_before_projection(monkeypatch):
    import json
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.a11y_prefs"].handler(
            mode="set",
            prefs={
                "font_size": "xlarge",
                "contrast": "high",
                "reduce_motion": True,
            },
        )

        assert result["ok"] is True
        assert result["cell_first"] is True
        assert result["brain_written"] is True
        assert result["cell_record_root"] == "assembly-instance:observe-1"
        assert result["prefs"]["font_size"] == "xlarge"
        assert result["prefs"]["contrast"] == "high"
        claims = json.loads(bridge.created[0]["fields"]["claims"])
        assert claims["operation"] == "brain.a11y_prefs.set"
        assert claims["keys"] == ["contrast", "font_size", "reduce_motion"]
        raw_claims = bridge.created[0]["fields"]["claims"]
        assert "xlarge" not in raw_claims
        assert "high" not in raw_claims
        assert "font_size" in raw_claims
        assert store.get_fragment("a11y:founder") is not None
    finally:
        store.close()


def test_a11y_prefs_cell_failure_prevents_projection(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.a11y_prefs"].handler(
            mode="set",
            prefs={"font_size": "xlarge", "contrast": "high"},
        )

        assert result["ok"] is False
        assert result["mode"] == "set"
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        assert result["prefs"]["font_size"] == "medium"
        assert result["prefs"]["contrast"] == "normal"
        assert store.get_fragment("a11y:founder") is None
    finally:
        store.close()


def test_edit_fact_creates_cell_receipt_before_projection(monkeypatch):
    import json
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    try:
        store.write_fragment(Fragment(
            id="fact-edit-1",
            kind=FragmentKind.FACT,
            text="old private fact",
            owner_user="founder",
            provenance=_prov(),
        ))
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.edit_fact"].handler(
            fragment_id="fact-edit-1",
            text="new private fact",
        )

        assert result["ok"] is True
        assert result["edited"] is True
        assert result["cell_first"] is True
        assert result["brain_written"] is True
        assert result["cell_record_root"] == "assembly-instance:observe-1"
        assert store.get_fragment("fact-edit-1").text == "new private fact"
        claims = json.loads(bridge.created[0]["fields"]["claims"])
        assert claims["operation"] == "brain.edit_fact"
        assert claims["old_text_len"] == len("old private fact")
        assert claims["new_text_len"] == len("new private fact")
        raw_claims = bridge.created[0]["fields"]["claims"]
        assert "old private fact" not in raw_claims
        assert "new private fact" not in raw_claims
    finally:
        store.close()


def test_edit_fact_cell_failure_prevents_projection(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        store.write_fragment(Fragment(
            id="fact-edit-denied",
            kind=FragmentKind.FACT,
            text="must stay old",
            owner_user="founder",
            provenance=_prov(),
        ))
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.edit_fact"].handler(
            fragment_id="fact-edit-denied",
            text="must not land",
        )

        assert result["ok"] is False
        assert result["edited"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        assert store.get_fragment("fact-edit-denied").text == "must stay old"
    finally:
        store.close()


def test_delete_fact_creates_cell_receipt_before_projection(monkeypatch):
    import json
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    try:
        store.write_fragment(Fragment(
            id="fact-delete-1",
            kind=FragmentKind.FACT,
            text="private deleted fact",
            owner_user="founder",
            provenance=_prov(),
        ))
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.delete_fact"].handler(
            fragment_id="fact-delete-1",
            hard=False,
        )

        assert result["ok"] is True
        assert result["deleted"] is True
        assert result["cell_first"] is True
        assert result["brain_written"] is True
        assert store.get_fragment("fact-delete-1").valid_until is not None
        claims = json.loads(bridge.created[0]["fields"]["claims"])
        assert claims["operation"] == "brain.delete_fact"
        assert claims["hard"] is False
        assert "private deleted fact" not in bridge.created[0]["fields"]["claims"]
    finally:
        store.close()


def test_delete_fact_cell_failure_prevents_projection(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        store.write_fragment(Fragment(
            id="fact-delete-denied",
            kind=FragmentKind.FACT,
            text="must stay active",
            owner_user="founder",
            provenance=_prov(),
        ))
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.delete_fact"].handler(
            fragment_id="fact-delete-denied",
        )

        assert result["ok"] is False
        assert result["deleted"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        assert store.get_fragment("fact-delete-denied").valid_until is None
    finally:
        store.close()


def test_restore_creates_cell_receipt_before_projection(monkeypatch):
    import json
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    try:
        frag = Fragment(
            id="fact-restore-1",
            kind=FragmentKind.FACT,
            text="private restored fact",
            owner_user="founder",
            provenance=_prov(),
        )
        frag.valid_until = datetime.now(timezone.utc)
        store.write_fragment(frag)
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.restore"].handler(
            fragment_id="fact-restore-1",
        )

        assert result["ok"] is True
        assert result["restored"] is True
        assert result["cell_first"] is True
        assert result["brain_written"] is True
        assert store.get_fragment("fact-restore-1").valid_until is None
        claims = json.loads(bridge.created[0]["fields"]["claims"])
        assert claims["operation"] == "brain.restore"
        assert claims["had_valid_until"] is True
        assert "private restored fact" not in bridge.created[0]["fields"]["claims"]
    finally:
        store.close()


def test_restore_cell_failure_prevents_projection(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        frag = Fragment(
            id="fact-restore-denied",
            kind=FragmentKind.FACT,
            text="must stay archived",
            owner_user="founder",
            provenance=_prov(),
        )
        frag.valid_until = datetime.now(timezone.utc)
        store.write_fragment(frag)
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.restore"].handler(
            fragment_id="fact-restore-denied",
        )

        assert result["ok"] is False
        assert result["restored"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        assert store.get_fragment("fact-restore-denied").valid_until is not None
    finally:
        store.close()


def test_skill_mint_persists_trace_and_returns_proposal():
    store = BrainStore.open(":memory:")
    try:
        trace = {
            "user_message": "Push the figma component spec to Code Connect",
            "trace_id": "tr-1",
            "tool_calls": [
                {"name": "figma_get_design_context", "status": "ok"},
                {"name": "gh_pr_create", "status": "ok"},
            ],
            "outcome": "success",
        }
        result = queue_skill_mint(
            store=store,
            trace=trace,
            outcome="success",
            owner_user="founder",
            contributing_agent="claude-sonnet-4.7",
            session_id="sess-42",
            critic_policy={
                "mode": "intent_first",
                "provider_mode": "deterministic",
                "source_label": "Figma Code Connect Handoff",
                "source_role": "workflow",
                "generic_name_policy": "reject",
                "minimum_intent_terms": 2,
            },
        )
        assert result.queued
        assert result.proposed_name
        assert result.novelty_score >= 0.0
        assert result.success_score == 1.0
        assert result.r1_gate["passed"] is True
        assert result.r2_gate["passed"] is True
        assert result.immediate_skill is not None
        stored_skill = store.get_skill(result.immediate_skill.id)
        assert stored_skill is not None
        assert stored_skill.mint_evidence["r1_gate"]["passed"] is True
        assert stored_skill.mint_evidence["r2_gate"]["passed"] is True
        assert stored_skill.mint_evidence["source_trace"]["trace_id"] == "tr-1"
        assert stored_skill.mint_evidence["source_trace"]["session_id"] == "sess-42"
        assert stored_skill.name == "figma_code_connect_handoff"
        assert stored_skill.mint_evidence["reflexion"]["critic_policy"][
            "source_label"] == "Figma Code Connect Handoff"
        assert stored_skill.mint_evidence["reflexion"]["proposal"][
            "proposed_name"] == "figma_code_connect_handoff"
        # Trace fragment persisted with kind=trace
        all_frags = store.search_fragments("figma", k=5)
        assert any(f.kind == FragmentKind.TRACE for f in all_frags)
    finally:
        store.close()


def test_skill_mint_below_floor_not_queued():
    store = BrainStore.open(":memory:")
    try:
        trace = {
            "user_message": "open browser",
            "tool_calls": [{"name": "navigate", "status": "ok"}],  # only 1
            "outcome": "success",
        }
        result = queue_skill_mint(
            store=store, trace=trace, outcome="success",
            owner_user="founder", contributing_agent="claude-sonnet-4.7",
        )
        assert not result.queued
        assert "below mint floor" in result.reason
    finally:
        store.close()


def test_skill_mint_failure_outcome_not_queued():
    store = BrainStore.open(":memory:")
    try:
        result = queue_skill_mint(
            store=store, trace={"tool_calls": []}, outcome="failed",
            owner_user="founder", contributing_agent="gpt-5",
        )
        assert not result.queued
        assert "no mint" in result.reason
    finally:
        store.close()


def test_skill_mint_tool_labels_its_cell_record_as_receipt_only(monkeypatch):
    import json
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    try:
        mcp = build_server(store=store, default_owner_user="founder")
        trace = {
            "trace_id": "tr-cell-mint",
            "tool_calls": [
                {"name": "host.probe", "status": "ok"},
                {"name": "host.write", "status": "ok"},
            ],
            "secret": "sk-test-1234567890abcdef",
        }

        result = mcp._tools["brain.skill_mint"].handler(
            trace=trace,
            outcome="success",
            contributing_agent="codex",
            session_id="codex-session-1",
        )

        assert result["ok"] is True
        assert result["cell_receipt"] is True
        assert result["cell_authority"] is False
        assert result["legacy_authority"] is True
        assert result["migration_status"] == "receipt-only"
        assert "cell_first" not in result
        assert result["brain_written"] is True
        assert result["legacy_projection_written"] is True
        assert result["cell_record_root"] \
            == "app:brain-control-ledger:v1:entry:1"
        assert bridge.created == []
        receipt = bridge.deliberations[0]
        assert receipt["space"] == "app:brain-control-ledger:v1"
        assert receipt["category"] \
            == "app:brain-control-ledger:v1:category:compliance-event"
        claims = receipt["payload"]
        assert claims["operation"] == "brain.skill_mint"
        assert claims["trace_id"] == "tr-cell-mint"
        assert claims["tool_call_count"] == 2
        assert "sk-test-1234567890abcdef" not in json.dumps(claims)
        assert receipt["idempotency_key"].startswith(
            "brain-control:skill-mint:"
        )
        repeated = mcp._tools["brain.skill_mint"].handler(
            trace=trace,
            outcome="success",
            contributing_agent="codex",
            session_id="codex-session-1",
        )
        assert repeated["ok"] is True
        assert bridge.deliberations[1]["idempotency_key"] \
            == receipt["idempotency_key"]
        assert bridge.deliberations[1]["payload"] == receipt["payload"]
        assert store.list_fragments(kinds=[FragmentKind.TRACE], limit=20)
    finally:
        store.close()


def test_skill_mint_tool_cell_failure_prevents_trace_projection(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        mcp = build_server(store=store, default_owner_user="founder")
        trace = {
            "trace_id": "tr-cell-denied",
            "tool_calls": [
                {"name": "host.probe", "status": "ok"},
                {"name": "host.write", "status": "ok"},
            ],
        }

        result = mcp._tools["brain.skill_mint"].handler(
            trace=trace,
            outcome="success",
            contributing_agent="codex",
            session_id="codex-session-1",
        )

        assert result["ok"] is False
        assert result["queued"] is False
        assert result["cell_receipt"] is False
        assert result["cell_authority"] is False
        assert result["legacy_authority"] is True
        assert result["migration_status"] == "receipt-required"
        assert "cell_first" not in result
        assert result["brain_written"] is False
        assert "cell unavailable" in result["error"]
        assert store.list_fragments(kinds=[FragmentKind.TRACE], limit=20) == []
    finally:
        store.close()


def test_hook_skill_mint_creates_cell_request_from_transcript(monkeypatch, tmp_path):
    import json
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        "\n".join([
            json.dumps({
                "message": {
                    "role": "user",
                    "content": "Build the cell-first route",
                },
            }),
            json.dumps({
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "u1", "name": "Read"},
                        {"type": "tool_use", "id": "u2", "name": "Write"},
                    ],
                },
            }),
        ]),
        encoding="utf-8",
    )
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.hook_skill_mint"].handler(
            session_id="claude-session-1",
            transcript_path=str(transcript),
        )

        assert result["ok"] is True
        assert result["cell_receipt"] is True
        assert result["cell_authority"] is False
        assert result["legacy_authority"] is True
        assert result["migration_status"] == "receipt-only"
        assert "cell_first" not in result
        assert result["brain_written"] is True
        assert result["legacy_projection_written"] is True
        assert result["cell_record_root"] \
            == "app:brain-control-ledger:v1:entry:1"
        assert bridge.created == []
        claims = bridge.deliberations[0]["payload"]
        assert claims["operation"] == "brain.skill_mint"
        assert claims["trace_id"] == "claude-session-1"
        assert claims["tool_call_count"] == 2
        assert store.list_fragments(kinds=[FragmentKind.TRACE], limit=20)
    finally:
        store.close()


def test_wiring_announce_registers_entries():
    store = BrainStore.open(":memory:")
    try:
        req = WiringAnnounceRequest(
            device_id="laptop-1",
            entries=[
                WiringEntry(name="revit-mcp", kind="mcp_server",
                             endpoint="http://localhost:48884",
                             device_id="laptop-1"),
                WiringEntry(name="notion-mcp", kind="mcp_server",
                             endpoint="https://api.notion.com",
                             device_id="laptop-1"),
            ],
            secret_refs=[
                SecretRef(ref="op://personal/notion/token",
                           resolver="1password", owner_user="founder"),
            ],
            cwd="/home/founder/some-project",
            git_remote="git@github.com:founder/some-project.git",
        )
        resp = announce_wiring(store=store, req=req, owner_user="founder")
        assert resp.registered == 2
        assert resp.scope_hint  # one of the Scope values
        entries = store.list_wiring(device_id="laptop-1")
        assert len(entries) == 2
        refs = store.list_secret_refs("founder")
        assert len(refs) == 1
    finally:
        store.close()


def test_wiring_announce_tool_cell_first_before_projection(monkeypatch):
    import json
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    bridge = _ObserveCellBridge()
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: bridge)
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.wiring_announce"].handler(
            device_id="laptop-1",
            entries=[{
                "name": "revit-mcp",
                "kind": "mcp_server",
                "endpoint": "http://localhost:48884",
            }],
            secret_refs=[{
                "ref": "op://personal/notion/token",
                "resolver": "1password",
            }],
            cwd="/home/founder/some-project",
            git_remote="git@github.com:founder/some-project.git",
            owner_user="founder",
        )

        assert result["ok"] is True
        assert result["cell_first"] is True
        assert result["brain_written"] is True
        assert result["registered"] == 1
        assert result["cell_record_root"] == "assembly-instance:observe-1"
        claims = json.loads(bridge.created[0]["fields"]["claims"])
        assert claims["operation"] == "brain.wiring_announce"
        assert claims["entry_count"] == 1
        assert claims["secret_ref_count"] == 1
        assert "op://personal/notion/token" not in bridge.created[0]["fields"]["claims"]
        assert len(store.list_wiring(device_id="laptop-1")) == 1
        assert len(store.list_secret_refs("founder")) == 1
    finally:
        store.close()


def test_wiring_announce_tool_cell_failure_prevents_projection(monkeypatch):
    from personal_brain import universal_runtime as ur

    store = BrainStore.open(":memory:")
    monkeypatch.setattr(ur, "UniversalRuntimeBridge", lambda: _ObserveCellBridge(
        fail=True,
    ))
    try:
        mcp = build_server(store=store, default_owner_user="founder")

        result = mcp._tools["brain.wiring_announce"].handler(
            device_id="laptop-1",
            entries=[{
                "name": "revit-mcp",
                "kind": "mcp_server",
                "endpoint": "http://localhost:48884",
            }],
            owner_user="founder",
        )

        assert result["ok"] is False
        assert result["cell_first"] is True
        assert result["brain_written"] is False
        assert result["registered"] == 0
        assert "cell unavailable" in result["error"]
        assert store.list_wiring(device_id="laptop-1") == []
    finally:
        store.close()


def test_scope_filter_in_context_excludes_other_users_private():
    store = BrainStore.open(":memory:")
    try:
        # founder's private fact
        store.write_fragment(Fragment(
            id="founder-private", kind=FragmentKind.FACT,
            text="founder secret note about Tower-A",
            scope=Scope.USER, owner_user="founder", provenance=_prov(),
        ))
        # teammate's private fact (same SCOPE=user but different owner)
        store.write_fragment(Fragment(
            id="teammate-private", kind=FragmentKind.FACT,
            text="teammate secret note about Tower-A",
            scope=Scope.USER, owner_user="teammate", provenance=_prov(),
        ))
        resp = make_context_payload(
            store=store, prompt="Tower-A note", owner_user="founder",
        )
        fact_ids = {f.id for f in resp.facts}
        assert "founder-private" in fact_ids
        assert "teammate-private" not in fact_ids, \
            "user-scope facts must be owner-filtered (arXiv 2505.18279)"
    finally:
        store.close()
