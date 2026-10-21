"""Collapsing a canvas frame: the group node is named after the frame and counts its members.

The Studio's frame collapse runs the graph's own Group control, which admits no
title argument. A group whose selected cards all sit in one frame takes that
frame's name instead of the generic "Composition"; a mixed selection keeps the
default. The projection states how many nodes the group holds.
"""
from pathlib import Path

import pytest

from nodelang import universal_application as app
from nodelang.universal_pipeline import create_engine_node


@pytest.fixture
def application():
    public_map = Path(app.__file__).parent / "data" / "public_runtime_map.json"
    return app.build_universal_application(public_map)


def _node(projection, root):
    return next(node for node in projection["nodes"] if node["id"] == root)


def test_a_group_of_one_frame_takes_the_frame_name_and_counts_its_members(application):
    store, registry = application
    first = create_engine_node(store, registry, title="Frame member A", engine="library.think")["root"]
    second = create_engine_node(store, registry, title="Frame member B", engine="library.think")["root"]
    third = create_engine_node(store, registry, title="Frame member C", engine="library.think")["root"]
    app.set_universal_selection(store, registry, [first, second, third])
    projection = app.project_universal_canvas(store, registry)
    frames = {_node(projection, root)["group"] for root in (first, second, third)}
    assert len(frames) == 1, frames
    frame = next(iter(frames))
    assert frame not in {"Cells", "Groups", "Composition"}, frame
    group, _ = app.group_universal_selection(store, registry, projected_canvas=projection)
    after = _node(app.project_universal_canvas(store, registry), group)
    assert after["composition"] is True
    assert after["label"] == frame, "the group is named after the frame it collapsed"
    assert after["member_count"] == 3


def test_a_selection_across_frames_keeps_the_default_name(application):
    store, registry = application
    first = create_engine_node(store, registry, title="Inner A", engine="library.think")["root"]
    second = create_engine_node(store, registry, title="Inner B", engine="library.think")["root"]
    loose = create_engine_node(store, registry, title="Loose", engine="library.think")["root"]
    app.set_universal_selection(store, registry, [first, second])
    inner, _ = app.group_universal_selection(store, registry, projected_canvas=app.project_universal_canvas(store, registry))
    app.set_universal_selection(store, registry, [inner, loose])
    projection = app.project_universal_canvas(store, registry)
    assert _node(projection, inner)["group"] != _node(projection, loose)["group"]
    outer, _ = app.group_universal_selection(store, registry, projected_canvas=projection)
    after = _node(app.project_universal_canvas(store, registry), outer)
    assert after["label"] == "Composition", "cards from two frames keep the default name"
    assert after["member_count"] == 2
