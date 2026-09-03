"""Courts for visible, restartable reaction-to-attention wiring."""
from pathlib import Path

import pytest

from nodelang.cell_attention import (
    bootstrap_attention_protocol,
    open_attention_protocol,
    read_signal,
)
from nodelang.cell_attention_reactions import (
    build_reaction_subscription,
    drain_reaction_subscriptions,
    read_reaction_subscription,
    set_reaction_subscription_active,
)
from nodelang.cell_authorization import AuthorizationDecision
from nodelang.cell_catalog import (
    bootstrap_assembly_protocol,
    instantiate_catalog_definition,
)
from nodelang.cell_reactions import (
    ReactionEngine,
    reaction_events,
    register_reaction_instance,
    wire_instance_source,
)
from nodelang.cell_standard_library import build_standard_library_v0
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore


CONFIG_ROOTS = (
    "observer",
    "trust",
    "sensitivity",
    "audience",
    "lifecycle",
    "action-observe",
    "authorization-policy",
    "authorization-rule",
)


def _replace_atom(store, root, atom):
    cell = store.read(root)
    store.commit(
        store.revision,
        replace=(Cell(cell.id, cell.link0, cell.link1, atom),),
    )


def _system(database=None):
    store = CellStore(database)
    assembly = bootstrap_assembly_protocol(store)
    library = build_standard_library_v0(store, assembly)
    attention = bootstrap_attention_protocol(store)
    store.commit(
        store.revision,
        create=(
            Cell("source:leaf", NULL_CELL_ID, NULL_CELL_ID, b"one"),
            Cell("source:root", "source:leaf", NULL_CELL_ID, b""),
            *(
                Cell(root, NULL_CELL_ID, NULL_CELL_ID, root.encode("ascii"))
                for root in CONFIG_ROOTS
            ),
        ),
    )
    instance = instantiate_catalog_definition(
        store,
        assembly,
        library.catalog_root,
        library.definition_roots[1],
    )
    wire_instance_source(store, assembly, instance.root_id, "source:root")
    reaction_root = register_reaction_instance(
        store, assembly, library.reaction_protocol, instance.root_id
    )[0]
    return store, assembly, library, attention, reaction_root


def _decision(reaction_root, *, allowed=True):
    return AuthorizationDecision(
        allowed=allowed,
        policy_root="authorization-policy",
        subject_root="observer",
        action_root="action-observe",
        object_root=reaction_root,
        determining_rule_roots=("authorization-rule",),
        reason="permit" if allowed else "default-deny",
    )


def _subscribe(store, library, attention, reaction_root):
    return build_reaction_subscription(
        store,
        attention,
        library.reaction_protocol,
        _decision(reaction_root),
        subscription_id="subscription:source",
        reaction_root=reaction_root,
        observer_root="observer",
        trust_root="trust",
        sensitivity_root="sensitivity",
        audience_root="audience",
        lifecycle_root="lifecycle",
    )


def test_reaction_events_enter_attention_only_through_visible_subscription():
    store, assembly, library, attention, reaction_root = _system()
    subscription = _subscribe(store, library, attention, reaction_root)
    assert subscription.cursor == 0
    members = read_reaction_subscription(
        store.snapshot(), attention, subscription.root_id
    )
    assert members.reaction_root == reaction_root
    assert members.authority_root == "authorization-policy"
    assert members.rule_roots == ("authorization-rule",)

    engine = ReactionEngine(store, assembly, library.reaction_protocol)
    assert engine.drain() == 1
    assert drain_reaction_subscriptions(
        store, attention, library.reaction_protocol
    ) == ()

    _replace_atom(store, "source:leaf", b"two")
    source_revision = store.revision
    assert engine.drain() == 1
    events = reaction_events(
        store.snapshot(), library.reaction_protocol, reaction_root
    )
    assert len(events) == 1
    emitted = drain_reaction_subscriptions(
        store, attention, library.reaction_protocol
    )
    assert len(emitted) == 1
    signal = read_signal(store.snapshot(), attention, emitted[0])
    assert signal.source_root == "source:root"
    assert signal.source_revision == source_revision
    assert signal.provenance_root == events[0].root_id
    assert signal.subscription_root == subscription.root_id
    assert signal.trust_root == "trust"
    assert read_reaction_subscription(
        store.snapshot(), attention, subscription.root_id
    ).cursor == 1
    assert drain_reaction_subscriptions(
        store, attention, library.reaction_protocol
    ) == ()


def test_subscription_authorization_and_blocking_fail_closed():
    store, assembly, library, attention, reaction_root = _system()
    with pytest.raises(PermissionError, match="denied"):
        build_reaction_subscription(
            store,
            attention,
            library.reaction_protocol,
            _decision(reaction_root, allowed=False),
            subscription_id="subscription:denied",
            reaction_root=reaction_root,
            observer_root="observer",
            trust_root="trust",
            sensitivity_root="sensitivity",
            audience_root="audience",
            lifecycle_root="lifecycle",
        )
    subscription = _subscribe(store, library, attention, reaction_root)
    engine = ReactionEngine(store, assembly, library.reaction_protocol)
    engine.drain()
    set_reaction_subscription_active(
        store, attention, subscription.root_id, False
    )
    _replace_atom(store, "source:leaf", b"blocked")
    engine.drain()
    assert drain_reaction_subscriptions(
        store, attention, library.reaction_protocol
    ) == ()
    assert read_reaction_subscription(
        store.snapshot(), attention, subscription.root_id
    ).cursor == 0
    set_reaction_subscription_active(
        store, attention, subscription.root_id, True
    )
    assert len(drain_reaction_subscriptions(
        store, attention, library.reaction_protocol
    )) == 1


def test_subscription_cursor_and_idempotency_survive_restart(tmp_path: Path):
    database = tmp_path / "attention-reactions.sqlite3"
    store, assembly, library, attention, reaction_root = _system(database)
    subscription = _subscribe(store, library, attention, reaction_root)
    engine = ReactionEngine(store, assembly, library.reaction_protocol)
    engine.drain()
    _replace_atom(store, "source:leaf", b"before-restart")
    engine.drain()
    first = drain_reaction_subscriptions(
        store, attention, library.reaction_protocol
    )
    assert len(first) == 1
    store.close()

    reopened = CellStore(database)
    reopened_attention = open_attention_protocol(reopened.snapshot())
    assert read_reaction_subscription(
        reopened.snapshot(), reopened_attention, subscription.root_id
    ).cursor == 1
    assert drain_reaction_subscriptions(
        reopened, reopened_attention, library.reaction_protocol
    ) == ()
    _replace_atom(reopened, "source:leaf", b"after-restart")
    ReactionEngine(
        reopened, assembly, library.reaction_protocol
    ).drain()
    second = drain_reaction_subscriptions(
        reopened, reopened_attention, library.reaction_protocol
    )
    assert len(second) == 1
    assert second != first
    assert read_reaction_subscription(
        reopened.snapshot(), reopened_attention, subscription.root_id
    ).cursor == 2
    assert all(type(cell) is Cell for cell in reopened.snapshot().cells.values())
    reopened.close()
