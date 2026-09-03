from __future__ import annotations

from nodelang.cell_protocols import CellBatch, read_relation
from nodelang.cell_timeline_view import (
    TIMELINE_TEMPLATE_MEMBER_ROOTS,
    TIMELINE_TEMPLATE_ROOT,
    VIEW_TEMPLATE_PREFIX,
    compose_timeline_template,
)
from nodelang.cell_view_template import (
    compose_view_template_protocol,
    is_view_template,
    render_view_template,
)
from nodelang.inspector_descriptor import _timeline
from nodelang.universal_cell import NULL_CELL_ID, CellStore


def _timeline_store():
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(
        batch, prefix=VIEW_TEMPLATE_PREFIX
    )
    assert compose_timeline_template(batch, protocol) == (
        TIMELINE_TEMPLATE_ROOT
    )
    batch.commit()
    return store, protocol


def _representative_projection():
    return {
        "selected": "assembly:alpha",
        "selected_assembly": {
            "lifecycle": {
                "states": [
                    {
                        "name": "WIP",
                        "head_count": 2,
                        "heads": [
                            {
                                "revision": "revision:wip-a",
                                "content_digest": "content-digest-a",
                                "content_bytes": 144,
                                "branch": "branch:main",
                                "branch_label": "main",
                                "parents": ["revision:base"],
                                "actor": "actor:founder",
                                "evidence": ["evidence:court-a"],
                                "evidence_details": [
                                    {
                                        "root": "evidence:court-a",
                                        "court": "court:release",
                                        "result": "failed",
                                        "checks": {
                                            "source-hash": True,
                                            "browser-court": False,
                                            "authority": True,
                                        },
                                        "builder": "builder:release",
                                        "duration_ms": 37,
                                        "digest": (
                                            "0123456789abcdef0123456789abcdef"
                                        ),
                                    },
                                ],
                            },
                            {
                                "revision": "revision:wip-b",
                                "content_digest": "content-digest-b",
                                "content_bytes": 233,
                                "branch": "branch:alternate",
                                "branch_label": "",
                                "parents": [
                                    "revision:base", "revision:other"
                                ],
                                "actor": "actor:reviewer",
                                "evidence": ["evidence:untyped"],
                                "evidence_details": [
                                    {
                                        "root": "evidence:untyped",
                                        "court": None,
                                        "result": "untyped evidence",
                                        "checks": {},
                                    },
                                ],
                            },
                        ],
                    },
                    {
                        "name": "SHARED",
                        "head_count": 0,
                        "heads": [],
                    },
                    {
                        "name": "PUBLISHED",
                        "head_count": 1,
                        "heads": [
                            {
                                "revision": "revision:published",
                                "content_digest": "published-digest",
                                "content_bytes": 377,
                                "branch": "branch:release",
                                "branch_label": "release",
                                "parents": [],
                                "actor": "actor:founder",
                                "evidence": [],
                                "evidence_details": [],
                            },
                        ],
                    },
                ],
                "transitions": [
                    {
                        "relation": "transition:share",
                        "source_name": "wip",
                        "target_name": "shared",
                        "source_revision": "revision:wip-a",
                        "ready": True,
                        "already_promoted": False,
                        "required_evidence": ["evidence-type:review"],
                        "court": "court:share",
                    },
                    {
                        "relation": "transition:publish",
                        "source_name": "shared",
                        "target_name": "published",
                        "source_revision": "revision:shared",
                        "ready": False,
                        "already_promoted": True,
                        "required_evidence": [],
                        "court": "court:publish",
                    },
                    {
                        "relation": "transition:archive",
                        "source_name": "published",
                        "target_name": "archived",
                        "source_revision": None,
                        "ready": False,
                        "already_promoted": False,
                        "required_evidence": [
                            "evidence-type:retention",
                            "evidence-type:approval",
                        ],
                        "court": "court:archive",
                    },
                    {
                        "relation": "transition:deploy",
                        "source_name": "published",
                        "target_name": "deployed",
                        "source_revision": "revision:published",
                        "ready": True,
                        "already_promoted": False,
                        "required_evidence": [],
                        "court": "court:deploy",
                    },
                ],
                "history": [
                    {
                        "revision": "revision:wip-a",
                        "state": "wip",
                        "branch": "branch:main",
                        "branch_label": "main",
                        "parents": ["revision:base"],
                        "actor": "actor:founder",
                        "evidence": ["evidence:court-a"],
                        "timestamp": "2026-07-16T12:30:00Z",
                    },
                    {
                        "revision": "revision:base",
                        "state": "wip",
                        "branch": "branch:base",
                        "branch_label": None,
                        "parents": [],
                        "actor": "actor:founder",
                        "evidence": [],
                        "timestamp": None,
                    },
                ],
            },
        },
    }


def test_timeline_has_twelve_migration_members_with_eleven_executable_roots():
    store, protocol = _timeline_store()
    snapshot = store.snapshot()

    assert len(TIMELINE_TEMPLATE_MEMBER_ROOTS) == 12
    assert len(set(TIMELINE_TEMPLATE_MEMBER_ROOTS)) == 11
    assert TIMELINE_TEMPLATE_MEMBER_ROOTS[5] == (
        TIMELINE_TEMPLATE_MEMBER_ROOTS[8]
    )
    assert all(
        is_view_template(snapshot, protocol, root)
        for root in set(TIMELINE_TEMPLATE_MEMBER_ROOTS)
    )
    assert all(
        snapshot.cells[root].link0 != NULL_CELL_ID
        for root in set(TIMELINE_TEMPLATE_MEMBER_ROOTS)
    )
    transparent_members = {
        root
        for root in set(TIMELINE_TEMPLATE_MEMBER_ROOTS)
        if any(
            member.role_id == protocol.role("transparent")
            for member in read_relation(snapshot, root, budget=256)
        )
    }
    assert transparent_members == {TIMELINE_TEMPLATE_MEMBER_ROOTS[4]}


def test_timeline_template_has_exact_representative_legacy_parity():
    store, protocol = _timeline_store()
    projection = _representative_projection()

    assert render_view_template(
        store.snapshot(),
        protocol,
        TIMELINE_TEMPLATE_ROOT,
        projection,
    ) == _timeline(projection)


def test_timeline_template_matches_legacy_when_lifecycle_is_absent():
    store, protocol = _timeline_store()
    projection = {
        "selected": "assembly:without-lifecycle",
        "selected_assembly": {"lifecycle": None},
    }

    assert render_view_template(
        store.snapshot(),
        protocol,
        TIMELINE_TEMPLATE_ROOT,
        projection,
    ) == _timeline(projection) == []


def test_timeline_projects_plain_session_actions_without_lifecycle_hashes():
    store, protocol = _timeline_store()
    projection = {
        "selected": "cell:alpha",
        "selected_assembly": None,
        "action_history": {
            "transactions": [{
                "root": "transaction:private-identity",
                "operation": "Property",
                "route": "POST /api/universal/property",
                "state": "applied",
                "timestamp": "2026-07-19T12:00:00+00:00",
                "change_count": 1,
                "capability": "catalog.configure",
                "scope_count": 1,
                "interface": None,
            }],
        },
    }

    rendered = render_view_template(
        store.snapshot(), protocol, TIMELINE_TEMPLATE_ROOT, projection
    )

    assert rendered == _timeline(projection)
    text = str(rendered)
    assert "APPLIED / Property" in text
    assert "1 change" in text
    assert "transaction:private-identity" not in {
        descriptor.get("text") for descriptor in rendered
    }
