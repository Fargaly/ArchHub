# -*- coding: utf-8 -*-
"""LEAF: an EFFECTFUL node (host_write) is FROZEN by default.

The §5b safety boundary, made executable and EXECUTED (not drawn):

  - FROZEN (the default): eval performs NO real write. It returns a dry-run
    PREVIEW of exactly what it WOULD do. The host file is never touched.
  - UNFREEZE + APPLY: only an explicit frozen=False AND apply=True makes eval
    perform the real side effect — the file appears on disk with the value.
  - REVERT: the change is undone. The History tree rerolls the GRAPH back to the
    frozen baseline, and the host file is restored to its prior state (it did not
    exist before -> it is gone again). Undo is real for BOTH the graph and the host.

REUSES node_lang.Graph / node_lang.History and the host_write kind the Engine
phase already put in node_lang.py. Edits nothing — own file, no collisions.
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from .node_lang import Graph, History


def _file_state(path):
    """The host's view of one file: whether it exists and its content if so.
    This is the 'prior state' a revert must be able to restore."""
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as fh:
            return {"exists": True, "content": fh.read()}
    return {"exists": False, "content": None}


def _restore_file(path, prior):
    """Restore the host file to a previously captured state — the host side of revert.
    The graph revert (History) cannot un-write a disk file on its own; the host that
    performed the effect is the one that undoes it, back to the captured prior state."""
    if prior["exists"]:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(prior["content"])
    elif os.path.exists(path):
        os.remove(path)


def run():
    print("=" * 70)
    print("LEAF — effectful host_write is FROZEN by default (dry-run -> apply -> revert)")
    print("=" * 70)

    tmp = tempfile.mkdtemp(prefix="leaf_effectful_")
    sentinel = os.path.join(tmp, "sentinel.txt")
    VALUE = "EFFECT-APPLIED-42"

    # the host's true starting point: the sentinel does NOT exist
    before_any = _file_state(sentinel)
    assert before_any["exists"] is False, ("sentinel should not pre-exist", before_any)
    print(f"   sentinel target : {sentinel}")
    print(f"   file BEFORE      : exists={before_any['exists']}  (clean host)")

    # ---- build the effectful node, FROZEN by default ----------------------
    g = Graph()
    # frozen defaults to True inside the engine; we don't even set it, to prove the default
    g.add("w", "host_write", params={"target": sentinel, "value": VALUE})

    hist = History()
    v_frozen = hist.commit(g, "v0 frozen-baseline")   # immutable snapshot of the safe state
    print(f"   committed v0     : frozen-baseline snapshot (graph is in the safe state)")

    # ---- 1) EVAL WHILE FROZEN -> no write, dry-run preview returned --------
    preview = g.eval("w")
    state_after_frozen = _file_state(sentinel)
    print()
    print("   [1] eval FROZEN (default):")
    print(f"       returned        : {preview}")
    print(f"       file exists?    : {state_after_frozen['exists']}")
    assert state_after_frozen["exists"] is False, ("FROZEN eval wrote the file!", state_after_frozen)
    assert preview["dry_run"] is True and preview["applied"] is False, ("not a dry-run preview", preview)
    assert preview["would"] == {"action": "write", "target": sentinel, "value": VALUE}, \
        ("preview does not describe the real intended write", preview)
    print("       -> NO write happened; a dry-run PREVIEW of the intended write was returned. OK")

    # ---- 2) UNFREEZE + APPLY -> the real file appears ---------------------
    g.set_param("w", "frozen", False)
    g.set_param("w", "apply", True)
    result = g.eval("w")
    state_after_apply = _file_state(sentinel)
    print()
    print("   [2] eval after frozen=False + apply=True:")
    print(f"       returned        : {result}")
    print(f"       file exists?    : {state_after_apply['exists']}  content={state_after_apply['content']!r}")
    assert state_after_apply["exists"] is True, ("apply did not write the file", state_after_apply)
    assert state_after_apply["content"] == VALUE, ("file has wrong value", state_after_apply)
    assert result["applied"] is True and result["dry_run"] is False, ("apply not marked applied", result)
    print("       -> the real file now exists with the value. OK")

    # ---- 3) REVERT -> graph rerolls to frozen baseline; host file undone --
    # capture the applied state so the host can restore the PRIOR (pre-apply) state
    prior_for_revert = before_any                      # what the file looked like before any apply
    label = hist.revert(g, v_frozen)                   # graph: back to the frozen-baseline snapshot
    _restore_file(sentinel, prior_for_revert)          # host: back to the captured prior file state
    state_after_revert = _file_state(sentinel)
    reverted_node = g.nodes["w"]["params"]
    re_eval = g.eval("w")
    print()
    print(f"   [3] revert to '{label}':")
    print(f"       graph node      : frozen={reverted_node.get('frozen', True)!r}  "
          f"apply={reverted_node.get('apply', False)!r}")
    print(f"       re-eval         : {re_eval}")
    print(f"       file exists?    : {state_after_revert['exists']}")
    assert state_after_revert["exists"] is False, ("revert did not undo the host write", state_after_revert)
    assert re_eval["applied"] is False and re_eval["dry_run"] is True, \
        ("reverted graph is not back in the frozen/dry-run state", re_eval)
    print("       -> graph is frozen again AND the host file is gone. Undo is real. OK")

    print()
    print("=" * 70)
    print("SUMMARY — effectful node frozen-by-default, explicit apply, real revert")
    print("=" * 70)
    print(f"   before any : exists={before_any['exists']}")
    print(f"   frozen eval: exists={state_after_frozen['exists']}  (dry-run preview, no write)")
    print(f"   applied    : exists={state_after_apply['exists']}  content={state_after_apply['content']!r}")
    print(f"   reverted   : exists={state_after_revert['exists']}  (host write undone)")
    print("   FROZEN_DEFAULT_OK")


if __name__ == "__main__":
    run()
