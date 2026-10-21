"""RATCHET (founder 2026-10-16: "الخرا زي ما هو بيزيد مبيتحلش" -- the mess keeps growing, never solved).
Measures mess counts in a tree; compare mode fails if any count is higher than the baseline.
Usage:
  python ratchet.py measure <tree> [--out ratchet.json]
  python ratchet.py compare <tree> <baseline.json>      # exit 1 if any count grew
Every count is a plain, reproducible heuristic; the definitions are printed with the table.
"""
import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from tools.pipeline import strict_check

BUTTON_HELPER = re.compile(r"\bconst\s+(\w*(?:[Bb]tn|[Bb]utton)\w*)\s*=\s*(?:\([^;]*?\)|\w+)\s*=>\s*\(\s*\{")

DEFS = {    "local_button_helpers": "style-returning const arrow factories with Btn/Button in the name, plus HoverBtn, in studio/*.jsx; ds/ is the shared owner",
    "inline_styles": "literal JSX style={{...}} attributes in studio/*.jsx; ds/ is the shared owner",

    "http_servers": "modules that construct an HTTP server (HTTPServer/ThreadingHTTPServer/uvicorn.run/web.run_app)",
    "graph_authorities": "modules that open the universal graph sqlite store directly (sqlite3.connect on a *universal*.sqlite3 path or class *GraphStore/*CellStore)",
    "revit_adapters": "modules defining Revit execution adapters (def/class names with 'revit' + exec/adapter/bridge)",
    "baboom_loops": "functions named like a BABOOM agent/tool loop (baboom.*loop|run_.*tool_loop)",
    "settings_stores": "modules that persist settings outside the graph (json dump to *settings*.json / QSettings)",
    "model_routers": "modules defining a model router (class/def *Router or route_model)",
    "memory_stores": "modules defining a memory/profile store (class *Memory*Store / *Profile*Store)",
    "unimported_modules": "01.APP/nodelang/*.py never imported by any other file in the tree (excluding __init__, __main__, tests, entry scripts)",
    "placeholder_strings": "UI/runtime strings 'Not available yet' / 'coming soon' / 'placeholder' / 'TODO' in nodelang (non-test)",
    "dead_params_known": "dead params from the R&D inventory still declared (default_view, default_tab, speech_budget_per_hour, tick_cadence_minutes)",
    "loc_nodelang": "lines in 01.APP/nodelang/**/*.py + 01.APP/nodelang/studio/*.jsx,*.js (excluding compiled/)",
}


def py_files(root):
    return [p for p in (root / "01.APP/nodelang").rglob("*.py") if "compiled" not in p.parts and "__pycache__" not in p.parts]


def measure(root, sources=None):
    root = pathlib.Path(root)
    files = py_files(root) if sources is None else [root / p for p in sources
            if p.startswith("01.APP/nodelang/") and p.endswith(".py") and "compiled" not in pathlib.Path(p).parts]
    texts = {p: p.read_text(encoding="utf-8", errors="replace") if sources is None
             else sources[p.relative_to(root).as_posix()] for p in files}
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
    names = {p.stem: p for p in files if p.parent == root / "01.APP/nodelang" and p.stem not in ("__init__", "__main__")}
    corpus = "\n".join(texts.values())
    if sources is None:
        for extra in list(root.glob("*.py")) + list((root / "06.CLOUD/cloud_backend").rglob("*.py")):
            try:
                corpus += "\n" + extra.read_text(encoding="utf-8", errors="replace")
            except OSError as error:
                raise strict_check.CompilerFailure(f"cannot read ratchet source {extra}: {error}") from error
    else:
        corpus += "\n" + "\n".join(text for path, text in sources.items()
                if path.endswith(".py") and ("/" not in path or path.startswith("06.CLOUD/cloud_backend/")))
    for stem, p in names.items():
        own = texts[p]
        rest = corpus.replace(own, "")
        if not re.search(r"(nodelang\.|from \.|import |[\"'])" + re.escape(stem) + r"\b", rest):
            c["unimported_modules"] += 1
    for name in ("default_view", "default_tab", "speech_budget_per_hour", "tick_cadence_minutes"):
        if re.search(r"[\"']" + name + r"[\"']", corpus):
            c["dead_params_known"] += 1
    loc = sum(t.count("\n") for t in texts.values())
    studio = root / "01.APP/nodelang" / "studio"
    if sources is None:
        for p in list(studio.glob("*.jsx")) + list(studio.glob("*.js")):
            loc += p.read_text(encoding="utf-8", errors="replace").count("\n")
    else:
        loc += sum(text.count("\n") for path, text in sources.items()
                   if pathlib.PurePosixPath(path).parent == pathlib.PurePosixPath("01.APP/nodelang/studio")
                   and pathlib.PurePosixPath(path).suffix in (".js", ".jsx"))
    jsx = "\n".join(p.read_text(encoding="utf-8") for p in studio.glob("*.jsx")) if sources is None else "\n".join(
        text for path, text in sources.items()
        if pathlib.PurePosixPath(path).parent == pathlib.PurePosixPath("01.APP/nodelang/studio") and path.endswith(".jsx"))
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


def _owned_sources(root, paths, revision=None):
    sources = {}
    for path in paths:
        if pathlib.PurePosixPath(path).suffix not in (".py", ".js", ".jsx"):
            continue
        if revision is None:
            candidate = root / path
            if candidate.is_file():
                sources[path] = candidate.read_text(encoding="utf-8", errors="replace")
        else:
            result = subprocess.run(["git", "-C", str(root), "show", f"{revision}:{path}"],
                                    capture_output=True, timeout=strict_check.node_timeout())
            if result.returncode == 0:
                sources[path] = result.stdout.decode("utf-8", errors="replace")
            elif subprocess.run(["git", "-C", str(root), "ls-tree", revision, "--", path],
                                capture_output=True, timeout=strict_check.node_timeout()).stdout:
                raise strict_check.CompilerFailure(f"cannot read owned base source: {path}")
    return sources


def measure_owned(root, paths, revision="HEAD"):
    root = pathlib.Path(root).resolve()
    return measure(root, _owned_sources(root, paths)), measure(root, _owned_sources(root, paths, revision))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("measure", "compare"))
    parser.add_argument("tree")
    parser.add_argument("baseline", nargs="?")
    parser.add_argument("--out")
    parser.add_argument("--whole-tree", action="store_true", help="release-only full legacy and compiler ratchets")
    parser.add_argument("--context")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--files", nargs="+")
    scope.add_argument("--session-record")
    scope.add_argument("--base")
    scope.add_argument("--commit")
    args = parser.parse_args(argv)
    root = pathlib.Path(args.tree).resolve()
    try:
        if args.mode == "measure":
            counts = measure(root)
            if args.out:
                pathlib.Path(args.out).write_text(json.dumps({"counts": counts, "definitions": DEFS}, indent=2), encoding="utf-8")
            print(table(counts))
            return 0
        if not args.baseline:
            raise ValueError("compare requires a baseline path")
        paths = strict_check.selected_files(root, files=args.files, session_record=args.session_record,
                                           base=args.base, commit=args.commit)
        if args.whole_tree:
            counts = measure(root)
            base = json.loads(pathlib.Path(args.baseline).read_text(encoding="utf-8"))["counts"]
        else:
            # Hook comparisons are deltas of owned source files, never a verdict
            # about another session's global legacy counts.
            if not paths:
                print("RATCHET PASS: no owned staged/session files")
                return 0
            revision = args.base or (f"{args.commit}^" if args.commit else "HEAD")
            counts, base = measure_owned(root, paths, revision)
        print(table(counts, base))
        missing = [key for key in DEFS if key not in base]
        if missing:
            raise ValueError("baseline missing " + ", ".join(missing))
        grew = [key for key in DEFS if counts[key] > base[key]]
        context_path = args.context or os.environ.get("ARCHHUB_INTENT_CONTEXT")
        context = json.loads(pathlib.Path(context_path).read_text(encoding="utf-8")) if context_path else None
        result = strict_check.check_changed(root, files=args.files, session_record=args.session_record,
                                           base=args.base, commit=args.commit, context=context)
        strict_check.print_diagnostics(result)
        compiler_ratchet = strict_check.check_ratchet(root) if args.whole_tree else {"ok": True, "regressions": []}
        for regression in compiler_ratchet["regressions"]:
            print(f"ACOMPILER RATCHET FAIL: {regression['code']}/{regression['language']} "
                  f"{regression['baseline']} -> {regression['current']}")
        failed = bool(grew) or not result["ok"] or not compiler_ratchet["ok"]
        print("RATCHET FAIL: " + (", ".join(grew) or "compiler diagnostics") if failed else "RATCHET PASS")
        return 1 if failed else 0
    except (strict_check.CompilerFailure, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"RATCHET REFUSED: {exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
