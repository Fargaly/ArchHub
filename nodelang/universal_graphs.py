"""Create and open graph compositions in the current application's own store."""
from . import universal_application as app
from .cell_protocols import read_relation
from .universal_cell import InvalidCell


def project_graph_index(store, registry, *, authentication_context=None):
    """List the root and top-level compositions admitted to this exact view."""
    # The normal projection settles indexes and checks the viewer, signed
    # resource grants, and current scope before any graph name is disclosed.
    canvas = app.project_universal_canvas(
        store, registry, authentication_context=authentication_context)
    snapshot = store.dense_snapshot()
    view, _ = app._view_session_for_context(registry, authentication_context)
    app._session_canvas_roots(snapshot, registry, view)
    top = app._visibility_scope_projection(snapshot, registry, view)[:3]
    visible, _, _ = app._apply_view_scope_exposure(
        snapshot, registry, view, registry.canvas_root, top)
    compositions = tuple(root for root in visible
                         if app._is_universal_composition(snapshot, registry, root))
    admitted = frozenset(compositions)
    title_roots = []
    for member in read_relation(snapshot, view.properties_lens_root, budget=100_000):
        if member.role_id != registry.roles["scope"]:
            continue
        members = read_relation(snapshot, member.participant_id, budget=16)
        if app._one_for_role(members, registry.roles["owner"]) in admitted:
            title_roots.append(member.participant_id)
    properties = app._property_index(snapshot, registry, tuple(title_roots))
    graphs = []
    for root in (registry.canvas_root, *compositions):
        rows = app._rows_by_label(snapshot, properties.get(root, ()))
        title = rows.get("title")
        graphs.append({
            "id": root,
            "title": (app._text(snapshot, title.value_root) if title is not None
                      else "ArchHub" if root == registry.canvas_root else "Graph"),
            "state": "idle", "host": "archhub", "when": "saved",
            "file": "Graph composition", "last": "Open graph", "model": "",
        })
    trail = app._read_view_scope_trail_structure(snapshot, registry, view)
    current = next((root for root in trail[1:] if root in admitted), registry.canvas_root)
    return {"ok": True, "graphs": graphs, "current_graph": current, "canvas": canvas}


def open_graph(store, registry, root, *, authentication_context=None):
    """Use the existing scope transition; a raw store root is not admission."""
    if type(root) is not str or not root:
        raise InvalidCell("graph root is required")
    index = project_graph_index(store, registry, authentication_context=authentication_context)
    if root not in {row["id"] for row in index["graphs"]}:
        raise InvalidCell("graph is outside the admitted graph list")
    canvas = index["canvas"]
    if canvas["scope"]["current"] == root:
        return index
    if canvas["scope"]["current"] != registry.canvas_root:
        app.set_universal_scope(store, registry, registry.canvas_root,
            projected_canvas=canvas, authentication_context=authentication_context)
        canvas = app.project_universal_canvas(store, registry,
            authentication_context=authentication_context)
    if root != registry.canvas_root:
        app.set_universal_scope(store, registry, root, projected_canvas=canvas,
            authentication_context=authentication_context)
    return project_graph_index(store, registry, authentication_context=authentication_context)


def create_graph(store, registry, title, *, authentication_context=None):
    """Create a blank WIP composition without grouping the current selection."""
    if type(title) is not str or not title.strip() or len(title.strip().encode("utf-8")) > 256:
        raise InvalidCell("graph title is empty or too large")
    index = open_graph(store, registry, registry.canvas_root,
                       authentication_context=authentication_context)
    root, _ = app._compose_universal_selection(store, registry, title=title,
        empty=True, projected_canvas=index["canvas"],
        authentication_context=authentication_context)
    result = open_graph(store, registry, root, authentication_context=authentication_context)
    result["graph"] = next(row for row in result["graphs"] if row["id"] == root)
    return result
