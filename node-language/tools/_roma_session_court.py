r"""Drive the just-encoded ROMA loop LIVE over the 2026-06-03 session's
deliverables and emit an honest verdict ledger.

This is NOT a unit test — it runs the REAL encoded court
(`personal_brain.court_harness.convene_court` +
`personal_brain.requirement_tree`) against the REAL artifacts on disk
(py_compile of the ROMA modules + the secret shim, file_exists of every
rendered doc), and HONESTLY marks the founder-gated items (DashScope key
rotation, cloud deploy, branch merge) as `needs_root` — never green —
because they carry no machine-checkable artifact gate.

SAFETY (load-bearing):
  * DEDICATED store under `.telemetry/roma_session_court.db` — NEVER the live
    brain.db / -wal / -shm. Created fresh each run (deleted if present) so the
    ledger is reproducible and isolated.
  * Read-only on git. No secret VALUES anywhere — gates check existence/compile
    only.
  * Anti-self-certify is honoured: every leaf is CLAIMED by an executor id and
    JUDGED by a DIFFERENT court id; `set_verdict` + the independence lens both
    refuse a self-graded green.

Run:
  PYTHONPATH=C:\Users\fargaly\00.ARCHUB\ArchHub\personal-brain-mcp\src \
    python C:\Users\fargaly\00.ARCHUB\ArchHub\tools\_roma_session_court.py
"""
from __future__ import annotations

import json
from pathlib import Path

from personal_brain.storage import BrainStore
from personal_brain import requirement_tree as rt
from personal_brain.court_harness import convene_court

REPO = Path(r"C:\Users\fargaly\00.ARCHUB\ArchHub")
TELEMETRY = REPO / ".telemetry"
DB_PATH = TELEMETRY / "roma_session_court.db"
JSON_OUT = TELEMETRY / "roma_session_court.json"

# Identities — the executor CLAIMS, a DIFFERENT court JUDGES (never self-certify).
EXECUTOR = "roma-session-executor"
COURT = "roma-session-court"

# Absolute paths to the REAL artifacts the court gates on.
SRC = REPO / "personal-brain-mcp" / "src" / "personal_brain"
DOCS = REPO / "docs" / "prototypes"


def _p(*parts: str) -> str:
    return str(REPO.joinpath(*parts))


# The decomposition: 4 internal branches, each splitting into machine-checkable
# leaves (py_compile / file_exists) — PLUS the founder-gated leaves that carry
# NO machine gate (gate_kind='manual') so the court lands them as needs_root.
BRANCHES: list[dict] = [
    {
        "title": "ROMA modules compile (the encoded loop is real Python)",
        "children": [
            {
                "title": "requirement_tree.py py_compiles",
                "gate_kind": "py_compile",
                "gate_spec": {"path": str(SRC / "requirement_tree.py")},
            },
            {
                "title": "court_harness.py py_compiles (the wired jury)",
                "gate_kind": "py_compile",
                "gate_spec": {"path": str(SRC / "court_harness.py")},
            },
            {
                "title": "roma.py py_compiles (orchestrator + MCP surface)",
                "gate_kind": "py_compile",
                "gate_spec": {"path": str(SRC / "roma.py")},
            },
            {
                "title": "test_roma.py exists + asserts the no-false-green guard",
                "gate_kind": "file_exists",
                "gate_spec": {
                    "path": str(SRC.parent.parent / "tests" / "test_roma.py"),
                    "contains": "dangling",
                },
            },
        ],
    },
    {
        "title": "Session docs rendered (each prototype exists on disk)",
        "children": [
            {
                "title": "brain-own-mcp-plan rendered",
                "gate_kind": "file_exists",
                "gate_spec": {"path": str(DOCS / "brain-own-mcp-plan-2026-06-03.html")},
            },
            {
                "title": "brain-supplychain-audit rendered",
                "gate_kind": "file_exists",
                "gate_spec": {"path": str(DOCS / "brain-supplychain-audit-2026-06-03.html")},
            },
            {
                "title": "ia-critique-ai-stemcells rendered",
                "gate_kind": "file_exists",
                "gate_spec": {"path": str(DOCS / "ia-critique-ai-stemcells-2026-06-03.html")},
            },
            {
                "title": "stem-buildfrom-plan rendered",
                "gate_kind": "file_exists",
                "gate_spec": {"path": str(DOCS / "stem-buildfrom-plan-2026-06-03.html")},
            },
            {
                "title": "stem-rebuild-inplace rendered",
                "gate_kind": "file_exists",
                "gate_spec": {"path": str(DOCS / "stem-rebuild-inplace-2026-06-03.html")},
            },
            {
                "title": "roma-loop-encoded doc rendered + closes its <defs>",
                "gate_kind": "file_exists",
                # the d575a95 render fix: defs are closed so the diagram paints.
                "gate_spec": {
                    "path": str(DOCS / "roma-loop-encoded-2026-06-03.html"),
                    "contains": "</defs>",
                },
            },
        ],
    },
    {
        "title": "Secret-resolve-at-launch shim compiles (the de-inline fix)",
        "children": [
            {
                "title": "app/archhub_mcp_server.py py_compiles",
                "gate_kind": "py_compile",
                "gate_spec": {"path": _p("app", "archhub_mcp_server.py")},
            },
        ],
    },
    {
        "title": "Founder-gated items (NOT machine-verifiable — must land as needs_root)",
        "children": [
            {
                # PENDING-FOUNDER: the fix de-inlined + added op:// resolution,
                # but ROTATING the live key is the founder's action — no machine
                # gate can (or should) verify a secret value. -> needs_root.
                "title": "PENDING-FOUNDER: rotate the DashScope API key + store new value",
                "gate_kind": "manual",
                "gate_spec": {},
            },
            {
                # GATED: founder OAuth + `fly secrets` — a live deploy only the
                # founder's credentials can do. -> needs_root.
                "title": "GATED: cloud deploy (founder OAuth + fly secrets)",
                "gate_kind": "manual",
                "gate_spec": {},
            },
            {
                # GATED: track-g-telemetry-phase0 -> main is a founder merge call.
                "title": "GATED: merge track-g-telemetry-phase0 -> main",
                "gate_kind": "manual",
                "gate_spec": {},
            },
        ],
    },
]


def main() -> dict:
    TELEMETRY.mkdir(parents=True, exist_ok=True)
    # Fresh, isolated, reproducible ledger — never the live brain.
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(DB_PATH) + suffix)
        if p.exists():
            p.unlink()

    store = BrainStore.open(str(DB_PATH))

    # ── ATOMIZE: root = the session; split into the 4 branches + leaves. ──
    root_title = "ArchHub 2026-06-03 session"
    tree = rt.create_root(store, title=root_title, owner_user="founder")
    tid = tree.tree_id
    rid = tree.root_id

    # Level 1: the four branches.
    rt.decompose(
        store, tree_id=tid, node_id=rid,
        children=[{"title": b["title"]} for b in BRANCHES],
    )
    # Level 2: leaves under each branch.
    for b in BRANCHES:
        bid = rt._node_id(tid, rid, b["title"])
        rt.decompose(
            store, tree_id=tid, node_id=bid,
            children=[
                {
                    "title": c["title"],
                    "gate_kind": c["gate_kind"],
                    "gate_spec": c["gate_spec"],
                }
                for c in b["children"]
            ],
        )

    # ── CLAIM + JUDGE each leaf: executor claims, a DIFFERENT court judges. ──
    ctx = {"repo_root": str(REPO), "cwd": str(REPO)}
    leaf_rows: list[dict] = []

    reloaded = rt.get_tree(store, tree_id=tid)
    assert reloaded is not None
    leaves = reloaded.leaves()

    for leaf in leaves:
        # 1) executor claims the leaf (anti-self-certify anchor).
        rt.claim_leaf(store, tree_id=tid, node_id=leaf.node_id, agent_id=EXECUTOR)

        # 2) the EXTERNAL court convenes on the REAL artifact (judge != executor).
        cv = convene_court(
            node_id=leaf.node_id,
            gate_kind=leaf.gate_kind,
            gate_spec=leaf.gate_spec,
            claimed_by=EXECUTOR,
            judged_by=COURT,
            context=ctx,
        )

        # 3) record the verdict in the tree (derives the up-tree green sweep).
        evref = next((l.evidence_ref for l in cv.lenses if l.evidence_ref), None)
        rt.set_verdict(
            store, tree_id=tid, node_id=leaf.node_id,
            verdict=cv.verdict, judged_by=COURT, evidence_ref=evref,
        )

        leaf_rows.append({
            "node_id": leaf.node_id,
            "branch": (reloaded.nodes[leaf.parent].title if leaf.parent else "(root)"),
            "title": leaf.title,
            "gate_kind": leaf.gate_kind,
            "verdict": cv.verdict,            # green | red | needs_root
            "green": cv.green,
            "reason": cv.reason[:300],
            "lenses": [
                {"lens": l.lens, "applied": l.applied, "refuted": l.refuted,
                 "detail": l.detail[:160], "evidence_ref": l.evidence_ref}
                for l in cv.lenses
            ],
        })

    # ── SWEEP: the loop-until-dry status (done == full green sweep). ──
    final_sweep = rt.sweep(store, tree_id=tid)

    # Map needs_root node ids back to human titles for the ledger.
    after = rt.get_tree(store, tree_id=tid)
    needs_root_titled = [
        {"node_id": nid, "title": after.nodes[nid].title}
        for nid in final_sweep["needs_root"]
        if after and nid in after.nodes
    ]

    out = {
        "store": str(DB_PATH),
        "tree_id": tid,
        "root_id": rid,
        "root_title": root_title,
        "court_id": COURT,
        "executor_id": EXECUTOR,
        "sweep": final_sweep,
        "needs_root_titled": needs_root_titled,
        "leaves": leaf_rows,
    }

    JSON_OUT.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")

    # ── print a human ledger ──
    print("=" * 78)
    print(f"ROMA SESSION COURT — {root_title}")
    print(f"store: {DB_PATH}  (DEDICATED — not the live brain.db)")
    print(f"court: {COURT}   executor: {EXECUTOR}   (judge != executor)")
    print("=" * 78)
    print(f"{'VERDICT':<11} {'GATE':<11} LEAF")
    print("-" * 78)
    order = {"green": 0, "red": 1, "needs_root": 2}
    for r in sorted(leaf_rows, key=lambda x: (order.get(x["verdict"], 9), x["branch"])):
        mark = {"green": "GREEN", "red": "RED", "needs_root": "NEEDS_ROOT"}[r["verdict"]]
        print(f"{mark:<11} {r['gate_kind']:<11} {r['title']}")
    print("-" * 78)
    s = final_sweep
    print(f"dry={s['dry']}  root_green={s['root_green']}  "
          f"counts={s['counts']}")
    print(f"total_leaves={s['total_leaves']}  green_leaves={s['green_leaves']}  "
          f"actionable={s['actionable_leaves']}")
    print(f"needs_root={[t['title'] for t in needs_root_titled]}")
    print(f"dangling_refs={s['dangling_refs']}")
    print(f"\nledger JSON -> {JSON_OUT}")
    return out


if __name__ == "__main__":
    main()
