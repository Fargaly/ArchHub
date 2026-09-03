"""Regenerate the-court-docket.json.

The docket used to be a hand-typed orphan: 418 rows nothing could rebuild, so a
single unescaped quote could take the whole court down (it did, on 2026-08-27).

This rebuilds the SPEC 11 rows from SPEC.md itself and merges each row's
declared measurement from court_bindings.json. The Core Values / 100 layers /
Grand Map rows are CARRIED from the existing docket, not regenerated - their
source documents are not parsed here yet, and pretending otherwise would be the
same lie in a new place. Every carried row is reported as carried.
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SPEC = ROOT / "SPEC.md"
DOCKET = HERE / "the-court-docket.json"
BINDINGS = HERE / "court_bindings.json"

SECTION = re.compile(r"^##\s*11\.\s", re.M)
NEXT = re.compile(r"^##\s*12\.\s", re.M)
ITEM = re.compile(r"^\s*(\d{1,2})\.\s+(.*?)(?=^\s*\d{1,2}\.\s|\Z)", re.M | re.S)


def spec_eleven_items():
    text = SPEC.read_text(encoding="utf-8")
    start = SECTION.search(text)
    if not start:
        raise SystemExit("SPEC.md has no section 11")
    end = NEXT.search(text, start.end())
    body = text[start.end(): end.start() if end else len(text)]
    items = []
    for number, raw in ITEM.findall(body):
        line = " ".join(raw.split())
        items.append({"source": "SPEC 11", "id": "SPEC-11.%s" % number, "text": line})
    return items


def main() -> int:
    decl = json.loads(BINDINGS.read_text(encoding="utf-8"))
    old = json.loads(DOCKET.read_text(encoding="utf-8"))
    carried = [i for i in old["items"] if i["source"] != "SPEC 11"]

    generated = spec_eleven_items()
    for item in generated:
        bound = decl["bindings"].get(item["id"])
        if bound:
            item["measured_by"] = bound["tests"]
        elif item["id"] in decl.get("deliberately_unbound", {}):
            item["measured_by_note"] = decl["deliberately_unbound"][item["id"]]

    items = generated + carried
    sources = {}
    for i in items:
        sources[i["source"]] = sources.get(i["source"], 0) + 1

    docket = {
        "generated_from": {
            "SPEC 11": "SPEC.md section 11 (parsed)",
            "Core Values": "carried from previous docket - no parser yet",
            "100 layers": "carried from previous docket - no parser yet",
            "Grand Map": "carried from previous docket - no parser yet",
        },
        "sources": sources,
        "items": items,
    }
    DOCKET.write_text(json.dumps(docket, indent=1, ensure_ascii=False), encoding="utf-8")

    print("DOCKET REBUILT  %d items" % len(items))
    print("  SPEC 11      %3d  regenerated from SPEC.md  (%d carry a measurement binding)"
          % (len(generated), sum(1 for i in generated if "measured_by" in i)))
    for src in ("Core Values", "100 layers", "Grand Map"):
        print("  %-12s %3d  CARRIED - not regenerated" % (src, sources.get(src, 0)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
