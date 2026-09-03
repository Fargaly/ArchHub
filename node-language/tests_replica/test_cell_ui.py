"""Court for safe browser projection from universal-cell UI relations."""
import pytest

from nodelang.cell_protocols import append_relation_member
from nodelang.cell_ui import UIBuilder, bootstrap_ui_protocol, render_ui
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def test_ui_structure_text_attributes_and_order_are_graph_cells():
    store = CellStore()
    protocol = bootstrap_ui_protocol(store)
    ui = UIBuilder(store, protocol)
    first = ui.element("span", text="First < safe")
    second = ui.element("strong", text="Second")
    root = ui.element(
        "section",
        class_name="panel active",
        attributes={"data-mode": "graph", "aria-label": "A & B"},
        children=(first, second),
    )
    ui.commit()
    assert render_ui(store.snapshot(), protocol, root) == (
        '<section class="panel active" data-mode="graph" '
        'aria-label="A &amp; B"><span>First &lt; safe</span>'
        '<strong>Second</strong></section>'
    )
    assert all(type(cell) is Cell for cell in store.snapshot().cells.values())


@pytest.mark.parametrize("tag,attributes,error", [
    ("script", {}, "tag"),
    ("div", {"onclick": "steal()"}, "executable"),
    ("div", {"style": "background:url(https://x)"}, "executable"),
    ("a", {"href": "javascript:steal()"}, "local absolute"),
    ("a", {"href": "https://example.com"}, "local absolute"),
])
def test_renderer_rejects_executable_or_unapproved_surface(tag, attributes, error):
    store = CellStore()
    protocol = bootstrap_ui_protocol(store)
    ui = UIBuilder(store, protocol)
    root = ui.element(tag, attributes=attributes)
    ui.commit()
    with pytest.raises(InvalidCell, match=error):
        render_ui(store.snapshot(), protocol, root)


def test_renderer_rejects_recursive_ui_and_budget_exhaustion():
    store = CellStore()
    protocol = bootstrap_ui_protocol(store)
    ui = UIBuilder(store, protocol)
    child = ui.element("span", text="child")
    root = ui.element("div", children=(child,))
    ui.commit()
    with pytest.raises(InvalidCell, match="budget"):
        render_ui(store.snapshot(), protocol, root, budget=1)
    append_relation_member(
        store, child, protocol.role("child"), root
    )
    with pytest.raises(InvalidCell, match="cycle"):
        render_ui(store.snapshot(), protocol, root)


def test_ui_text_can_bind_an_existing_value_cell_without_copying_it():
    store = CellStore()
    protocol = bootstrap_ui_protocol(store)
    value = Cell("shared:title", NULL_CELL_ID, NULL_CELL_ID, b"First title")
    store.commit(store.revision, create=(value,))
    ui = UIBuilder(store, protocol)
    root = ui.element("h1", text_root=value.id)
    ui.commit()
    assert render_ui(store.snapshot(), protocol, root) == "<h1>First title</h1>"
    store.commit(store.revision, replace=(Cell(
        value.id, value.link0, value.link1, b"Changed title"
    ),))
    assert render_ui(store.snapshot(), protocol, root) == "<h1>Changed title</h1>"


def test_ui_element_cannot_copy_and_bind_text_at_the_same_time():
    store = CellStore()
    protocol = bootstrap_ui_protocol(store)
    ui = UIBuilder(store, protocol)
    with pytest.raises(InvalidCell, match="copy and bind"):
        ui.element("span", text="copy", text_root="shared:title")
