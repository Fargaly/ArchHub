"""Legacy typed-runtime UI compatibility shim.

`ui.element` is not the Universal Cell authority. It remains here only so saved
typed-runtime graphs and old Studio comparison courts can still cook while the
Cell-native application consumes the behavior capability by capability.

The active node-language authority is the Universal Cell floor in
`10.PRODUCT/13.NODE-LANGUAGE/SPEC.md`: persisted semantic facts are Cells, and
UI, relations, parameters, properties, sessions, and gates are graph structure.
This shim must not be promoted as a new primitive or used to widen the typed
catalogue.
"""
from __future__ import annotations

from typing import Any

from ..graph import Port, PortType
from ..registry import NodeSpec, register


LEGACY_MIGRATION_ONLY = True
AUTHORITY_STATUS = "superseded_by_universal_cell"
ACTIVE_AUTHORITY = "10.PRODUCT/13.NODE-LANGUAGE"
PROMOTION_ALLOWED = False


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _string(value: Any) -> str:
    return "" if value is None else str(value)


def _project_element(config: dict, node_id: str, inputs: dict) -> dict:
    """Build the DOM spec for one legacy ui.element compatibility node."""
    data = _as_dict(config.get("data")) or config
    tag = data.get("tag") or config.get("tag") or "div"

    attrs: dict = {"data-node": node_id} if node_id else {}
    cls = data.get("cls", config.get("cls"))
    if cls:
        attrs["class"] = cls

    text = _string(data.get("text", config.get("text", "")))
    bind = data.get("bind", config.get("bind"))
    if bind:
        # A bound value arrives on the `value` input when wired; fall back to a
        # literal `value` in data so an unwired preview still renders.
        bound = inputs.get("value")
        if bound is None:
            bound = data.get("value", config.get("value"))
        text += _string(bound)

    # Children already-projected upstream (list of DOM specs) ride through when
    # provided on the `children` input; otherwise this element is a leaf here
    # and the full-graph projector expands `data.children` by id.
    children = inputs.get("children")
    if isinstance(children, dict):
        children = [children]
    elif not isinstance(children, list):
        children = []

    return {"tag": tag, "attrs": attrs, "text": text, "children": children}


def _ui_element_executor(config: dict, inputs: dict, ctx) -> dict:
    """Project this compatibility node into a DOM spec on `child`."""
    node_id = ""
    node = getattr(ctx, "node", None)
    if isinstance(node, dict):
        node_id = node.get("id") or ""
    else:
        node_id = getattr(node, "id", "") or config.get("__node_id__", "") or ""

    child = _project_element(config or {}, node_id, inputs or {})
    return {"child": child, "parent": (inputs or {}).get("parent")}


register(
    NodeSpec(
        type="ui.element",
        category="ui",
        display_name="UI Element",
        description=(
            "Legacy typed-runtime DOM element compatibility node. Wire its "
            "`child` into another element's `parent` to compose a UI tree; "
            "superseded by Universal Cell authority."
        ),
        inputs=[
            Port(name="parent", type=PortType.UI,
                 description="DOM parent this element hangs under"),
            Port(name="children", type=PortType.UI,
                 description="Projected child element or child element list"),
            Port(name="value", type=PortType.ANY,
                 description="Bound value appended when `bind` is set"),
        ],
        outputs=[
            Port(name="child", type=PortType.UI,
                 description="This element's projected DOM spec"),
        ],
        config_schema={
            "tag": {"type": "string", "default": "div",
                    "description": "HTML tag name"},
            "text": {"type": "string", "default": "",
                     "description": "Static text content"},
            "cls": {"type": "string", "default": "",
                    "description": "CSS class"},
            "bind": {"type": "string", "default": "",
                     "description": "Node id whose value appends to text"},
        },
        icon="UI",
    ),
    _ui_element_executor,
)
