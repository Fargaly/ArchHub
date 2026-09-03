# -*- coding: utf-8 -*-
"""LEAF: the map's UI is a VIEW computed FROM the UI-domain's nodes, and the
WATCHER node is the live editor.

  accent + ui_element nodes  --feed-->  ui_render node  ==  the toolbar HTML
  watcher node               --targets->  those same nodes

Editing a target THROUGH the watcher (recolor accent / rename / add / delete a
button) invalidates ui_render, so ui_render RE-RUNS and the produced+written UI
changes. The UI is NOT hand-drawn: it is the return value of eval(ui_render).

Self-contained leaf. It REUSES node_lang (Graph/History) unchanged — no edits to
node_lang.py / server.py — and PROVES the capability by running every edit, writing
the served HTML, and asserting the propagation end-to-end. Run it directly.
"""
import os, sys, json

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from .node_lang import Graph, History   # REUSE the real engine, do not rebuild

OUT = os.path.join(HERE, "watcher_ui.html")
PAGE = ('<!doctype html><body style="background:#0e0e11;padding:24px">'
        '<div style="color:#9b938a;font-family:Inter,sans-serif;font-size:12px;'
        'margin-bottom:8px">this toolbar was produced by the node graph, '
        'edited through the watcher node</div>%s</body>')


def serve(g, render):
    """Write the served UI = the live eval of the ui_render node (a VIEW, not drawn)."""
    html = PAGE % g.eval(render)
    open(OUT, "w", encoding="utf-8").write(html)
    return html


def edit_via_watcher(g, watcher, op, **kw):
    """Drive an edit THROUGH the watcher: it only touches nodes it is watching,
    then the dependent ui_render re-runs on next eval (incremental invalidation)."""
    targets = g.nodes[watcher]["params"]["targets"]
    render = g.nodes[watcher]["params"]["render"]
    if op == "recolor":
        acc = kw["target"]
        assert acc in targets, "watcher may only edit nodes it watches"
        g.set_param(acc, "color", kw["color"])             # one param, every button follows
    elif op == "rename":
        el = kw["target"]
        assert el in targets, "watcher may only edit nodes it watches"
        g.set_param(el, "label", kw["label"])
    elif op == "add":
        el = g.add(kw["id"], "ui_element", params={"type": "button", "label": kw["label"]})
        g.nodes[render]["params"]["elements"].append(el)   # new node feeds ui_render
        targets.append(el)                                 # watcher now watches it too
        g._invalidate(render)
    elif op == "delete":
        el = kw["target"]
        assert el in targets, "watcher may only edit nodes it watches"
        g.remove(el)                                       # scrubs it from elements + targets
    return g.eval(render)                                   # ui_render RE-RAN -> fresh HTML


def buttons(g, render):
    return [g.eval(e)["label"] for e in g.nodes[render]["params"]["elements"]]


def build():
    g = Graph(); hist = History()
    # --- the UI domain, AS NODES (this IS the toolbar's source of truth) ---
    accent = g.add("ui_accent", "accent", params={"color": "#d97757"})
    labels = ["Run", "Save", "Wire", "Fit"]
    els = [g.add("ui_el_" + l.lower(), "ui_element",
                 params={"type": "button", "label": l}) for l in labels]
    render = g.add("ui_render", "ui_render", params={"accent": accent, "elements": els})
    # --- the WATCHER: the live editor; it watches the UI nodes + knows its render ---
    watcher = g.add("ui_watcher", "watcher",
                    params={"targets": [accent] + els, "render": render})
    return g, hist, accent, render, watcher


def main():
    g, hist, accent, render, watcher = build()
    print("=" * 72)
    print("LEAF: UI is a VIEW computed from nodes; the watcher is the live editor")
    print("=" * 72)

    # the watcher exposes the watched nodes as an editable view
    print("watcher view (the editable UI nodes):")
    for item in g.eval(watcher):
        print("   edit  %-14s %s" % (item["id"], item["params"]))
    print()

    h_start = serve(g, render)
    base_evals = g.evals
    print("start   accent=%s  buttons=%s" % (g.eval(accent), buttons(g, render)))
    hist.commit(g, "start")

    # 1) RECOLOR the accent through the watcher -> every button re-runs with new colour
    edit_via_watcher(g, watcher, "recolor", target=accent, color="#7ec18e")
    h1 = serve(g, render)
    print("recolor accent=%s  buttons=%s   (ui_render re-ran)" % (g.eval(accent), buttons(g, render)))
    assert "#7ec18e" in h1 and "#d97757" not in h1 and h1 != h_start

    # 2) RENAME Save -> Commit through the watcher
    edit_via_watcher(g, watcher, "rename", target="ui_el_save", label="Commit")
    h2 = serve(g, render)
    print("rename  Save -> Commit            buttons=%s" % buttons(g, render))
    assert "Commit" in h2 and "Save" not in buttons(g, render)

    # 3) DELETE 'Fit' through the watcher
    edit_via_watcher(g, watcher, "delete", target="ui_el_fit")
    print("delete  Fit                       buttons=%s" % buttons(g, render))
    assert "Fit" not in buttons(g, render)

    # 4) ADD 'Deploy' through the watcher
    edit_via_watcher(g, watcher, "add", id="ui_el_deploy", label="Deploy")
    h4 = serve(g, render)
    print("add     Deploy                    buttons=%s" % buttons(g, render))
    assert "Deploy" in h4

    # incremental proof: edits recomputed, but it never re-evaluated the whole graph from
    # scratch — only the invalidated chain (accent/elements -> ui_render) was recomputed.
    print()
    print("incremental: %d real node computations across 4 watcher edits + 4 re-serves"
          % (g.evals - base_evals))

    # history still works (revert restores the pre-edit UI from an immutable snapshot)
    hist.commit(g, "after edits")
    hist.revert(g, 0)
    assert "#d97757" in g.eval(render) and "Fit" in buttons(g, render)
    print("history: reverted to 'start' snapshot -> UI back to %s %s"
          % (g.eval(accent), buttons(g, render)))
    hist.revert(g, 1)   # roll forward to the edited UI (that's what we serve)
    final = serve(g, render)

    # FINAL served HTML must carry all four propagated edits
    assert "#7ec18e" in final and "#d97757" not in final
    assert "Commit" in final and "Deploy" in final and "Run" in final and "Fit" not in final
    print()
    print("wrote %s  (%d chars, computed from the node graph)"
          % (os.path.basename(OUT), len(final)))

    # mirror the exact programmatic check from the task, inline, so one run proves it
    g2 = Graph()
    a = g2.add("acc", "accent", params={"color": "#d97757"})
    e = g2.add("b", "ui_element", params={"type": "button", "label": "Run"})
    r = g2.add("r", "ui_render", params={"accent": a, "elements": [e]})
    w = g2.add("w", "watcher", params={"targets": [a, e]})
    h0 = g2.eval(r)
    assert "#d97757" in h0 and any(t["id"] == "acc" for t in g2.eval(w))
    g2.set_param(a, "color", "#7ec18e")
    h1b = g2.eval(r)
    assert "#7ec18e" in h1b and "#d97757" not in h1b and h1b != h0
    print("WATCHER_RERAN_UI_OK")


if __name__ == "__main__":
    main()
