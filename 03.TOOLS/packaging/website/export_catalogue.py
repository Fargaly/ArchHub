"""Export the app's node library and starters for the public site.

Run at release time from the repository root, before the site is built:
    python 03.TOOLS/packaging/website/export_catalogue.py
It writes .cache/site/catalogue.json (ignored by Git; the library stays the one owner). build_site.py reads that file and never
imports the application runtime, so the site shows exactly the nodes and starters this release ships.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
# A build input, regenerated every build and never committed: the library itself is the one owner of these nodes.
OUT = ROOT / ".cache" / "site" / "catalogue.json"
# Rows built from this machine (saved skills, workspace folders, local model list, installed agents) are not
# part of the product and never reach the public site.
LOCAL_CATEGORIES = {"skill", "workspaces", "models", "agents"}


def export():
    sys.path.insert(0, str(ROOT / "01.APP"))
    from nodelang.library_engines import engine_categories, library_catalogue
    from nodelang.starters import listing
    groups = library_catalogue()
    labels = {row.get("id", row.get("cat")): row.get("label", row.get("name", "")) for row in engine_categories(groups)
              if isinstance(row, dict)}
    nodes = [{
        "id": item["id"], "cat": item["cat"], "title": item["title"], "sub": item.get("sub", ""),
        "pure": bool(item.get("pure")),
        "params": [{"name": d.get("name") or d.get("id"), "type": d.get("type", ""),
                    "default": item.get("params", {}).get(d.get("id"))} for d in item.get("paramDefs", [])],
        "inputs": [{"name": p["id"], "type": p.get("type", "")} for p in item.get("ports", {}).get("target", [])],
        "outputs": [{"name": p["id"], "type": p.get("type", "")} for p in item.get("ports", {}).get("source", [])],
    } for group in groups if group["cat"] not in LOCAL_CATEGORIES for item in group["items"]]
    starters = [{"id": s["id"].split(":", 1)[-1], "title": s["title"], "stops_at": s.get("stops_at", ""),
                 "needs": list(s.get("needs") or []), "steps": [c["title"] for c in s.get("children", [])]}
                for s in listing([])]
    data = {"categories": [{"id": g["cat"], "label": labels.get(g["cat"]) or g["cat"].capitalize()} for g in groups if g["cat"] not in LOCAL_CATEGORIES],
            "nodes": nodes, "starters": starters}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    print(f"{OUT}: {len(nodes)} nodes, {len(starters)} starters")


if __name__ == "__main__":
    export()
