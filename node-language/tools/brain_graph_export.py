"""Export the ArchHub memory/brain graph to JSON for the visualizer.

Reads the on-disk MemoryGraph (capabilities / decisions / skills + typed
edges) and writes `app/web_ui/brain-graph-data.json` — the payload the
`brain-graph.html` force-directed view fetches, and the same shape the
`bridge.brain_graph_export` slot returns to the in-app JSX panel.

Run:  python tools/brain_graph_export.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))


def build_payload() -> dict:
    from memory import MemoryGraph, default_graph_path

    g = MemoryGraph.open(default_graph_path())
    nodes = [n.to_dict() for n in g.all_nodes()]
    edges = [e.to_dict() for e in g.all_edges()]

    # degree → node size; computed here so the view stays dumb.
    degree: Counter[str] = Counter()
    for e in edges:
        degree[e["source"]] += 1
        degree[e["target"]] += 1
    for n in nodes:
        n["degree"] = degree.get(n["id"], 0)

    kinds = Counter(n["kind"] for n in nodes)
    rels = Counter(e["relation"] for e in edges)
    return {
        "ok": True,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "kinds": dict(kinds.most_common()),
            "relations": dict(rels.most_common()),
        },
        "nodes": nodes,
        "edges": edges,
    }


def main() -> int:
    payload = build_payload()
    out = APP / "web_ui" / "brain-graph-data.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    s = payload["stats"]
    print(f"wrote {out}")
    print(f"  nodes={s['nodes']} edges={s['edges']} kinds={s['kinds']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
