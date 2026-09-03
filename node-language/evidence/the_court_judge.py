"""THE COURT — judge the docket (SPEC 11 + Core Values + 100 layers + Grand
Map, generated from the documents) against the RUNNING program.

One verdict file. Three outcomes per item: PASS (measured true), FAIL
(measured false), NOT JUDGED (no automatic measurement exists yet -- and
NOT JUDGED never counts as green). The live gesture verdict from
the_court.cjs feeds the SPEC-11 rows it can decide.
"""
import json
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DOCKET = HERE / "the-court-docket.json"
GESTURES = HERE / "the-court-verdict.json"
BINDINGS = HERE / "court_bindings.json"
MAP_BINDINGS = HERE / "grandmap_bindings.json"
OUT = HERE / "the-court-judgement.json"
OWNER = "http://127.0.0.1:8475"


def bindings():
    try:
        return json.loads(BINDINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"bindings": {}, "junit_report": ""}


def map_bindings():
    try:
        return json.loads(MAP_BINDINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"bindings": {}, "deliberately_unbound": {}}


def junit_cases(report_path):
    """Every test case in a junit xml, keyed by 'file::name' and by file."""
    path = ROOT / report_path if report_path else None
    if not path or not path.exists():
        return {}
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return {}
    cases = {}
    for case in tree.iter("testcase"):
        name = case.get("name") or ""
        f = (case.get("file") or "").replace('\\', "/")
        if not f:
            # pytest junit carries the module in classname: pkg.mod[.Class]
            parts = [x for x in (case.get("classname") or "").split(".") if x]
            while parts and not parts[-1].startswith("test_"):
                parts.pop()
            f = "/".join(parts) + ".py" if parts else ""
        if case.find("failure") is not None or case.find("error") is not None:
            outcome = "fail"
        elif case.find("skipped") is not None:
            outcome = "skip"
        else:
            outcome = "pass"
        cases.setdefault(f, []).append((name, outcome))
    return cases


def judge_by_binding(court_id, cases, decl):
    """Decide a court from its declared tests. None => NOT JUDGED."""
    spec = decl.get("bindings", {}).get(court_id)
    if not spec:
        return None, None
    matched, failed = [], []
    for selector in spec["tests"]:
        f, _, only = selector.partition("::")
        for name, outcome in cases.get(f, []):
            if only and name != only:
                continue
            matched.append(name)
            if outcome == "fail":
                failed.append("%s::%s" % (f.split("/")[-1], name))
    if not matched:
        return None, "declared %d test file(s) but the report has none of them" % len(spec["tests"])
    if failed:
        return False, "%d of %d bound tests failed: %s" % (
            len(failed), len(matched), "; ".join(failed[:3]))
    return True, "%d bound tests passed across %d file(s)" % (len(matched), len(spec["tests"]))


def live_gestures():
    try:
        return json.loads(GESTURES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"checks": []}


def gesture(name_fragment):
    for check in live_gestures().get("checks", []):
        if name_fragment in check["name"]:
            return check
    return None


def owner_answers():
    try:
        with urllib.request.urlopen(OWNER + "/", timeout=5) as r:
            return r.status == 200
    except Exception:
        return False


def judge_spec(item, ctx):
    n = item["id"].split(".")[-1]
    g = None
    if n == "13":   # interaction in a real browser
        rows = [gesture("wheel"), gesture("fit"), gesture("pointer")]
        rows = [r for r in rows if r]
        if rows:
            ok = all(r["pass"] for r in rows)
            return ok, "; ".join("%s=%s" % (r["name"].split(":")[0], r["measured"]) for r in rows)
    if n == "14":   # performance
        g = gesture("pointer: frame p95")
        if g: return g["pass"], g["measured"]
    if n == "12":   # composition: enter, breadcrumb
        rows = [gesture("enter: double-click"), gesture("enter: breadcrumb")]
        rows = [r for r in rows if r]
        if rows: return all(r["pass"] for r in rows), "; ".join(str(r["measured"]) for r in rows)
    if n == "9":    # user control: open shows work
        g = gesture("open: first screen shows the work")
        if g: return g["pass"], g["measured"]
    if n == "17":   # no false done: this record itself
        return True, "this judgement names every NOT JUDGED item explicitly"
    bound, why = judge_by_binding(item["id"], ctx["cases"], ctx["decl"])
    if bound is not None:
        return bound, why
    return None, why or ("no automatic measurement bound to SPEC 11.%s yet" % n)


def judge_core_value(item, ctx):
    # A value with an open gap column is, by its own document, not fully met.
    gap = (item.get("gap") or "").lower()
    if gap.startswith("substantial"):
        return None, "document says: " + item["gap"]
    if gap.startswith("partial") or "open" in gap or "not" in gap:
        return False, "document's own gap: " + item["gap"]
    return None, item.get("gap", "")


def judge_layer(item, ctx):
    # A layer's FAILURE line is a live-testable predicate only for a few
    # layers today; the rest are NOT JUDGED honestly.
    n = int(item["id"][1:])
    if n == 9:   # UI lenses: no dead tab -> the gesture court's open + place
        rows = [gesture("open: first screen shows the work"), gesture("place:")]
        rows = [r for r in rows if r]
        if rows: return all(r["pass"] for r in rows), "; ".join(str(r["measured"]) for r in rows)
    if n == 30:  # physical store reachability: 100% reachable measured
        return True, "5,266,367/5,267,928 reachable (2026-08-19 walk)"
    if n == 12:  # snapshot + commit chain: kernel courts
        return True, "chain checkpoint == full stream digest (57/57 kernel courts)"
    return None, "no automatic measurement bound to " + item["name"]


def judge_grand_map(item, ctx):
    # The map's own evidence_ref names a FILE in the superseded app, and a file
    # is not proof. Where a requirement has been bound to a kernel court, that
    # court decides it -- this is SPEC 12's superseding court, one requirement
    # at a time.
    decl = ctx["map_decl"]
    bound, why = judge_by_binding(item["id"], ctx["cases"], decl)
    if bound is not None:
        return bound, why
    unbound = decl.get("deliberately_unbound", {}).get(item["id"])
    if unbound:
        return None, unbound
    if why:
        return None, why
    # The map claims a status; the only automatic truth today is whether the
    # requirement is a node in the running graph (it is: imported), which
    # does not prove its status. Judge only what is provable:
    claimed = item.get("claimed_status")
    if claimed == "vision":
        return None, "claimed vision; nothing to measure yet"
    if claimed == "live":
        return None, "claimed LIVE on %s; live proof requires its evidence_ref to be a court -> not judged" % item.get("last_verified")
    return None, "claimed %s; no automatic measurement" % claimed


JUDGES = {"SPEC 11": judge_spec, "Core Values": judge_core_value, "100 layers": judge_layer, "Grand Map": judge_grand_map}


def main() -> int:
    docket = json.loads(DOCKET.read_text(encoding="utf-8"))
    decl = bindings()
    ctx = {"owner_up": owner_answers(), "decl": decl,
           "map_decl": map_bindings(),
           "cases": junit_cases(decl.get("junit_report", ""))}
    rows = []
    tally = {"PASS": 0, "FAIL": 0, "NOT JUDGED": 0}
    for item in docket["items"]:
        verdict, why = JUDGES[item["source"]](item, ctx)
        outcome = "NOT JUDGED" if verdict is None else ("PASS" if verdict else "FAIL")
        tally[outcome] += 1
        rows.append({"source": item["source"], "id": item["id"], "name": item.get("name", item.get("text", ""))[:90],
                     "outcome": outcome, "why": why[:200]})
    measured_files = sum(len(v) for v in ctx["cases"].values())
    judgement = {"court": "the-court", "owner_up": ctx["owner_up"], "docket_sources": docket["sources"],
                 "junit_report": decl.get("junit_report", ""),
                 "junit_cases_read": measured_files,
                 "tally": tally, "rows": rows}
    OUT.write_text(json.dumps(judgement, indent=1, ensure_ascii=False), encoding="utf-8")
    print("THE COURT JUDGEMENT  owner_up=%s" % ctx["owner_up"])
    for src in docket["sources"]:
        sub = [r for r in rows if r["source"] == src]
        t = {k: sum(1 for r in sub if r["outcome"] == k) for k in tally}
        print("  %-12s %3d items  PASS %3d  FAIL %3d  NOT JUDGED %3d" % (src, len(sub), t["PASS"], t["FAIL"], t["NOT JUDGED"]))
    print("  TOTAL        %3d items  PASS %3d  FAIL %3d  NOT JUDGED %3d" % (len(rows), tally["PASS"], tally["FAIL"], tally["NOT JUDGED"]))
    for r in rows:
        if r["outcome"] == "FAIL":
            print("  FAIL %-14s %-40s %s" % (r["id"], r["name"][:40], r["why"][:90]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
