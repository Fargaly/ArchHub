from __future__ import annotations

import hashlib

from nodelang.cell_authority_view import (
    AUTHORITY_LIST_PREFIX,
    AUTHORITY_LIST_TEMPLATE_MEMBER_ROOTS,
    AUTHORITY_LIST_TEMPLATE_ROOT,
    VIEW_TEMPLATE_PREFIX,
    compose_authority_list_template,
)
from nodelang.cell_browser_sessions import (
    issue_browser_session,
    revoke_browser_session,
)
from nodelang.cell_protocols import CellBatch, read_relation
from nodelang.cell_view_template import (
    compose_view_template_protocol,
    is_view_template,
    render_view_template,
)
from nodelang.inspector_descriptor import _authority
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    _PROPERTIES_PRESENTER_PARTS,
    build_universal_application,
    project_universal_canvas,
)
from nodelang.universal_cell import NULL_CELL_ID, CellStore


def _authority_template():
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(
        batch, prefix=VIEW_TEMPLATE_PREFIX
    )
    assert compose_authority_list_template(batch, protocol) == (
        AUTHORITY_LIST_TEMPLATE_ROOT
    )
    batch.commit()
    return store, protocol


def _render(store, protocol, projection):
    return render_view_template(
        store.snapshot(),
        protocol,
        AUTHORITY_LIST_TEMPLATE_ROOT,
        projection,
        budget=1_000_000,
    )


REPRESENTATIVE_PROJECTION = {
    "selected": "authority:subject:alpha",
    "authorization": {
        "subject_label": "Founder Alpha",
        "scope_label": "Governed workspace",
        "session": "session:desktop:alpha",
        "assigned_canvas_roots": 0,
        "state": "released",
        "version": "2.4.0",
        "default": "deny",
        "rule_count": 17,
        "assurance_label": "Hardware-bound authentication",
        "tenant_label": "Tenant Alpha",
        "native_identity": {
            "device_custody": {
                "active": 1,
                "hardware_backed": 1,
            },
        },
        "browser_sessions": [
            {
                "root": "browser-session:active",
                "state": "active",
                "assurance": "assurance:hardware",
                "expires_at": "2026-07-16T22:00:00Z",
                "revocation_reason": None,
            },
            {
                "root": "browser-session:revoked",
                "state": "revoked",
                "assurance": "assurance:local",
                "expires_at": "2026-07-16T21:00:00Z",
                "revocation_reason": "User signed out\nfrom this browser",
            },
        ],
        "relationships": [
            {
                "root": "authority:relationship:verified",
                "source": "identity:founder",
                "target": "tenant:alpha",
                "kind": "membership",
                "state": "active",
                "scope": None,
                "actions": [],
                "issuer": "identity:founder",
                "changed_by": "identity:founder",
                "changed_at": "2026-07-16T20:00:00Z",
                "reason": "Founder belongs to tenant Alpha",
                "verified": True,
                "authority_reason": "verified",
            },
            {
                "root": "authority:relationship:denied",
                "source": "principal:reader",
                "target": "identity:guest",
                "kind": "delegation",
                "state": "revoked",
                "scope": "scope:restricted",
                "actions": ["action:read"],
                "issuer": "identity:founder",
                "changed_by": "identity:reviewer",
                "changed_at": "2026-07-16T20:30:00Z",
                "reason": "Signature mismatch \"court\"",
                "verified": False,
                "authority_reason": "signature verification failed",
            },
        ],
    },
    "configuration": {
        "state": "WIP",
        "heads": ["revision:wip-a", "revision:wip-b"],
    },
    "composer": {
        "state": "released",
        "admitted_adapters": 2,
        "extension_mode": "proposal-only",
    },
    "catalog": [
        {"id": "definition:one"},
        {"id": "definition:two"},
        {"id": "definition:three"},
    ],
    "authority_stack": [
        {
            "root": "authority:catalog",
            "label": "Assembly catalogue",
            "role": "catalogue",
            "state": "released",
        },
        {
            "root": "authority:adapter",
            "label": "Device custody adapter",
            "role": "allowlisted adapter",
            "state": "WIP",
        },
    ],
}


def test_authority_list_preserves_eight_ordered_migration_incidences():
    store, protocol = _authority_template()
    try:
        snapshot = store.snapshot()
        assert _PROPERTIES_PRESENTER_PARTS["authority-list"] == (
            "section",
            "heading",
            "list",
            "row",
            "text",
            "button",
            "details",
            "action-binding",
        )
        assert len(AUTHORITY_LIST_TEMPLATE_MEMBER_ROOTS) == 8
        assert len(set(AUTHORITY_LIST_TEMPLATE_MEMBER_ROOTS)) == 7
        assert AUTHORITY_LIST_TEMPLATE_MEMBER_ROOTS[0] == (
            AUTHORITY_LIST_TEMPLATE_ROOT
        )
        assert AUTHORITY_LIST_TEMPLATE_MEMBER_ROOTS[5] == (
            AUTHORITY_LIST_TEMPLATE_MEMBER_ROOTS[7]
        )
        assert all(
            is_view_template(snapshot, protocol, root)
            for root in set(AUTHORITY_LIST_TEMPLATE_MEMBER_ROOTS)
        )
        assert all(
            snapshot.cells[root].link0 != NULL_CELL_ID
            for root in set(AUTHORITY_LIST_TEMPLATE_MEMBER_ROOTS)
        )
    finally:
        store.close()


def test_authority_list_uses_parent_map_and_transparent_fragments():
    store, protocol = _authority_template()
    try:
        snapshot = store.snapshot()
        operation_role = protocol.role("operation")

        def operation(expression_name):
            members = read_relation(
                snapshot,
                "%s:expression:%s" % (
                    AUTHORITY_LIST_PREFIX,
                    expression_name,
                ),
                budget=128,
            )
            return next(
                member.participant_id
                for member in members
                if member.role_id == operation_role
            )

        assert operation("parent-context") == protocol.operation("parent")
        assert operation("stack-roots") == protocol.operation("map")
        assert operation("relationship-mapping-fragments") == (
            protocol.operation("map")
        )
        fragment_roots = {
            AUTHORITY_LIST_PREFIX + ":stack:fragment",
            AUTHORITY_LIST_PREFIX + ":browser:fragment",
            AUTHORITY_LIST_PREFIX + ":relationship:fragment",
        }
        assert all(
            is_view_template(snapshot, protocol, root)
            for root in fragment_roots
        )
        assert all(
            any(
                member.role_id == protocol.role("transparent")
                for member in read_relation(snapshot, root, budget=128)
            )
            for root in fragment_roots
        )
    finally:
        store.close()


def test_authority_list_has_exact_representative_raw_projection_parity():
    store, protocol = _authority_template()
    try:
        assert _render(store, protocol, REPRESENTATIVE_PROJECTION) == (
            _authority(REPRESENTATIVE_PROJECTION)
        )
    finally:
        store.close()


def test_live_universal_application_states_have_exact_authority_parity():
    template_store, protocol = _authority_template()
    store, registry = build_universal_application(resolve_map_path())
    try:
        initial = project_universal_canvas(store, registry)
        assert _render(template_store, protocol, initial) == _authority(initial)

        browser_root, _ = issue_browser_session(
            store,
            registry.browser_session_protocol,
            subject_root=registry.authorization.subject_root,
            view_root=registry.application_root,
            tenant_root=registry.authorization.tenant_root,
            assurance_root=registry.authorization.assurance_root,
            token_digest=hashlib.sha256(b"authority-view-token").hexdigest(),
            csrf_digest=hashlib.sha256(b"authority-view-csrf").hexdigest(),
            issued_at=1_784_224_000.0,
            lifetime_seconds=1_800.0,
        )
        active = project_universal_canvas(store, registry)
        assert active["authorization"]["browser_sessions"]
        assert _render(template_store, protocol, active) == _authority(active)

        revoke_browser_session(
            store,
            registry.browser_session_protocol,
            browser_root,
            reason="Founder closed the browser session",
        )
        revoked = project_universal_canvas(store, registry)
        assert revoked["authorization"]["browser_sessions"][0][
            "revocation_reason"
        ] == "Founder closed the browser session"
        assert _render(template_store, protocol, revoked) == _authority(revoked)
    finally:
        store.close()
        template_store.close()
