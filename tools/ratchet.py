"""RATCHET (founder 2026-10-16: "الخرا زي ما هو بيزيد مبيتحلش" -- the mess keeps growing, never solved).
Measures mess counts in a tree; compare mode fails if any count is higher than the baseline.
Usage:
  python ratchet.py measure <tree> [--out ratchet.json]
  python ratchet.py compare <tree> <baseline.json>      # exit 1 if any count grew
Every count is a plain, reproducible heuristic; the definitions are printed with the table.
"""
import ast
import json
import pathlib
import re
import sys

BUTTON_HELPER = re.compile(r"\bconst\s+(\w*(?:[Bb]tn|[Bb]utton)\w*)\s*=\s*(?:\([^;]*?\)|\w+)\s*=>\s*\(\s*\{")

DEFS = {
    "local_button_helpers": "style-returning const arrow factories with Btn/Button in the name, plus HoverBtn, in studio/*.jsx; ds/ is the shared owner",
    "inline_styles": "literal JSX style={{...}} attributes in studio/*.jsx; ds/ is the shared owner",
    "http_servers": "modules that construct an HTTP server (HTTPServer/ThreadingHTTPServer/uvicorn.run/web.run_app)",
    "graph_authorities": "modules that open the universal graph sqlite store directly (sqlite3.connect on a *universal*.sqlite3 path or class *GraphStore/*CellStore)",
    "revit_adapters": "modules defining Revit execution adapters (def/class names with 'revit' + exec/adapter/bridge)",
    "baboom_loops": "functions named like a BABOOM agent/tool loop (baboom.*loop|run_.*tool_loop)",
    "settings_stores": "modules that persist settings outside the graph (json dump to *settings*.json / QSettings)",
    "model_routers": "modules defining a model router (class/def *Router or route_model)",
    "memory_stores": "modules defining a memory/profile store (class *Memory*Store / *Profile*Store)",
    "unimported_modules": "nodelang/*.py never imported by any other file in the tree (excluding __init__, __main__, tests, entry scripts)",
    "placeholder_strings": "UI/runtime strings 'Not available yet' / 'coming soon' / 'placeholder' / 'TODO' in nodelang (non-test)",
    "dead_params_known": "dead params from the R&D inventory still declared (default_view, default_tab, speech_budget_per_hour, tick_cadence_minutes)",
    "loc_nodelang": "lines in nodelang/**/*.py + nodelang/studio/*.jsx,*.js (excluding compiled/)",
}


def py_files(root):
    return [p for p in (root / "nodelang").rglob("*.py") if "compiled" not in p.parts and "__pycache__" not in p.parts]


def measure(root):
    root = pathlib.Path(root)
    files = py_files(root)
    texts = {p: p.read_text(encoding="utf-8", errors="replace") for p in files}
    c = {k: 0 for k in DEFS}
    for p, t in texts.items():
        if re.search(r"\b(ThreadingHTTPServer|HTTPServer)\s*\(|uvicorn\.run\(|web\.run_app\(", t):
            c["http_servers"] += 1
        if re.search(r"sqlite3\.connect\([^)]*universal", t) or re.search(r"class \w*(GraphStore|CellStore)\b", t):
            c["graph_authorities"] += 1
        if re.search(r"(?i)(def|class) \w*revit\w*(exec|adapter|bridge)\w*", t):
            c["revit_adapters"] += 1
        c["baboom_loops"] += len(re.findall(r"def (\w*baboom\w*loop\w*|run_\w*tool_loop\w*)\(", t))
        if re.search(r"settings\w*\.json['\"]", t) and "json.dump" in t or "QSettings(" in t:
            c["settings_stores"] += 1
        if re.search(r"class \w*Router\b|def route_model\(", t):
            c["model_routers"] += 1
        if re.search(r"class \w*(Memory|Profile)\w*Store\b", t):
            c["memory_stores"] += 1
        c["placeholder_strings"] += len(re.findall(r"(?i)not available yet|coming soon|\bplaceholder\b", t))
    # unimported modules
    names = {p.stem: p for p in files if p.parent == root / "nodelang" and p.stem not in ("__init__", "__main__")}
    corpus = "\n".join(texts.values())
    for extra in list(root.glob("*.py")) + list((root / "tests_replica").glob("*.py"))[:0] + list((root / "cloud_backend").rglob("*.py")):
        try:
            corpus += "\n" + extra.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
    for stem, p in names.items():
        own = texts[p]
        rest = corpus.replace(own, "")
        if not re.search(r"(nodelang\.|from \.|import |[\"'])" + re.escape(stem) + r"\b", rest):
            c["unimported_modules"] += 1
    for name in ("default_view", "default_tab", "speech_budget_per_hour", "tick_cadence_minutes"):
        if re.search(r"[\"']" + name + r"[\"']", corpus):
            c["dead_params_known"] += 1
    loc = sum(t.count("\n") for t in texts.values())
    studio = root / "nodelang" / "studio"
    for p in list(studio.glob("*.jsx")) + list(studio.glob("*.js")):
        loc += p.read_text(encoding="utf-8", errors="replace").count("\n")
    jsx = "\n".join(p.read_text(encoding="utf-8") for p in studio.glob("*.jsx"))
    c["local_button_helpers"] = len(BUTTON_HELPER.findall(jsx)) + len(re.findall(r"\bconst HoverBtn\s*=", jsx))
    c["inline_styles"] = len(re.findall(r"\bstyle\s*=\s*\{\s*\{", jsx))
    c["loc_nodelang"] = loc
    return c


def table(counts, base=None):
    rows = ["| count | value | main | verdict |", "|---|---|---|---|"]
    for k in DEFS:
        v = counts[k]
        b = base.get(k) if base else None
        verdict = "" if b is None else ("FAIL (grew)" if v > b else ("dropped" if v < b else "held"))
        rows.append(f"| {k} | {v} | {'' if b is None else b} | {verdict} |")
    return "\n".join(rows)


if __name__ == "__main__":
    mode, tree = sys.argv[1], sys.argv[2]
    counts = measure(tree)
    if mode == "measure":
        out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
        if out:
            pathlib.Path(out).write_text(json.dumps({"counts": counts, "definitions": DEFS}, indent=2), encoding="utf-8")
        print(table(counts))
    else:
        base = json.loads(pathlib.Path(sys.argv[3]).read_text(encoding="utf-8"))["counts"]
        print(table(counts, base))
        missing = [k for k in DEFS if k not in base]
        if missing:
            raise SystemExit("RATCHET FAIL: baseline missing " + ", ".join(missing))
        grew = [k for k in DEFS if counts[k] > base[k]]
        print("RATCHET FAIL: " + ", ".join(grew) if grew else "RATCHET PASS")
        sys.exit(1 if grew else 0)
