"""Real-application court for the generic graph-held interaction path."""
from nodelang.cell_interactions import (
    InteractionProjectionBroker,
    execute_interaction,
)
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    ensure_universal_properties_panel_interactions,
    project_universal_canvas,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell


def test_real_properties_tabs_execute_through_one_generic_graph_path():
    store, registry = build_universal_application(resolve_map_path())
    authority = registry.authorization
    view = registry.view_sessions[authority.subject_root]
    browser_session_root = "test:interaction-browser-session"
    store.commit(store.revision, create=(Cell(
        browser_session_root,
        NULL_CELL_ID,
        NULL_CELL_ID,
        b"test browser session",
    ),))
    event_root, interactions = ensure_universal_properties_panel_interactions(
        store, registry, authority.subject_root
    )
    canvas = project_universal_canvas(
        store,
        registry,
        authentication_context=authority.session.context(),
    )
    panels = tuple(
        panel["id"]
        for panel in canvas["inspector"]["presentation"]["panels"]
    )
    assert len(panels) >= 2
    current = store.read(view.properties_panel_incidence).link1
    desired = next(panel for panel in panels if panel != current)

    broker = InteractionProjectionBroker()
    handle = broker.mint(
        store.snapshot(),
        session_root=browser_session_root,
        subject_root=authority.subject_root,
        view_root=view.root_id,
    )
    broker.issue(
        handle,
        store.snapshot(),
        registry.interaction_protocol,
        panels,
        tuple(interactions[panel] for panel in panels),
        rule_protocol=registry.rule_protocol,
        transaction_protocol=registry.transaction_protocol,
    )
    result = execute_interaction(
        store,
        registry.interaction_protocol,
        registry.transaction_protocol,
        registry.rule_protocol,
        authority.protocol,
        authority.broker,
        authority.session.context(),
        broker,
        handle,
        interaction_root=interactions[desired],
        control_root=desired,
        event_root=event_root,
        expected_revision=store.revision,
    )

    assert view.properties_panel_incidence in result.rewrite.touched_roots
    assert store.read(view.properties_panel_incidence).link1 == desired
    projected = project_universal_canvas(
        store,
        registry,
        authentication_context=authority.session.context(),
    )
    assert projected["inspector"]["presentation"]["active"] == desired
