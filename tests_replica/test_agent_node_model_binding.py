"""Node model routing uses the viewer's actual graph; providers stay stubbed."""
import json
from pathlib import Path

import pytest

from nodelang import agent_composer as composer
from nodelang import universal_application as app
from nodelang.cell_protocols import read_relation, remove_relation_member
from nodelang.universal_cell import Cell, InvalidCell, NULL_CELL_ID
from nodelang.universal_pipeline import create_engine_node


@pytest.fixture
def application():
    public_map = Path(app.__file__).parent / "data" / "public_runtime_map.json"
    return app.build_universal_application(public_map)


def test_entered_group_keeps_visible_node_model_routing(application, monkeypatch):
    store, registry = application
    chosen = "openrouter/free"
    first = create_engine_node(store, registry, title="Grouped Think", engine="library.think",
        properties={"model": chosen})["root"]
    second = create_engine_node(store, registry, title="Grouped Vision", engine="library.vision",
        properties={"model": "ollama/vision-court"})["root"]
    app.set_universal_selection(store, registry, [first, second])
    projection = app.project_universal_canvas(store, registry)
    group, _ = app.group_universal_selection(store, registry, projected_canvas=projection)
    with pytest.raises(InvalidCell, match="visible"):
        composer.run_agent_composer(store, registry, "Ask", node_root=first)
    app.set_universal_scope(store, registry, group)
    app.select_universal_root(store, registry, first)
    projection = app.project_universal_canvas(store, registry)
    assert first in {row["id"] for row in projection["nodes"]}
    assert next(row["value"] for row in projection["properties"]
        if row["owner"] == first and row["label"] == "model") == chosen
    calls = []
    monkeypatch.setattr(composer, "_chat", lambda prompt, context, model:
        calls.append(model) or json.dumps({"actions": [], "answer": "Route checked."}))
    composer.run_agent_composer(store, registry, "Ask", node_root=first)
    composer.run_agent_composer(store, registry, "Ask", node_root=second)
    assert calls == [chosen, "ollama/vision-court"]
    model = next(row for row in projection["properties"]
        if row["owner"] == first and row["label"] == "model")

    # Withhold the model from this actual view's admitted Properties lens.
    # The value still exists in the store, so a global-property fallback leaks it.
    view, _ = app._view_session_for_context(registry, None)
    incidence = next(member for member in read_relation(
        store.snapshot(), view.properties_lens_root, budget=100_000)
        if member.role_id == registry.roles["scope"] and member.participant_id == model["relation"])
    remove_relation_member(store, view.properties_lens_root, incidence.incidence_id, budget=100_000)
    assert store.snapshot().cells[model["value_root"]].atom == chosen.encode()
    withheld = app.project_universal_canvas(store, registry)
    assert not any(row["label"] == "model" and row["owner"] == first
        for row in withheld["properties"])
    with pytest.raises(InvalidCell, match="graph model parameter"):
        composer.run_agent_composer(store, registry, "Ask", node_root=first, model=chosen)
    assert len(calls) == 2

    # A signed composition read grant remains necessary, even for a node whose
    # model is still admitted to the lens and routed successfully above.
    authority = registry.authorization
    grant = next(row for row in withheld["authorization"]["relationships"]
        if row["kind"] == "delegation" and row["scope"] == group
        and row["source"] == authority.resource_reader_principal_root
        and row["target"] == view.subject_root and row["state"] == "active")
    app.revoke_universal_authority_relationship(store, registry, grant["root"], reason="Court revokes group access")
    with pytest.raises(InvalidCell, match="signed composition grants"):
        composer.run_agent_composer(store, registry, "Ask", node_root=second)
    assert len(calls) == 2


def test_entered_group_model_edit_rejects_hidden_owner(application):
    store, registry = application
    first = create_engine_node(store, registry, title="Editable grouped Think", engine="library.think",
        properties={"model": "openrouter/free"})["root"]
    second = create_engine_node(store, registry, title="Grouped companion", engine="library.think")["root"]
    outside = create_engine_node(store, registry, title="Outside group Think", engine="library.think",
        properties={"model": "ollama/outside-court"})["root"]
    app.select_universal_root(store, registry, outside)
    top = app.project_universal_canvas(store, registry)
    outside_model = next(row for row in top["properties"]
        if row["owner"] == outside and row["label"] == "model")
    app.set_universal_selection(store, registry, [first, second])
    top = app.project_universal_canvas(store, registry)
    group, _ = app.group_universal_selection(store, registry, projected_canvas=top)
    app.set_universal_scope(store, registry, group)
    app.select_universal_root(store, registry, first)
    projection = app.project_universal_canvas(store, registry)
    model = next(row for row in projection["properties"]
        if row["owner"] == first and row["label"] == "model")
    app.edit_universal_property(store, registry, model["relation"], "ollama/group-edit-court")
    assert store.snapshot().cells[model["value_root"]].atom == b"ollama/group-edit-court"
    assert composer.resolve_node_model_route(store, registry,
        app.project_universal_canvas(store, registry), first) == "ollama/group-edit-court"

    assert outside not in {row["id"] for row in projection["nodes"]}
    with pytest.raises(InvalidCell, match="outside the application lens"):
        app.edit_universal_property(store, registry, outside_model["relation"], "openrouter/free")
    assert store.snapshot().cells[outside_model["value_root"]].atom == b"ollama/outside-court"

    app.set_universal_selection(store, registry, [first, second])
    selected = app.project_universal_canvas(store, registry)
    batch = next(row for row in selected["properties"] if row["label"] == "model")
    assert batch["batch"] and set(batch["owners"]) == {first, second}
    app.edit_universal_property_batch(store, registry, batch["relations"], "ollama/group-batch-court")
    assert all(store.snapshot().cells[root].atom == b"ollama/group-batch-court"
        for root in batch["value_roots"])
    with pytest.raises(InvalidCell, match="outside the application lens"):
        app.edit_universal_property_batch(store, registry,
            [model["relation"], outside_model["relation"]], "openrouter/free")
    assert all(store.snapshot().cells[root].atom == b"ollama/group-batch-court"
        for root in batch["value_roots"])
    assert store.snapshot().cells[outside_model["value_root"]].atom == b"ollama/outside-court"

    view, _ = app._view_session_for_context(registry, None)
    incidence = next(member for member in read_relation(
        store.snapshot(), view.properties_lens_root, budget=100_000)
        if member.role_id == registry.roles["scope"] and member.participant_id == model["relation"])
    remove_relation_member(store, view.properties_lens_root, incidence.incidence_id, budget=100_000)
    with pytest.raises(InvalidCell, match="outside the application lens"):
        app.edit_universal_property(store, registry, model["relation"], "openrouter/free")
    with pytest.raises(InvalidCell, match="outside the application lens"):
        app.edit_universal_property_batch(store, registry, batch["relations"], "openrouter/free")
    assert all(store.snapshot().cells[root].atom == b"ollama/group-batch-court"
        for root in batch["value_roots"])


def test_real_node_model_persists_and_invisible_wrong_missing_models_refuse(application, monkeypatch):
    store, registry = application
    chosen = "openrouter/free"
    first = create_engine_node(store, registry, title="First agent", engine="library.think",
        properties={"prompt": "", "extra1": "1", "extra2": "2", "model": chosen})["root"]
    second = create_engine_node(store, registry, title="Vision agent", engine="library.vision",
        properties={"model": "ollama/vision-court"})["root"]
    wrong = create_engine_node(store, registry, title="Agent is only a title", engine="library.filter_field",
        properties={"model": chosen})["root"]
    projection = app.project_universal_canvas(store, registry)
    first_node = next(node for node in projection["nodes"] if node["id"] == first)
    assert not any(row["label"] == "model" for row in first_node["params"])
    calls = []
    monkeypatch.setattr(composer, "_DEFAULT_MODEL", "must-not-use/global-default")
    monkeypatch.setattr(composer, "_chat", lambda prompt, context, model:
        calls.append(model) or json.dumps({"actions": [], "answer": "Route checked."}))
    composer.run_agent_composer(store, registry, "Review", node_root=first)
    composer.run_agent_composer(store, registry, "Review", node_root=second)
    assert calls == [chosen, "ollama/vision-court"]
    for root, supplied in ((first, "openai/other"), (wrong, chosen), (None, chosen), ("", chosen)):
        with pytest.raises(InvalidCell):
            composer.run_agent_composer(store, registry, "Review", node_root=root, model=supplied)
    assert len(calls) == 2
    app.select_universal_root(store, registry, first)
    projection = app.project_universal_canvas(store, registry)
    model_relation = next(row["relation"] for row in projection["properties"] if row["label"] == "model")
    value_root = app.edit_universal_property(store, registry, model_relation, "ollama/changed-court")
    assert store.snapshot().cells[value_root].atom == b"ollama/changed-court"
    composer.run_agent_composer(store, registry, "Review", node_root=first)
    assert calls[-1] == "ollama/changed-court"
    app.edit_universal_property(store, registry, model_relation, "")
    with pytest.raises(InvalidCell, match="model"):
        composer.run_agent_composer(store, registry, "Review", node_root=first, model=chosen)
    member = "test:node-model:member"
    store.commit(store.revision, create=(Cell(member, NULL_CELL_ID, NULL_CELL_ID, b"Member"),))
    app.provision_universal_view_session(store, registry, member)
    authority = registry.authorization
    context = authority.broker.mint_authenticated_context(member,
        principal_roots=(authority.member_principal_root,), tenant_root=authority.tenant_root,
        assurance_root=authority.assurance_root, lifetime_seconds=120)
    assert first not in {node["id"] for node in app.project_universal_canvas(
        store, registry, authentication_context=context)["nodes"]}
    with pytest.raises(InvalidCell, match="visible"):
        composer.run_agent_composer(store, registry, "Review", node_root=first,
            model=chosen, authentication_context=context)
    assert len(calls) == 3


def test_library_placement_declares_editable_model_without_ui_defaults(application):
    store, registry = application
    node = create_engine_node(store, registry, title="New agent", engine="library.think")["root"]
    app.select_universal_root(store, registry, node)
    projection = app.project_universal_canvas(store, registry)
    models = [row for row in projection["properties"] if row["label"] == "model"]
    assert len(models) == 1 and models[0]["editable"]
    assert models[0]["value"] == ""
    with pytest.raises(InvalidCell, match="No model chosen"):
        composer.run_agent_composer(store, registry, "Ask", node_root=node)
    app.edit_universal_property(store, registry, models[0]["relation"], "provider-selected")
    with pytest.raises(InvalidCell, match="No model chosen"):
        composer.run_agent_composer(store, registry, "Ask", node_root=node)


def test_provider_failure_does_not_expose_provider_details(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("private-provider-diagnostic")
    monkeypatch.setattr(composer, "route_chat", fail)
    with pytest.raises(InvalidCell, match="The model provider did not answer") as error:
        composer._chat("Hello", "Public context", "openrouter/free")
    assert "private-provider-diagnostic" not in str(error.value)
