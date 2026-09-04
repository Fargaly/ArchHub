"""C4 -- INDEPENDENT node court (judged_by=claude, NOT codex).

MIGRATION GATE. Proves the brain daemon's Python meeting-room feed
(from / to / kind / text / refs / reply) maps LOSSLESSLY onto Codex's
Cell-native `cell_deliberation` entries and projects back identically --
so retiring the Python room onto the node graph provably loses nothing
BEFORE the bridge is ever flipped. Imports ONLY Codex's public API;
never edits Codex's files. Self-contained fixture space -- no rebuild of
the real 126k-cell app. Honors the patent hold: local only, nothing
external.

  python node_courts/court_room_feed_equivalence.py   # exit 0 = GREEN
"""
import sys, os

_HERE = os.path.dirname(os.path.abspath(__file__))
# node-language/ inside this repository first (PR #306); the sibling
# 13.NODE-LANGUAGE worktree is the founder-workstation fallback.
NL = next((c for c in (os.path.join(_HERE, "..", "..", "node-language"),
                       os.path.join(_HERE, "..", "..", "..", "13.NODE-LANGUAGE"))
           if os.path.isdir(os.path.join(c, "nodelang"))),
          os.path.join(_HERE, "..", "..", "..", "13.NODE-LANGUAGE"))
sys.path.insert(0, os.path.abspath(NL))

from nodelang.cell_authorization import (
    AuthenticationBroker,
    PolicyReleaseBroker,
    bootstrap_authorization_protocol,
    build_authorization_policy,
    build_authorization_rule,
    release_authorization_policy,
)
from nodelang.cell_deliberation import (
    append_deliberation_entry,
    bootstrap_deliberation_protocol,
    compose_deliberation_space,
    list_deliberation_entries,
    read_deliberation_entry,
)
from nodelang.universal_cell import Cell, CellStore, NULL_CELL_ID


# ---- the brain daemon's real room-feed shape (source of record to migrate) ----
# (from, to, kind, text, refs, reply_index_or_None)  -- covers every shape the
# live room actually emits: all 9 kinds, to-room + to-agent, 0/1/2 refs, replies.
CATEGORIES = ("say", "plan", "research", "coord", "exec",
              "decision", "blocker", "finding", "note")
PARTICIPANTS = ("claude", "codex", "founder")
LEAVES = ("leaf-app-workshop", "leaf-cell-deliberation")

FEED = [
    ("founder", "",       "plan",     "Plan the room->cell migration first.",   ("leaf-app-workshop",),                          None),
    ("claude",  "codex",  "finding",  "app:workshop is relation-not-blob.",      ("leaf-app-workshop", "leaf-cell-deliberation"), None),
    ("codex",   "claude", "coord",    "Ack -- append via public API only.",      (),                                              1),
    ("claude",  "",       "exec",     "Ran C1/C2/C3 -- all green.",              ("leaf-cell-deliberation",),                     None),
    ("founder", "",       "decision", "Everything is a node. No parallel engine.", (),                                            None),
    ("claude",  "codex",  "blocker",  "Need your boundary: where does the surface live?", (),                                     None),
    ("codex",   "",       "research", "Reviewing one-root multi-lens options.",  (),                                              None),
    ("claude",  "",       "say",      "Standing by, prepping the equivalence gate.", (),                                          None),
    ("codex",   "claude", "note",     "Noted -- will set the boundary.",         (),                                              6),
]


def _build_space(store):
    delib = bootstrap_deliberation_protocol(store, prefix="claude:c4:deliberation")
    authz = bootstrap_authorization_protocol(store, prefix="claude:c4:authorization")

    roots = {p: p.encode() for p in PARTICIPANTS}
    roots["workspace"] = b"ArchHub workspace"
    roots["assurance-strong"] = b"Strong authentication"
    roots["lifecycle-wip"] = b"WIP"
    for c in CATEGORIES:
        roots["category-" + c] = c.encode()
    for leaf in LEAVES:
        roots[leaf] = leaf.encode()
    store.commit(store.revision, create=tuple(
        Cell(rid, NULL_CELL_ID, NULL_CELL_ID, atom) for rid, atom in roots.items()))

    # every participant is permitted to author (create) in the workspace
    rules = tuple(
        build_authorization_rule(
            store, authz,
            rule_id="claude:c4:rule:" + p,
            effect="permit", principal_root=p, object_root="workspace",
            action_root=authz.actions["create"],
        )
        for p in PARTICIPANTS
    )
    policy = build_authorization_policy(
        store, authz, rules, policy_id="claude:c4:policy", version="1.0.0")
    releases = PolicyReleaseBroker()
    handle = releases.mint_from_trusted_administrator(policy, "founder")
    release_authorization_policy(
        store, authz, policy, releases, handle, administrator_root="founder")

    space = compose_deliberation_space(
        store, delib,
        space_id="claude:c4:workshop",
        title="ArchHub Workshop (equivalence fixture)",
        participant_roots=PARTICIPANTS,
        category_roots=tuple("category-" + c for c in CATEGORIES),
        policy_root=policy,
        action_root=authz.actions["create"],
        scope_roots=("workspace",),
        lifecycle_root="lifecycle-wip",
    )

    identities = AuthenticationBroker()
    contexts = {
        p: identities.mint_authenticated_context(
            p, principal_roots=(p,), tenant_root="workspace",
            assurance_root="assurance-strong", lifetime_seconds=600)
        for p in PARTICIPANTS
    }
    return delib, authz, identities, contexts, space


def run():
    store = CellStore(None)
    delib, authz, identities, contexts, _space = _build_space(store)

    # --- WRITE: every room message becomes a Cell deliberation entry ---
    entry_ids = []
    for i, (frm, to, kind, text, refs, reply_i) in enumerate(FEED):
        entry = append_deliberation_entry(
            store, delib,
            space_root="claude:c4:workshop",
            actor_root=frm,
            category_root="category-" + kind,
            content=text,
            reference_roots=refs,
            recipient_roots=((to,) if to else ()),
            evidence_roots=(),
            reply_to_root=(entry_ids[reply_i] if reply_i is not None else None),
            idempotency_key="c4:msg:%d" % i,
            created_at="2026-07-17T12:%02d:00+00:00" % i,
            authorization_protocol=authz,
            authentication_broker=identities,
            authentication_context=contexts[frm],
        )
        entry_ids.append(entry.root_id)

    # --- READ BACK: project the Cell entries to the room-feed shape ---
    snap = store.snapshot()
    listed = list_deliberation_entries(snap, delib, "claude:c4:workshop")
    projected = []
    id_to_index = {rid: i for i, rid in enumerate(entry_ids)}
    for item in listed:
        e = read_deliberation_entry(snap, delib, item.root_id)
        kind = e.category_root[len("category-"):]
        to = e.recipient_roots[0] if e.recipient_roots else ""
        reply_i = id_to_index.get(e.reply_to_root) if e.reply_to_root else None
        projected.append((e.actor_root, to, kind, e.content,
                          tuple(e.reference_roots), reply_i))

    # --- EQUIVALENCE: projected feed is identical to the source, in order ---
    assert len(projected) == len(FEED), \
        "entry count drift: %d != %d" % (len(projected), len(FEED))
    for i, (src, got) in enumerate(zip(FEED, projected)):
        assert got == src, "row %d lost fidelity:\n  src=%r\n  got=%r" % (i, src, got)

    # entries are relations (leaf atom), never JSON room blobs
    for rid in entry_ids:
        c = snap.cells[rid]
        assert c.atom == b"", "entry %s is not a leaf-atom relation" % rid

    return {"C4_room_feed_equivalence": "GREEN",
            "messages": len(FEED), "kinds": len(CATEGORIES),
            "actors": len(PARTICIPANTS), "replies_preserved": True,
            "entries_are_relations": True}


if __name__ == "__main__":
    r = run()
    print("C4 ROOM-FEED <-> CELL-DELIBERATION EQUIVALENCE:", r)
    print("GREEN" if r["C4_room_feed_equivalence"] == "GREEN" else "RED")
