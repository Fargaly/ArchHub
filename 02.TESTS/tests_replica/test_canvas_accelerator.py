"""The canvas accelerator is disposable, revision-bound and never changes meaning.

SPEC 3.1.6-7: a cache may exist only as revision-bound acceleration, and
deleting it must not change the answer. These courts compare the remembered
answer byte for byte with the generic interpreter, prove a commit and a
revocation are never answered from memory, prove the answer is never served
past an expiry its build compared against, and prove a deleted accelerator
rebuilds the same bytes.
"""
from __future__ import annotations

import json

import pytest

import nodelang.universal_application as ua
from nodelang.cell_authorization import AuthorizationDenied
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    build_universal_application,
    clear_canvas_accelerator,
    project_universal_canvas,
    provision_universal_view_session,
    revoke_universal_authority_relationship,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell


def _counting(monkeypatch):
    calls = []
    real = ua._project_universal_canvas_interpreter

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(ua, "_project_universal_canvas_interpreter", counted)
    return calls


def _generic(store, registry, monkeypatch, **kwargs):
    with monkeypatch.context() as scoped:
        scoped.setenv("ARCHHUB_CANVAS_ACCELERATOR", "0")
        return json.dumps(project_universal_canvas(store, registry, **kwargs))


def test_remembered_canvas_is_byte_equal_to_the_generic_build(monkeypatch):
    store, registry = build_universal_application(resolve_map_path())
    clear_canvas_accelerator(store)
    calls = _counting(monkeypatch)
    generic = _generic(store, registry, monkeypatch)
    built = json.dumps(project_universal_canvas(store, registry))
    remembered = json.dumps(project_universal_canvas(store, registry))
    assert len(calls) == 2  # generic + first accelerated build; third remembered
    assert built == generic
    assert remembered == generic
    # The caller owns what it receives: mutating it never reaches the memory.
    handed = project_universal_canvas(store, registry)
    handed["revision"] = -1
    handed.setdefault("interaction_projection", {})["poisoned"] = True
    assert json.dumps(project_universal_canvas(store, registry)) == generic
    # Deleting the accelerator rebuilds exactly the same bytes.
    clear_canvas_accelerator(store)
    assert json.dumps(project_universal_canvas(store, registry)) == generic
    assert len(calls) == 3


def test_any_commit_is_never_answered_from_memory(monkeypatch):
    store, registry = build_universal_application(resolve_map_path())
    clear_canvas_accelerator(store)
    calls = _counting(monkeypatch)
    project_universal_canvas(store, registry)
    project_universal_canvas(store, registry)
    assert len(calls) == 1
    store.commit(store.revision, create=(
        Cell("test:accelerator:unrelated", NULL_CELL_ID, NULL_CELL_ID, b"moved"),
    ))
    after = json.dumps(project_universal_canvas(store, registry))
    assert len(calls) == 2
    assert after == _generic(store, registry, monkeypatch)


def test_revoked_grant_is_refused_even_after_a_remembered_answer(monkeypatch):
    store, registry = build_universal_application(resolve_map_path())
    clear_canvas_accelerator(store)
    authority = registry.authorization
    member_root = "test:identity:accelerated-member"
    store.commit(store.revision, create=(
        Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Accelerated member"),
    ))
    view, _ = provision_universal_view_session(store, registry, member_root)
    member = authority.broker.mint_authenticated_context(
        member_root,
        tenant_root=authority.tenant_root,
        assurance_root=authority.assurance_root,
        lifetime_seconds=120,
    )
    first = project_universal_canvas(store, registry, authentication_context=member)
    again = project_universal_canvas(store, registry, authentication_context=member)
    assert json.dumps(first) == json.dumps(again)
    revoke_universal_authority_relationship(
        store, registry, view.principal_membership_root,
        reason="application access removed",
    )
    with pytest.raises(AuthorizationDenied, match="default-deny"):
        project_universal_canvas(store, registry, authentication_context=member)
    # The founder's own answer moved with the revocation too.
    founder = project_universal_canvas(store, registry)
    assert json.dumps(founder) == _generic(store, registry, monkeypatch)
    revoked = next(
        item for item in founder["authorization"]["relationships"]
        if item["root"] == view.principal_membership_root
    )
    assert revoked["state"] == "revoked"


def test_answer_is_never_served_past_an_expiry_its_build_compared(monkeypatch):
    store, registry = build_universal_application(resolve_map_path())
    clear_canvas_accelerator(store)
    authority = registry.authorization
    member_root = "test:identity:expiring-member"
    store.commit(store.revision, create=(
        Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Expiring member"),
    ))
    provision_universal_view_session(store, registry, member_root)
    member = authority.broker.mint_authenticated_context(
        member_root,
        tenant_root=authority.tenant_root,
        assurance_root=authority.assurance_root,
        lifetime_seconds=60,
    )
    expires_at = authority.broker.resolve(member).expires_at
    project_universal_canvas(store, registry, authentication_context=member)
    held = [
        value for (_registry, key), value in ua._CANVAS_ACCELERATOR[store].items()
        if key[2] == member_root
    ]
    assert len(held) == 1
    _cells, filled_at, valid_until, _encoded = held[0][:4]
    assert filled_at < valid_until <= expires_at

    class Later:
        @staticmethod
        def time():
            return valid_until + 1

        def __getattr__(self, name):
            import time as real
            return getattr(real, name)

    calls = _counting(monkeypatch)
    monkeypatch.setattr(ua, "time", Later())
    # The generic path would refuse the expired context; so does this one,
    # and it does not answer from memory on the way.
    with pytest.raises(AuthorizationDenied, match="expired"):
        project_universal_canvas(store, registry, authentication_context=member)
    assert calls == []


def test_each_identity_gets_its_own_answer_never_another_viewers(monkeypatch):
    store, registry = build_universal_application(resolve_map_path())
    clear_canvas_accelerator(store)
    authority = registry.authorization
    contexts = {}
    for name in ("alpha", "beta"):
        member_root = "test:identity:accelerated-%s" % name
        store.commit(store.revision, create=(
            Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, name.encode()),
        ))
        provision_universal_view_session(store, registry, member_root)
        contexts[name] = authority.broker.mint_authenticated_context(
            member_root,
            tenant_root=authority.tenant_root,
            assurance_root=authority.assurance_root,
            lifetime_seconds=120,
        )
    contexts["founder"] = None
    calls = _counting(monkeypatch)
    answers = {}
    for name in ("alpha", "beta", "founder", "alpha", "beta", "founder"):
        answer = json.dumps(project_universal_canvas(
            store, registry, authentication_context=contexts[name]
        ))
        assert answer == _generic(
            store, registry, monkeypatch, authentication_context=contexts[name]
        ), "%s received an answer built for someone else" % name
        answers.setdefault(name, answer)
        assert answers[name] == answer
    # One build per identity, then remembered; never shared across viewers.
    assert len(calls) == 3 + 6  # 3 accelerated builds + 6 generic comparisons
    assert len(set(answers.values())) == 3


def _counting_delta(monkeypatch):
    taken = []
    real = ua._canvas_position_delta

    def counted(*args, **kwargs):
        out = real(*args, **kwargs)
        taken.append(out is not None)
        return out

    monkeypatch.setattr(ua, "_canvas_position_delta", counted)
    return taken


def test_node_moves_answer_by_exact_delta_byte_equal_to_the_build(monkeypatch):
    import random

    store, registry = build_universal_application(resolve_map_path())
    clear_canvas_accelerator(store)
    taken = _counting_delta(monkeypatch)
    builds = _counting(monkeypatch)
    answer = project_universal_canvas(store, registry)
    selected = answer.get("selected")
    roots = [node["id"] for node in answer["nodes"]][:5]
    assert selected in roots and len(roots) > 2

    def move(root, x, y):
        nonlocal answer
        ua.apply_universal_canvas_gesture(
            store, registry, positions={root: {"x": x, "y": y}},
            expected_scope=answer["scope"]["current"],
        )
        before = len(builds)
        answer = project_universal_canvas(store, registry)
        used = bool(taken) and taken[-1] and len(builds) == before
        assert json.dumps(answer) == _generic(store, registry, monkeypatch)
        return used

    # The session's first transaction creates its history relation: rebuild.
    move(selected, 31.0, 32.0)
    rng = random.Random(20260925)
    moved_before = {selected}
    first_moves = repeat_moves = 0
    for _ in range(12):
        root = rng.choice(roots)
        node = next(item for item in answer["nodes"] if item["id"] == root)
        used = move(
            root,
            float(node["x"] + rng.choice((-1, 1)) * rng.randint(5, 60)),
            float(node["y"] + rng.choice((-1, 1)) * rng.randint(5, 60)),
        )
        if root == selected:
            continue  # its Properties panel shows the pin: byte-equal only
        if root in moved_before:
            repeat_moves += 1
            assert used, "a repeat move of an unselected node rebuilt"
        else:
            first_moves += 1
            assert used, "a first move (which creates the placed pin) rebuilt"
        moved_before.add(root)
    assert first_moves and repeat_moves


def test_node_move_mixed_with_other_change_or_revocation_never_takes_the_delta(monkeypatch):
    store, registry = build_universal_application(resolve_map_path())
    clear_canvas_accelerator(store)
    taken = _counting_delta(monkeypatch)
    authority = registry.authorization
    member_root = "test:identity:delta-member"
    store.commit(store.revision, create=(
        Cell(member_root, NULL_CELL_ID, NULL_CELL_ID, b"Delta member"),
    ))
    view, _ = provision_universal_view_session(store, registry, member_root)
    answer = project_universal_canvas(store, registry)
    root = next(
        node["id"] for node in answer["nodes"]
        if node["id"] != answer.get("selected")
    )
    # Place it once so the next move is an ordinary repeat move.
    ua.apply_universal_canvas_gesture(
        store, registry, positions={root: {"x": 11.0, "y": 12.0}},
        expected_scope=answer["scope"]["current"],
    )
    answer = project_universal_canvas(store, registry)
    # Move + viewport in one commit rebuilds.
    taken.clear()
    ua.apply_universal_canvas_gesture(
        store, registry, positions={root: {"x": 21.0, "y": 22.0}},
        viewport={"pan_x": 5.0, "pan_y": 6.0, "zoom": 1.0},
        expected_scope=answer["scope"]["current"],
    )
    answer = project_universal_canvas(store, registry)
    assert not any(taken)
    assert json.dumps(answer) == _generic(store, registry, monkeypatch)
    # A grant revocation rebuilds, and the member is refused.
    member = authority.broker.mint_authenticated_context(
        member_root,
        tenant_root=authority.tenant_root,
        assurance_root=authority.assurance_root,
        lifetime_seconds=120,
    )
    project_universal_canvas(store, registry, authentication_context=member)
    taken.clear()
    revoke_universal_authority_relationship(
        store, registry, view.principal_membership_root,
        reason="delta court revoke",
    )
    founder = project_universal_canvas(store, registry)
    assert not any(taken)
    assert json.dumps(founder) == _generic(store, registry, monkeypatch)
    with pytest.raises(AuthorizationDenied, match="default-deny"):
        project_universal_canvas(store, registry, authentication_context=member)
    assert not any(taken)


def test_a_canvas_with_an_unplaced_card_never_takes_the_move_delta(monkeypatch):
    store, registry = build_universal_application(resolve_map_path())
    clear_canvas_accelerator(store)
    taken = _counting_delta(monkeypatch)
    answer = project_universal_canvas(store, registry)
    root = next(
        node["id"] for node in answer["nodes"]
        if node["id"] != answer.get("selected")
    )
    for x in (11.0, 21.0):  # history exists and the card is placed
        ua.apply_universal_canvas_gesture(
            store, registry, positions={root: {"x": x, "y": 12.0}},
            expected_scope=answer["scope"]["current"],
        )
        answer = project_universal_canvas(store, registry)
    assert taken and taken[-1], "precondition: a repeat move takes the delta"
    # Stand in for a canvas holding a card with no stored position: such a
    # card is drawn from the placed cards' edges, which a move can shift.
    with ua._CANVAS_ACCELERATOR_LOCK:
        entries = ua._CANVAS_ACCELERATOR[store]
        memory_key, entry = next(
            (item, value) for item, value in entries.items()
            if value[0] is store.snapshot().cells
        )
        held = json.loads(entry[3])
        other = next(node for node in held["nodes"] if node["id"] != root)
        other["placed"] = False
        entries[memory_key] = (*entry[:3], json.dumps(held), *entry[4:])
    taken.clear()
    ua.apply_universal_canvas_gesture(
        store, registry, positions={root: {"x": 31.0, "y": 12.0}},
        expected_scope=answer["scope"]["current"],
    )
    answer = project_universal_canvas(store, registry)
    assert taken == [False]
    assert json.dumps(answer) == _generic(store, registry, monkeypatch)


def test_a_cell_named_like_the_new_transaction_but_not_part_of_it_rebuilds(monkeypatch):
    store, registry = build_universal_application(resolve_map_path())
    clear_canvas_accelerator(store)
    taken = _counting_delta(monkeypatch)
    answer = project_universal_canvas(store, registry)
    root = next(
        node["id"] for node in answer["nodes"]
        if node["id"] != answer.get("selected")
    )
    for x in (11.0, 21.0):
        ua.apply_universal_canvas_gesture(
            store, registry, positions={root: {"x": x, "y": 12.0}},
            expected_scope=answer["scope"]["current"],
        )
        answer = project_universal_canvas(store, registry)
    assert taken and taken[-1], "precondition: a repeat move takes the delta"
    ua.apply_universal_canvas_gesture(
        store, registry, positions={root: {"x": 31.0, "y": 12.0}},
        expected_scope=answer["scope"]["current"],
    )
    transaction = next(
        cell_id for cell_id in store.revision_changes(store.revision)
        if cell_id.startswith("change:") and cell_id.count(":") == 1
    )
    store.commit(store.revision, create=(
        Cell(transaction + ":forged", NULL_CELL_ID, NULL_CELL_ID, b"forged"),
    ))
    taken.clear()
    answer = project_universal_canvas(store, registry)
    assert taken == [False]
    assert json.dumps(answer) == _generic(store, registry, monkeypatch)
