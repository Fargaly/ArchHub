"""Acceptance court: the top canvas is the user's, and deleting from it is safe.

Founder order (2026-09-24): "Why is the application's graph visible to the
user at all, and why is nothing organised or grouped?" His graph drew 204
cards; 190 were the application's own (agent sessions, map domains, core
values, the Work registry, Work value nodes) and 14 were his. Deleting a
map-domain card made the next boot raise "visibility interface leaves its
scope"; a hand move after grouping two instances raised "visibility
interface lacks a visible graph owner".

These courts bind:
  * every top-level card is marked with who placed it, judged by graph
    shape and never by a list of names; the Studio draws the user's cards
    and keeps the application's for the founder's System view;
  * each application card names its System view frame, grouped by domain,
    and only the founder is offered that view;
  * a hand-moved card is pinned and Arrange never moves it, also after the
    user grouped two instances;
  * cards without stored coordinates are drawn in free space, by frame;
  * deleting ANY card the founder can see, then restarting the store,
    boots; a card the user placed always deletes.
"""
from __future__ import annotations

import json
import shutil
from urllib.request import Request, urlopen

import pytest

import nodelang.universal_application as application_module
from nodelang.cell_secret_keys import MemorySigningKeyProvider
from nodelang.map_import import resolve_map_path
from nodelang.universal_application import (
    apply_universal_canvas_gesture,
    build_universal_application,
    create_universal_governed_work,
    group_universal_selection,
    instantiate_universal_definition,
    instantiate_universal_primitive,
    project_universal_canvas,
    promote_universal_resource_lifecycle,
    provision_universal_view_session,
    revoke_universal_authority_relationship,
    restore_universal_application,
    set_universal_scope,
    set_universal_selection,
)
from nodelang.universal_cell import NULL_CELL_ID, Cell, CellStore, InvalidCell


def _provider():
    provider = MemorySigningKeyProvider(
        "archhub.local.relationship-authority", b"w" * 32
    )
    provider.add_key("archhub.local.court-attestation", b"c" * 32)
    return provider


def _ids(projection):
    return [node["id"] for node in projection["nodes"]]


def _marks(projection):
    return {node["id"]: node.get("application") for node in projection["nodes"]}


def _user_content(store, registry):
    """What a user places by hand: three instances, a Cell, and a group."""
    definitions = registry.standard_library.definition_roots
    first, _ = instantiate_universal_definition(
        store, registry, definitions[0], x=420.0, y=120.0
    )
    second, _ = instantiate_universal_definition(
        store, registry, definitions[0], x=700.0, y=120.0
    )
    third, _ = instantiate_universal_definition(
        store, registry, definitions[0], x=980.0, y=120.0
    )
    cell, _ = instantiate_universal_primitive(
        store, registry, x=420.0, y=420.0, title="Note"
    )
    set_universal_selection(store, registry, (second, third), focus_root=third)
    group, _ = group_universal_selection(store, registry, title="My group")
    return {"instance": first, "cell": cell, "group": group}


def _application_internals(registry):
    return set(registry.map.domains.values()) | {
        registry.governed_work_registry_root,
    }


def test_every_top_level_card_says_who_placed_it(tmp_path):
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(tmp_path / "g.sqlite3"),
        key_provider=_provider(),
    )
    try:
        fresh = _marks(project_universal_canvas(store, registry))
        assert _application_internals(registry) <= set(fresh)
        assert set(fresh.values()) == {True}, (
            "a fresh application has placed nothing of the user's: %s"
            % sorted(root for root, mark in fresh.items() if mark is not True)
        )
        user = _user_content(store, registry)
        marks = _marks(project_universal_canvas(store, registry))
        assert {root for root, mark in marks.items() if mark is False} == set(
            user.values()
        )
        assert {root for root, mark in marks.items() if mark is True} == (
            set(fresh)
        )
    finally:
        store.close()
    # Derived from the graph, so it holds after a restart.
    store, registry = restore_universal_application(
        resolve_map_path(), CellStore(tmp_path / "g.sqlite3"),
        key_provider=_provider(),
    )
    try:
        assert _marks(project_universal_canvas(store, registry)) == marks
    finally:
        store.close()


def test_the_system_view_frames_are_domains_and_only_the_founder_has_it():
    store, registry = build_universal_application(
        resolve_map_path(), key_provider=_provider()
    )
    user = _user_content(store, registry)
    founder = project_universal_canvas(store, registry)
    assert founder["authorization"]["system_view"] is True
    nodes = {node["id"]: node for node in founder["nodes"]}
    titles = {
        key: application_module._scope_label(
            store.snapshot(), registry, root
        )
        for key, root in registry.map.domains.items()
    }
    for key, root in registry.map.domains.items():
        assert nodes[root]["group"] == titles[key], key
    other = {
        node["group"] for node in founder["nodes"]
        if node["application"] and node["id"] not in
        set(registry.map.domains.values())
    }
    assert other and all(isinstance(group, str) and group for group in other)
    for root in user.values():
        assert nodes[root]["application"] is False
        assert nodes[root]["group"] in ("Groups", "Cells") or nodes[root][
            "group"
        ] not in titles.values()
    # A member's view holds none of the application's cards and is not
    # offered the System view.
    member = "test:system-view:member"
    shared, _ = instantiate_universal_definition(
        store, registry, registry.standard_library.definition_roots[2],
        x=420.0, y=640.0,
    )
    promote_universal_resource_lifecycle(store, registry, shared, "shared")
    store.commit(store.revision, create=(
        Cell(member, NULL_CELL_ID, NULL_CELL_ID, b"Member"),
    ))
    provision_universal_view_session(
        store, registry, member, visible_roots=(shared,)
    )
    authority = registry.authorization
    context = authority.broker.mint_authenticated_context(
        member,
        principal_roots=(authority.member_principal_root,),
        tenant_root=authority.tenant_root,
        assurance_root=authority.assurance_root,
        lifetime_seconds=120,
    )
    member_canvas = project_universal_canvas(
        store, registry, authentication_context=context
    )
    assert member_canvas["authorization"]["system_view"] is False
    assert [node["id"] for node in member_canvas["nodes"]] == [shared]
    assert not any(node.get("application") for node in member_canvas["nodes"])


def test_the_canvas_route_carries_the_marks_and_the_founder_switch():
    from nodelang.application_server import ApplicationServer

    store, registry = build_universal_application(
        resolve_map_path(), key_provider=_provider()
    )
    user = _user_content(store, registry)
    server = ApplicationServer(
        universal_store=store, universal_registry=registry
    ).start()
    try:
        session, _csrf = server.issue_browser_session(
            registry.authorization.session.context()
        )
        request = Request(server.url + "/api/universal/canvas",
                          headers={"X-ArchHub-Session": session})
        with urlopen(request, timeout=120) as response:
            canvas = json.loads(response.read())
        assert canvas["authorization"]["system_view"] is True
        marks = {node["id"]: node["application"] for node in canvas["nodes"]}
        assert {root for root, mark in marks.items() if not mark} == set(
            user.values()
        )
        assert _application_internals(registry) <= {
            root for root, mark in marks.items() if mark
        }
    finally:
        server.close()


def test_a_hand_moved_card_is_pinned_and_arrange_never_moves_it():
    store, registry = build_universal_application(
        resolve_map_path(), key_provider=_provider()
    )
    user = _user_content(store, registry)
    moved, other = user["instance"], user["cell"]
    # A hand move after grouping two instances used to refuse the graph.
    apply_universal_canvas_gesture(
        store, registry, positions={moved: {"x": 1200.0, "y": 600.0}}
    )
    nodes = {node["id"]: node for node in
             project_universal_canvas(store, registry)["nodes"]}
    assert nodes[moved]["pinned"] is True
    assert (nodes[moved]["x"], nodes[moved]["y"]) == (1200.0, 600.0)
    assert nodes[other]["pinned"] is False
    before = store.revision
    with pytest.raises(InvalidCell, match="placed by hand"):
        apply_universal_canvas_gesture(
            store, registry, positions={moved: {"x": 0.0, "y": 0.0}},
            placement="arrange",
        )
    assert store.revision == before
    apply_universal_canvas_gesture(
        store, registry, positions={other: {"x": 60.0, "y": 900.0}},
        placement="arrange",
    )
    nodes = {node["id"]: node for node in
             project_universal_canvas(store, registry)["nodes"]}
    assert (nodes[other]["x"], nodes[other]["y"]) == (60.0, 900.0)
    assert nodes[other]["pinned"] is False, "Arrange pinned a card"
    assert (nodes[moved]["x"], nodes[moved]["y"]) == (1200.0, 600.0)
    # Every drawn card names the frame it is drawn in.
    assert all(isinstance(node.get("group"), str) and node["group"]
               for node in nodes.values())


def test_cards_without_coordinates_are_drawn_in_free_space():
    place = getattr(application_module, "_place_unplaced_canvas_nodes", None)
    assert place is not None, "unplaced cards are drawn on a blind grid"
    placed = {"id": "placed", "x": 60.0, "y": 92.0, "placed": True}
    loose = [
        {"id": "loose-%d" % index, "x": 60.0 + 244.0 * (index % 5),
         "y": 92.0 + 174.0 * (index // 5), "placed": False,
         "application": index % 2 == 0,
         "group": "Models & Agents" if index % 2 == 0 else "Ordered List"}
        for index in range(9)
    ] + [{"id": "cell", "x": 60.0, "y": 92.0, "placed": False,
          "application": False, "group": "Cells"}]
    nodes = [placed, *loose]
    place(nodes)
    width, height = 240.0, 170.0
    for index, first in enumerate(nodes):
        for second in nodes[index + 1:]:
            assert (abs(first["x"] - second["x"]) >= width
                    or abs(first["y"] - second["y"]) >= height), (
                first["id"], second["id"])


def test_deleting_any_card_the_founder_can_see_keeps_the_next_boot(tmp_path):
    from nodelang.universal_pipeline import retract_universal_node

    base = tmp_path / "base.sqlite3"
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(base), key_provider=_provider()
    )
    try:
        user = set(_user_content(store, registry).values())
        visible = _ids(project_universal_canvas(store, registry))
    finally:
        store.close()
    assert user <= set(visible)
    broke, refused = [], []
    for index, root in enumerate(visible):
        work = tmp_path / ("d%d.sqlite3" % index)
        shutil.copy2(base, work)
        store, registry = restore_universal_application(
            resolve_map_path(), CellStore(work), key_provider=_provider()
        )
        try:
            before = store.revision
            try:
                retract_universal_node(store, registry, root)
            except InvalidCell as refusal:
                # A refusal writes nothing; the card stays and the graph opens.
                assert store.revision == before
                refused.append((root, str(refusal)[:100]))
            else:
                assert root not in _ids(
                    project_universal_canvas(store, registry)
                )
        finally:
            store.close()
        try:
            store, registry = restore_universal_application(
                resolve_map_path(), CellStore(work), key_provider=_provider()
            )
            try:
                project_universal_canvas(store, registry)
            finally:
                store.close()
        except Exception as error:  # the court names every card that broke
            broke.append((root, type(error).__name__, str(error)[:120]))
    assert not broke, "deleting a card broke the next boot: %s" % broke
    assert not [row for row in refused if row[0] in user], (
        "a card the user placed would not delete: %s" % refused
    )
    # What the application placed is refused before anything is written,
    # with a reason the canvas can show; it lives in the System view.
    assert {row[0] for row in refused} == set(visible) - user
    assert all("belongs to the application" in row[1] for row in refused)



# ---------------------------------------------------------------------------
# Verifier findings, 2026-09-24 (one court each).
# ---------------------------------------------------------------------------

def _member(store, registry, name, visible_roots):
    store.commit(store.revision, create=(
        Cell(name, NULL_CELL_ID, NULL_CELL_ID, b"Member"),
    ))
    provision_universal_view_session(
        store, registry, name, visible_roots=visible_roots
    )
    authority = registry.authorization
    return authority.broker.mint_authenticated_context(
        name,
        tenant_root=authority.tenant_root,
        assurance_root=authority.assurance_root,
        lifetime_seconds=300,
    )


def _shared_instance(store, registry):
    shared, _ = instantiate_universal_definition(
        store, registry, registry.standard_library.definition_roots[2],
        x=420.0, y=640.0,
    )
    promote_universal_resource_lifecycle(store, registry, shared, "shared")
    return shared


def test_a_group_never_launders_an_application_card(monkeypatch):
    """Finding 1 (critical): grouping a domain with a user card made the
    group user-placed, and deleting the group removed the domain."""
    from nodelang.universal_pipeline import retract_universal_node

    store, registry = build_universal_application(
        resolve_map_path(), key_provider=_provider()
    )
    user = _user_content(store, registry)
    domain = registry.map.domains["brain"]
    set_universal_selection(
        store, registry, (domain, user["instance"]), focus_root=domain
    )
    before = store.revision
    with pytest.raises(InvalidCell, match="holds only cards you placed"):
        group_universal_selection(store, registry, title="Laundered")
    assert store.revision == before
    # A group that holds an application card, one level or two levels
    # down, is the application's: marked so, and deleting it is refused.
    # outer = group(inner, c), inner = group(a, b); leaf `a` is then read as
    # an application card (an older build let such a group be made).
    definitions = registry.standard_library.definition_roots
    a, b, c = (
        instantiate_universal_definition(
            store, registry, definitions[0], x=400.0 + 300 * i, y=1400.0
        )[0]
        for i in range(3)
    )
    set_universal_selection(store, registry, (a, b), focus_root=b)
    inner, _ = group_universal_selection(store, registry, title="Inner")
    set_universal_selection(store, registry, (inner, c), focus_root=c)
    outer, _ = group_universal_selection(store, registry, title="Outer")
    snapshot = store.snapshot()
    assert application_module._user_canvas_root(snapshot, registry, outer)
    original = application_module._user_canvas_root

    def leaf_a_is_the_applications(snapshot, registry, root_id, *rest, **kw):
        if root_id == a:
            return False
        return original(snapshot, registry, root_id, *rest, **kw)

    with monkeypatch.context() as patch:
        patch.setattr(
            application_module, "_user_canvas_root",
            leaf_a_is_the_applications,
        )
        assert not application_module._user_canvas_root(
            snapshot, registry, outer
        )
        nodes = {node["id"]: node for node in
                 project_universal_canvas(store, registry)["nodes"]}
        assert nodes[outer]["application"] is True
        before = store.revision
        with pytest.raises(InvalidCell, match="belongs to the application"):
            retract_universal_node(store, registry, outer)
        assert store.revision == before
        set_universal_scope(store, registry, outer)
        with pytest.raises(InvalidCell, match="belongs to the application"):
            retract_universal_node(store, registry, inner)
        assert store.revision >= before
    assert {a, b, c, inner, outer} <= set(store.snapshot().cells)
    assert domain in store.snapshot().cells


def test_a_card_the_user_placed_deletes_at_any_depth(tmp_path):
    """Finding 2: a card placed inside a domain or a group answered "that
    node has no visibility to retract"."""
    from nodelang.universal_pipeline import retract_universal_node

    path = tmp_path / "depth.sqlite3"
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    definitions = registry.standard_library.definition_roots
    domain = registry.map.domains["brain"]
    try:
        set_universal_scope(store, registry, domain)
        inside_domain, _ = instantiate_universal_definition(
            store, registry, definitions[0], x=300.0, y=300.0
        )
        assert inside_domain in _ids(project_universal_canvas(store, registry))
        retract_universal_node(store, registry, inside_domain)
        assert inside_domain not in _ids(
            project_universal_canvas(store, registry)
        )
        # Inside a user group of three cards.
        set_universal_scope(store, registry, registry.canvas_root)
        cards = [
            instantiate_universal_definition(
                store, registry, definitions[0], x=400.0 + 280 * i, y=900.0
            )[0]
            for i in range(3)
        ]
        set_universal_selection(
            store, registry, tuple(cards), focus_root=cards[-1]
        )
        group, _ = group_universal_selection(store, registry, title="Mine")
        set_universal_scope(store, registry, group)
        assert set(cards) <= set(_ids(project_universal_canvas(store, registry)))
        retract_universal_node(store, registry, cards[0])
        inside_group = _ids(project_universal_canvas(store, registry))
        assert cards[0] not in inside_group
        assert set(cards[1:]) <= set(inside_group)
    finally:
        store.close()
    # The next boot opens, at the level the view was left on.
    store, registry = restore_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        reread = _ids(project_universal_canvas(store, registry))
        assert cards[0] not in reread and set(cards[1:]) <= set(reread)
        set_universal_scope(store, registry, registry.canvas_root)
        set_universal_scope(store, registry, domain)
        assert inside_domain not in _ids(
            project_universal_canvas(store, registry)
        )
    finally:
        store.close()


def test_the_member_boundary_is_enforced_by_the_server():
    """Finding 3 (security), as SPEC reads it (verifier 2026-09-24, v4/v5):
    a member sees user content and the released application roots the
    founder assigned under signed authority -- nothing else, and no System
    view. The boundary is the server's signed projection grant, not a Studio
    filter: once the real grant is revoked, the domain never reaches the
    member (the canvas fails closed; it is never drawn with the domain)."""
    store, registry = build_universal_application(
        resolve_map_path(), key_provider=_provider()
    )
    shared = _shared_instance(store, registry)
    domain = registry.map.domains["brain"]
    context = _member(store, registry, "test:member:assigned", (shared, domain))
    canvas = project_universal_canvas(
        store, registry, authentication_context=context
    )
    assert set(_ids(canvas)) == {shared, domain}
    assert canvas["authorization"]["system_view"] is False
    grants = [
        relationship
        for relationship in canvas["authorization"]["relationships"]
        if relationship["kind"] == "delegation"
        and relationship["target"] == "test:member:assigned"
        and relationship["scope"] == domain
        and relationship["state"] == "active"
    ]
    assert len(grants) == 1
    revoke_universal_authority_relationship(
        store, registry, grants[0]["root"],
        reason="take the domain off the member's canvas",
    )
    try:
        after = project_universal_canvas(
            store, registry, authentication_context=context
        )
    except InvalidCell as refusal:
        assert "signed projection grants" in str(refusal)
    else:
        assert domain not in _ids(after)
        assert domain not in json.dumps(after["nodes"])


def test_member_reads_answer_json_instead_of_dropping_the_connection():
    """Finding 4: a member's /work and /grand-map-work closed the connection
    with no response; every member read now answers JSON."""
    from urllib.error import HTTPError

    from nodelang.application_server import ApplicationServer

    store, registry = build_universal_application(
        resolve_map_path(), key_provider=_provider()
    )
    shared = _shared_instance(store, registry)
    context = _member(store, registry, "test:member:http", (shared,))
    server = ApplicationServer(
        universal_store=store, universal_registry=registry
    ).start()

    def read(path, session):
        request = Request(server.url + path,
                          headers={"X-ArchHub-Session": session})
        try:
            with urlopen(request, timeout=120) as response:
                return response.status, json.loads(response.read())
        except HTTPError as error:
            return error.code, json.loads(error.read())

    try:
        session, _csrf = server.issue_browser_session(context)
        for path in (
            "/api/universal/canvas",
            "/api/universal/work",
            "/api/universal/grand-map-work",
            "/api/universal/roma-tree",
        ):
            status, body = read(path, session)
            assert status in (200, 403), (path, status)
            if status == 403:
                assert body["ok"] is False and body["error"], path
        status, canvas = read("/api/universal/canvas", session)
        assert status == 200
        assert [node["id"] for node in canvas["nodes"]] == [shared]
    finally:
        server.close()


def test_groups_stay_granted_through_placement_group_ungroup_and_delete(
    tmp_path,
):
    """Found while fixing finding 1, present on HEAD 839dcca: placing a card
    after a group exists (or grouping, or ungrouping beside another group)
    advanced the exposure without re-granting the other groups, and the next
    read refused the whole canvas ("scope exposure differs from signed
    composition grants")."""
    from nodelang.universal_pipeline import retract_universal_node

    path = tmp_path / "groups.sqlite3"
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    definitions = registry.standard_library.definition_roots

    def place(index):
        return instantiate_universal_definition(
            store, registry, definitions[0], x=400.0 + 300 * index, y=100.0
        )[0]

    try:
        cards = [place(index) for index in range(5)]
        set_universal_selection(
            store, registry, (cards[0], cards[1]), focus_root=cards[1]
        )
        first, _ = group_universal_selection(store, registry, title="G1")
        late = place(9)
        project_universal_canvas(store, registry)
        set_universal_selection(
            store, registry, (cards[2], cards[3]), focus_root=cards[3]
        )
        second, _ = group_universal_selection(store, registry, title="G2")
        project_universal_canvas(store, registry)
        application_module.ungroup_universal_composition(
            store, registry, second
        )
        project_universal_canvas(store, registry)
        retract_universal_node(store, registry, cards[4])
        retract_universal_node(store, registry, first)
        drawn = {
            node["id"] for node in
            project_universal_canvas(store, registry)["nodes"]
            if node["application"] is False
        }
    finally:
        store.close()
    assert drawn == {cards[2], cards[3], late}
    store, registry = restore_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        assert {
            node["id"] for node in
            project_universal_canvas(store, registry)["nodes"]
            if node["application"] is False
        } == drawn
    finally:
        store.close()


def _incidences(store, relation_root):
    from nodelang.cell_protocols import read_relation

    return tuple(
        (member.incidence_id, member.role_id, member.participant_id)
        for member in read_relation(
            store.snapshot(), relation_root, budget=100_000
        )
    )


def test_nothing_inside_a_map_domain_is_the_users_to_delete():
    """Verifier 2026-09-24 (v4, HIGH): inside every map domain the
    application's own terminal Cells (public authority, runtime contract,
    sessions, the secret vault, registries) read as user content, and
    deleting them edited the domain relation -- the application itself.
    Every card the application placed inside a domain is refused, with the
    reason, and nothing is written."""
    from nodelang.universal_pipeline import retract_universal_node

    store, registry = build_universal_application(
        resolve_map_path(), key_provider=_provider()
    )
    tried, deleted = 0, []
    for domain in registry.map.domains.values():
        set_universal_scope(store, registry, registry.canvas_root)
        set_universal_scope(store, registry, domain)
        before_members = _incidences(store, domain)
        for card in _ids(project_universal_canvas(store, registry)):
            before = store.revision
            tried += 1
            try:
                retract_universal_node(store, registry, card)
            except InvalidCell as refusal:
                assert "belongs to the application" in str(refusal), card
                assert store.revision == before, card
            else:
                deleted.append(card)
                continue
            assert not application_module._user_canvas_root(
                store.snapshot(), registry, card, level_root=domain
            ), card
        assert _incidences(store, domain) == before_members, domain
    assert tried and not deleted, "%d of %d deleted: %s" % (
        len(deleted), tried, deleted[:12])


def test_registered_work_is_never_read_as_user_content():
    """Verifier 2026-09-24 (v4, latent): Work carries provenance, so the
    shape rule read application-registered Work as user-placed."""
    store, registry = build_universal_application(
        resolve_map_path(), key_provider=_provider()
    )
    work, _wire, _revision = create_universal_governed_work(
        store, registry, title="Review the release",
        description="Review the design release", x=600.0, y=380.0,
        structured_references={"requirements": {
            "acceptance_criteria": ["the release is reviewed"],
        }},
    )
    snapshot = store.snapshot()
    assert not application_module._user_canvas_root(snapshot, registry, work)
    for value in snapshot.cells:
        if value.startswith(work + ":data:"):
            assert not application_module._user_canvas_root(
                snapshot, registry, value
            ), value


def test_a_cell_the_user_places_inside_any_domain_deletes_cleanly():
    """Verifier 2026-09-24 (v5, MEDIUM): a primitive Cell the user placed
    inside a domain answered "belongs to the application". Placement writes
    the read-only authorship fact; the Cell deletes, and the domain relation
    is exactly what it was before the Cell was placed, in every domain."""
    from nodelang.universal_pipeline import retract_universal_node

    store, registry = build_universal_application(
        resolve_map_path(), key_provider=_provider()
    )
    for domain in registry.map.domains.values():
        set_universal_scope(store, registry, registry.canvas_root)
        set_universal_scope(store, registry, domain)
        before = _incidences(store, domain)
        cell, _ = instantiate_universal_primitive(
            store, registry, x=300.0, y=300.0, title="Mine"
        )
        assert cell in _ids(project_universal_canvas(store, registry)), domain
        assert _incidences(store, domain) != before, domain
        retract_universal_node(store, registry, cell)
        assert cell not in _ids(project_universal_canvas(store, registry))
        assert _incidences(store, domain) == before, domain


def test_group_and_ungroup_undo_redo_redraw_the_same_canvas():
    """canvas2-v6 (2026-09-25): group left the wires with one end in the
    selection in the view index, so the next canvas READ committed twice to
    shed them; the gesture that followed failed on a stale revision
    ("expected revision 931, current revision is 933") and redo replayed an
    index the reader had rewritten ("scope exposure invents a non-
    composition root"). Each gesture now commits the whole change: a read
    writes nothing, and every undo/redo redraws the canvas it returns to,
    byte for byte."""
    from nodelang.universal_application import (
        redo_universal_change,
        undo_universal_change,
        ungroup_universal_composition,
    )

    store, registry = build_universal_application(resolve_map_path())

    def drawn():
        revision = store.revision
        canvas = project_universal_canvas(store, registry)
        assert store.revision == revision, "a canvas read wrote the graph"
        return json.dumps(
            {"nodes": canvas["nodes"], "wires": canvas["wires"]},
            sort_keys=True,
        )

    first = json.loads(drawn())["nodes"]
    selected = (first[0]["id"], first[1]["id"])
    set_universal_selection(store, registry, selected, focus_root=selected[-1])
    # Undo returns to the moment before the gesture: the selection is set.
    before = drawn()
    group, _ = group_universal_selection(store, registry, title="Undo me")
    grouped = drawn()
    undo_universal_change(store, registry)
    assert drawn() == before
    redo_universal_change(store, registry)
    assert drawn() == grouped
    ungroup_universal_composition(store, registry, group)
    ungrouped = drawn()
    undo_universal_change(store, registry)
    assert drawn() == grouped
    redo_universal_change(store, registry)
    assert drawn() == ungrouped


@pytest.mark.parametrize("members", ["user cards", "domains"])
def test_group_undo_redo_undo_redo_round_trips(members, tmp_path):
    """Verifier finding (canvas2 r4 probe6, 2026-09-25, on main 6e167b6):
    undo right after redo of a group was refused, "created Cell gained
    references after the recorded transaction". Undo and redo are a
    round trip at every step: each lands on the canvas it returns to.
    Round 3 (2026-09-25): the THIRD undo was refused -- the grants revoked
    in cycle 2 still reference the group. Four cycles, then a reopen."""
    from nodelang.universal_application import (
        redo_universal_change,
        undo_universal_change,
    )

    path = tmp_path / "round-trip.sqlite3"
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )

    def drawn():
        canvas = project_universal_canvas(store, registry)
        return json.dumps(
            {"nodes": canvas["nodes"], "wires": canvas["wires"]},
            sort_keys=True,
        )

    if members == "domains":
        domains = registry.map.domains
        selected = (domains["brain"], domains["ui"])
    else:
        definitions = registry.standard_library.definition_roots
        selected = tuple(
            instantiate_universal_definition(
                store, registry, definitions[0], x=400.0 + 300 * i, y=1400.0
            )[0]
            for i in range(2)
        )
    set_universal_selection(store, registry, selected, focus_root=selected[-1])
    before = drawn()
    group_universal_selection(store, registry, title="Round trip")
    grouped = drawn()
    try:
        for cycle in range(4):
            undo_universal_change(store, registry)
            assert drawn() == before, cycle
            redo_universal_change(store, registry)
            assert drawn() == grouped, cycle
    finally:
        store.close()
    store, registry = restore_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        assert drawn() == grouped
    finally:
        store.close()


def test_undo_still_refuses_a_foreign_signed_reference_after_redo():
    """Coordinator gap (A): only the reconciler's own view grants for THIS
    group may reference it after redo. A signed relationship of another
    kind that references the group is a later edit; undo refuses it and
    writes nothing."""
    from nodelang.universal_application import (
        redo_universal_change,
        undo_universal_change,
    )
    from nodelang.cell_identity import grant_authority_relationship
    from nodelang.universal_cell import Conflict

    store, registry = build_universal_application(resolve_map_path())
    definitions = registry.standard_library.definition_roots
    selected = tuple(
        instantiate_universal_definition(
            store, registry, definitions[0], x=400.0 + 300 * i, y=1400.0
        )[0]
        for i in range(2)
    )
    set_universal_selection(store, registry, selected, focus_root=selected[-1])
    group, _ = group_universal_selection(store, registry, title="Held")
    undo_universal_change(store, registry)
    redo_universal_change(store, registry)
    authority = registry.authorization
    context = application_module._active_authentication_context(authority, None)
    admin = authority.broker.resolve(context).subject_root
    grant_authority_relationship(
        store,
        authority.identity_protocol,
        authority.relationship_broker,
        authority.relationship_broker.mint_from_trusted_administrator(admin),
        relationship_id="test:foreign-membership:" + group,
        source_root=group,
        target_root=authority.tenant_root,
        kind="membership",
        tenant_root=authority.tenant_root,
        administrator_root=admin,
        reason="a later, foreign signed reference to the group",
    )
    before = store.revision
    with pytest.raises(Conflict, match="gained references"):
        undo_universal_change(store, registry)
    assert store.revision == before


def _live_grants_on(store, registry, root):
    from nodelang.cell_identity import verify_relationship_authority_snapshot

    authority = registry.authorization
    kinds = authority.identity_protocol.kinds
    verified = verify_relationship_authority_snapshot(
        store.snapshot(), authority.identity_protocol,
        authority.relationship_broker,
    )
    return sorted(
        relationship.root_id for relationship in verified.active_relationships
        if (relationship.kind_root == kinds["audience-binding"]
            and relationship.source_root == root)
        or (relationship.kind_root == kinds["delegation"]
            and relationship.scope_root == root)
    )


def test_undo_after_redo_leaves_no_live_grant_on_the_group(tmp_path):
    """Round-2 finding: group -> undo -> redo -> undo left an ACTIVE signed
    audience binding on the undone group, and it survived reopen."""
    from nodelang.universal_application import (
        redo_universal_change,
        undo_universal_change,
    )

    path = tmp_path / "undone.sqlite3"
    store, registry = build_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        definitions = registry.standard_library.definition_roots
        selected = tuple(
            instantiate_universal_definition(
                store, registry, definitions[0], x=400.0 + 300 * i, y=1400.0
            )[0]
            for i in range(2)
        )
        set_universal_selection(
            store, registry, selected, focus_root=selected[-1]
        )
        group, _ = group_universal_selection(store, registry, title="Gone")
        undo_universal_change(store, registry)
        redo_universal_change(store, registry)
        assert _live_grants_on(store, registry, group), "redo re-grants"
        undo_universal_change(store, registry)
        assert group not in _ids(project_universal_canvas(store, registry))
        assert _live_grants_on(store, registry, group) == []
    finally:
        store.close()
    store, registry = restore_universal_application(
        resolve_map_path(), CellStore(path), key_provider=_provider()
    )
    try:
        assert _live_grants_on(store, registry, group) == []
        assert group not in _ids(project_universal_canvas(store, registry))
    finally:
        store.close()


def test_undo_refuses_a_broader_delegation_on_the_group():
    """Round-2 finding: only a read-only delegation is the reconciler's; a
    delegation granting more than read that references the group is a
    later edit, and undo refuses it without writing."""
    from nodelang.universal_application import (
        redo_universal_change,
        undo_universal_change,
    )
    from nodelang.cell_identity import grant_authority_relationship
    from nodelang.universal_cell import Conflict

    store, registry = build_universal_application(resolve_map_path())
    definitions = registry.standard_library.definition_roots
    selected = tuple(
        instantiate_universal_definition(
            store, registry, definitions[0], x=400.0 + 300 * i, y=1400.0
        )[0]
        for i in range(2)
    )
    set_universal_selection(store, registry, selected, focus_root=selected[-1])
    group, _ = group_universal_selection(store, registry, title="Held")
    undo_universal_change(store, registry)
    redo_universal_change(store, registry)
    authority = registry.authorization
    context = application_module._active_authentication_context(authority, None)
    admin = authority.broker.resolve(context).subject_root
    actions = authority.protocol.actions
    grant_authority_relationship(
        store,
        authority.identity_protocol,
        authority.relationship_broker,
        authority.relationship_broker.mint_from_trusted_administrator(admin),
        relationship_id="test:broader-delegation:" + group,
        source_root=authority.resource_reader_principal_root,
        target_root=registry.view_sessions[admin].subject_root,
        kind="delegation",
        tenant_root=authority.tenant_root,
        scope_root=group,
        action_roots=(actions["read"], actions["edit"]),
        administrator_root=admin,
        reason="a broader delegation than the reconciler issues",
    )
    before = store.revision
    with pytest.raises(Conflict, match="gained references"):
        undo_universal_change(store, registry)
    assert store.revision == before


def test_undo_of_a_group_another_view_draws_keeps_that_views_grant(tmp_path):
    """Round 3: undo retires only what THIS view drew. When a member view
    also draws the group, the founder's undo must not revoke the grant
    that view reads it through: either the undo is refused and writes
    nothing, or it lands and the member still draws the group."""
    from nodelang.universal_application import (
        redo_universal_change,
        undo_universal_change,
    )
    from nodelang.universal_cell import Conflict

    store, registry = build_universal_application(
        resolve_map_path(), key_provider=_provider()
    )
    definitions = registry.standard_library.definition_roots
    selected = tuple(
        instantiate_universal_definition(
            store, registry, definitions[0], x=400.0 + 300 * i, y=1400.0
        )[0]
        for i in range(2)
    )
    set_universal_selection(store, registry, selected, focus_root=selected[-1])
    group, _ = group_universal_selection(store, registry, title="Shared group")
    undo_universal_change(store, registry)
    redo_universal_change(store, registry)
    # A group is personal WIP and cannot be promoted ("resource lifecycle
    # requires the released lifecycle capability"), so today no other view
    # can be handed it. Record that refusal: if it ever opens, this court
    # runs the undo below instead and holds the member's view to it.
    revision = store.revision
    try:
        context = _member(
            store, registry, "test:other-view:member", (group,)
        )
    except (InvalidCell, PermissionError) as refusal:
        assert "WIP resource is outside this subject's authority" in str(
            refusal
        ), refusal
        # The member Cell is committed before provisioning refuses; the
        # refusal itself writes nothing more.
        assert store.revision == revision + 1
        return
    member_before = _ids(project_universal_canvas(
        store, registry, authentication_context=context
    ))
    assert group in member_before
    revision = store.revision
    try:
        undo_universal_change(store, registry)
    except (Conflict, InvalidCell):
        assert store.revision == revision
    assert _ids(project_universal_canvas(
        store, registry, authentication_context=context
    )) == member_before
