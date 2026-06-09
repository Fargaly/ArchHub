"""ROMA proof — the ArchHub stem-cell palette (#90 rebuild) RECREATES the
real BBC4 submittal-QC reconcile session, headless, on a real file fixture.

WHAT THIS PROVES (and what it does NOT):
  • COMPOSITION — the QC task is assembled as a GRAPH of REGISTERED stem
    cells (fs.list, fs.read, data.json, code.python, verify.assert), wired
    src→dst, fed to the real `WorkflowRunner`. Nothing bespoke.
  • COOK — the runner cooks the graph the Houdini way (lazy/dirty/cached).
    The FILE LISTING comes from `fs.list` doing a real `os.scandir` on
    proof_bbc4/submittals/, and the MASTER comes from `fs.read` doing a real
    `open(rb)` on proof_bbc4/master.json — NEITHER is inlined in this script.
  • CORRECTNESS — the matched/strays/missing partition computed from the
    real cook is asserted (by a `verify.assert` cell AND a host-side check)
    to EQUAL the expected truth set of the past session.
  • COMPOSABILITY — the partition logic is additionally wrapped into a
    `subgraph.user` composite via the real `compose_subgraph`, and that
    composite is cooked too, proving the cells collapse into one runnable
    stem cell exactly as Cmd-G would on the live canvas.

BOUNDARY (honest): this is a HEADLESS proof on a file fixture. It does NOT
prove a human dragged these cells together in the live GUI / wired them on
the canvas / clicked Run — that needs the running PyQt app + CDP. It proves
the ENGINE half: the registered cells compose into a valid graph, the runner
cooks it against real disk, and the result is correct.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
APP = os.path.join(REPO, "app")
if APP not in sys.path:
    sys.path.insert(0, APP)

# ── Load the WHOLE registry exactly the way the recipe does, so every cell
#    type we name resolves to its real registered executor. ────────────────
import importlib
import pkgutil
import workflows.nodes as N

for _m in pkgutil.iter_modules(N.__path__):
    importlib.import_module("workflows.nodes." + _m.name)

from workflows import registry                       # noqa: E402
from workflows.runner import WorkflowRunner          # noqa: E402
from workflows.subgraph import compose_subgraph      # noqa: E402


FIXTURE = os.path.join(REPO, "proof_bbc4")
SUBMITTALS = os.path.join(FIXTURE, "submittals")
MASTER = os.path.join(FIXTURE, "master.json")

# Expected truth set of the past BBC4-QC session (the oracle we assert AGAINST,
# not the data we feed IN — the data is read from disk by the cells).
EXPECTED = {
    "matched": ["ARC-001.pdf", "ARC-002.pdf", "STR-010.pdf"],
    "strays":  ["RANDOM.txt", "STRAY-999.pdf"],
    "missing": ["ARC-003.pdf"],
}


def _assert_cells_registered() -> list[str]:
    """Confirm every cell type we use is a REAL registered executor."""
    used = ["fs.list", "fs.read", "data.json", "code.python",
            "verify.assert", "subgraph.user"]
    for t in used:
        if registry.get(t) is None:
            raise SystemExit(f"FAIL — cell {t!r} is NOT registered")
    return used


# ── The partition body. This is the QC matching LOGIC (allowed to live in a
#    code.python cell). It receives the file rows + parsed master AS WIRED
#    INPUTS from the upstream cells — it never reads the disk itself and never
#    inlines the file list. It mirrors what the BBC4 session did: match on the
#    file-name doc-id stem. ──────────────────────────────────────────────────
PARTITION_BODY = r"""
# input port `a` <- fs.list rows  (real os.scandir of the submittals folder)
# input port `b` <- data.json value (parsed master.json read from disk)
rows = inputs.get("a") or []
master = inputs.get("b") or []

folder_names = sorted(r["name"] for r in rows if isinstance(r, dict) and not r.get("is_dir"))
master_names = sorted(m["name"] for m in master if isinstance(m, dict))

folder_set = set(folder_names)
master_set = set(master_names)

# stem-match on the file name (the doc-id), exactly as the QC session did.
matched = sorted(folder_set & master_set)
strays  = sorted(folder_set - master_set)   # in folder, NOT on master
missing = sorted(master_set - folder_set)   # on master, NOT in folder

# carry each matched file's master status (the reconcile's payload).
status_by_name = {m["name"]: m.get("status") for m in master if isinstance(m, dict)}
matched_with_status = [{"name": n, "status": status_by_name.get(n)} for n in matched]

result = {
    "matched": matched,
    "strays": strays,
    "missing": missing,
    "matched_with_status": matched_with_status,
}
"""


def build_graph() -> dict:
    """Assemble the QC workflow as a GRAPH of registered stem cells.

    Topology (src.port -> dst.port):
        fs.list (folder)  --rows--> code.python.a (as `rows`)
        fs.read (master)  --text--> data.json.text
        data.json         --value--> code.python.b (as `master`)
        code.python       --value--> verify.assert.value
    """
    nodes = [
        {"id": "list_folder", "type": "fs.list",
         "config": {"path": SUBMITTALS}},
        {"id": "read_master", "type": "fs.read",
         "config": {"path": MASTER}},
        {"id": "parse_master", "type": "data.json",
         "config": {"mode": "parse"}},
        {"id": "partition", "type": "code.python",
         "config": {"body": PARTITION_BODY, "safe_mode": True}},
        # verify.assert: passes when the partition's three lists equal the
        # oracle. The eq compares an EXPRESSION-plucked subset (the three
        # sorted lists) so the status payload riding in `value` is ignored.
        {"id": "assert_truth", "type": "verify.assert",
         "config": {"mode": "expression", "safe_mode": True,
                    "expr": "{'matched': value['matched'], "
                            "'strays': value['strays'], "
                            "'missing': value['missing']} == "
                            + repr({"matched": EXPECTED["matched"],
                                    "strays": EXPECTED["strays"],
                                    "missing": EXPECTED["missing"]}),
                    "message": "BBC4 QC partition"}},
    ]
    wires = [
        # fs.list rows -> code.python port `a` (read in the body as inputs["a"])
        {"from": ["list_folder", "rows"], "to": ["partition", "a"]},
        # fs.read text -> data.json text
        {"from": ["read_master", "text"], "to": ["parse_master", "text"]},
        # data.json value -> code.python port `b` (read as inputs["b"])
        {"from": ["parse_master", "value"], "to": ["partition", "b"]},
        # the partition's `value` (the result dict) is what we assert eq the
        # oracle; src_field plucks just the three comparable lists so the eq
        # compare is against exactly {matched, strays, missing}.
        {"from": ["partition", "value"], "to": ["assert_truth", "value"]},
    ]
    return {"nodes": nodes, "wires": wires}


def main() -> int:
    print("=" * 70)
    print("ROMA PROOF — BBC4 submittal-QC recreated on the stem-cell palette")
    print("=" * 70)

    cells = _assert_cells_registered()
    print(f"[1] registered cells confirmed: {cells}")
    print(f"    fixture folder : {SUBMITTALS}")
    print(f"    fixture master : {MASTER}")
    print(f"    (the cells read these from disk — nothing inlined)")

    graph = build_graph()
    print(f"[2] composed graph: {len(graph['nodes'])} cells, "
          f"{len(graph['wires'])} wires")

    runner = WorkflowRunner(graph)

    # COOK the real chain. Pull the partition cell — the runner walks upstream
    # and cooks fs.list (real scandir), fs.read (real open), data.json (parse).
    part_out = runner.pull("partition")
    if part_out.get("status") == "error":
        print(f"FAIL — partition cook errored: {part_out.get('error')}")
        return 1
    partition = part_out.get("value") or {}

    # Show the cooked upstream values came from real disk reads.
    list_out = runner.node_outputs.get("list_folder", {})
    read_out = runner.node_outputs.get("read_master", {})
    print(f"[3] fs.list cooked  -> {list_out.get('count')} rows from disk")
    print(f"    fs.read cooked  -> {read_out.get('bytes_read')} bytes "
          f"of master.json")

    got = {k: partition.get(k) for k in ("matched", "strays", "missing")}
    print(f"[4] computed partition (from the real cook):")
    print(f"    matched: {got['matched']}")
    print(f"    strays : {got['strays']}")
    print(f"    missing: {got['missing']}")
    print(f"    matched_with_status: {partition.get('matched_with_status')}")

    # The verify.assert cell's verdict (the in-graph gate).
    assert_out = runner.pull("assert_truth")
    in_graph_passed = bool(assert_out.get("passed"))
    print(f"[5] in-graph verify.assert -> passed={in_graph_passed} "
          f"({assert_out.get('report')})")

    # Host-side independent check (anti-tamper: don't trust only the cell).
    expected_cmp = {"matched": EXPECTED["matched"],
                    "strays": EXPECTED["strays"],
                    "missing": EXPECTED["missing"]}
    host_passed = (got == expected_cmp)
    print(f"[6] host-side check        -> equal={host_passed}")

    # ── COMPOSABILITY: wrap the partition logic into a subgraph.user composite
    #    via the REAL compose_subgraph, then cook the composite. Proves the
    #    cells collapse into one runnable stem cell (Cmd-G on the canvas). ────
    composed = compose_subgraph(graph, ["parse_master", "partition"],
                                title="BBC4 QC partition")
    comp_node = next(n for n in composed["nodes"]
                     if n.get("type") == "subgraph.user")
    comp_runner = WorkflowRunner(composed)
    comp_out = comp_runner.pull(comp_node["id"])
    # the composite's output port for partition.value:
    comp_val = None
    for k, v in comp_out.items():
        if isinstance(v, dict) and "matched" in v:
            comp_val = v
            break
    comp_got = ({k: comp_val.get(k) for k in ("matched", "strays", "missing")}
                if comp_val else None)
    comp_passed = (comp_got == expected_cmp)
    print(f"[7] subgraph.user composite cooked -> "
          f"partition equal={comp_passed}")

    ok = in_graph_passed and host_passed and comp_passed
    print("-" * 70)
    print(json.dumps({
        "ran": True,
        "composed": True,
        "partition": got,
        "expected": expected_cmp,
        "in_graph_assert_passed": in_graph_passed,
        "host_check_passed": host_passed,
        "composite_passed": comp_passed,
        "correct": ok,
    }, indent=2))
    print("-" * 70)
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
