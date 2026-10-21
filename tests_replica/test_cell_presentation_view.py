from __future__ import annotations

from copy import deepcopy

import pytest

from nodelang.cell_presentation_view import (
    PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS,
    PRESENTATION_LIST_TEMPLATE_ROOT,
    VIEW_TEMPLATE_PREFIX,
    compose_presentation_list_template,
)
from nodelang.cell_protocols import CellBatch
from nodelang.cell_view_template import (
    compose_view_template_protocol,
    is_view_template,
    render_view_template,
)
from nodelang.inspector_descriptor import _presentation
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    preview_universal_theme,
    project_universal_canvas,
    select_universal_root,
)
from nodelang.universal_cell import NULL_CELL_ID, CellStore


def _template_store():
    store = CellStore()
    batch = CellBatch(store)
    protocol = compose_view_template_protocol(
        batch, prefix=VIEW_TEMPLATE_PREFIX
    )
    assert compose_presentation_list_template(batch, protocol) == (
        PRESENTATION_LIST_TEMPLATE_ROOT
    )
    batch.commit()
    return store, protocol


def _render(store, protocol, projection):
    return render_view_template(
        store.snapshot(),
        protocol,
        PRESENTATION_LIST_TEMPLATE_ROOT,
        projection,
    )


def _nonpersonal_projection():
    return {
        "selected": "node:alpha",
        "properties": [
            {
                "relation": "property:color",
                "label": "color",
                "value": "#aBcD09",
                "editable": False,
                "presentation_editable": True,
                "presentation_control": "control:color",
                "presentation_event_fact_input": "fact:submitted-value",
                "presentation_reset": False,
                "presentation_source_mode": "inherited",
                "presentation_source": "Inherited node appearance",
            },
            {
                "relation": "property:icon",
                "label": "icon",
                "value": "grid_view",
                "editable": False,
            },
            {
                "relation": "property:presentation",
                "label": "presentation",
                "value": "#12345g",
                "editable": True,
                "control": "property:presentation",
                "event_fact_input": "fact:submitted-value",
            },
            {
                "relation": "property:title",
                "label": "title",
                "value": "Alpha",
                "editable": True,
            },
        ],
        "configuration": {"personal_asset": "settings:founder"},
    }


def _personal_projection():
    return {
        "selected": "settings:founder",
        "properties": [],
        "configuration": {
            "personal_asset": "settings:founder",
            "state": "wip",
            "binding_mode": "personal-wip",
            "preview_revision": "revision:new",
            "binding": "binding:founder",
            "court": {"state": "passed"},
            "theme": {
                "accent": "#d97757",
                "ink_soft": "rgba(10, 20, 30, .6)",
            },
            "theme_fields": [
                {
                    "key": "accent",
                    "value": "#d97757",
                    "control": "control:theme:accent",
                    "event_fact_input": "fact:submitted-value",
                },
                {
                    "key": "ink_soft",
                    "value": "rgba(10, 20, 30, .6)",
                    "control": "control:theme:ink-soft",
                    "event_fact_input": "fact:submitted-value",
                },
            ],
            "history": [
                {
                    "revision": "revision:old",
                    "state": "wip",
                    "reason": None,
                    "digest": "00112233445566778899",
                    "evidence": [],
                    "current": False,
                    "restore_control": "control:restore:old",
                },
                {
                    "revision": "revision:new",
                    "state": "shared",
                    "reason": "founder-review",
                    "digest": "ffeeddccbbaa99887766",
                    "evidence": [
                        {
                            "root": "court:evidence:theme",
                            "result": "passed",
                            "checks": {
                                "source-hash": True,
                                "browser-court": False,
                                "authority": True,
                            },
                            "builder": "builder:theme",
                            "duration_ms": 37,
                            "digest": "abcdef0123456789abcdef",
                        },
                        {
                            "root": None,
                            "result": "failed",
                            "checks": {},
                            "builder": "builder:fallback",
                            "duration_ms": 5,
                            "digest": "99887766554433221100",
                        },
                    ],
                    "current": True,
                    "restore_control": None,
                },
            ],
            "shared_revision": "revision:shared",
            "published_revision": None,
            "can_promote": False,
            "can_publish": True,
        },
    }


def test_presentation_has_thirteen_ordered_migration_incidences():
    store, protocol = _template_store()
    snapshot = store.snapshot()

    assert len(PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS) == 13
    assert len(set(PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS)) == 12
    assert PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS[6] == (
        PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS[9]
    )
    assert all(
        is_view_template(snapshot, protocol, root)
        for root in set(PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS)
    )
    assert all(
        snapshot.cells[root].link0 != NULL_CELL_ID
        for root in set(PRESENTATION_LIST_TEMPLATE_MEMBER_ROOTS)
    )


def test_nonpersonal_presentation_has_exact_raw_projection_parity():
    store, protocol = _template_store()
    projection = _nonpersonal_projection()

    assert _render(store, protocol, projection) == _presentation(projection)


def test_nonpersonal_presentation_is_absent_without_presentable_rows():
    store, protocol = _template_store()
    projection = _nonpersonal_projection()
    projection["properties"] = [projection["properties"][-1]]

    assert _render(store, protocol, projection) == _presentation(projection) == []


def test_personal_presentation_has_exact_theme_history_and_evidence_parity():
    store, protocol = _template_store()
    projection = _personal_projection()

    actual = _render(store, protocol, projection)
    assert actual == _presentation(projection)
    history = actual[0]["children"][-2]
    assert [row["key"] for row in history["children"][1:]] == [
        "theme-history-row:revision:new",
        "theme-history-row:revision:old",
    ]


@pytest.mark.parametrize(
    (
        "published_revision",
        "can_publish",
        "can_promote",
        "shared_revision",
    ),
    (
        ("revision:published", False, False, "revision:shared"),
        (None, True, False, "revision:shared"),
        (None, False, True, None),
        (None, False, False, "revision:shared"),
        (None, False, False, None),
    ),
)
def test_personal_action_states_have_exact_raw_projection_parity(
    published_revision,
    can_publish,
    can_promote,
    shared_revision,
):
    store, protocol = _template_store()
    projection = _personal_projection()
    configuration = projection["configuration"]
    configuration.update({
        "published_revision": published_revision,
        "can_publish": can_publish,
        "can_promote": can_promote,
        "shared_revision": shared_revision,
    })

    assert _render(store, protocol, projection) == _presentation(projection)


def test_live_universal_application_projections_keep_exact_parity():
    template_store, protocol = _template_store()
    store, registry = build_universal_application(resolve_map_path())

    projections = [project_universal_canvas(store, registry)]
    personal_asset = registry.view_sessions[
        registry.authorization.subject_root
    ].settings_root
    select_universal_root(store, registry, personal_asset)
    projections.append(project_universal_canvas(store, registry))
    preview_universal_theme(store, registry, {"accent": "#1188cc"})
    projections.append(project_universal_canvas(store, registry))

    for projection in projections:
        assert _render(template_store, protocol, projection) == _presentation(
            projection
        )


def test_template_consumes_projection_without_presenter_specific_shaping():
    store, protocol = _template_store()
    projection = _personal_projection()
    before = deepcopy(projection)

    _render(store, protocol, projection)

    assert projection == before
