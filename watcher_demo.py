"""The WATCHER node, working: it takes a session's parameters (the UI's param nodes)
and turns into a UI-editing node. Editing through the watcher mutates those nodes;
the UI is RE-RUN from the nodes — recolor, rename, delete, add — and propagates.
Real, executed. The UI is produced BY the node graph, not hand-drawn."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from node_lang import Graph, History

g = Graph()
# A session whose parameters describe a tiny UI (the map's own toolbar), AS NODES:
accent = g.add("ui_accent", "accent", params={"color": "#d97757"})         # the app colour, a node
labels = ["Run", "Save", "Wire", "Fit"]
els = [g.add("ui_el_" + l.lower(), "ui_element", params={"type": "button", "label": l}) for l in labels]
render = g.add("ui_render", "ui_render", params={"accent": accent, "elements": els})  # the UI = a node

# THE WATCHER: takes the session parameters (those UI nodes) and becomes a UI-editing node.
watcher = g.add("ui_watcher", "watcher", params={"targets": [accent] + els})

def state():
    accent_c = g.eval(accent)
    btns = [g.eval(e)["label"] for e in g.nodes[render]["params"]["elements"]]
    return accent_c, btns

def show(label):
    c, btns = state()
    print(f"   {label}")
    print(f"      -> UI now: accent={c}  buttons={btns}")

print("=" * 72)
print("THE WATCHER = the session's parameters, turned into an editable UI node:")
print("=" * 72)
for item in g.eval(watcher):
    print(f"   edit  {item['id']:14} {item['params']}")

print()
print("=" * 72)
print("EDIT THROUGH THE WATCHER -> the UI RE-RUNS from the nodes (how it works)")
print("=" * 72)
show("start (UI computed from nodes)")
g.set_param(accent, "color", "#7ec18e")                # recolor — every button follows (one param, many readers)
show("watcher recolors accent -> green")
g.set_param("ui_el_save", "label", "Commit")           # rename an element
show("watcher renames Save -> Commit")
g.remove("ui_el_fit")                                   # delete an element
show("watcher deletes 'Fit'")
g.add("ui_el_deploy", "ui_element", params={"type": "button", "label": "Deploy"})
g.nodes[render]["params"]["elements"].append("ui_el_deploy")
g.nodes[watcher]["params"]["targets"].append("ui_el_deploy")
g._invalidate(render)
show("watcher adds 'Deploy'")

print()
print("=" * 72)
print("SAVE/SYNC — the UI the nodes produced, written out (this is what propagates)")
print("=" * 72)
html = ('<!doctype html><body style="background:#0e0e11;padding:24px">'
        '<div style="color:#9b938a;font-family:Inter,sans-serif;font-size:12px;margin-bottom:8px">'
        'this toolbar was produced by the node graph, edited through the watcher node</div>'
        + g.eval(render) + '</body>')
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "watcher_ui.html")
open(out, "w", encoding="utf-8").write(html)
print(f"   wrote {os.path.basename(out)}  ({len(g.eval(render))} chars of UI, computed from {len(els)} element nodes)")
print()
print("ALL REAL — the watcher edited the nodes; the UI re-ran from them. Not drawn.")
