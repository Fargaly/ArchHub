from urllib.parse import urlencode

from tests_replica.test_workshop_milestone_one import (
    _draft,
    _proposal_reply,
    harness,
)

from nodelang import agent_composer as composer

CARD_W = 210.0


class _Store:
    revision = 1


def _canvas(h, scope):
    return h.request('/api/universal/canvas?' + urlencode({'scope': scope}))


def _card_h(node):
    rows = [row for row in node.get('params', ()) if row.get('label') not in ('engine', 'status')]
    return max(110.0, 60.0 + 22.0 * len(rows))


def _box(node):
    return (float(node['x']), float(node['y']), CARD_W, _card_h(node))


def _overlaps(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def test_workflow_draft_nodes_and_anchor_land_in_free_canvas_space(harness):
    h = harness
    h.start()
    convo = h.conversation_with_two_agents()
    reply_id = _proposal_reply(h, convo)
    before = _canvas(h, convo['scope'])
    existing = {str(node['id']): node for node in before['nodes']}

    drafted = _draft(h, convo, reply_id, 'draft-placement')

    after = _canvas(h, convo['scope'])
    nodes = {str(node['id']): node for node in after['nodes']}
    drafted_roots = [str(root) for root in drafted['members']] + [str(drafted['workflow'])]
    missing = [root for root in drafted_roots if root not in nodes]
    assert missing == []
    assert all(nodes[root].get('placed') is False for root in drafted_roots)

    clashes = []
    for root in drafted_roots:
        for existing_root, existing_node in existing.items():
            if _overlaps(_box(nodes[root]), _box(existing_node)):
                clashes.append((root, existing_root))
    assert clashes == []

    internal = []
    for index, root in enumerate(drafted_roots):
        for other in drafted_roots[index + 1:]:
            if _overlaps(_box(nodes[root]), _box(nodes[other])):
                internal.append((root, other))
    assert internal == []


def test_draft_position_omitted_coordinates_respect_unplaced_mode():
    assert composer._draft_position({}, unplaced_when_omitted=False) == (400.0, 300.0)
    assert composer._draft_position({}, unplaced_when_omitted=True) == (None, None)
    assert composer._draft_position({"x": 120, "y": 240}, unplaced_when_omitted=False) == (120.0, 240.0)
    assert composer._draft_position({"x": 120, "y": 240}, unplaced_when_omitted=True) == (120.0, 240.0)


def test_work_without_coordinates_preserves_none_for_product_path(monkeypatch):
    captured = {}

    def create_work(store, registry, *, title, description, x, y,
                    structured_references, authentication_context):
        captured["x"] = x
        captured["y"] = y
        return "work-root", "membership-wire", 2

    monkeypatch.setattr(
        "nodelang.universal_application.create_universal_governed_work",
        create_work,
    )

    result = composer._apply_draft_actions(
        _Store(),
        object(),
        {"nodes": (), "catalog": ()},
        {"answer": "draft"},
        [{
            "op": "work",
            "title": "Review",
            "description": "Review the supplied text.",
            "criteria": [{
                "criterion": "Finding is stated.",
                "verification": "Read the finding.",
            }],
        }],
        authentication_context=None,
        unplaced_when_omitted=False,
    )

    assert captured == {"x": None, "y": None}
    assert result["applied"][0]["ok"] is True


def test_place_without_coordinates_keeps_product_default(monkeypatch):
    captured = {}

    def instantiate_definition(store, registry, definition_root, *, x, y,
                               title_override, interface_values,
                               authentication_context):
        captured["definition_root"] = definition_root
        captured["x"] = x
        captured["y"] = y
        return "placed-root", 2

    monkeypatch.setattr(
        "nodelang.universal_application.instantiate_universal_definition",
        instantiate_definition,
    )

    result = composer._apply_draft_actions(
        _Store(),
        object(),
        {"nodes": (), "catalog": ({"name": "Review", "id": "definition-root"},)},
        {"answer": "draft"},
        [{
            "op": "place",
            "definition": "Review",
        }],
        authentication_context=None,
        unplaced_when_omitted=False,
    )

    assert captured == {"definition_root": "definition-root", "x": 400.0, "y": 300.0}
    assert result["applied"][0]["ok"] is True
